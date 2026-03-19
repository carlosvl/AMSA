#!/usr/bin/env python3
"""
Observership__c Duplicate Detection Tool
Detects duplicate Observership__c records within a single Salesforce org.

Duplicate key: Applicant__c + Application_Number__c (fallback to OMI_App_Date_I__c).

Usage:
    python3 detect_observership_duplicates.py <org_alias> [--export-json] [--export-csv]

Example:
    python3 detect_observership_duplicates.py "AMSA Prod"
    python3 detect_observership_duplicates.py "AMSA Prod" --export-json
"""
import json
import subprocess
import sys
import argparse
import csv
from datetime import datetime
from pathlib import Path
from collections import defaultdict

import db_utils

BASE_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = BASE_DIR / 'results'
RESULTS_DIR.mkdir(exist_ok=True)

OBJECT_TYPE = 'Observership__c'
RUN_TYPE = 'observership__c_duplicate_detection'


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


def get_org_credentials(org_alias):
    """Validate org connectivity."""
    try:
        result = subprocess.run(
            ['sf', 'org', 'display', '--target-org', org_alias, '--json'],
            capture_output=True, text=True, check=True, timeout=30,
        )
        data = json.loads(result.stdout)
        return {
            'alias': org_alias,
            'username': data['result']['username'],
            'instance_url': data['result']['instanceUrl'],
        }
    except Exception as e:
        print(f"❌ Error connecting to {org_alias}: {e}")
        return None


def query_all_records(org_alias):
    """Query all Observership__c records."""
    print(f"📥 Querying Observership__c from {org_alias}...")
    query = """
        SELECT Id, Name, Applicant__c, Application_Stage__c, Application_Number__c,
               Application_Notes__c, OMI_App_Date_I__c, Alianza_App_Date_II__c,
               Budgeted_Cost__c, Actual_Cost__c, Actual_Cost_MXP__c,
               EI__c, SI__c, Flight__c, Flight_Cost__c,
               Rejection_Reason__c, Item_ID__c, Purchase_Date__c,
               CreatedDate, LastModifiedDate
        FROM Observership__c
        ORDER BY Applicant__c, Application_Number__c
    """
    records = run_soql(org_alias, query)
    print(f"  ✅ Found {len(records)} records")
    return records


def build_duplicate_key(record):
    """Build composite key: Applicant + ApplicationNumber (fallback to date)."""
    applicant = record.get('Applicant__c') or 'NULL'
    secondary = record.get('Application_Number__c') or record.get('OMI_App_Date_I__c') or 'UNKNOWN'
    return f"{applicant}|{secondary}"


def detect_duplicates(records):
    """Group records by key and find groups with more than one member."""
    print(f"\n🔍 Analyzing {len(records)} Observership__c records for duplicates...")

    groups = defaultdict(list)
    for rec in records:
        key = build_duplicate_key(rec)
        groups[key].append(rec)

    duplicate_groups = {}
    total_duplicates = 0

    for key, recs in groups.items():
        if len(recs) > 1:
            recs.sort(key=lambda x: x.get('LastModifiedDate') or '', reverse=True)
            duplicate_groups[key] = {
                'group_key': key,
                'applicant': recs[0].get('Applicant__c'),
                'application_number': recs[0].get('Application_Number__c'),
                'records': recs,
                'count': len(recs),
            }
            total_duplicates += len(recs)

    print(f"  📊 Found {len(duplicate_groups)} duplicate groups")
    print(f"  📊 Total duplicate records: {total_duplicates}")
    print(f"  📊 Unique records: {len(records) - total_duplicates + len(duplicate_groups)}")
    return duplicate_groups


def generate_report(duplicate_groups, org_alias):
    """Generate a human-readable text report."""
    total_groups = len(duplicate_groups)
    total_records = sum(g['count'] for g in duplicate_groups.values())

    lines = [
        "=" * 80,
        "OBSERVERSHIP DUPLICATE DETECTION REPORT",
        "=" * 80, "",
        f"Org: {org_alias}",
        f"Report Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", "",
        "=" * 80, "SUMMARY", "=" * 80,
        f"Total Duplicate Groups: {total_groups}",
        f"Total Duplicate Records: {total_records}",
        f"Unique Observerships Affected: {total_groups}", "",
    ]

    if duplicate_groups:
        lines += ["=" * 80, f"DUPLICATE GROUPS ({total_groups} groups)", "=" * 80, ""]
        sorted_groups = sorted(duplicate_groups.values(), key=lambda x: x['count'], reverse=True)
        for idx, group in enumerate(sorted_groups[:50], 1):
            lines.append(f"Group {idx}: Applicant={group['applicant']}  AppNumber={group.get('application_number', 'N/A')}")
            lines.append(f"  Duplicate Count: {group['count']}")
            lines.append("  Records:")
            for rec in group['records']:
                lines.append(f"    - ID: {rec['Id']}")
                lines.append(f"      Name: {rec.get('Name', 'N/A')}")
                lines.append(f"      Stage: {rec.get('Application_Stage__c', 'N/A')}")
                lines.append(f"      Created: {rec.get('CreatedDate', 'N/A')}")
                lines.append(f"      Last Modified: {rec.get('LastModifiedDate', 'N/A')}")
            lines.append("")
        if len(sorted_groups) > 50:
            lines.append(f"  ... and {len(sorted_groups) - 50} more duplicate groups\n")
    else:
        lines.append("✅ No duplicates found!\n")

    return "\n".join(lines)


def show_existing_runs():
    """Display existing runs from the database."""
    runs = db_utils.get_duplicate_detection_runs(OBJECT_TYPE)
    if not runs:
        print("  📭 No existing duplicate detection runs found")
        return []

    print(f"\n  📊 Found {len(runs)} existing run(s):")
    print("  " + "-" * 76)
    print(f"  {'Run ID':<8} {'Date':<20} {'Org':<25} {'Groups':<8} {'Status':<10}")
    print("  " + "-" * 76)
    for run in runs:
        ts = run.get('timestamp', 'N/A')
        try:
            ts = datetime.fromisoformat(str(ts).replace('Z', '+00:00')).strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            ts = str(ts)[:19]
        print(f"  {run['id']:<8} {ts:<20} {(run.get('source_org') or 'N/A')[:24]:<25} "
              f"{run.get('matched_count', 0):<8} {run.get('status', 'N/A'):<10}")
    print("  " + "-" * 76 + "\n")
    return runs


def prompt_clear_results():
    """Interactive prompt to manage existing results."""
    runs = show_existing_runs()
    if not runs:
        return True

    print("⚠️  Existing duplicate detection results found.")
    print("  1. Clear ALL existing results and run fresh")
    print("  2. Keep existing and add new run")
    print("  3. Exit")

    while True:
        choice = input("\nEnter choice (1-3): ").strip()
        if choice == '1':
            confirm = input("  ⚠️  Delete ALL results? (yes/no): ").strip().lower()
            if confirm in ('yes', 'y'):
                r, g, d = db_utils.delete_all_duplicate_groups(OBJECT_TYPE)
                print(f"  ✅ Deleted {r} run(s), {g} group(s), {d} record(s)")
                return True
            return False
        elif choice == '2':
            return True
        elif choice == '3':
            sys.exit(0)
        print("  ❌ Invalid choice.")


def main():
    parser = argparse.ArgumentParser(description='Detect duplicate Observership__c records')
    parser.add_argument('org_alias', help='Salesforce org alias')
    parser.add_argument('--export-json', action='store_true')
    parser.add_argument('--export-csv', action='store_true')
    parser.add_argument('--clear-all', action='store_true')
    parser.add_argument('--no-prompt', action='store_true')
    args = parser.parse_args()

    print("=" * 80)
    print("🔍 OBSERVERSHIP DUPLICATE DETECTION TOOL")
    print("=" * 80)
    print(f"\n📋 Org: {args.org_alias}")
    print(f"   Matching Fields: Applicant__c + Application_Number__c (fallback OMI_App_Date_I__c)\n")

    org_info = get_org_credentials(args.org_alias)
    if not org_info:
        sys.exit(1)
    print(f"  ✅ Connected: {org_info['username']} ({org_info['instance_url']})\n")

    db_utils.init_database()

    if args.clear_all:
        r, g, d = db_utils.delete_all_duplicate_groups(OBJECT_TYPE)
        print(f"🗑️  Cleared {r} run(s), {g} group(s), {d} record(s)\n")
    elif not args.no_prompt:
        if not prompt_clear_results():
            sys.exit(0)

    records = query_all_records(args.org_alias)
    if not records:
        print("\n⚠️  No Observership__c records found")
        sys.exit(0)

    duplicate_groups = detect_duplicates(records)

    run_id = db_utils.create_comparison_run(
        run_type=RUN_TYPE,
        source_org=args.org_alias,
        notes='Duplicate detection: Applicant + ApplicationNumber/Date',
    )

    print(f"\n💾 Saving results to database...")
    saved = 0
    for group_key, group_data in duplicate_groups.items():
        recs = group_data['records']
        for i, rec in enumerate(recs):
            rec['is_keeper'] = 1 if i == 0 else 0
        db_utils.save_duplicate_group(
            run_id=run_id, object_type=OBJECT_TYPE,
            group_key=group_key, records=recs, action='pending',
        )
        saved += 1
    print(f"  ✅ Saved {saved} duplicate groups")

    db_utils.update_comparison_run(
        run_id=run_id,
        total_source_records=len(records),
        matched_count=len(duplicate_groups),
        unmatched_count=len(records) - sum(g['count'] for g in duplicate_groups.values()) + len(duplicate_groups),
        status='completed',
    )

    report_text = generate_report(duplicate_groups, args.org_alias)
    print("\n" + report_text)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    if args.export_json:
        path = RESULTS_DIR / f'observership_duplicates_{timestamp}.json'
        path.write_text(json.dumps({
            'metadata': {'org_alias': args.org_alias, 'run_id': run_id, 'timestamp': timestamp},
            'summary': {
                'total_records': len(records),
                'duplicate_groups': len(duplicate_groups),
                'total_duplicate_records': sum(g['count'] for g in duplicate_groups.values()),
            },
            'duplicate_groups': {k: {**v, 'records': v['records']} for k, v in duplicate_groups.items()},
        }, indent=2, default=str))
        print(f"📄 JSON: {path}")

    if args.export_csv:
        path = RESULTS_DIR / f'observership_duplicates_{timestamp}.csv'
        with open(path, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Group Key', 'Applicant', 'App Number', 'Record ID', 'Name',
                             'Stage', 'Created Date', 'Last Modified Date', 'Is Keeper'])
            for gk, gd in duplicate_groups.items():
                for rec in gd['records']:
                    writer.writerow([
                        gk, gd['applicant'], gd.get('application_number', ''),
                        rec['Id'], rec.get('Name', ''), rec.get('Application_Stage__c', ''),
                        rec.get('CreatedDate', ''), rec.get('LastModifiedDate', ''),
                        'Yes' if rec.get('is_keeper') else 'No',
                    ])
        print(f"📄 CSV: {path}")

    report_path = RESULTS_DIR / f'observership_duplicates_{timestamp}.txt'
    report_path.write_text(report_text)
    print(f"📄 Report: {report_path}")

    print(f"\n{'=' * 80}")
    print(f"✅ Duplicate detection complete!  Run ID: {run_id}")
    print(f"   Database: {db_utils.DB_PATH}")
    print(f"{'=' * 80}")


if __name__ == '__main__':
    main()
