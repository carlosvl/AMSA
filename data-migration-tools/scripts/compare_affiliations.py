#!/usr/bin/env python3
"""
Affiliation__c Comparison Tool
Compares Affiliation__c records between two Salesforce orgs.

Affiliations link Contacts to Accounts (via Contact__c and Affiliated_Account__c).
Matching is done by mapping Contact and Account IDs from source to target.

Results are stored in SQLite database.

Usage:
  python3 compare_affiliations.py <source_org> <target_org> [--export-json] [--export-csv]

Example:
  python3 compare_affiliations.py 'AMSA-Royalty-Prod' 'AMSA Prod'
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
    account_map = db_utils.get_id_mappings('Account')
    
    print(f"  ✅ Contact mappings:  {len(contact_map)} entries")
    print(f"  ✅ Account mappings:  {len(account_map)} entries")
    
    if not contact_map:
        print("  ⚠️  Warning: No Contact mappings found in database")
    if not account_map:
        print("  ⚠️  Warning: No Account mappings found in database")
    
    return contact_map, account_map


def query_affiliations(org_alias: str):
    """Query all Affiliation__c records from an org."""
    print(f"📥 Querying Affiliation__c from {org_alias}...")

    query = """
        SELECT Id, Name, Contact__c, Affiliated_Account__c, Affiliation_Type__c,
               Affiliated_Description__c, Committee_Name__c, Sub_Committee_Name__c,
               Policital_Affiliation__c, Related_Account__c, Related_Account_2__c,
               Contact_2__c, CreatedDate, LastModifiedDate
        FROM Affiliation__c
    """

    records = run_soql(org_alias, query)
    print(f"  ✅ Retrieved {len(records)} Affiliation__c records")
    return records


def build_affiliation_key(contact_id: str, account_id: str = None, aff_type: str = None) -> str:
    """Build a unique key for an Affiliation__c record.
    
    Uses Contact__c + Affiliated_Account__c + Affiliation_Type__c as the key.
    """
    account_key = account_id or 'NULL'
    type_key = (aff_type or '').strip().lower()
    return f"{contact_id}|{account_key}|{type_key}"


def compare_affiliations(source_records, target_records, contact_map, account_map):
    """Compare Affiliation__c records between source and target."""
    print("\n🔍 Comparing Affiliation__c records...")

    # Map source affiliations into target IDs
    source_keys = set()
    unmapped_source = []
    source_details = {}

    for aff in source_records:
        src_contact = aff.get('Contact__c')
        src_account = aff.get('Affiliated_Account__c')
        aff_type = aff.get('Affiliation_Type__c')
        
        if not src_contact:
            # Skip records without Contact (shouldn't happen)
            unmapped_source.append({
                'id': aff.get('Id'),
                'reason': 'Missing Contact__c'
            })
            continue

        # Map Contact
        if src_contact not in contact_map:
            unmapped_source.append({
                'id': aff.get('Id'),
                'contact': src_contact,
                'account': src_account,
                'reason': 'Contact not mapped'
            })
            continue

        tgt_contact = contact_map[src_contact]

        # Map Account if present
        tgt_account = None
        if src_account:
            if src_account not in account_map:
                unmapped_source.append({
                    'id': aff.get('Id'),
                    'contact': src_contact,
                    'account': src_account,
                    'reason': 'Account not mapped'
                })
                continue
            tgt_account = account_map[src_account]

        key = build_affiliation_key(tgt_contact, tgt_account, aff_type)
        source_keys.add(key)
        source_details[key] = {
            'source_id': aff.get('Id'),
            'target_contact': tgt_contact,
            'target_account': tgt_account,
            'affiliation_type': aff_type,
            'description': aff.get('Affiliated_Description__c'),
            'committee': aff.get('Committee_Name__c'),
        }

    print(f"  📊 Source mapped affiliations: {len(source_keys)}")
    print(f"  ⚠️  Source unmapped affiliations: {len(unmapped_source)}")

    # Build target affiliations
    target_keys = set()
    target_details = {}
    extra_records = []

    for aff in target_records:
        contact = aff.get('Contact__c')
        account = aff.get('Affiliated_Account__c')
        aff_type = aff.get('Affiliation_Type__c')
        
        if not contact:
            continue

        key = build_affiliation_key(contact, account, aff_type)
        target_keys.add(key)
        target_details[key] = {
            'id': aff.get('Id'),
            'contact': contact,
            'account': account,
            'affiliation_type': aff_type,
        }

        # Check if this key exists in source
        if key not in source_keys:
            extra_records.append({
                'id': aff.get('Id'),
                'name': aff.get('Name'),
                'contact_id': contact,
                'account_id': account,
                'affiliation_type': aff_type,
            })

    print(f"  📊 Target affiliations: {len(target_keys)}")

    matched = source_keys & target_keys
    missing = source_keys - target_keys
    extra = target_keys - source_keys

    print(f"  ✅ Matched affiliation keys: {len(matched)}")
    print(f"  ❌ Missing affiliation keys in target: {len(missing)}")
    print(f"  ⚠️  Extra affiliation keys in target: {len(extra)}")

    # Build missing records list for migration
    missing_records = []
    for key in missing:
        if key in source_details:
            missing_records.append(source_details[key])

    return {
        'source_mapped_affiliations': len(source_keys),
        'unmapped_source_affiliations': len(unmapped_source),
        'target_affiliations': len(target_keys),
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
    lines.append("AFFILIATION COMPARISON REPORT")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"Source Org: {source_org}")
    lines.append(f"Target Org: {target_org}")
    lines.append(f"Report Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("=" * 80)
    lines.append("SUMMARY")
    lines.append("=" * 80)
    lines.append(f"Source mapped affiliations:    {results['source_mapped_affiliations']}")
    lines.append(f"Unmapped source affiliations:  {results['unmapped_source_affiliations']}")
    lines.append(f"Target affiliations:           {results['target_affiliations']}")
    lines.append(f"Matched affiliation keys:      {results['matched_keys']}")
    lines.append(f"Missing keys in target:        {results['missing_keys']}")
    lines.append(f"Extra keys in target:          {results['extra_keys']}")
    lines.append("")

    if results['missing_records']:
        lines.append("=" * 80)
        lines.append("MISSING IN TARGET (Need to Create)")
        lines.append("=" * 80)
        lines.append("")
        for rec in results['missing_records'][:50]:
            lines.append(f"❌ Source ID: {rec['source_id']}")
            lines.append(f"   Contact: {rec['target_contact']}")
            lines.append(f"   Account: {rec.get('target_account', 'N/A')}")
            lines.append(f"   Type: {rec.get('affiliation_type', 'N/A')}")
            lines.append("")
        if len(results['missing_records']) > 50:
            lines.append(f"... and {len(results['missing_records']) - 50} more")
        lines.append("")

    if results['unmapped_source_details']:
        lines.append("=" * 80)
        lines.append("UNMAPPED SOURCE AFFILIATIONS")
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
    print("🔗 AFFILIATION COMPARISON TOOL")
    print("=" * 80)
    print()

    parser = argparse.ArgumentParser(
        description='Compare Affiliation__c records between two Salesforce orgs'
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
        run_type='affiliation_comparison',
        source_org=source_org,
        target_org=target_org
    )
    print(f"  ✅ Run ID: {run_id}")
    print()

    try:
        # Load mappings
        contact_map, account_map = load_mappings()
        if not contact_map:
            db_utils.update_comparison_run(run_id, status='failed',
                                          notes='No Contact mappings found')
            print("❌ No Contact mappings found in database")
            print("   Run compare_contacts.py first!")
            sys.exit(1)
        print()

        # Query affiliations
        src_affs = query_affiliations(source_org)
        tgt_affs = query_affiliations(target_org)

        if not src_affs:
            db_utils.update_comparison_run(run_id, status='completed',
                                          total_source_records=0,
                                          notes='No affiliations in source org')
            print("⚠️  No Affiliation__c records in source org")
            sys.exit(0)

        # Compare
        results = compare_affiliations(src_affs, tgt_affs, contact_map, account_map)

        # Update run statistics
        db_utils.update_comparison_run(
            run_id,
            total_source_records=len(src_affs),
            total_target_records=len(tgt_affs),
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
                json_path = RESULTS_DIR / f'affiliation_comparison_{timestamp}.json'
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
                
                txt_path = RESULTS_DIR / f'affiliation_comparison_{timestamp}.txt'
                txt_path.write_text(report_text)
                print(f"  📄 Exported report: {txt_path}")

        print(f"\n{'='*80}")
        print(f"✅ Comparison completed successfully!")
        print(f"{'='*80}")
        print(f"Run ID: {run_id}")
        print(f"Database: {db_utils.DB_PATH}")
        
        if results['missing_keys'] > 0:
            print(f"\n💡 Next Steps:")
            print(f"  {results['missing_keys']} affiliations need to be created in target org")
            print(f"  Run: python3 upsert_affiliations.py {source_org} {target_org}")

    except Exception as e:
        db_utils.update_comparison_run(run_id, status='failed',
                                      notes=f'Error: {str(e)}')
        raise


if __name__ == '__main__':
    main()
