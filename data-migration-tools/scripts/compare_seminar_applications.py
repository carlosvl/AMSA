#!/usr/bin/env python3
"""
Compare Seminar_Application__c records between two orgs.

Goal: Identify Seminar_Application__c records in the target org that don't exist
in the source org, based on the combination of Applicant__c (Contact) and
Seminar__c (Campaign). These extra records may need to be deleted.

Results are stored in SQLite database. Use --export-json or --export-csv 
to also generate legacy file formats.

Usage:
  python3 compare_seminar_applications.py <source_org> <target_org> [--export-json] [--export-csv]

Example:
  python3 compare_seminar_applications.py "AMSA-Royalty-Prod" "AMSA Prod"
"""

import json
import subprocess
import sys
import argparse
from datetime import datetime
from pathlib import Path

import db_utils

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / 'data'
RESULTS_DIR = BASE_DIR / 'results'


def run_soql(org_alias: str, query: str):
    """Run a SOQL query and return list of records (or [])."""
    result = subprocess.run(
        [
            'sf', 'data', 'query',
            '--query', query,
            '--target-org', org_alias,
            '--json',
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.returncode != 0:
        print(f"  ❌ SOQL error for org {org_alias}:")
        print(result.stderr.strip())
        return []

    try:
        data = json.loads(result.stdout)
        return data.get('result', {}).get('records', [])
    except Exception as e:
        print(f"  ❌ Failed to parse SOQL JSON for org {org_alias}: {e}")
        return []


def load_mappings():
    """Load ID mappings from database"""
    print("📂 Loading ID mappings from database...")
    
    contact_map = db_utils.get_id_mappings('Contact')
    campaign_map = db_utils.get_id_mappings('Campaign')
    
    print(f"  ✅ Contact mappings:  {len(contact_map)} entries")
    print(f"  ✅ Campaign mappings: {len(campaign_map)} entries")
    
    if not contact_map:
        print("  ⚠️  Warning: No contact mappings found in database")
    if not campaign_map:
        print("  ⚠️  Warning: No campaign mappings found in database")
    
    return contact_map, campaign_map


def query_all_applications(org_alias: str):
    """Query all Seminar_Application__c records from an org."""
    print(f"📥 Querying ALL Seminar_Application__c from {org_alias}...")

    query = (
        "SELECT Id, Applicant__c, Seminar__c, Application_Stage__c, "
        "App_Date__c, CreatedDate, Name "
        "FROM Seminar_Application__c"
    )

    records = run_soql(org_alias, query)
    print(f"  ✅ Retrieved {len(records)} Seminar_Application__c records")
    return records


def build_application_key(applicant_id: str, seminar_id: str = None) -> str:
    """Build a unique key for a Seminar_Application__c record.
    
    Uses Applicant__c + Seminar__c as the key. If Seminar__c is null,
    uses only Applicant__c (though this should be rare).
    """
    if seminar_id:
        return f"{applicant_id}|{seminar_id}"
    else:
        return f"{applicant_id}|NULL"


def compare_applications(source_records, target_records, contact_map, campaign_map):
    print("\n🔍 Comparing Seminar_Application__c records (Applicant + Seminar)...")

    # Map source applications into target IDs
    source_keys = set()
    unmapped_source = []
    source_details = {}  # key -> record details

    for app in source_records:
        src_applicant = app.get('Applicant__c')
        src_seminar = app.get('Seminar__c')
        
        if not src_applicant:
            # Skip records without Applicant (shouldn't happen due to master-detail)
            continue

        # Map Applicant (Contact)
        if src_applicant not in contact_map:
            unmapped_source.append({
                'id': app.get('Id'),
                'applicant': src_applicant,
                'seminar': src_seminar,
                'reason': 'Applicant not mapped'
            })
            continue

        tgt_applicant = contact_map[src_applicant]

        # Map Seminar (Campaign) if present
        tgt_seminar = None
        if src_seminar:
            if src_seminar not in campaign_map:
                unmapped_source.append({
                    'id': app.get('Id'),
                    'applicant': src_applicant,
                    'seminar': src_seminar,
                    'reason': 'Seminar not mapped'
                })
                continue
            tgt_seminar = campaign_map[src_seminar]

        key = build_application_key(tgt_applicant, tgt_seminar)
        source_keys.add(key)
        source_details[key] = {
            'source_id': app.get('Id'),
            'target_applicant': tgt_applicant,
            'target_seminar': tgt_seminar,
            'stage': app.get('Application_Stage__c'),
            'app_date': app.get('App_Date__c'),
        }

    print(f"  📊 Source mapped applications: {len(source_keys)}")
    print(f"  ⚠️  Source unmapped applications: {len(unmapped_source)}")

    # Build target applications
    target_keys = set()
    target_details = {}  # key -> list of records (can have duplicates)
    extra_records = []  # Records in target that don't exist in source

    for app in target_records:
        applicant = app.get('Applicant__c')
        seminar = app.get('Seminar__c')
        
        if not applicant:
            continue

        key = build_application_key(applicant, seminar)
        target_keys.add(key)
        
        if key not in target_details:
            target_details[key] = []
        target_details[key].append({
            'id': app.get('Id'),
            'applicant': applicant,
            'seminar': seminar,
            'stage': app.get('Application_Stage__c'),
            'app_date': app.get('App_Date__c'),
            'created_date': app.get('CreatedDate'),
            'name': app.get('Name'),
        })

        # Check if this key exists in source
        if key not in source_keys:
            extra_records.append({
                'id': app.get('Id'),
                'name': app.get('Name'),
                'applicant_id': applicant,
                'seminar_id': seminar,
                'stage': app.get('Application_Stage__c'),
                'app_date': app.get('App_Date__c'),
                'created_date': app.get('CreatedDate'),
            })

    print(f"  📊 Target applications: {len(target_keys)}")

    matched = source_keys & target_keys
    missing = source_keys - target_keys
    extra = target_keys - source_keys

    print(f"  ✅ Matched application keys: {len(matched)}")
    print(f"  ❌ Missing application keys in target: {len(missing)}")
    print(f"  ⚠️  Extra application keys in target (no source match): {len(extra)}")
    print(f"  🗑️  Extra records in target (for deletion): {len(extra_records)}")

    return {
        'source_mapped_applications': len(source_keys),
        'unmapped_source_applications': len(unmapped_source),
        'target_applications': len(target_keys),
        'matched_keys': len(matched),
        'missing_keys': len(missing),
        'extra_keys': len(extra),
        'extra_records': extra_records,
        'unmapped_source_details': unmapped_source,
    }


def generate_report(results, source_org, target_org):
    lines = []
    lines.append("=" * 80)
    lines.append("SEMINAR APPLICATION COMPARISON REPORT")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"Source Org: {source_org}")
    lines.append(f"Target Org: {target_org}")
    lines.append(f"Report Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("=" * 80)
    lines.append("SUMMARY")
    lines.append("=" * 80)
    lines.append(f"Source mapped applications:        {results['source_mapped_applications']}")
    lines.append(f"Unmapped source applications:      {results['unmapped_source_applications']}")
    lines.append(f"Target applications:               {results['target_applications']}")
    lines.append(f"Matched application keys:         {results['matched_keys']}")
    lines.append(f"Missing keys in target:           {results['missing_keys']}")
    lines.append(f"Extra keys in target:             {results['extra_keys']}")
    lines.append(f"Extra records for deletion:      {len(results['extra_records'])}")
    lines.append("")

    if results['extra_records']:
        lines.append("=" * 80)
        lines.append("EXTRA RECORDS IN TARGET (Candidates for Deletion)")
        lines.append("=" * 80)
        lines.append("")
        lines.append(f"Total extra records: {len(results['extra_records'])}")
        lines.append("")
        lines.append("Sample records (first 50):")
        lines.append("")
        for rec in results['extra_records'][:50]:
            lines.append(f"  🗑️  ID: {rec['id']}")
            lines.append(f"      Name: {rec.get('name', 'N/A')}")
            lines.append(f"      Applicant: {rec['applicant_id']}")
            lines.append(f"      Seminar: {rec.get('seminar_id', 'NULL')}")
            lines.append(f"      Stage: {rec.get('stage', 'N/A')}")
            lines.append(f"      App Date: {rec.get('app_date', 'N/A')}")
            lines.append(f"      Created: {rec.get('created_date', 'N/A')}")
            lines.append("")
        if len(results['extra_records']) > 50:
            lines.append(f"... and {len(results['extra_records']) - 50} more records")
        lines.append("")

    if results['unmapped_source_applications']:
        lines.append("=" * 80)
        lines.append("UNMAPPED SOURCE APPLICATIONS")
        lines.append("=" * 80)
        lines.append("")
        for rec in results['unmapped_source_details'][:20]:
            lines.append(f"  ⚠️  ID: {rec['id']}")
            lines.append(f"      Reason: {rec['reason']}")
            lines.append(f"      Applicant: {rec['applicant']}")
            lines.append(f"      Seminar: {rec.get('seminar', 'NULL')}")
            lines.append("")
        if len(results['unmapped_source_details']) > 20:
            lines.append(f"... and {len(results['unmapped_source_details']) - 20} more")
        lines.append("")

    return "\n".join(lines)


def main():
    print("=" * 80)
    print("📊 SEMINAR APPLICATION COMPARISON TOOL")
    print("=" * 80)
    print()

    # Parse arguments
    parser = argparse.ArgumentParser(
        description='Compare Seminar Applications between two Salesforce orgs'
    )
    parser.add_argument('source_org', help='Source org alias')
    parser.add_argument('target_org', help='Target org alias')
    parser.add_argument('--export-json', action='store_true',
                        help='Export results to JSON file (legacy format)')
    parser.add_argument('--export-csv', action='store_true',
                        help='Export results to CSV file (legacy format)')
    
    args = parser.parse_args()
    
    source_org = args.source_org
    target_org = args.target_org

    print("📋 Parameters:")
    print(f"  Source Org: {source_org}")
    print(f"  Target Org: {target_org}")
    print(f"  Storage: SQLite database")
    if args.export_json:
        print(f"  Export: JSON enabled")
    if args.export_csv:
        print(f"  Export: CSV enabled")
    print()

    # Create database run
    print("💾 Initializing database...")
    run_id = db_utils.create_comparison_run(
        run_type='seminar_application_comparison',
        source_org=source_org,
        target_org=target_org
    )
    print(f"  ✅ Run ID: {run_id}")
    print()

    try:
        contact_map, campaign_map = load_mappings()
        if not contact_map and not campaign_map:
            db_utils.update_comparison_run(run_id, status='failed',
                                          notes='No ID mappings found')
            print("❌ No ID mappings found in database")
            sys.exit(1)
        print()

        src_apps = query_all_applications(source_org)
        tgt_apps = query_all_applications(target_org)

        results = compare_applications(src_apps, tgt_apps, contact_map, campaign_map)

        # Save matches to database
        print("\n💾 Saving results to database...")
        
        # Save matched applications
        matched_apps = []
        for key in results.get('matched_keys', []):
            matched_apps.append({
                'match_status': 'matched',
                'record_id': key
            })
        
        # Save extra records (in target, not in source)
        for rec in results['extra_records']:
            matched_apps.append({
                'record_id': rec['id'],
                'applicant_id': rec['applicant_id'],
                'seminar_id': rec.get('seminar_id'),
                'match_status': 'extra',
                'stage': rec.get('stage'),
                'app_date': rec.get('app_date')
            })
        
        db_utils.save_seminar_app_matches(run_id, matched_apps)
        
        # Update run statistics
        db_utils.update_comparison_run(
            run_id,
            total_source_records=results['source_mapped_applications'],
            total_target_records=results['target_applications'],
            matched_count=results['matched_keys'],
            unmatched_count=results['missing_keys'],
            status='completed'
        )
        
        print(f"  ✅ Saved {len(matched_apps)} application records")
        
        # Export if requested
        if args.export_json or args.export_csv:
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            if args.export_json:
                json_path = RESULTS_DIR / f'seminar_application_comparison_{timestamp}.json'
                db_utils.export_run_to_json(run_id, json_path)
                
                txt_path = RESULTS_DIR / f'seminar_application_comparison_{timestamp}.txt'
                txt_path.write_text(generate_report(results, source_org, target_org))
                
                print(f"  📄 Exported to JSON: {json_path}")
                print(f"  📄 Exported report: {txt_path}")
            
            if args.export_csv and results['extra_records']:
                import csv
                csv_path = RESULTS_DIR / f'seminar_application_extra_records_{timestamp}.csv'
                with csv_path.open('w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        'Id', 'Name', 'Applicant__c', 'Seminar__c', 
                        'Application_Stage__c', 'App_Date__c', 'CreatedDate'
                    ])
                    for rec in results['extra_records']:
                        writer.writerow([
                            rec['id'],
                            rec.get('name', ''),
                            rec['applicant_id'],
                            rec.get('seminar_id', ''),
                            rec.get('stage', ''),
                            rec.get('app_date', ''),
                            rec.get('created_date', ''),
                        ])
                print(f"  📄 Exported to CSV: {csv_path}")

        print("\n" + "=" * 80)
        print("✅ Comparison completed successfully!")
        print("=" * 80)
        print(f"Run ID: {run_id}")
        print(f"Database: {db_utils.DB_PATH}")
        print(f"\nUse query_results.py to view results:")
        print(f"  python3 query_results.py run-details {run_id}")
        print("=" * 80)
    
    except Exception as e:
        db_utils.update_comparison_run(run_id, status='failed',
                                      notes=f'Error: {str(e)}')
        raise


if __name__ == '__main__':
    main()

