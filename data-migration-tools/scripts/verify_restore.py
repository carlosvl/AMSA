#!/usr/bin/env python3
"""
Verify Restore Completeness

Confirms that all files from the local backup (for contacts matching the date filter)
exist in the receiving org. Run after restore_contact_files.py to verify success.

Usage:
    python verify_restore.py <receiving_org> <backup_name> [--since YYYY-MM-DD] [--date YYYY-MM-DD]

Examples:
    python verify_restore.py "AMSA-Prod" "AMSA_Enero-2026"
    python verify_restore.py "AMSA-Prod" "AMSA_Enero-2026" --since 2026-01-01
"""

import argparse
import json
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

import db_utils

from restore_contact_files import (
    get_backup_db_path,
    get_backup_metadata,
    get_files_to_restore,
    query_contacts,
    run_soql,
)


def query_org_files_for_contacts(receiving_org: str, contact_ids: List[str]) -> Set[Tuple[str, str, int]]:
    """
    Query receiving org for files linked to the given contacts.
    Returns set of (contact_id, title, content_size) for matching.
    """
    if not contact_ids:
        return set()

    result = set()
    batch_size = 200

    for i in range(0, len(contact_ids), batch_size):
        batch = contact_ids[i : i + batch_size]
        ids_str = "','".join(batch)
        query = f"""
            SELECT LinkedEntityId, ContentDocument.Title, ContentDocument.ContentSize
            FROM ContentDocumentLink
            WHERE LinkedEntity.Type = 'Contact' AND LinkedEntityId IN ('{ids_str}')
        """
        records = run_soql(receiving_org, query)
        for r in records:
            eid = r.get('LinkedEntityId')
            doc = r.get('ContentDocument', {}) or {}
            title = doc.get('Title', '')
            size = doc.get('ContentSize', 0) or 0
            if eid and title:
                result.add((eid, title, size))

    return result


def main():
    parser = argparse.ArgumentParser(
        description='Verify that all backup files were restored to the receiving org'
    )
    parser.add_argument('receiving_org', help='Org alias (e.g., AMSA-Prod)')
    parser.add_argument('backup_name', help='Backup name (e.g., AMSA_Enero-2026)')
    parser.add_argument('--since', '--date', dest='since', default='2026-01-01',
                        help='Contact filter: LastModifiedDate > this date (default: 2026-01-01)')
    args = parser.parse_args()

    receiving_org = args.receiving_org
    backup_name = args.backup_name
    since_date = args.since

    print("=" * 80)
    print("VERIFY RESTORE COMPLETENESS")
    print("=" * 80)
    print(f"Receiving org: {receiving_org}")
    print(f"Backup name:   {backup_name}")
    print(f"Since date:    {since_date}")
    print()

    db_path = get_backup_db_path(backup_name)
    if not db_path.exists():
        print(f"Backup database not found: {db_path}")
        sys.exit(2)

    print("Querying contacts from receiving org...")
    contacts = query_contacts(receiving_org, since_date)
    if not contacts:
        print("  No contacts found matching the date filter.")
        sys.exit(0)
    contact_ids = [c['Id'] for c in contacts]
    contact_id_to_name = {c['Id']: c.get('Name', '') for c in contacts}
    print(f"  Found {len(contact_ids)} contacts")

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        metadata = get_backup_metadata(conn)
        backup_org = metadata.get('org_alias', '') if metadata else ''
        print(f"  Backup was created from org: {backup_org}")

        print("\nBuilding expected file list from backup...")
        receiving_id_to_email = {c['Id']: c.get('Email') or '' for c in contacts}
        expected_files = get_files_to_restore(
            conn, contact_ids, receiving_id_to_email, backup_org, receiving_org
        )
        if not expected_files:
            print("  No files found in backup for these contacts.")
            print("\nVERIFICATION: N/A (nothing to verify)")
            sys.exit(0)

        print(f"  Expected {len(expected_files)} files from backup")

        print("\nQuerying files in receiving org...")
        org_files = query_org_files_for_contacts(receiving_org, contact_ids)
        print(f"  Found {len(org_files)} file-contact links in org")

        expected_keys = {
            (f['contact_id'], f['title'], f['content_size']) for f in expected_files
        }
        found_keys = org_files
        missing = expected_keys - found_keys

        print()
        print("=" * 80)
        print("VERIFICATION REPORT")
        print("=" * 80)
        print(f"Expected files (from backup): {len(expected_files)}")
        print(f"Found in org:                 {len(expected_keys & found_keys)}")
        print(f"Missing:                      {len(missing)}")
        print()

        if missing:
            print("Missing files:")
            for i, (cid, title, size) in enumerate(sorted(missing), 1):
                name = contact_id_to_name.get(cid, '')
                size_kb = size / 1024
                print(f"  {i}. Contact {cid[:18]}... ({name[:30]}) - \"{title[:50]}\" ({size_kb:.1f} KB)")
            print()
            print("Status: FAIL")
            sys.exit(1)
        else:
            print("Status: PASS")
            sys.exit(0)
    finally:
        conn.close()


if __name__ == '__main__':
    main()
