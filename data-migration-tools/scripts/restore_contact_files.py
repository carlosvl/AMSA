#!/usr/bin/env python3
"""
Restore Contact Files from Local Backup to Receiving Org

Restores Files (ContentVersion) from the local backup database to the receiving org
for contacts that were modified there (LastModifiedDate > since-date). Use after files
were accidentally deleted in the receiving org.

Usage:
    python restore_contact_files.py <receiving_org> <backup_name> [--since YYYY-MM-DD] [--date YYYY-MM-DD] [--dry-run]

Examples:
    python restore_contact_files.py "AMSA Prod" "AMSA_Enero-2026"
    python restore_contact_files.py "AMSA Prod" "AMSA_Enero-2026" --since 2026-01-15
    python restore_contact_files.py "AMSA Prod" "AMSA_Enero-2026" --dry-run
"""

import argparse
import json
import mimetypes
import re
import sqlite3
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import db_utils
import urllib.request

BASE_DIR = Path(__file__).resolve().parents[1]
BACKUPS_DIR = BASE_DIR / 'backups'


def sanitize_filename(name: str) -> str:
    """Convert backup name to safe filename."""
    safe = re.sub(r'[^\w\-]', '_', name)
    return safe


def get_backup_db_path(backup_name: str) -> Path:
    """Get the path for a backup database."""
    safe_name = sanitize_filename(backup_name)
    return BACKUPS_DIR / f'{safe_name}.db'


def get_backup_files_dir(backup_name: str) -> Path:
    """Get the path for backup files directory."""
    safe_name = sanitize_filename(backup_name)
    return BACKUPS_DIR / safe_name / 'files'


def run_soql(org_alias: str, query: str) -> List[Dict]:
    """Run a SOQL query and return list of records."""
    cleaned_query = ' '.join(line.strip() for line in query.strip().split('\n') if line.strip())
    cmd = ['sf', 'data', 'query', '--query', cleaned_query, '--target-org', org_alias, '--json']

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            try:
                err_data = json.loads(result.stdout)
                msg = err_data.get('message', result.stderr or 'Unknown error')
            except Exception:
                msg = result.stderr or result.stdout or 'Unknown error'
            print(f"  ❌ SOQL error: {msg[:200]}")
            return []

        data = json.loads(result.stdout)
        records = data.get('result', {}).get('records', [])
        return [{k: v for k, v in r.items() if not k.startswith('attributes')} for r in records]
    except Exception as e:
        print(f"  ❌ Query failed: {e}")
        return []


def get_org_credentials(org_alias: str) -> Tuple[Optional[str], Optional[str]]:
    """Get access token and instance URL."""
    try:
        result = subprocess.run(
            ['sf', 'org', 'display', '--target-org', org_alias, '--json'],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            return None, None
        data = json.loads(result.stdout)
        info = data.get('result', {})
        return info.get('accessToken'), info.get('instanceUrl')
    except Exception:
        return None, None


def query_contacts(receiving_org: str, since_date: str) -> List[Dict]:
    """Query contacts from receiving org modified after since_date."""
    dt_literal = f"{since_date}T00:00:00.000Z"
    query = f"SELECT Id, Name, Email, LastModifiedDate FROM Contact WHERE LastModifiedDate > {dt_literal}"
    return run_soql(receiving_org, query)


def get_backup_metadata(conn: sqlite3.Connection) -> Optional[Dict]:
    """Get backup metadata (org_alias, etc.) from backup DB."""
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM backup_metadata ORDER BY created_at DESC LIMIT 1")
    row = cursor.fetchone()
    if row:
        return dict(row)
    return None


def _normalize_email(email: Optional[str]) -> str:
    """Normalize email for matching (lowercase, strip)."""
    if not email or not isinstance(email, str):
        return ""
    return email.strip().lower()


def _build_email_mapping(
    cursor: sqlite3.Cursor,
    receiving_contact_ids: List[str],
    receiving_id_to_email: Dict[str, str],
) -> Tuple[set, Dict[str, str]]:
    """
    Build backup_contact_id -> receiving_contact_id mapping using Email.
    Returns (effective_contact_ids, contact_id_map).
    """
    receiving_set = set(receiving_contact_ids)
    email_to_receiving_id = {}
    for cid, email in receiving_id_to_email.items():
        key = _normalize_email(email)
        if key and cid in receiving_set:
            email_to_receiving_id[key] = cid

    cursor.execute("""
        SELECT DISTINCT cdl.linked_entity_id, c.email
        FROM content_document_links cdl
        JOIN content_versions cv ON cv.content_document_id = cdl.content_document_id
        JOIN contacts c ON c.sf_id = cdl.linked_entity_id
    """)
    backup_contact_rows = cursor.fetchall()
    if not backup_contact_rows:
        return set(), {}

    effective_contact_ids = set()
    contact_id_map = {}
    for row in backup_contact_rows:
        backup_id, email = row[0], row[1]
        key = _normalize_email(email)
        receiving_id = email_to_receiving_id.get(key)
        if receiving_id:
            effective_contact_ids.add(backup_id)
            contact_id_map[backup_id] = receiving_id
    return effective_contact_ids, contact_id_map


def get_files_to_restore(
    conn: sqlite3.Connection,
    receiving_contact_ids: List[str],
    receiving_id_to_email: Dict[str, str],
    backup_org_alias: str,
    receiving_org: str,
) -> List[Dict]:
    """
    Find files in backup linked to the given contacts.
    Returns list of {contact_id, content_document_id, content_version_id, title, file_extension, file_path, file_data, content_size}.
    """
    cursor = conn.cursor()
    contact_id_map = {}

    if backup_org_alias == receiving_org:
        effective_contact_ids = set(receiving_contact_ids)
        contact_id_map = {cid: cid for cid in receiving_contact_ids}
    else:
        id_mappings = db_utils.get_id_mappings('Contact')
        target_to_source = {v: k for k, v in id_mappings.items()}
        effective_contact_ids = set()
        for cid in receiving_contact_ids:
            src = target_to_source.get(cid)
            if src:
                effective_contact_ids.add(src)
                contact_id_map[src] = cid

        if not effective_contact_ids:
            print("  ⚠️  No id_mappings found; trying Email-based match with backup contacts...")
            effective_contact_ids, contact_id_map = _build_email_mapping(
                cursor, receiving_contact_ids, receiving_id_to_email
            )
            if not effective_contact_ids:
                print("  ⚠️  No matching contacts found by Email either.")
                return []
            print(f"  📋 Mapped {len(effective_contact_ids)} backup contacts to receiving contacts via Email")
        else:
            contact_id_map = {k: v for k, v in contact_id_map.items()}
            print(f"  📋 Mapped {len(receiving_contact_ids)} contacts via id_mappings to {len(effective_contact_ids)} backup IDs")

    if not effective_contact_ids:
        return []

    placeholders = ','.join('?' * len(effective_contact_ids))
    cursor.execute(f"""
        SELECT cdl.linked_entity_id, cdl.content_document_id,
               cv.sf_id as content_version_id, cv.title, cv.file_extension,
               cv.file_path, cv.file_data, cv.content_size
        FROM content_document_links cdl
        JOIN content_versions cv ON cv.content_document_id = cdl.content_document_id
        JOIN contacts c ON c.sf_id = cdl.linked_entity_id
        WHERE cdl.linked_entity_id IN ({placeholders})
    """, list(effective_contact_ids))

    rows = cursor.fetchall()
    result = []
    receiving_set = set(receiving_contact_ids)
    for row in rows:
        linked_entity_id = row['linked_entity_id']
        target_contact_id = contact_id_map.get(linked_entity_id) or linked_entity_id
        if target_contact_id not in receiving_set:
            continue
        result.append({
            'contact_id': target_contact_id,
            'content_document_id': row['content_document_id'],
            'content_version_id': row['content_version_id'],
            'title': row['title'] or 'Untitled',
            'file_extension': row['file_extension'] or '',
            'file_path': row['file_path'],
            'file_data': row['file_data'],
            'content_size': row['content_size'] or 0,
        })
    return result


def resolve_file_content(
    file_path: Optional[str],
    file_data: Optional[bytes],
    backup_files_dir: Path,
    title: str = "",
    file_extension: str = "",
) -> Tuple[Optional[bytes], Optional[str]]:
    """
    Resolve file bytes from file_path, file_data, or by matching title in backup dir.
    Returns (bytes, suggested_filename) or (None, None) if not found.
    """
    if file_data and len(file_data) > 0:
        return file_data, None

    if file_path:
        path = Path(file_path)
        if path.exists():
            with open(path, 'rb') as f:
                return f.read(), path.name
        alt_path = backup_files_dir / path.name
        if alt_path.exists():
            with open(alt_path, 'rb') as f:
                return f.read(), path.name

    if title and backup_files_dir.exists():
        if file_extension and not title.lower().endswith(f'.{file_extension.lower()}'):
            candidate = f"{title}.{file_extension}"
        else:
            candidate = title
        safe_name = re.sub(r'[<>:"/\\|?*]', '_', candidate).strip('. ')[:200]
        exact = backup_files_dir / safe_name
        if exact.is_file():
            with open(exact, 'rb') as f:
                return f.read(), exact.name
    return None, None


def upload_file_multipart(
    access_token: str,
    instance_url: str,
    file_content: bytes,
    title: str,
    file_extension: str,
    target_contact_id: str,
) -> Tuple[Optional[str], Optional[str]]:
    """Upload file using multipart/form-data."""
    try:
        if file_extension and not title.lower().endswith(f'.{file_extension.lower()}'):
            filename = f"{title}.{file_extension}"
        else:
            filename = title
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename).strip('. ')[:200]

        mime_type, _ = mimetypes.guess_type(filename)
        if not mime_type:
            mime_type = 'application/octet-stream'

        boundary = f'----Boundary{uuid.uuid4().hex}'
        entity_data = {
            "Title": title,
            "PathOnClient": filename,
            "FirstPublishLocationId": target_contact_id,
        }
        parts = [
            f'--{boundary}'.encode(),
            b'Content-Disposition: form-data; name="entity_content"',
            b'Content-Type: application/json',
            b'',
            json.dumps(entity_data).encode(),
            f'--{boundary}'.encode(),
            f'Content-Disposition: form-data; name="VersionData"; filename="{filename}"'.encode(),
            f'Content-Type: {mime_type}'.encode(),
            b'',
            file_content,
            f'--{boundary}--'.encode(),
            b'',
        ]
        body = b'\r\n'.join(parts)

        url = f"{instance_url}/services/data/v59.0/sobjects/ContentVersion"
        req = urllib.request.Request(url, data=body)
        req.add_header('Authorization', f'Bearer {access_token}')
        req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
        req.add_header('Content-Length', str(len(body)))

        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.loads(response.read().decode('utf-8'))
            if result.get('success'):
                return result['id'], None
            return None, str(result.get('errors', []))
    except Exception as e:
        return None, str(e)


def query_existing_files(receiving_org: str) -> Dict[str, set]:
    """Query existing files in receiving org by contact, keyed by title|size."""
    query = """
        SELECT LinkedEntityId, ContentDocument.Title, ContentDocument.ContentSize
        FROM ContentDocumentLink
        WHERE LinkedEntity.Type = 'Contact'
    """
    records = run_soql(receiving_org, query)
    by_contact = {}
    for r in records:
        eid = r.get('LinkedEntityId')
        if not eid:
            continue
        doc = r.get('ContentDocument', {}) or {}
        key = f"{doc.get('Title', '')}|{doc.get('ContentSize', 0)}"
        if eid not in by_contact:
            by_contact[eid] = set()
        by_contact[eid].add(key)
    return by_contact


def main():
    parser = argparse.ArgumentParser(
        description='Restore Contact files from local backup to receiving org'
    )
    parser.add_argument('receiving_org', help='Org alias (e.g., AMSA Prod)')
    parser.add_argument('backup_name', help='Backup name (e.g., AMSA_Enero-2026)')
    parser.add_argument('--since', '--date', dest='since', default='2026-01-01',
                        help='Contact filter: LastModifiedDate > this date (default: 2026-01-01)')
    parser.add_argument('--dry-run', action='store_true', help='List files only, do not upload')
    args = parser.parse_args()

    receiving_org = args.receiving_org
    backup_name = args.backup_name
    since_date = args.since
    dry_run = args.dry_run

    print("=" * 80)
    print("RESTORE CONTACT FILES FROM LOCAL BACKUP")
    print("=" * 80)
    print(f"Receiving org: {receiving_org}")
    print(f"Backup name:  {backup_name}")
    print(f"Since date:   {since_date}")
    if dry_run:
        print("Mode:        DRY RUN")
    print()

    db_path = get_backup_db_path(backup_name)
    if not db_path.exists():
        print(f"❌ Backup database not found: {db_path}")
        sys.exit(1)

    print("📥 Querying contacts from receiving org...")
    contacts = query_contacts(receiving_org, since_date)
    if not contacts:
        print("  ⚠️  No contacts found matching the date filter.")
        sys.exit(0)
    contact_ids = [c['Id'] for c in contacts]
    print(f"  ✅ Found {len(contact_ids)} contacts")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        metadata = get_backup_metadata(conn)
        backup_org = metadata.get('org_alias', '') if metadata else ''
        print(f"  📋 Backup was created from org: {backup_org}")

        print("\n📂 Finding files in backup...")
        receiving_id_to_email = {c['Id']: c.get('Email') or '' for c in contacts}
        files_to_restore = get_files_to_restore(
            conn, contact_ids, receiving_id_to_email, backup_org, receiving_org
        )
        if not files_to_restore:
            print("  ⚠️  No files found in backup for these contacts.")
            sys.exit(0)
        print(f"  ✅ Found {len(files_to_restore)} files to restore")

        existing_by_contact = {}
        if not dry_run:
            print("\n📥 Checking existing files in receiving org...")
            existing_by_contact = query_existing_files(receiving_org)
            print(f"  ✅ Queried existing files")

        backup_files_dir = get_backup_files_dir(backup_name)
        access_token, instance_url = None, None
        if not dry_run:
            access_token, instance_url = get_org_credentials(receiving_org)
            if not access_token:
                print("❌ Failed to authenticate to receiving org")
                sys.exit(1)

        results = {'total': 0, 'success': 0, 'skipped': 0, 'failed': 0}
        for i, f in enumerate(files_to_restore, 1):
            results['total'] += 1
            title = f['title']
            contact_id = f['contact_id']
            file_key = f"{title}|{f['content_size']}"

            existing = existing_by_contact.get(contact_id, set())
            if file_key in existing and not dry_run:
                print(f"[{i}/{len(files_to_restore)}] {title[:60]} - ⏭️  Already exists")
                results['skipped'] += 1
                continue

            content, _ = resolve_file_content(
                f['file_path'], f['file_data'], backup_files_dir,
                title=f['title'], file_extension=f['file_extension']
            )
            if not content:
                print(f"[{i}/{len(files_to_restore)}] {title[:60]} - ❌ File not found on disk")
                results['failed'] += 1
                continue

            if dry_run:
                size_kb = len(content) / 1024
                print(f"[{i}/{len(files_to_restore)}] {title[:60]} ({size_kb:.1f} KB) -> Contact {contact_id[:15]}...")
                results['success'] += 1
                continue

            cv_id, err = upload_file_multipart(
                access_token, instance_url,
                content, title, f['file_extension'],
                contact_id,
            )
            if err:
                print(f"[{i}/{len(files_to_restore)}] {title[:60]} - ❌ Upload failed: {str(err)[:80]}")
                results['failed'] += 1
            else:
                print(f"[{i}/{len(files_to_restore)}] {title[:60]} - ✅ Restored")
                results['success'] += 1
    finally:
        conn.close()

    print()
    print("=" * 80)
    print("RESTORE SUMMARY")
    print("=" * 80)
    print(f"Total files:   {results['total']}")
    print(f"✅ Restored:   {results['success']}")
    print(f"⏭️  Skipped:    {results['skipped']}")
    print(f"❌ Failed:     {results['failed']}")
    if dry_run:
        print("\n⚠️  DRY RUN - No files were uploaded")
    print("=" * 80)


if __name__ == '__main__':
    main()
