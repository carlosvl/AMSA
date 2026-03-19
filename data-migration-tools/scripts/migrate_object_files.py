#!/usr/bin/env python3
"""
Generic Object File Migration Tool

Migrates files (ContentDocument/ContentVersion) linked to ANY Salesforce object 
from source org to target org. Uses the ContentDocumentLink junction object.

This is a generic script that works for:
- Contact files
- Account files
- Campaign files
- Seminar_Application__c files
- Any custom object files

Uses the proven multipart/form-data upload method with FirstPublishLocationId.

Usage:
  python3 migrate_object_files.py <source_org> <target_org> <object_type> [--batch-size N] [--dry-run]

Examples:
  python3 migrate_object_files.py "AMSA-Royalty-Prod" "AMSA Prod" Contact
  python3 migrate_object_files.py "AMSA-Royalty-Prod" "AMSA Prod" Account --batch-size 25
  python3 migrate_object_files.py "AMSA-Royalty-Prod" "AMSA Prod" Campaign --dry-run
"""

import json
import subprocess
import sys
import os
import time
import argparse
import tempfile
import shutil
import mimetypes
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple
import urllib.request
import urllib.error
import urllib.parse

import db_utils

BASE_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = BASE_DIR / 'results'


def run_soql(org_alias: str, query: str):
    """Run a SOQL query and return list of records (or [])."""
    cleaned_query = ' '.join(line.strip() for line in query.strip().split('\n') if line.strip())
    result = subprocess.run(
        [
            'sf', 'data', 'query',
            '--query', cleaned_query,
            '--target-org', org_alias,
            '--json',
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.returncode != 0:
        print(f"  ❌ SOQL error for org {org_alias}:")
        try:
            err_data = json.loads(result.stdout)
            msg = err_data.get('message', err_data.get('detail', str(err_data)))
            print(f"  {msg}")
        except Exception:
            print(f"  {result.stderr.strip() or result.stdout[:500]}")
        return []

    try:
        data = json.loads(result.stdout)
        if data.get('status', 0) != 0:
            print(f"  ❌ SOQL error for org {org_alias}: {data.get('message', 'Unknown')}")
            return []
        return data.get('result', {}).get('records', [])
    except Exception as e:
        print(f"  ❌ Failed to parse SOQL JSON for org {org_alias}: {e}")
        return []


def get_org_credentials(org_alias: str):
    """Get access token and instance URL from sf org display."""
    try:
        result = subprocess.run(
            ['sf', 'org', 'display', '--target-org', org_alias, '--json'],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"❌ Failed to get org info for {org_alias}:")
            print(result.stderr.strip())
            return None, None

        data = json.loads(result.stdout)
        info = data.get('result', {})
        return info.get('accessToken'), info.get('instanceUrl')
    except Exception as e:
        print(f"❌ Error getting org credentials for {org_alias}: {e}")
        return None, None


def load_id_mappings(object_type: str) -> Dict[str, str]:
    """Load ID mappings for the specified object type from database."""
    print(f"📂 Loading {object_type} ID mappings from database...")
    
    mappings = db_utils.get_id_mappings(object_type)
    
    print(f"  ✅ {object_type} mappings: {len(mappings)} entries")
    
    return mappings


def query_source_files(org_alias: str, object_type: str, source_entity_ids: List[str]) -> List[Dict]:
    """Query all files linked to the given entity IDs from source org.
    ContentDocumentLink requires filtering by LinkedEntityId (cannot use LinkedEntity.Type)."""
    print(f"📥 Querying files linked to {object_type} from {org_alias}...")

    if not source_entity_ids:
        print(f"  ⚠️ No source entity IDs to query")
        return []

    # Batch IDs (Salesforce IN clause limit ~200)
    batch_size = 200
    all_records = []
    for i in range(0, len(source_entity_ids), batch_size):
        batch_ids = source_entity_ids[i:i + batch_size]
        ids_str = "','".join(batch_ids)
        query = f"""
            SELECT Id, ContentDocumentId, LinkedEntityId, ShareType, Visibility,
                   ContentDocument.Title, ContentDocument.FileType, ContentDocument.ContentSize,
                   ContentDocument.LatestPublishedVersionId
            FROM ContentDocumentLink
            WHERE LinkedEntityId IN ('{ids_str}')
        """
        records = run_soql(org_alias, query)
        all_records.extend(records)
        if records and i + batch_size < len(source_entity_ids):
            time.sleep(0.5)  # Brief pause between batches to avoid rate limits

    print(f"  ✅ Retrieved {len(all_records)} file links")
    return all_records


def query_target_files(org_alias: str, object_type: str, target_entity_ids: List[str]) -> Dict[str, List[str]]:
    """Query existing files in target org, grouped by linked entity.
    ContentDocumentLink requires filtering by LinkedEntityId (cannot use LinkedEntity.Type)."""
    print(f"📥 Querying existing files in target org for {object_type}...")

    if not target_entity_ids:
        print(f"  ⚠️ No target entity IDs to query")
        return {}

    # Deduplicate and batch
    unique_ids = list(dict.fromkeys(target_entity_ids))
    batch_size = 200
    all_records = []
    for i in range(0, len(unique_ids), batch_size):
        batch_ids = unique_ids[i:i + batch_size]
        ids_str = "','".join(batch_ids)
        query = f"""
            SELECT Id, ContentDocumentId, LinkedEntityId,
                   ContentDocument.Title, ContentDocument.ContentSize
            FROM ContentDocumentLink
            WHERE LinkedEntityId IN ('{ids_str}')
        """
        records = run_soql(org_alias, query)
        all_records.extend(records)
        if records and i + batch_size < len(unique_ids):
            time.sleep(0.5)

    records = all_records
    
    # Group files by LinkedEntityId and create lookup by title+size
    files_by_entity = {}
    for rec in records:
        entity_id = rec.get('LinkedEntityId')
        if not entity_id:
            continue
        
        doc = rec.get('ContentDocument', {}) or {}
        title = doc.get('Title', '')
        size = doc.get('ContentSize', 0)
        file_key = f"{title}|{size}"
        
        if entity_id not in files_by_entity:
            files_by_entity[entity_id] = set()
        files_by_entity[entity_id].add(file_key)
    
    print(f"  ✅ Found files for {len(files_by_entity)} {object_type} records in target")
    return files_by_entity


def identify_missing_files(source_files: List[Dict], target_files: Dict[str, List[str]], 
                           id_mappings: Dict[str, str]) -> List[Dict]:
    """Identify files that need to be migrated (exist in source but not in target)."""
    print("\n🔍 Identifying missing files...")
    
    missing_files = []
    unmapped_records = 0
    already_exists = 0
    
    for link in source_files:
        source_entity_id = link.get('LinkedEntityId')
        
        if not source_entity_id:
            continue
        
        # Check if we have a mapping for this record
        if source_entity_id not in id_mappings:
            unmapped_records += 1
            continue
        
        target_entity_id = id_mappings[source_entity_id]
        
        # Get file details
        doc = link.get('ContentDocument', {}) or {}
        title = doc.get('Title', '')
        size = doc.get('ContentSize', 0)
        file_key = f"{title}|{size}"
        
        # Check if this file already exists in target
        target_entity_files = target_files.get(target_entity_id, set())
        if file_key in target_entity_files:
            already_exists += 1
            continue
        
        # This file needs to be migrated
        missing_files.append({
            'source_entity_id': source_entity_id,
            'target_entity_id': target_entity_id,
            'content_document_id': link.get('ContentDocumentId'),
            'content_version_id': doc.get('LatestPublishedVersionId'),
            'title': title,
            'file_type': doc.get('FileType', ''),
            'size': size,
            'share_type': link.get('ShareType', 'V'),
            'visibility': link.get('Visibility', 'AllUsers'),
        })
    
    print(f"  📊 Total source file links: {len(source_files)}")
    print(f"  ⚠️  Unmapped records (skipped): {unmapped_records}")
    print(f"  ✅ Already in target (skipped): {already_exists}")
    print(f"  ❌ Missing files to migrate: {len(missing_files)}")
    
    return missing_files


def download_file(access_token: str, instance_url: str, content_version_id: str, 
                  output_dir: str, title: str, file_type: str) -> Tuple[str, str]:
    """Download a file from Salesforce."""
    try:
        url = f"{instance_url}/services/data/v59.0/sobjects/ContentVersion/{content_version_id}/VersionData"
        
        req = urllib.request.Request(url)
        req.add_header('Authorization', f'Bearer {access_token}')
        
        with urllib.request.urlopen(req, timeout=120) as response:
            file_content = response.read()
        
        # Determine filename
        import re
        if file_type and not title.lower().endswith(f'.{file_type.lower()}'):
            filename = f"{title}.{file_type}"
        else:
            filename = title
        
        # Sanitize filename
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        filename = filename.strip('. ')[:200]
        
        filepath = os.path.join(output_dir, filename)
        
        with open(filepath, 'wb') as f:
            f.write(file_content)
        
        return filepath, None
    
    except Exception as e:
        return None, str(e)


def upload_file_multipart(access_token: str, instance_url: str, file_path: str, 
                          title: str, target_entity_id: str) -> Tuple[str, str]:
    """Upload file using multipart/form-data - THE PROVEN METHOD."""
    try:
        # Detect mime type
        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type:
            mime_type = 'application/octet-stream'
        
        # Read file
        with open(file_path, 'rb') as f:
            file_content = f.read()
        
        # Create multipart boundary
        boundary = f'----Boundary{uuid.uuid4().hex}'
        
        # Build multipart body
        parts = []
        
        # Part 1: JSON metadata
        entity_data = {
            "Title": title,
            "PathOnClient": os.path.basename(file_path),
            "FirstPublishLocationId": target_entity_id  # Auto-links to record
        }
        
        parts.append(f'--{boundary}'.encode())
        parts.append(b'Content-Disposition: form-data; name="entity_content"')
        parts.append(b'Content-Type: application/json')
        parts.append(b'')
        parts.append(json.dumps(entity_data).encode())
        
        # Part 2: File content
        parts.append(f'--{boundary}'.encode())
        parts.append(f'Content-Disposition: form-data; name="VersionData"; filename="{os.path.basename(file_path)}"'.encode())
        parts.append(f'Content-Type: {mime_type}'.encode())
        parts.append(b'')
        parts.append(file_content)
        
        # End boundary
        parts.append(f'--{boundary}--'.encode())
        parts.append(b'')
        
        # Join all parts
        body = b'\r\n'.join(parts)
        
        # Make request
        url = f"{instance_url}/services/data/v59.0/sobjects/ContentVersion"
        
        req = urllib.request.Request(url, data=body)
        req.add_header('Authorization', f'Bearer {access_token}')
        req.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
        req.add_header('Content-Length', str(len(body)))
        
        with urllib.request.urlopen(req, timeout=120) as response:
            result = json.loads(response.read().decode('utf-8'))
            if result.get('success'):
                return result['id'], None
            else:
                errors = result.get('errors', [])
                return None, str(errors)
    
    except Exception as e:
        return None, str(e)


def wait_for_content_document(access_token: str, instance_url: str, 
                               content_version_id: str, max_wait: int = 30) -> Tuple[str, str]:
    """Wait for ContentDocument to be created (async in Salesforce)."""
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        try:
            query = f"SELECT ContentDocumentId FROM ContentVersion WHERE Id = '{content_version_id}'"
            encoded = urllib.parse.quote(query)
            url = f"{instance_url}/services/data/v59.0/query/?q={encoded}"
            
            req = urllib.request.Request(url)
            req.add_header('Authorization', f'Bearer {access_token}')
            
            with urllib.request.urlopen(req, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                records = data.get('records', [])
                if records and records[0].get('ContentDocumentId'):
                    return records[0]['ContentDocumentId'], None
            
            time.sleep(2)
        
        except Exception:
            time.sleep(2)
    
    return None, "Timeout waiting for ContentDocument"


def migrate_files(source_org: str, target_org: str, missing_files: List[Dict], 
                  batch_size: int, dry_run: bool) -> Dict:
    """Migrate missing files from source to target org."""
    
    if dry_run:
        print("  🔍 DRY RUN - No files will be migrated")
        return {
            'total': len(missing_files),
            'success': 0,
            'failed': 0,
            'skipped': 0,
            'details': [],
            'dry_run': True
        }
    
    # Get credentials for both orgs
    print("🔐 Authenticating to both orgs...")
    source_token, source_url = get_org_credentials(source_org)
    target_token, target_url = get_org_credentials(target_org)
    
    if not source_token or not target_token:
        raise Exception("Failed to authenticate to one or both orgs")
    
    print(f"  ✅ Source: {source_url}")
    print(f"  ✅ Target: {target_url}")
    
    # Create temp directory for downloads
    temp_dir = tempfile.mkdtemp(prefix='sf_file_migration_')
    print(f"📁 Temp directory: {temp_dir}")
    
    results = {
        'total': len(missing_files),
        'success': 0,
        'failed': 0,
        'skipped': 0,
        'details': []
    }
    
    try:
        total_batches = (len(missing_files) + batch_size - 1) // batch_size
        
        for batch_num in range(total_batches):
            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, len(missing_files))
            batch = missing_files[start_idx:end_idx]
            
            print(f"\n{'='*80}")
            print(f"📦 BATCH {batch_num + 1}/{total_batches} ({len(batch)} files)")
            print(f"{'='*80}\n")
            
            for i, file_info in enumerate(batch):
                overall_idx = start_idx + i + 1
                title = file_info['title']
                size_mb = file_info['size'] / (1024 * 1024)
                
                print(f"[{overall_idx}/{len(missing_files)}] {title[:65]}")
                
                # Skip if too large (25 MB Salesforce limit)
                if size_mb > 25:
                    print(f"  ⏭️  Skipped: Too large ({size_mb:.2f} MB)")
                    results['skipped'] += 1
                    results['details'].append({
                        'file': title,
                        'status': 'skipped',
                        'reason': f'Too large ({size_mb:.2f} MB)'
                    })
                    continue
                
                # Download from source
                print(f"  📥 Downloading ({size_mb:.2f} MB)...")
                filepath, error = download_file(
                    source_token, source_url,
                    file_info['content_version_id'],
                    temp_dir, title, file_info['file_type']
                )
                
                if error:
                    print(f"  ❌ Download failed: {error[:80]}")
                    results['failed'] += 1
                    results['details'].append({
                        'file': title,
                        'status': 'download_failed',
                        'error': error
                    })
                    continue
                
                # Upload to target
                print(f"  📤 Uploading...")
                content_version_id, error = upload_file_multipart(
                    target_token, target_url, filepath, title,
                    file_info['target_entity_id']
                )
                
                if error:
                    print(f"  ❌ Upload failed: {error[:80]}")
                    results['failed'] += 1
                    results['details'].append({
                        'file': title,
                        'status': 'upload_failed',
                        'error': error
                    })
                    # Clean up
                    if os.path.exists(filepath):
                        os.remove(filepath)
                    continue
                
                # Verify ContentDocument creation
                print(f"  ⏳ Verifying...")
                content_doc_id, error = wait_for_content_document(
                    target_token, target_url, content_version_id
                )
                
                if error:
                    print(f"  ⚠️  Verification warning: {error}")
                    # Still count as success since file uploaded
                    results['success'] += 1
                    results['details'].append({
                        'file': title,
                        'status': 'success_no_verify',
                        'content_version_id': content_version_id,
                        'target_entity_id': file_info['target_entity_id']
                    })
                else:
                    print(f"  ✅ SUCCESS! Document: {content_doc_id}")
                    results['success'] += 1
                    results['details'].append({
                        'file': title,
                        'status': 'success',
                        'content_version_id': content_version_id,
                        'content_document_id': content_doc_id,
                        'target_entity_id': file_info['target_entity_id']
                    })
                
                # Clean up downloaded file
                if os.path.exists(filepath):
                    os.remove(filepath)
            
            # Delay between batches
            if batch_num < total_batches - 1:
                print(f"\n⏸️  Waiting 5s before next batch...")
                time.sleep(5)
    
    finally:
        # Clean up temp directory
        try:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
                print(f"\n🧹 Cleaned up temp directory")
        except Exception:
            pass
    
    return results


def main():
    print("=" * 80)
    print("📁 GENERIC OBJECT FILE MIGRATION TOOL")
    print("=" * 80)
    print()

    parser = argparse.ArgumentParser(
        description='Migrate files linked to any Salesforce object between orgs'
    )
    parser.add_argument('source_org', help='Source org alias')
    parser.add_argument('target_org', help='Target org alias')
    parser.add_argument('object_type', help='Object type (e.g., Contact, Account, Campaign)')
    parser.add_argument('--batch-size', type=int, default=50,
                        help='Number of files per batch (default: 50)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Compare only, do not migrate')
    parser.add_argument('--export-json', action='store_true',
                        help='Export comparison results to JSON')
    
    args = parser.parse_args()

    source_org = args.source_org
    target_org = args.target_org
    object_type = args.object_type
    batch_size = args.batch_size
    dry_run = args.dry_run

    print("📋 Parameters:")
    print(f"  Source Org: {source_org}")
    print(f"  Target Org: {target_org}")
    print(f"  Object Type: {object_type}")
    print(f"  Batch Size: {batch_size}")
    if dry_run:
        print(f"  Mode: DRY RUN (comparison only)")
    print()

    # Load ID mappings
    id_mappings = load_id_mappings(object_type)
    if not id_mappings:
        print(f"❌ No {object_type} mappings found in database")
        print(f"   Run compare_{object_type.lower()}s.py first!")
        sys.exit(1)
    print()

    # Query source files (by source entity IDs - ContentDocumentLink requires LinkedEntityId filter)
    source_entity_ids = list(id_mappings.keys())
    source_files = query_source_files(source_org, object_type, source_entity_ids)
    if not source_files:
        print(f"⚠️  No files found linked to {object_type} in source org")
        sys.exit(0)

    # Query target files (by target entity IDs)
    target_entity_ids = list(id_mappings.values())
    target_files = query_target_files(target_org, object_type, target_entity_ids)

    # Identify missing files
    missing_files = identify_missing_files(source_files, target_files, id_mappings)
    
    if not missing_files:
        print(f"\n✅ All {object_type} files already exist in target org!")
        sys.exit(0)

    # Migrate files
    print(f"\n🚀 Starting migration of {len(missing_files)} files...")
    results = migrate_files(source_org, target_org, missing_files, batch_size, dry_run)

    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    json_path = RESULTS_DIR / f'{object_type.lower()}_files_migration_{timestamp}.json'
    json_path.write_text(
        json.dumps({
            'metadata': {
                'source_org': source_org,
                'target_org': target_org,
                'object_type': object_type,
                'timestamp': timestamp,
                'dry_run': dry_run
            },
            'summary': {
                'total_source_files': len(source_files),
                'missing_files': len(missing_files),
                'success': results['success'],
                'failed': results['failed'],
                'skipped': results['skipped'],
            },
            'details': results['details']
        }, indent=2)
    )

    # Print summary
    print(f"\n{'='*80}")
    print(f"📊 MIGRATION SUMMARY")
    print(f"{'='*80}")
    print(f"Object Type: {object_type}")
    print(f"Total Source Files: {len(source_files)}")
    print(f"Missing Files: {len(missing_files)}")
    print(f"✅ Successful: {results['success']}")
    print(f"⏭️  Skipped: {results['skipped']}")
    print(f"❌ Failed: {results['failed']}")
    if len(missing_files) > 0:
        success_rate = results['success'] / len(missing_files) * 100
        print(f"📈 Success Rate: {success_rate:.1f}%")
    if dry_run:
        print(f"\n⚠️  DRY RUN - No files were migrated")
    print(f"{'='*80}")
    print(f"\n📄 Results saved to: {json_path}")

    if results['success'] > 0:
        print(f"\n🎉 Successfully migrated {results['success']} {object_type} files!")


if __name__ == '__main__':
    main()
