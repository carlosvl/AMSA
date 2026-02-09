#!/usr/bin/env python3
"""
Delete Seminar_Application__c records that have NULL Seminar__c field.

This script reads the extra records CSV and deletes only those records
where Seminar__c is NULL or empty.

Usage:
  python3 delete_seminar_applications_null_seminar.py <target_org> [--dry-run] [--csv-file <path>]

Example:
  python3 delete_seminar_applications_null_seminar.py "AMSA Prod"
  python3 delete_seminar_applications_null_seminar.py "AMSA Prod" --dry-run
"""

import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Dict

BASE_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = BASE_DIR / 'results'

# Default CSV file (most recent)
DEFAULT_CSV_PATTERN = 'seminar_application_extra_records_*.csv'


def find_latest_csv() -> Path:
    """Find the most recent extra records CSV file."""
    csv_files = sorted(RESULTS_DIR.glob(DEFAULT_CSV_PATTERN))
    if not csv_files:
        raise FileNotFoundError(
            f"No CSV file found matching pattern: {DEFAULT_CSV_PATTERN}"
        )
    return csv_files[-1]


def load_null_seminar_records(csv_path: Path) -> List[Dict]:
    """Load records from CSV that have NULL Seminar__c."""
    records = []
    with csv_path.open('r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            seminar_id = row.get('Seminar__c', '').strip()
            if not seminar_id:
                records.append({
                    'id': row['Id'],
                    'name': row.get('Name', ''),
                    'applicant': row.get('Applicant__c', ''),
                    'stage': row.get('Application_Stage__c', ''),
                    'app_date': row.get('App_Date__c', ''),
                    'created_date': row.get('CreatedDate', ''),
                })
    return records


def delete_records_bulk(org_alias: str, record_ids: List[str], dry_run: bool = False) -> Dict:
    """Delete records using Salesforce Bulk API via CLI."""
    if dry_run:
        print(f"  [DRY RUN] Would delete {len(record_ids)} records")
        return {
            'success': len(record_ids),
            'failed': 0,
            'errors': []
        }

    # Create a temporary CSV for bulk delete (must use CRLF line endings)
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
        writer = csv.writer(f, lineterminator='\r\n')  # Use CRLF for Salesforce bulk API
        writer.writerow(['Id'])  # Header
        for rec_id in record_ids:
            writer.writerow([rec_id])
        temp_csv = f.name

    try:
        # Use sf data delete bulk
        result = subprocess.run(
            [
                'sf', 'data', 'delete', 'bulk',
                '--sobject', 'Seminar_Application__c',
                '--file', temp_csv,
                '--target-org', org_alias,
                '--json',
                '--wait', '30',
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )

        # Parse stdout (warnings may be in stderr but JSON is in stdout)
        try:
            # Extract JSON from stdout (may have warnings before JSON)
            stdout_lines = result.stdout.strip().split('\n')
            json_start = None
            for i, line in enumerate(stdout_lines):
                if line.strip().startswith('{'):
                    json_start = i
                    break
            
            if json_start is None:
                raise ValueError("No JSON found in output")
            
            json_str = '\n'.join(stdout_lines[json_start:])
            data = json.loads(json_str)
        except Exception as e:
            print(f"  ❌ Failed to parse bulk delete response: {e}")
            print(f"  stdout: {result.stdout[:500]}")
            print(f"  stderr: {result.stderr[:500]}")
            return {
                'success': 0,
                'failed': len(record_ids),
                'errors': [f"Parse error: {str(e)}"]
            }

        # Check if there's an error in the response
        if result.returncode != 0 or data.get('status') != 0:
            error_msg = data.get('message', 'Unknown error')
            print(f"  ❌ Bulk delete error: {error_msg}")
            return {
                'success': 0,
                'failed': len(record_ids),
                'errors': [error_msg]
            }

        # Parse job result
        job_info = data.get('result', {}).get('jobInfo', {})
        records_result = data.get('result', {}).get('records', {})
        
        # Get counts from job info
        processed = job_info.get('numberRecordsProcessed', 0)
        failed = job_info.get('numberRecordsFailed', 0)
        success_count = processed - failed
        
        # Get detailed errors if any
        errors = []
        if records_result:
            failed_results = records_result.get('failedResults', [])
            for fail in failed_results:
                errors.append({
                    'id': fail.get('id', ''),
                    'error': fail.get('error', '')
                })

        return {
            'success': success_count,
            'failed': failed,
            'errors': errors
        }
    finally:
        # Clean up temp file
        Path(temp_csv).unlink(missing_ok=True)


def delete_records_individual(org_alias: str, record_ids: List[str], dry_run: bool = False) -> Dict:
    """Delete records one by one using REST API."""
    import urllib.request
    import urllib.error

    # Get org credentials
    result = subprocess.run(
        ['sf', 'org', 'display', '--target-org', org_alias, '--json'],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise Exception(f"Failed to get org info: {result.stderr}")

    data = json.loads(result.stdout)
    info = data.get('result', {})
    access_token = info.get('accessToken')
    instance_url = info.get('instanceUrl')

    success = 0
    failed = 0
    errors = []

    for i, rec_id in enumerate(record_ids, 1):
        if dry_run:
            if i <= 5 or i % 100 == 0:
                print(f"  [DRY RUN] Would delete record {i}/{len(record_ids)}: {rec_id}")
            continue

        url = f"{instance_url}/services/data/v59.0/sobjects/Seminar_Application__c/{rec_id}"
        req = urllib.request.Request(url, method='DELETE')
        req.add_header('Authorization', f'Bearer {access_token}')

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status == 204:  # No Content = success
                    success += 1
                else:
                    failed += 1
                    errors.append({'id': rec_id, 'status': resp.status, 'error': 'Unexpected status'})
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8')
            try:
                err_data = json.loads(err_body)
                # Check if the error is "entity is deleted" - this means it's already deleted, so count as success
                if isinstance(err_data, list) and len(err_data) > 0:
                    error_code = err_data[0].get('errorCode', '')
                    if error_code == 'ENTITY_IS_DELETED':
                        success += 1  # Already deleted, count as success
                    else:
                        failed += 1
                        errors.append({'id': rec_id, 'status': e.code, 'error': err_data})
                else:
                    failed += 1
                    errors.append({'id': rec_id, 'status': e.code, 'error': err_data})
            except:
                # If we can't parse the error, check if it's a 404 (likely already deleted)
                if e.code == 404:
                    success += 1  # 404 likely means already deleted
                else:
                    failed += 1
                    errors.append({'id': rec_id, 'status': e.code, 'error': err_body})
        except Exception as e:
            failed += 1
            errors.append({'id': rec_id, 'error': str(e)})

        if i % 25 == 0:
            print(f"  Progress: {i}/{len(record_ids)} (success={success}, failed={failed})")
        if i % 100 == 0:
            time.sleep(1)  # Rate limiting every 100 records
        elif i % 10 == 0:
            time.sleep(0.1)  # Small delay every 10 records

    if not dry_run:
        return {
            'success': success,
            'failed': failed,
            'errors': errors
        }
    else:
        return {
            'success': len(record_ids),
            'failed': 0,
            'errors': []
        }


def main():
    parser = argparse.ArgumentParser(
        description='Delete Seminar_Application__c records with NULL Seminar__c'
    )
    parser.add_argument('target_org', help='Target org alias (e.g., "AMSA Prod")')
    parser.add_argument('--dry-run', action='store_true', help='Dry run mode (no actual deletion)')
    parser.add_argument('--csv-file', type=Path, help='Path to CSV file (default: latest)')
    parser.add_argument('--batch-size', type=int, default=200, help='Batch size for deletions (default: 200)')
    parser.add_argument('--method', choices=['bulk', 'individual'], default='bulk',
                       help='Deletion method (default: bulk)')

    args = parser.parse_args()

    print("=" * 80)
    print("🗑️  DELETE SEMINAR APPLICATION RECORDS (NULL Seminar__c)")
    print("=" * 80)
    print()

    # Find CSV file
    if args.csv_file:
        csv_path = args.csv_file
        if not csv_path.exists():
            print(f"❌ CSV file not found: {csv_path}")
            sys.exit(1)
    else:
        try:
            csv_path = find_latest_csv()
            print(f"📂 Using CSV file: {csv_path.name}")
        except FileNotFoundError as e:
            print(f"❌ {e}")
            sys.exit(1)

    print(f"📋 Parameters:")
    print(f"  Target Org: {args.target_org}")
    print(f"  CSV File: {csv_path}")
    print(f"  Method: {args.method}")
    print(f"  Batch Size: {args.batch_size}")
    print(f"  Dry Run: {args.dry_run}")
    print()

    # Load records with NULL Seminar__c
    print("📥 Loading records with NULL Seminar__c...")
    records = load_null_seminar_records(csv_path)
    print(f"  ✅ Found {len(records)} records with NULL Seminar__c")
    print()

    if not records:
        print("✅ No records to delete!")
        sys.exit(0)

    # Show sample
    print("Sample records to delete (first 5):")
    for i, rec in enumerate(records[:5], 1):
        print(f"  {i}. ID: {rec['id']}, Name: {rec['name']}, Applicant: {rec['applicant']}")
    print()

    if args.dry_run:
        print("⚠️  DRY RUN MODE - No records will be deleted")
        print()
    else:
        # Check if running non-interactively (stdin not available or piped)
        import sys
        if sys.stdin.isatty():
            response = input(f"⚠️  Are you sure you want to delete {len(records)} records? (yes/no): ")
            if response.lower() != 'yes':
                print("❌ Deletion cancelled")
                sys.exit(0)
        else:
            print(f"⚠️  Proceeding with deletion of {len(records)} records (non-interactive mode)...")
        print()

    # Delete records
    print(f"🗑️  Deleting {len(records)} records...")
    record_ids = [rec['id'] for rec in records]

    if args.method == 'bulk':
        # Delete in batches
        total_success = 0
        total_failed = 0
        all_errors = []

        for i in range(0, len(record_ids), args.batch_size):
            batch = record_ids[i:i + args.batch_size]
            batch_num = (i // args.batch_size) + 1
            total_batches = (len(record_ids) + args.batch_size - 1) // args.batch_size

            print(f"  Batch {batch_num}/{total_batches} ({len(batch)} records)...")
            result = delete_records_bulk(args.target_org, batch, args.dry_run)
            total_success += result['success']
            total_failed += result['failed']
            all_errors.extend(result['errors'])

            if not args.dry_run and batch_num < total_batches:
                time.sleep(2)  # Rate limiting between batches

        print()
        print("=" * 80)
        print("📊 DELETION SUMMARY")
        print("=" * 80)
        print(f"Total records:     {len(record_ids)}")
        print(f"Success:           {total_success}")
        print(f"Failed:             {total_failed}")
        print("=" * 80)

        if all_errors and not args.dry_run:
            error_file = RESULTS_DIR / f'seminar_application_deletion_errors_{int(time.time())}.json'
            error_file.write_text(json.dumps(all_errors, indent=2))
            print(f"\n⚠️  Errors saved to: {error_file}")

    else:  # individual
        result = delete_records_individual(args.target_org, record_ids, args.dry_run)
        print()
        print("=" * 80)
        print("📊 DELETION SUMMARY")
        print("=" * 80)
        print(f"Total records:     {len(record_ids)}")
        print(f"Success:           {result['success']}")
        print(f"Failed:             {result['failed']}")
        print("=" * 80)

        if result['errors'] and not args.dry_run:
            error_file = RESULTS_DIR / f'seminar_application_deletion_errors_{int(time.time())}.json'
            error_file.write_text(json.dumps(result['errors'], indent=2))
            print(f"\n⚠️  Errors saved to: {error_file}")


if __name__ == '__main__':
    main()

