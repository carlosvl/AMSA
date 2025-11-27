#!/usr/bin/env python3
"""
Contact Comparison Tool
Compares contacts between two Salesforce orgs with detailed matching analysis
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

def query_contacts_from_source(org_alias, start_date, end_date=None):
    """Query contacts from source org with date filter"""
    print(f"📥 Querying contacts from {org_alias}...")
    
    # Build SOQL query with proper date format
    # Convert YYYY-MM-DD to YYYY-MM-DDT00:00:00Z for SOQL
    start_datetime = f"{start_date}T00:00:00Z"
    date_filter = f"CreatedDate >= {start_datetime}"
    
    if end_date:
        end_datetime = f"{end_date}T23:59:59Z"
        date_filter += f" AND CreatedDate <= {end_datetime}"
    
    query = f"SELECT Id, FirstName, LastName, Email, Phone, AccountId, CreatedDate, LastModifiedDate, OwnerId FROM Contact WHERE {date_filter} ORDER BY CreatedDate DESC"
    
    try:
        result = subprocess.run(
            ['sf', 'data', 'query', 
             '--query', query,
             '--target-org', org_alias,
             '--json'],
            capture_output=True,
            text=True,
            check=True,
            timeout=120
        )
        
        data = json.loads(result.stdout)
        contacts = data.get('result', {}).get('records', [])
        
        print(f"  ✅ Found {len(contacts)} contacts")
        return contacts
    
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return []

def query_contacts_from_target(org_alias):
    """Query all contacts from target org"""
    print(f"📥 Querying contacts from {org_alias}...")
    
    query = "SELECT Id, ExternalID__c, FirstName, LastName, Email, Phone, AccountId, CreatedDate, LastModifiedDate, OwnerId FROM Contact ORDER BY CreatedDate DESC"
    
    try:
        result = subprocess.run(
            ['sf', 'data', 'query', 
             '--query', query,
             '--target-org', org_alias,
             '--json'],
            capture_output=True,
            text=True,
            check=True,
            timeout=120
        )
        
        data = json.loads(result.stdout)
        contacts = data.get('result', {}).get('records', [])
        
        print(f"  ✅ Found {len(contacts)} contacts")
        return contacts
    
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return []

def compare_contacts(source_contacts, target_contacts):
    """Compare contacts using ExternalID__c and Email"""
    print(f"\n🔍 Comparing contacts...")
    
    # Build lookup dictionaries for target org
    target_by_external_id = {}
    target_by_email = {}
    
    for contact in target_contacts:
        external_id = contact.get('ExternalID__c')
        if external_id:
            target_by_external_id[external_id] = contact
        
        email = contact.get('Email')
        if email:
            target_by_email[email.lower()] = contact
    
    print(f"  📊 Target org: {len(target_by_external_id)} with ExternalID__c")
    print(f"  📊 Target org: {len(target_by_email)} with Email")
    
    # Compare each source contact
    results = {
        'matched_by_external_id': [],
        'matched_by_email': [],
        'not_matched': [],
        'multiple_email_matches': []
    }
    
    for source_contact in source_contacts:
        source_id = source_contact['Id']
        source_email = source_contact.get('Email', '').lower() if source_contact.get('Email') else None
        source_name = f"{source_contact.get('FirstName', '')} {source_contact.get('LastName', '')}"
        
        match_info = {
            'source_id': source_id,
            'source_name': source_name,
            'source_email': source_email,
            'source_created': source_contact.get('CreatedDate'),
            'target_id': None,
            'target_name': None,
            'match_type': None
        }
        
        # Try matching by ExternalID__c (primary)
        if source_id in target_by_external_id:
            target_contact = target_by_external_id[source_id]
            match_info['target_id'] = target_contact['Id']
            match_info['target_name'] = f"{target_contact.get('FirstName', '')} {target_contact.get('LastName', '')}"
            match_info['target_email'] = target_contact.get('Email')
            match_info['match_type'] = 'ExternalID__c'
            results['matched_by_external_id'].append(match_info)
        
        # Try matching by Email (secondary)
        elif source_email and source_email in target_by_email:
            target_contact = target_by_email[source_email]
            match_info['target_id'] = target_contact['Id']
            match_info['target_name'] = f"{target_contact.get('FirstName', '')} {target_contact.get('LastName', '')}"
            match_info['target_email'] = target_contact.get('Email')
            match_info['target_external_id'] = target_contact.get('ExternalID__c')
            match_info['match_type'] = 'Email'
            results['matched_by_email'].append(match_info)
        
        # No match found
        else:
            results['not_matched'].append(match_info)
    
    return results

def generate_report(results, source_org, target_org, start_date, end_date=None):
    """Generate detailed comparison report"""
    total = (len(results['matched_by_external_id']) + 
             len(results['matched_by_email']) + 
             len(results['not_matched']))
    
    matched_total = len(results['matched_by_external_id']) + len(results['matched_by_email'])
    match_percentage = (matched_total / total * 100) if total > 0 else 0
    
    report = []
    report.append("="*80)
    report.append("CONTACT COMPARISON REPORT")
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
    report.append(f"Total Source Contacts: {total}")
    report.append(f"✅ Matched (ExternalID__c): {len(results['matched_by_external_id'])} ({len(results['matched_by_external_id'])/total*100:.1f}%)")
    report.append(f"✅ Matched (Email): {len(results['matched_by_email'])} ({len(results['matched_by_email'])/total*100:.1f}%)")
    report.append(f"❌ Not Matched: {len(results['not_matched'])} ({len(results['not_matched'])/total*100:.1f}%)")
    report.append(f"📊 Overall Match Rate: {match_percentage:.1f}%")
    report.append("")
    
    # Matched by ExternalID__c
    if results['matched_by_external_id']:
        report.append("="*80)
        report.append(f"MATCHED BY ExternalID__c ({len(results['matched_by_external_id'])} contacts)")
        report.append("="*80)
        report.append("")
        for match in results['matched_by_external_id'][:20]:  # Show first 20
            report.append(f"✅ {match['source_name']}")
            report.append(f"   Source ID: {match['source_id']}")
            report.append(f"   Target ID: {match['target_id']}")
            report.append(f"   Email: {match['source_email']}")
            report.append(f"   Created: {match['source_created']}")
            report.append("")
        if len(results['matched_by_external_id']) > 20:
            report.append(f"   ... and {len(results['matched_by_external_id']) - 20} more")
            report.append("")
    
    # Matched by Email
    if results['matched_by_email']:
        report.append("="*80)
        report.append(f"MATCHED BY EMAIL ({len(results['matched_by_email'])} contacts)")
        report.append("="*80)
        report.append("")
        for match in results['matched_by_email'][:20]:  # Show first 20
            report.append(f"✅ {match['source_name']}")
            report.append(f"   Source ID: {match['source_id']}")
            report.append(f"   Target ID: {match['target_id']}")
            report.append(f"   Email: {match['source_email']}")
            report.append(f"   Target ExternalID__c: {match.get('target_external_id', 'Not set')}")
            report.append(f"   Created: {match['source_created']}")
            report.append("")
        if len(results['matched_by_email']) > 20:
            report.append(f"   ... and {len(results['matched_by_email']) - 20} more")
            report.append("")
    
    # Not Matched
    if results['not_matched']:
        report.append("="*80)
        report.append(f"NOT MATCHED ({len(results['not_matched'])} contacts)")
        report.append("="*80)
        report.append("")
        for match in results['not_matched'][:20]:  # Show first 20
            report.append(f"❌ {match['source_name']}")
            report.append(f"   Source ID: {match['source_id']}")
            report.append(f"   Email: {match['source_email'] or 'No email'}")
            report.append(f"   Created: {match['source_created']}")
            report.append("")
        if len(results['not_matched']) > 20:
            report.append(f"   ... and {len(results['not_matched']) - 20} more")
            report.append("")
    
    return "\n".join(report)

def main():
    """Main execution function"""
    print("="*80)
    print("🔍 CONTACT COMPARISON TOOL")
    print("="*80)
    print()
    
    # Get parameters from command line or prompt
    if len(sys.argv) >= 4:
        source_org = sys.argv[1]
        target_org = sys.argv[2]
        start_date = sys.argv[3]
        end_date = sys.argv[4] if len(sys.argv) > 4 else None
    else:
        print("❌ Missing parameters!")
        print("\nUsage:")
        print("  python3 compare_contacts.py <source_org> <target_org> <start_date> [end_date]")
        print("\nExample:")
        print("  python3 compare_contacts.py 'AMSA-Royalty-Prod' 'AMSA Prod' '2025-08-01'")
        print("  python3 compare_contacts.py 'AMSA-Royalty-Prod' 'AMSA Prod' '2025-08-01' '2025-11-27'")
        print("\nDate format: YYYY-MM-DD")
        sys.exit(1)
    
    # Validate and display parameters
    print("📋 Parameters:")
    print(f"  Source Org: {source_org}")
    print(f"  Target Org: {target_org}")
    print(f"  Start Date: {start_date}")
    if end_date:
        print(f"  End Date: {end_date}")
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
    
    # Query contacts
    source_contacts = query_contacts_from_source(source_org, start_date, end_date)
    if not source_contacts:
        print("\n⚠️  No contacts found in source org with given date range")
        sys.exit(0)
    
    target_contacts = query_contacts_from_target(target_org)
    if not target_contacts:
        print("\n⚠️  No contacts found in target org")
        sys.exit(0)
    
    # Compare contacts
    results = compare_contacts(source_contacts, target_contacts)
    
    # Generate report
    report_text = generate_report(results, source_org, target_org, start_date, end_date)
    
    # Display summary
    print("\n" + report_text)
    
    # Save results
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Save detailed JSON
    json_filename = f"../results/contact_comparison_{timestamp}.json"
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
    report_filename = f"../results/contact_comparison_{timestamp}.txt"
    with open(report_filename, 'w') as f:
        f.write(report_text)
    
    print(f"\n{'='*80}")
    print(f"📄 Results saved:")
    print(f"  - {json_filename}")
    print(f"  - {report_filename}")
    print(f"{'='*80}")

if __name__ == '__main__':
    main()

