#!/usr/bin/env python3
"""
Replica__c Comparison Tool
Compares Replica__c records between two Salesforce orgs.

Replica__c has a Lookup relationship to Contact (Replica__c field - confusingly named).
The Replica__c field points to Contact (labeled "Contact" in the UI).

Results are stored in SQLite database.

Usage:
  python3 compare_replicas.py <source_org> <target_org> [--export-json] [--export-csv]

Example:
  python3 compare_replicas.py 'AMSA-Royalty-Prod' 'AMSA Prod'
"""

import json
import subprocess
import sys
import argparse
from datetime import datetime
from pathlib import Path

import db_utils

BASE_DIR = Path(__file__).resolve().parents[1]
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
    
    print(f"  ✅ Contact mappings:  {len(contact_map)} entries")
    
    if not contact_map:
        print("  ⚠️  Warning: No Contact mappings found in database")
    
    return contact_map


def query_replicas(org_alias: str):
    """Query all Replica__c records from an org."""
    print(f"📥 Querying Replica__c from {org_alias}...")

    query = """
        SELECT Id, Name, Replica__c, Date__c, End_date__c, 
               Place__c, Type_of_replica__c, Nu__c, Other__c,
               CreatedDate, LastModifiedDate
        FROM Replica__c
    """

    records = run_soql(org_alias, query)
    print(f"  ✅ Retrieved {len(records)} Replica__c records")
    return records


def build_replica_key(contact_id: str, date: str = None, place: str = None) -> str:
    """Build a unique key for a Replica__c record.
    
    Uses Replica__c (Contact) + Date__c + Place__c as the key.
    """
    date_key = date or 'NODATE'
    place_key = (place or 'NOPLACE').strip().lower()
    return f"{contact_id}|{date_key}|{place_key}"


def compare_replicas(source_records, target_records, contact_map):
    """Compare Replica__c records between source and target."""
    print("\n🔍 Comparing Replica__c records...")

    # Map source records into target IDs
    source_keys = set()
    unmapped_source = []
    source_details = {}

    for rec in source_records:
        src_contact = rec.get('Replica__c')  # This is the Contact lookup field
        date = rec.get('Date__c')
        place = rec.get('Place__c')
        
        if not src_contact:
            unmapped_source.append({
                'id': rec.get('Id'),
                'reason': 'Missing Replica__c (Contact)'
            })
            continue

        # Map Contact
        if src_contact not in contact_map:
            unmapped_source.append({
                'id': rec.get('Id'),
                'contact': src_contact,
                'reason': 'Contact not mapped'
            })
            continue

        tgt_contact = contact_map[src_contact]

        key = build_replica_key(tgt_contact, date, place)
        source_keys.add(key)
        source_details[key] = {
            'source_id': rec.get('Id'),
            'target_contact': tgt_contact,
            'date': date,
            'place': place,
            'type': rec.get('Type_of_replica__c'),
        }

    print(f"  📊 Source mapped records: {len(source_keys)}")
    print(f"  ⚠️  Source unmapped records: {len(unmapped_source)}")

    # Build target records
    target_keys = set()
    target_details = {}
    extra_records = []

    for rec in target_records:
        contact = rec.get('Replica__c')
        date = rec.get('Date__c')
        place = rec.get('Place__c')
        
        if not contact:
            continue

        key = build_replica_key(contact, date, place)
        target_keys.add(key)
        target_details[key] = {
            'id': rec.get('Id'),
            'contact': contact,
            'date': date,
            'place': place,
        }

        # Check if this key exists in source
        if key not in source_keys:
            extra_records.append({
                'id': rec.get('Id'),
                'name': rec.get('Name'),
                'contact_id': contact,
                'date': date,
                'place': place,
            })

    print(f"  📊 Target records: {len(target_keys)}")

    matched = source_keys & target_keys
    missing = source_keys - target_keys
    extra = target_keys - source_keys

    print(f"  ✅ Matched keys: {len(matched)}")
    print(f"  ❌ Missing keys in target: {len(missing)}")
    print(f"  ⚠️  Extra keys in target: {len(extra)}")

    # Build missing records list for migration
    missing_records = []
    for key in missing:
        if key in source_details:
            missing_records.append(source_details[key])

    return {
        'source_mapped_records': len(source_keys),
        'unmapped_source_records': len(unmapped_source),
        'target_records': len(target_keys),
        'matched_keys': len(matched),
        'missing_keys': len(missing),
        'extra_keys': len(extra),
        'missing_records': missing_records,
        'extra_records': extra_records,
        'unmapped_source_details': unmapped_source,
    }


def generate_report(results, source_org, target_org):
    """Generate detailed comparison report."""
    lines = []
    lines.append("=" * 80)
    lines.append("REPLICA COMPARISON REPORT")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"Source Org: {source_org}")
    lines.append(f"Target Org: {target_org}")
    lines.append(f"Report Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("=" * 80)
    lines.append("SUMMARY")
    lines.append("=" * 80)
    lines.append(f"Source mapped records:    {results['source_mapped_records']}")
    lines.append(f"Unmapped source records:  {results['unmapped_source_records']}")
    lines.append(f"Target records:           {results['target_records']}")
    lines.append(f"Matched keys:             {results['matched_keys']}")
    lines.append(f"Missing keys in target:   {results['missing_keys']}")
    lines.append(f"Extra keys in target:     {results['extra_keys']}")
    lines.append("")

    if results['missing_records']:
        lines.append("=" * 80)
        lines.append("MISSING IN TARGET (Need to Create)")
        lines.append("=" * 80)
        lines.append("")
        for rec in results['missing_records'][:50]:
            lines.append(f"❌ Source ID: {rec['source_id']}")
            lines.append(f"   Contact: {rec['target_contact']}")
            lines.append(f"   Date: {rec.get('date', 'N/A')}")
            lines.append(f"   Place: {rec.get('place', 'N/A')}")
            lines.append(f"   Type: {rec.get('type', 'N/A')}")
            lines.append("")
        if len(results['missing_records']) > 50:
            lines.append(f"... and {len(results['missing_records']) - 50} more")
        lines.append("")

    if results['unmapped_source_details']:
        lines.append("=" * 80)
        lines.append("UNMAPPED SOURCE RECORDS")
        lines.append("=" * 80)
        lines.append("")
        for rec in results['unmapped_source_details'][:20]:
            lines.append(f"⚠️  ID: {rec['id']}")
            lines.append(f"   Reason: {rec['reason']}")
            lines.append("")
        if len(results['unmapped_source_details']) > 20:
            lines.append(f"... and {len(results['unmapped_source_details']) - 20} more")
        lines.append("")

    return "\n".join(lines)


def main():
    print("=" * 80)
    print("🔄 REPLICA COMPARISON TOOL")
    print("=" * 80)
    print()

    parser = argparse.ArgumentParser(
        description='Compare Replica__c records between two Salesforce orgs'
    )
    parser.add_argument('source_org', help='Source org alias')
    parser.add_argument('target_org', help='Target org alias')
    parser.add_argument('--export-json', action='store_true',
                        help='Export results to JSON file')
    parser.add_argument('--export-csv', action='store_true',
                        help='Export results to CSV file')
    
    args = parser.parse_args()
    
    source_org = args.source_org
    target_org = args.target_org

    print("📋 Parameters:")
    print(f"  Source Org: {source_org}")
    print(f"  Target Org: {target_org}")
    print(f"  Storage: SQLite database")
    print()

    # Create database run
    print("💾 Initializing database...")
    run_id = db_utils.create_comparison_run(
        run_type='replica_comparison',
        source_org=source_org,
        target_org=target_org
    )
    print(f"  ✅ Run ID: {run_id}")
    print()

    try:
        # Load mappings
        contact_map = load_mappings()
        if not contact_map:
            db_utils.update_comparison_run(run_id, status='failed',
                                          notes='No Contact mappings found')
            print("❌ No Contact mappings found in database")
            print("   Run compare_contacts.py first!")
            sys.exit(1)
        print()

        # Query records
        src_records = query_replicas(source_org)
        tgt_records = query_replicas(target_org)

        if not src_records:
            db_utils.update_comparison_run(run_id, status='completed',
                                          total_source_records=0,
                                          notes='No Replica__c in source org')
            print("⚠️  No Replica__c records in source org")
            sys.exit(0)

        # Compare
        results = compare_replicas(src_records, tgt_records, contact_map)

        # Update run statistics
        db_utils.update_comparison_run(
            run_id,
            total_source_records=len(src_records),
            total_target_records=len(tgt_records),
            matched_count=results['matched_keys'],
            unmatched_count=results['missing_keys'],
            status='completed'
        )

        # Generate and display report
        report_text = generate_report(results, source_org, target_org)
        print("\n" + report_text)

        # Export if requested
        if args.export_json or args.export_csv:
            RESULTS_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            
            if args.export_json:
                json_path = RESULTS_DIR / f'replica_comparison_{timestamp}.json'
                with open(json_path, 'w') as f:
                    json.dump({
                        'metadata': {
                            'source_org': source_org,
                            'target_org': target_org,
                            'timestamp': timestamp,
                            'run_id': run_id
                        },
                        'results': results
                    }, f, indent=2)
                print(f"  📄 Exported to JSON: {json_path}")
                
                txt_path = RESULTS_DIR / f'replica_comparison_{timestamp}.txt'
                txt_path.write_text(report_text)
                print(f"  📄 Exported report: {txt_path}")

        print(f"\n{'='*80}")
        print(f"✅ Comparison completed successfully!")
        print(f"{'='*80}")
        print(f"Run ID: {run_id}")
        print(f"Database: {db_utils.DB_PATH}")
        
        if results['missing_keys'] > 0:
            print(f"\n💡 Next Steps:")
            print(f"  {results['missing_keys']} replicas need to be created in target org")
            print(f"  Run: python3 upsert_replicas.py {source_org} {target_org}")

    except Exception as e:
        db_utils.update_comparison_run(run_id, status='failed',
                                      notes=f'Error: {str(e)}')
        raise


if __name__ == '__main__':
    main()
