#!/usr/bin/env python3
"""
Account Comparison Tool
Compares Account records between two Salesforce orgs using Name and ExternalID__c.

Results are stored in SQLite database. Use --export-json or --export-csv 
to also generate legacy file formats.

Usage:
  python3 compare_accounts.py <source_org> <target_org> [start_date] [end_date] [--export-json] [--export-csv]

Example:
  python3 compare_accounts.py 'AMSA-Royalty-Prod' 'AMSA Prod' '2025-01-01'
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


def query_accounts_from_source(org_alias, start_date=None, end_date=None):
    """Query accounts from source org with optional date filter"""
    print(f"📥 Querying accounts from {org_alias}...")
    
    # Build SOQL query
    query = """
        SELECT Id, Name, Type, Industry, BillingCity, BillingCountry,
               Website, Phone, CreatedDate, LastModifiedDate
        FROM Account
    """
    
    # Add date filter if provided
    if start_date:
        start_datetime = f"{start_date}T00:00:00Z"
        query += f" WHERE CreatedDate >= {start_datetime}"
        if end_date:
            end_datetime = f"{end_date}T23:59:59Z"
            query += f" AND CreatedDate <= {end_datetime}"
    
    query += " ORDER BY CreatedDate DESC"
    
    records = run_soql(org_alias, query)
    print(f"  ✅ Found {len(records)} accounts")
    return records


def query_accounts_from_target(org_alias):
    """Query all accounts from target org"""
    print(f"📥 Querying accounts from {org_alias}...")
    
    query = """
        SELECT Id, Name, ExternalID__c, Type, Industry, BillingCity, BillingCountry,
               Website, Phone, CreatedDate
        FROM Account
        ORDER BY CreatedDate DESC
    """
    
    records = run_soql(org_alias, query)
    print(f"  ✅ Found {len(records)} accounts")
    return records


def compare_accounts(source_accounts, target_accounts):
    """Compare accounts using Name as primary key and ExternalID__c as secondary"""
    print(f"\n🔍 Comparing accounts...")
    
    # Build lookup dictionaries for target org
    target_by_name = {}
    target_by_external_id = {}
    
    for account in target_accounts:
        name = account.get('Name')
        if name:
            # Store with normalized name (case-insensitive)
            target_by_name[name.strip().lower()] = account
        
        external_id = account.get('ExternalID__c')
        if external_id:
            target_by_external_id[external_id] = account
    
    print(f"  📊 Target org: {len(target_by_name)} unique account names")
    print(f"  📊 Target org: {len(target_by_external_id)} with ExternalID__c")
    
    # Compare each source account
    results = {
        'matched_by_name': [],
        'matched_by_external_id': [],
        'not_matched': [],
        'name_mismatch': []  # ExternalID matches but name doesn't
    }
    
    for source_account in source_accounts:
        source_id = source_account['Id']
        source_name = source_account.get('Name', '')
        source_name_normalized = source_name.strip().lower()
        
        match_info = {
            'source_id': source_id,
            'source_name': source_name,
            'source_type': source_account.get('Type'),
            'source_industry': source_account.get('Industry'),
            'source_city': source_account.get('BillingCity'),
            'source_country': source_account.get('BillingCountry'),
            'source_created': source_account.get('CreatedDate'),
            'target_id': None,
            'target_name': None,
            'match_type': None
        }
        
        # Try matching by Name (primary)
        if source_name_normalized in target_by_name:
            target_account = target_by_name[source_name_normalized]
            match_info['target_id'] = target_account['Id']
            match_info['target_name'] = target_account.get('Name')
            match_info['target_type'] = target_account.get('Type')
            match_info['target_external_id'] = target_account.get('ExternalID__c')
            match_info['match_type'] = 'Name'
            results['matched_by_name'].append(match_info)
        
        # Try matching by ExternalID__c (secondary)
        elif source_id in target_by_external_id:
            target_account = target_by_external_id[source_id]
            match_info['target_id'] = target_account['Id']
            match_info['target_name'] = target_account.get('Name')
            match_info['target_type'] = target_account.get('Type')
            match_info['target_external_id'] = target_account.get('ExternalID__c')
            match_info['match_type'] = 'ExternalID__c'
            
            # Check if names match
            target_name_normalized = target_account.get('Name', '').strip().lower()
            if source_name_normalized != target_name_normalized:
                match_info['name_mismatch'] = True
                results['name_mismatch'].append(match_info)
            else:
                results['matched_by_external_id'].append(match_info)
        
        # No match found
        else:
            results['not_matched'].append(match_info)
    
    return results


def generate_report(results, source_org, target_org, start_date, end_date=None):
    """Generate detailed comparison report"""
    total = (len(results['matched_by_name']) + 
             len(results['matched_by_external_id']) +
             len(results['name_mismatch']) +
             len(results['not_matched']))
    
    matched_total = len(results['matched_by_name']) + len(results['matched_by_external_id'])
    match_percentage = (matched_total / total * 100) if total > 0 else 0
    
    report = []
    report.append("="*80)
    report.append("ACCOUNT COMPARISON REPORT")
    report.append("="*80)
    report.append("")
    report.append(f"Source Org: {source_org}")
    report.append(f"Target Org: {target_org}")
    if start_date:
        report.append(f"Date Range: {start_date}" + (f" to {end_date}" if end_date else " onwards"))
    else:
        report.append("Date Range: ALL")
    report.append(f"Report Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("")
    report.append("="*80)
    report.append("SUMMARY")
    report.append("="*80)
    report.append(f"Total Source Accounts: {total}")
    report.append(f"✅ Matched (Name): {len(results['matched_by_name'])} ({len(results['matched_by_name'])/total*100:.1f}%)" if total > 0 else "✅ Matched (Name): 0")
    report.append(f"✅ Matched (ExternalID__c): {len(results['matched_by_external_id'])} ({len(results['matched_by_external_id'])/total*100:.1f}%)" if total > 0 else "✅ Matched (ExternalID__c): 0")
    report.append(f"⚠️  Name Mismatch: {len(results['name_mismatch'])} ({len(results['name_mismatch'])/total*100:.1f}%)" if total > 0 else "⚠️  Name Mismatch: 0")
    report.append(f"❌ Not Matched: {len(results['not_matched'])} ({len(results['not_matched'])/total*100:.1f}%)" if total > 0 else "❌ Not Matched: 0")
    report.append(f"📊 Overall Match Rate: {match_percentage:.1f}%")
    report.append("")
    
    # Matched by Name
    if results['matched_by_name']:
        report.append("="*80)
        report.append(f"MATCHED BY NAME ({len(results['matched_by_name'])} accounts)")
        report.append("="*80)
        report.append("")
        for match in results['matched_by_name'][:20]:
            report.append(f"✅ {match['source_name']}")
            report.append(f"   Source ID: {match['source_id']}")
            report.append(f"   Target ID: {match['target_id']}")
            report.append(f"   Type: {match['source_type']} | Industry: {match.get('source_industry', 'N/A')}")
            report.append(f"   Target ExternalID__c: {match.get('target_external_id', 'Not set')}")
            report.append("")
        if len(results['matched_by_name']) > 20:
            report.append(f"   ... and {len(results['matched_by_name']) - 20} more")
            report.append("")
    
    # Not Matched
    if results['not_matched']:
        report.append("="*80)
        report.append(f"NOT MATCHED ({len(results['not_matched'])} accounts)")
        report.append("="*80)
        report.append("")
        for match in results['not_matched'][:20]:
            report.append(f"❌ {match['source_name']}")
            report.append(f"   Source ID: {match['source_id']}")
            report.append(f"   Type: {match.get('source_type', 'N/A')} | Industry: {match.get('source_industry', 'N/A')}")
            report.append(f"   City: {match.get('source_city', 'N/A')} | Country: {match.get('source_country', 'N/A')}")
            report.append(f"   Created: {match['source_created']}")
            report.append("")
        if len(results['not_matched']) > 20:
            report.append(f"   ... and {len(results['not_matched']) - 20} more")
            report.append("")
    
    return "\n".join(report)


def main():
    """Main execution"""
    print("="*80)
    print("🏢 ACCOUNT COMPARISON TOOL")
    print("="*80)
    print()
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='Compare accounts between two Salesforce orgs',
        epilog='Results are stored in SQLite. Use --export flags for legacy file formats.'
    )
    parser.add_argument('source_org', help='Source org alias')
    parser.add_argument('target_org', help='Target org alias')
    parser.add_argument('start_date', nargs='?', help='Start date (YYYY-MM-DD, optional)')
    parser.add_argument('end_date', nargs='?', help='End date (YYYY-MM-DD, optional)')
    parser.add_argument('--export-json', action='store_true', 
                        help='Export results to JSON file (legacy format)')
    parser.add_argument('--export-csv', action='store_true',
                        help='Export results to CSV file (legacy format)')
    
    args = parser.parse_args()
    
    source_org = args.source_org
    target_org = args.target_org
    start_date = args.start_date
    end_date = args.end_date
    
    # Validate and display parameters
    print("📋 Parameters:")
    print(f"  Source Org: {source_org}")
    print(f"  Target Org: {target_org}")
    if start_date:
        print(f"  Start Date: {start_date}")
    if end_date:
        print(f"  End Date: {end_date}")
    print(f"  Matching Strategy: Account Name (primary), ExternalID__c (secondary)")
    print(f"  Storage: SQLite database")
    print()
    
    # Create database run entry
    print("💾 Initializing database...")
    run_id = db_utils.create_comparison_run(
        run_type='account_comparison',
        source_org=source_org,
        target_org=target_org,
        start_date=start_date,
        end_date=end_date
    )
    print(f"  ✅ Run ID: {run_id}")
    print()
    
    try:
        # Query accounts
        source_accounts = query_accounts_from_source(source_org, start_date, end_date)
        if not source_accounts:
            db_utils.update_comparison_run(run_id, status='completed',
                                          total_source_records=0,
                                          notes='No accounts found in source org')
            print("\n⚠️  No accounts found in source org")
            sys.exit(0)
        
        target_accounts = query_accounts_from_target(target_org)
        if not target_accounts:
            db_utils.update_comparison_run(run_id, status='completed',
                                          total_target_records=0,
                                          notes='No accounts found in target org')
            print("\n⚠️  No accounts found in target org")
        
        # Compare accounts
        results = compare_accounts(source_accounts, target_accounts)
        
        # Generate report
        report_text = generate_report(results, source_org, target_org, start_date, end_date)
        
        # Display summary
        print("\n" + report_text)
        
        # Calculate totals
        total_source = len(source_accounts)
        total_target = len(target_accounts)
        matched = len(results['matched_by_name']) + len(results['matched_by_external_id'])
        unmatched = len(results['not_matched'])
        
        # Save to database - update ID mappings
        print("\n💾 Saving results to database...")
        
        account_mapping = {}
        for match in results['matched_by_name']:
            account_mapping[match['source_id']] = match['target_id']
        for match in results['matched_by_external_id']:
            account_mapping[match['source_id']] = match['target_id']
        
        db_utils.bulk_update_id_mappings('Account', account_mapping)
        
        # Update run statistics
        db_utils.update_comparison_run(
            run_id,
            total_source_records=total_source,
            total_target_records=total_target,
            matched_count=matched,
            unmatched_count=unmatched,
            status='completed'
        )
        
        print(f"  ✅ Updated {len(account_mapping)} Account ID mappings")
        
        # Export to legacy formats if requested
        if args.export_json or args.export_csv:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            RESULTS_DIR.mkdir(exist_ok=True)
            
            if args.export_json:
                json_path = RESULTS_DIR / f'account_comparison_{timestamp}.json'
                with open(json_path, 'w') as f:
                    json.dump({
                        'metadata': {
                            'source_org': source_org,
                            'target_org': target_org,
                            'start_date': start_date,
                            'end_date': end_date,
                            'timestamp': timestamp
                        },
                        'results': results
                    }, f, indent=2)
                print(f"  📄 Exported to JSON: {json_path}")
                
                # Also save text report
                txt_path = RESULTS_DIR / f'account_comparison_{timestamp}.txt'
                txt_path.write_text(report_text)
                print(f"  📄 Exported report: {txt_path}")
        
        print(f"\n{'='*80}")
        print(f"✅ Comparison completed successfully!")
        print(f"{'='*80}")
        print(f"Run ID: {run_id}")
        print(f"Database: {db_utils.DB_PATH}")
        print(f"\nUse query_results.py to view and analyze results:")
        print(f"  python3 query_results.py run-details {run_id}")
        print(f"{'='*80}")
        
        # Recommendations
        if len(results['not_matched']) > 0:
            print(f"\n💡 Next Steps:")
            print(f"  {len(results['not_matched'])} accounts need to be created in target org")
            print(f"  Run: python3 upsert_accounts.py {source_org} {target_org}")
    
    except Exception as e:
        db_utils.update_comparison_run(run_id, status='failed', 
                                      notes=f'Error: {str(e)}')
        raise


if __name__ == '__main__':
    main()
