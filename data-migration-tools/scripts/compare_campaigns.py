#!/usr/bin/env python3
"""
Campaign Comparison Tool
Compares campaigns between two Salesforce orgs using unique campaign names
"""
import json
import subprocess
import sys
from datetime import datetime

def get_org_credentials(org_alias):
    """Get org details"""
    try:
        result = subprocess.run(
            ['sf', 'org', 'display', '--target-org', org_alias, '--json'],
            capture_output=True,
            text=True,
            check=True,
            timeout=30
        )
        data = json.loads(result.stdout)
        return {
            'alias': org_alias,
            'username': data['result']['username'],
            'org_id': data['result']['id'],
            'instance_url': data['result']['instanceUrl']
        }
    except Exception as e:
        print(f"❌ Error connecting to {org_alias}: {e}")
        return None

def query_campaigns_from_source(org_alias, start_date, end_date=None):
    """Query campaigns from source org with date filter"""
    print(f"📥 Querying campaigns from {org_alias}...")
    
    # Build SOQL query with proper date format
    start_datetime = f"{start_date}T00:00:00Z"
    date_filter = f"CreatedDate >= {start_datetime}"
    
    if end_date:
        end_datetime = f"{end_date}T23:59:59Z"
        date_filter += f" AND CreatedDate <= {end_datetime}"
    
    query = f"""
        SELECT Id, Name, Type, Status, StartDate, 
               CreatedDate, NumberOfContacts
        FROM Campaign 
        WHERE {date_filter}
        ORDER BY CreatedDate DESC
    """
    
    try:
        result = subprocess.run(
            ['sf', 'data', 'query', 
             '--query', query,
             '--target-org', org_alias,
             '--json'],
            capture_output=True,
            text=True,
            timeout=120
        )
        
        data = json.loads(result.stdout)
        campaigns = data.get('result', {}).get('records', [])
        
        print(f"  ✅ Found {len(campaigns)} campaigns")
        return campaigns
    
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return []

def query_campaigns_from_target(org_alias):
    """Query all campaigns from target org"""
    print(f"📥 Querying campaigns from {org_alias}...")
    
    query = "SELECT Id, Name, Type, Status, StartDate, CreatedDate, NumberOfContacts FROM Campaign ORDER BY CreatedDate DESC"
    
    try:
        result = subprocess.run(
            ['sf', 'data', 'query', 
             '--query', query,
             '--target-org', org_alias,
             '--json'],
            capture_output=True,
            text=True,
            timeout=180
        )
        
        data = json.loads(result.stdout)
        campaigns = data.get('result', {}).get('records', [])
        
        print(f"  ✅ Found {len(campaigns)} campaigns")
        return campaigns
    
    except Exception as e:
        print(f"  ❌ Error: {e}")
        print(f"  ❌ STDERR: {result.stderr if 'result' in locals() else 'N/A'}")
        return []

def compare_campaigns(source_campaigns, target_campaigns):
    """Compare campaigns using Name as primary key and ExternalID__c as secondary"""
    print(f"\n🔍 Comparing campaigns...")
    
    # Build lookup dictionaries for target org
    target_by_name = {}
    target_by_external_id = {}
    
    for campaign in target_campaigns:
        name = campaign.get('Name')
        if name:
            # Store with normalized name (case-insensitive)
            target_by_name[name.strip().lower()] = campaign
        
        external_id = campaign.get('ExternalID__c')
        if external_id:
            target_by_external_id[external_id] = campaign
    
    print(f"  📊 Target org: {len(target_by_name)} unique campaign names")
    print(f"  📊 Target org: {len(target_by_external_id)} with ExternalID__c")
    
    # Compare each source campaign
    results = {
        'matched_by_name': [],
        'matched_by_external_id': [],
        'not_matched': [],
        'name_mismatch': []  # ExternalID matches but name doesn't
    }
    
    for source_campaign in source_campaigns:
        source_id = source_campaign['Id']
        source_name = source_campaign.get('Name', '')
        source_name_normalized = source_name.strip().lower()
        
        match_info = {
            'source_id': source_id,
            'source_name': source_name,
            'source_type': source_campaign.get('Type'),
            'source_status': source_campaign.get('Status'),
            'source_start_date': source_campaign.get('StartDate'),
            'source_created': source_campaign.get('CreatedDate'),
            'source_contacts': source_campaign.get('NumberOfContacts'),
            'target_id': None,
            'target_name': None,
            'match_type': None
        }
        
        # Try matching by Name (primary - campaigns should have unique names)
        if source_name_normalized in target_by_name:
            target_campaign = target_by_name[source_name_normalized]
            match_info['target_id'] = target_campaign['Id']
            match_info['target_name'] = target_campaign.get('Name')
            match_info['target_type'] = target_campaign.get('Type')
            match_info['target_status'] = target_campaign.get('Status')
            match_info['target_external_id'] = target_campaign.get('ExternalID__c')
            match_info['target_contacts'] = target_campaign.get('NumberOfContacts')
            match_info['match_type'] = 'Name'
            results['matched_by_name'].append(match_info)
        
        # Try matching by ExternalID__c (secondary)
        elif source_id in target_by_external_id:
            target_campaign = target_by_external_id[source_id]
            match_info['target_id'] = target_campaign['Id']
            match_info['target_name'] = target_campaign.get('Name')
            match_info['target_type'] = target_campaign.get('Type')
            match_info['target_status'] = target_campaign.get('Status')
            match_info['target_external_id'] = target_campaign.get('ExternalID__c')
            match_info['target_contacts'] = target_campaign.get('NumberOfContacts')
            match_info['match_type'] = 'ExternalID__c'
            
            # Check if names match
            target_name_normalized = target_campaign.get('Name', '').strip().lower()
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
    report.append("CAMPAIGN COMPARISON REPORT")
    report.append("="*80)
    report.append("")
    report.append(f"Source Org: {source_org}")
    report.append(f"Target Org: {target_org}")
    report.append(f"Date Range: {start_date}" + (f" to {end_date}" if end_date else " onwards"))
    report.append(f"Report Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("")
    report.append("="*80)
    report.append("SUMMARY")
    report.append("="*80)
    report.append(f"Total Source Campaigns: {total}")
    report.append(f"✅ Matched (Name): {len(results['matched_by_name'])} ({len(results['matched_by_name'])/total*100:.1f}%)")
    report.append(f"✅ Matched (ExternalID__c): {len(results['matched_by_external_id'])} ({len(results['matched_by_external_id'])/total*100:.1f}%)")
    report.append(f"⚠️  Name Mismatch: {len(results['name_mismatch'])} ({len(results['name_mismatch'])/total*100:.1f}%)")
    report.append(f"❌ Not Matched: {len(results['not_matched'])} ({len(results['not_matched'])/total*100:.1f}%)")
    report.append(f"📊 Overall Match Rate: {match_percentage:.1f}%")
    report.append("")
    
    # Matched by Name
    if results['matched_by_name']:
        report.append("="*80)
        report.append(f"MATCHED BY NAME ({len(results['matched_by_name'])} campaigns)")
        report.append("="*80)
        report.append("")
        for match in results['matched_by_name'][:20]:
            report.append(f"✅ {match['source_name']}")
            report.append(f"   Source ID: {match['source_id']}")
            report.append(f"   Target ID: {match['target_id']}")
            report.append(f"   Type: {match['source_type']} | Status: {match['source_status']}")
            report.append(f"   Target ExternalID__c: {match.get('target_external_id', 'Not set')}")
            report.append(f"   Contacts: Source={match.get('source_contacts', 0)}, Target={match.get('target_contacts', 0)}")
            report.append(f"   Created: {match['source_created']}")
            report.append("")
        if len(results['matched_by_name']) > 20:
            report.append(f"   ... and {len(results['matched_by_name']) - 20} more")
            report.append("")
    
    # Matched by ExternalID__c
    if results['matched_by_external_id']:
        report.append("="*80)
        report.append(f"MATCHED BY ExternalID__c ({len(results['matched_by_external_id'])} campaigns)")
        report.append("="*80)
        report.append("")
        for match in results['matched_by_external_id'][:20]:
            report.append(f"✅ {match['source_name']}")
            report.append(f"   Source ID: {match['source_id']}")
            report.append(f"   Target ID: {match['target_id']}")
            report.append(f"   Target Name: {match['target_name']}")
            report.append(f"   Type: {match['source_type']}")
            report.append(f"   Created: {match['source_created']}")
            report.append("")
        if len(results['matched_by_external_id']) > 20:
            report.append(f"   ... and {len(results['matched_by_external_id']) - 20} more")
            report.append("")
    
    # Name Mismatches
    if results['name_mismatch']:
        report.append("="*80)
        report.append(f"NAME MISMATCHES ({len(results['name_mismatch'])} campaigns)")
        report.append("="*80)
        report.append("ExternalID__c matches but campaign names are different")
        report.append("")
        for match in results['name_mismatch']:
            report.append(f"⚠️  Source: {match['source_name']}")
            report.append(f"   Target: {match['target_name']}")
            report.append(f"   Source ID: {match['source_id']}")
            report.append(f"   Target ID: {match['target_id']}")
            report.append("")
    
    # Not Matched
    if results['not_matched']:
        report.append("="*80)
        report.append(f"NOT MATCHED ({len(results['not_matched'])} campaigns)")
        report.append("="*80)
        report.append("")
        for match in results['not_matched'][:20]:
            report.append(f"❌ {match['source_name']}")
            report.append(f"   Source ID: {match['source_id']}")
            report.append(f"   Type: {match.get('source_type', 'N/A')} | Status: {match.get('source_status', 'N/A')}")
            report.append(f"   Start Date: {match.get('source_start_date', 'N/A')}")
            report.append(f"   Contacts: {match.get('source_contacts', 0)}")
            report.append(f"   Created: {match['source_created']}")
            report.append("")
        if len(results['not_matched']) > 20:
            report.append(f"   ... and {len(results['not_matched']) - 20} more")
            report.append("")
    
    return "\n".join(report)

def main():
    """Main execution"""
    print("="*80)
    print("🎯 CAMPAIGN COMPARISON TOOL")
    print("="*80)
    print()
    
    # Get parameters from command line
    if len(sys.argv) >= 4:
        source_org = sys.argv[1]
        target_org = sys.argv[2]
        start_date = sys.argv[3]
        end_date = sys.argv[4] if len(sys.argv) > 4 else None
    else:
        print("❌ Missing parameters!")
        print("\nUsage:")
        print("  python3 compare_campaigns.py <source_org> <target_org> <start_date> [end_date]")
        print("\nExample:")
        print("  python3 compare_campaigns.py 'AMSA-Royalty-Prod' 'AMSA Prod' '2025-01-01'")
        print("  python3 compare_campaigns.py 'AMSA-Royalty-Prod' 'AMSA Prod' '2025-01-01' '2025-12-31'")
        print("\nDate format: YYYY-MM-DD")
        print("\nNote: Campaigns are matched by Name (primary) since names should be unique")
        sys.exit(1)
    
    # Validate and display parameters
    print("📋 Parameters:")
    print(f"  Source Org: {source_org}")
    print(f"  Target Org: {target_org}")
    print(f"  Start Date: {start_date}")
    if end_date:
        print(f"  End Date: {end_date}")
    print(f"  Matching Strategy: Campaign Name (primary), ExternalID__c (secondary)")
    print()
    
    # Connect to orgs
    print("🔐 Connecting to orgs...")
    source_info = get_org_credentials(source_org)
    target_info = get_org_credentials(target_org)
    
    if not source_info or not target_info:
        print("\n❌ Failed to connect to one or both orgs")
        sys.exit(1)
    
    print(f"  ✅ Source: {source_info['username']} ({source_info['instance_url']})")
    print(f"  ✅ Target: {target_info['username']} ({target_info['instance_url']})")
    print()
    
    # Query campaigns
    source_campaigns = query_campaigns_from_source(source_org, start_date, end_date)
    if not source_campaigns:
        print("\n⚠️  No campaigns found in source org with given date range")
        sys.exit(0)
    
    target_campaigns = query_campaigns_from_target(target_org)
    if not target_campaigns:
        print("\n⚠️  No campaigns found in target org")
        sys.exit(0)
    
    # Compare campaigns
    results = compare_campaigns(source_campaigns, target_campaigns)
    
    # Generate report
    report_text = generate_report(results, source_org, target_org, start_date, end_date)
    
    # Display summary
    print("\n" + report_text)
    
    # Save results
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Save detailed JSON
    json_filename = f"../results/campaign_comparison_{timestamp}.json"
    with open(json_filename, 'w') as f:
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
    
    # Save report
    report_filename = f"../results/campaign_comparison_{timestamp}.txt"
    with open(report_filename, 'w') as f:
        f.write(report_text)
    
    # Create campaign ID mapping file (like we do for contacts)
    campaign_mapping = {}
    
    # Add name matches
    for match in results['matched_by_name']:
        campaign_mapping[match['source_id']] = match['target_id']
    
    # Add ExternalID matches
    for match in results['matched_by_external_id']:
        campaign_mapping[match['source_id']] = match['target_id']
    
    # Save mapping
    mapping_filename = f"../data/campaign_id_mapping_{timestamp}.json"
    with open(mapping_filename, 'w') as f:
        json.dump(campaign_mapping, f, indent=2)
    
    print(f"\n{'='*80}")
    print(f"📄 Results saved:")
    print(f"  - {json_filename}")
    print(f"  - {report_filename}")
    print(f"  - {mapping_filename}")
    print(f"{'='*80}")
    
    # Recommendations
    if len(results['not_matched']) > 0:
        print(f"\n💡 Next Steps:")
        print(f"  {len(results['not_matched'])} campaigns need to be created in target org")

if __name__ == '__main__':
    main()

