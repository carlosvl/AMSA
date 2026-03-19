#!/usr/bin/env python3
"""
Ghost Observership__c Record Detector and Cleaner

Detects and optionally deletes "ghost" Observership__c records that are
connected to a Contact (Applicant__c) but lack meaningful data.

Two categories:
  Category A: Missing key lookup fields (Application_Number__c AND OMI_App_Date_I__c are NULL)
  Category B: Fully empty ghosts (ALL data fields are NULL/empty except Applicant__c and auto-fields)

Usage:
  python3 delete_ghost_observerships.py <org_alias> [--dry-run] [--execute] [--category A|B|both]

Examples:
  python3 delete_ghost_observerships.py "AMSA Prod"                   # detect only (dry-run)
  python3 delete_ghost_observerships.py "AMSA Prod" --execute         # detect and delete
  python3 delete_ghost_observerships.py "AMSA Prod" --category B      # only fully-empty ghosts
"""
import argparse
import csv
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict

import db_utils

BASE_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = BASE_DIR / 'results'
RESULTS_DIR.mkdir(exist_ok=True)
BACKUP_DIR = RESULTS_DIR / 'backups'
BACKUP_DIR.mkdir(exist_ok=True)

DATA_FIELDS = [
    'Application_Stage__c', 'Application_Number__c', 'Application_Notes__c',
    'OMI_App_Date_I__c', 'Alianza_App_Date_II__c',
    'Budgeted_Cost__c', 'Actual_Cost__c', 'Actual_Cost_MXP__c',
    'EI__c', 'SI__c', 'Flight__c', 'Flight_Cost__c',
    'Rejection_Reason__c', 'Item_ID__c', 'Purchase_Date__c',
]


def run_soql(org_alias: str, query: str):
    """Run a SOQL query and return list of records."""
    result = subprocess.run(
        ['sf', 'data', 'query',
         '--query', query,
         '--target-org', org_alias,
         '--json'],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        print(f"  ❌ SOQL error: {result.stderr.strip()}")
        return []
    try:
        data = json.loads(result.stdout)
        return data.get('result', {}).get('records', [])
    except Exception as e:
        print(f"  ❌ Failed to parse SOQL JSON: {e}")
        return []


def query_all_records(org_alias: str) -> List[Dict]:
    """Query all Observership__c records with all data fields."""
    print(f"📥 Querying Observership__c from {org_alias}...")
    fields = ', '.join(['Id', 'Name', 'Applicant__c', 'CreatedDate', 'LastModifiedDate'] + DATA_FIELDS)
    query = f"SELECT {fields} FROM Observership__c"
    records = run_soql(org_alias, query)
    print(f"  ✅ Retrieved {len(records)} records")
    return records


def is_field_empty(value) -> bool:
    """Check if a field value is effectively empty."""
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == '':
        return True
    if isinstance(value, (int, float)) and value == 0:
        return False
    return False


def classify_ghosts(records: List[Dict], category: str) -> Dict[str, List[Dict]]:
    """Classify records into ghost categories."""
    print(f"\n🔍 Scanning {len(records)} records for ghost records...")

    cat_a = []  # Missing key lookup fields
    cat_b = []  # Fully empty

    for rec in records:
        if not rec.get('Applicant__c'):
            continue

        app_number = rec.get('Application_Number__c')
        app_date = rec.get('OMI_App_Date_I__c')
        missing_key = is_field_empty(app_number) and is_field_empty(app_date)

        all_empty = all(is_field_empty(rec.get(f)) for f in DATA_FIELDS)

        if category in ('A', 'both') and missing_key:
            cat_a.append(rec)
        if category in ('B', 'both') and all_empty:
            cat_b.append(rec)

    # Category B is a subset of Category A in most cases; deduplicate for "both"
    results = {}
    if category in ('A', 'both'):
        results['A'] = cat_a
        print(f"  📊 Category A (missing key lookups): {len(cat_a)} records")
    if category in ('B', 'both'):
        results['B'] = cat_b
        print(f"  📊 Category B (fully empty ghosts):  {len(cat_b)} records")

    return results


def save_backup(records_to_delete: List[Dict], timestamp: str) -> Path:
    """Save a full backup of records before deletion (JSON + CSV)."""
    all_fields = ['Id', 'Name', 'Applicant__c', 'CreatedDate', 'LastModifiedDate'] + DATA_FIELDS

    json_path = BACKUP_DIR / f'backup_observerships_{timestamp}.json'
    json_path.write_text(json.dumps({
        'backup_type': 'pre_deletion_backup',
        'object': 'Observership__c',
        'timestamp': timestamp,
        'record_count': len(records_to_delete),
        'records': records_to_delete,
    }, indent=2, default=str))

    csv_path = BACKUP_DIR / f'backup_observerships_{timestamp}.csv'
    with open(csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=all_fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(records_to_delete)

    print(f"  💾 JSON backup: {json_path}")
    print(f"  💾 CSV backup:  {csv_path}")
    return json_path


def delete_records_bulk(org_alias: str, record_ids: List[str], batch_size: int = 200) -> Dict:
    """Delete records using Salesforce Bulk API."""
    import tempfile

    total_success = 0
    total_failed = 0
    all_errors = []

    for i in range(0, len(record_ids), batch_size):
        batch = record_ids[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(record_ids) + batch_size - 1) // batch_size
        print(f"  Batch {batch_num}/{total_batches} ({len(batch)} records)...")

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            writer = csv.writer(f, lineterminator='\n')
            writer.writerow(['Id'])
            for rid in batch:
                writer.writerow([rid])
            temp_csv = f.name

        try:
            result = subprocess.run(
                ['sf', 'data', 'delete', 'bulk',
                 '--sobject', 'Observership__c',
                 '--file', temp_csv,
                 '--target-org', org_alias,
                 '--json', '--wait', '30'],
                capture_output=True, text=True, timeout=600,
            )
            try:
                stdout_lines = result.stdout.strip().split('\n')
                json_start = next((i for i, l in enumerate(stdout_lines) if l.strip().startswith('{')), None)
                if json_start is None:
                    raise ValueError("No JSON in output")
                data = json.loads('\n'.join(stdout_lines[json_start:]))
            except Exception as e:
                print(f"    ❌ Parse error: {e}")
                total_failed += len(batch)
                all_errors.append(f"Batch {batch_num}: parse error: {e}")
                continue

            if result.returncode != 0 and 'result' not in data:
                error_msg = data.get('message', 'Unknown bulk API error')
                print(f"    ❌ Bulk API error: {error_msg}")
                total_failed += len(batch)
                all_errors.append(f"Batch {batch_num}: {error_msg}")
                continue

            job_info = data.get('result', {}).get('jobInfo', {})
            processed = job_info.get('numberRecordsProcessed', 0)
            failed = job_info.get('numberRecordsFailed', 0)
            total_success += processed - failed
            total_failed += failed

            if failed:
                for fail in data.get('result', {}).get('records', {}).get('failedResults', []):
                    all_errors.append({'id': fail.get('id', ''), 'error': fail.get('error', '')})
        finally:
            Path(temp_csv).unlink(missing_ok=True)

        if batch_num < total_batches:
            time.sleep(2)

    return {'success': total_success, 'failed': total_failed, 'errors': all_errors}


def generate_report(ghost_results: Dict, org_alias: str) -> str:
    """Generate a human-readable report."""
    lines = [
        "=" * 80, "GHOST OBSERVERSHIP RECORDS REPORT", "=" * 80, "",
        f"Org: {org_alias}",
        f"Report Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "",
        "=" * 80, "SUMMARY", "=" * 80,
    ]
    for cat, recs in ghost_results.items():
        label = "Missing key lookups" if cat == 'A' else "Fully empty ghosts"
        lines.append(f"Category {cat} ({label}): {len(recs)} records")
    lines.append("")

    for cat, recs in ghost_results.items():
        if not recs:
            continue
        label = "Missing key lookups" if cat == 'A' else "Fully empty ghosts"
        lines += ["=" * 80, f"CATEGORY {cat}: {label} ({len(recs)} records)", "=" * 80, ""]
        for rec in recs[:30]:
            lines.append(f"  ID: {rec['Id']}  Name: {rec.get('Name', 'N/A')}  Applicant: {rec.get('Applicant__c', 'N/A')}")
        if len(recs) > 30:
            lines.append(f"  ... and {len(recs) - 30} more")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description='Detect and delete ghost Observership__c records')
    parser.add_argument('org_alias', help='Salesforce org alias')
    parser.add_argument('--execute', action='store_true', help='Actually delete records (default is dry-run)')
    parser.add_argument('--category', choices=['A', 'B', 'both'], default='both',
                        help='Which category to process (default: both)')
    parser.add_argument('--batch-size', type=int, default=200)
    parser.add_argument('--export-csv', action='store_true')
    args = parser.parse_args()

    dry_run = not args.execute

    print("=" * 80)
    print("👻 GHOST OBSERVERSHIP RECORD DETECTOR")
    print("=" * 80)
    print(f"\n📋 Org: {args.org_alias}")
    print(f"   Category: {args.category}")
    print(f"   Mode: {'DRY RUN' if dry_run else 'EXECUTE (will delete)'}\n")

    records = query_all_records(args.org_alias)
    if not records:
        print("⚠️  No Observership__c records found")
        sys.exit(0)

    ghost_results = classify_ghosts(records, args.category)

    total_ghosts = sum(len(v) for v in ghost_results.values())
    if total_ghosts == 0:
        print("\n✅ No ghost records found!")
        sys.exit(0)

    report_text = generate_report(ghost_results, args.org_alias)
    print("\n" + report_text)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_path = RESULTS_DIR / f'ghost_observerships_{timestamp}.txt'
    report_path.write_text(report_text)
    print(f"📄 Report: {report_path}")

    if args.export_csv:
        for cat, recs in ghost_results.items():
            if not recs:
                continue
            csv_path = RESULTS_DIR / f'ghost_observerships_cat{cat}_{timestamp}.csv'
            with open(csv_path, 'w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['Id', 'Name', 'Applicant__c', 'CreatedDate'] + DATA_FIELDS)
                for rec in recs:
                    writer.writerow([rec.get('Id'), rec.get('Name'), rec.get('Applicant__c'),
                                     rec.get('CreatedDate')] + [rec.get(fld) for fld in DATA_FIELDS])
            print(f"📄 CSV (Category {cat}): {csv_path}")

    # Log run in database
    run_id = db_utils.create_comparison_run(
        run_type='ghost_observership_detection',
        source_org=args.org_alias,
        notes=f"Category={args.category}, ghosts_found={total_ghosts}, mode={'dry_run' if dry_run else 'execute'}",
    )
    db_utils.update_comparison_run(
        run_id=run_id,
        total_source_records=len(records),
        matched_count=total_ghosts,
        status='completed' if dry_run else 'in_progress',
    )

    # Always save a backup of detected ghost records (even in dry-run)
    seen_ids = set()
    all_ghost_records = []
    for recs in ghost_results.values():
        for rec in recs:
            if rec['Id'] not in seen_ids:
                seen_ids.add(rec['Id'])
                all_ghost_records.append(rec)

    print(f"\n💾 Saving backup of {len(all_ghost_records)} ghost records...")
    save_backup(all_ghost_records, timestamp)

    if dry_run:
        print(f"\n{'=' * 80}")
        print("⚠️  DRY RUN - No records were deleted")
        print(f"{'=' * 80}")
        print(f"\nTo delete these records, re-run with --execute:")
        print(f"  python3 delete_ghost_observerships.py \"{args.org_alias}\" --category {args.category} --execute")
        return

    print(f"\n🗑️  Preparing to delete {len(all_ghost_records)} ghost records...")

    if sys.stdin.isatty():
        response = input(f"⚠️  Are you sure you want to delete {len(all_ghost_records)} records? (yes/no): ")
        if response.lower() != 'yes':
            print("❌ Deletion cancelled")
            db_utils.update_comparison_run(run_id, status='cancelled')
            sys.exit(0)

    ids_to_delete = [rec['Id'] for rec in all_ghost_records]
    result = delete_records_bulk(args.org_alias, ids_to_delete, args.batch_size)

    print(f"\n{'=' * 80}")
    print("📊 DELETION SUMMARY")
    print(f"{'=' * 80}")
    print(f"Total records:  {len(ids_to_delete)}")
    print(f"Success:        {result['success']}")
    print(f"Failed:         {result['failed']}")
    print(f"{'=' * 80}")

    db_utils.update_comparison_run(
        run_id=run_id, status='completed',
        notes=f"Deleted: {result['success']} success, {result['failed']} failed",
    )

    if result['errors']:
        error_path = RESULTS_DIR / f'ghost_observership_errors_{timestamp}.json'
        error_path.write_text(json.dumps(result['errors'], indent=2))
        print(f"\n⚠️  Errors saved to: {error_path}")


if __name__ == '__main__':
    main()
