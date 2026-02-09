#!/usr/bin/env python3
"""
Contact Duplicate Merge Tool
Interactive tool to merge duplicate Contact records detected by detect_contact_duplicates.py.

Uses Salesforce SOAP API to perform merges. Master record is selected based on most recent
LastModifiedDate. Supports interactive one-by-one merging or batch processing.

Usage:
    python3 merge_contact_duplicates.py <org_alias> [--run-id <id>] [--batch] [--dry-run]

Example:
    python3 merge_contact_duplicates.py "AMSA Prod"
    python3 merge_contact_duplicates.py "AMSA Prod" --run-id 5 --batch
    python3 merge_contact_duplicates.py "AMSA Prod" --dry-run
"""
import json
import subprocess
import sys
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import urllib.request
import urllib.error
import urllib.parse

# Note: Merge uses raw SOAP API directly, no external SOAP library required

import db_utils

BASE_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = BASE_DIR / 'results'
RESULTS_DIR.mkdir(exist_ok=True)


def get_org_credentials(org_alias):
    """Get org access token and instance URL"""
    try:
        result = subprocess.run(
            ['sf', 'org', 'display', '--target-org', org_alias, '--json'],
            capture_output=True,
            text=True,
            check=True,
            timeout=30
        )
        data = json.loads(result.stdout)
        info = data.get('result', {})
        return {
            'access_token': info.get('accessToken'),
            'instance_url': info.get('instanceUrl'),
            'username': info.get('username'),
            'org_id': info.get('id')
        }
    except Exception as e:
        print(f"❌ Error connecting to {org_alias}: {e}")
        return None


def query_contact_details(org_alias, contact_ids):
    """Query detailed contact information including LastModifiedBy"""
    if not contact_ids:
        return []
    
    # Build SOQL query with relationship fields
    ids_str = "', '".join(contact_ids)
    query = f"""
        SELECT Id, FirstName, LastName, Email, Phone, AccountId, 
               CreatedDate, LastModifiedDate, LastModifiedBy.Name, LastModifiedBy.Id,
               OwnerId, Owner.Name
        FROM Contact
        WHERE Id IN ('{ids_str}')
        ORDER BY LastModifiedDate DESC
    """
    
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
        
        # Flatten relationship fields
        for contact in contacts:
            if 'LastModifiedBy' in contact and contact['LastModifiedBy']:
                contact['LastModifiedByName'] = contact['LastModifiedBy'].get('Name', 'N/A')
                contact['LastModifiedById'] = contact['LastModifiedBy'].get('Id', '')
            else:
                contact['LastModifiedByName'] = 'N/A'
                contact['LastModifiedById'] = ''
            
            if 'Owner' in contact and contact['Owner']:
                contact['OwnerName'] = contact['Owner'].get('Name', 'N/A')
            else:
                contact['OwnerName'] = 'N/A'
        
        return contacts
    
    except Exception as e:
        print(f"  ❌ Error querying contacts: {e}")
        return []


def identify_master_record(contacts):
    """
    Identify master record based on most recent LastModifiedDate.
    
    Args:
        contacts: List of contact dictionaries
        
    Returns:
        Tuple of (master_contact, duplicate_contacts)
    """
    if not contacts:
        return None, []
    
    # Sort by LastModifiedDate descending (most recent first)
    sorted_contacts = sorted(
        contacts,
        key=lambda x: x.get('LastModifiedDate') or '',
        reverse=True
    )
    
    master = sorted_contacts[0]
    duplicates = sorted_contacts[1:]
    
    return master, duplicates


def create_soap_client(instance_url, access_token):
    """Create SOAP API client for merge operations"""
    if not ZEEP_AVAILABLE:
        raise ImportError("zeep library is required for merge operations")
    
    # SOAP endpoint URL
    soap_url = f"{instance_url}/services/Soap/u/59.0"
    
    # Create session with authentication
    session = Session()
    session.headers.update({
        'SOAPAction': 'merge',
        'Content-Type': 'text/xml; charset=UTF-8'
    })
    
    # Create transport with cache
    cache = SqliteCache(path='/tmp/zeep_cache.db', timeout=3600)
    transport = Transport(cache=cache, session=session)
    
    # Create client
    client = Client(wsdl=None, transport=transport)
    
    return client, soap_url, access_token


def merge_contacts_soap(org_alias, master_id, duplicate_ids, access_token, instance_url):
    """
    Merge contacts using Salesforce SOAP API via simple-salesforce library.
    
    Args:
        org_alias: Org alias for error reporting
        master_id: ID of master record (to keep)
        duplicate_ids: List of duplicate record IDs to merge
        access_token: Access token for authentication
        instance_url: Instance URL
        
    Returns:
        Tuple of (success: bool, error_message: Optional[str])
    """
    if not duplicate_ids:
        return False, "No duplicate IDs provided"
    
    # Merge can handle up to 3 records total (1 master + 2 duplicates)
    if len(duplicate_ids) > 2:
        return False, f"Cannot merge more than 2 duplicates at once (found {len(duplicate_ids)})"
    
    # Use raw SOAP API directly
    return merge_contacts_raw_soap(org_alias, master_id, duplicate_ids, access_token, instance_url)


def merge_contacts_raw_soap(org_alias, master_id, duplicate_ids, access_token, instance_url):
    """
    Raw SOAP merge using correct Salesforce Partner API structure.
    Based on Salesforce Partner API WSDL, merge takes an array of MergeRequest objects.
    Each MergeRequest contains masterRecord (SObject) and recordToMergeIds (string array).
    """
    try:
        soap_url = f"{instance_url}/services/Soap/u/59.0"
        
        # Based on Salesforce Partner API WSDL structure:
        # merge() takes MergeRequest[] where each MergeRequest has:
        # - masterRecord: SObject with xsi:type and Id
        # - recordToMergeIds: string[] (array of IDs)
        # The recordToMergeIds should be a single element containing multiple string values
        record_to_merge_ids_xml = ''.join([f'<urn:recordToMergeIds>{did}</urn:recordToMergeIds>' for did in duplicate_ids])
        
        soap_body = f"""<?xml version="1.0" encoding="utf-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:urn="urn:partner.soap.sforce.com" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
   <soapenv:Header>
      <urn:SessionHeader>
         <urn:sessionId>{access_token}</urn:sessionId>
      </urn:SessionHeader>
   </soapenv:Header>
   <soapenv:Body>
      <urn:merge>
         <urn:request>
            <urn:masterRecord xsi:type="urn:Contact">
               <urn:Id>{master_id}</urn:Id>
            </urn:masterRecord>
            {record_to_merge_ids_xml}
         </urn:request>
      </urn:merge>
   </soapenv:Body>
</soapenv:Envelope>"""
        
        req = urllib.request.Request(soap_url, data=soap_body.encode('utf-8'))
        req.add_header('Content-Type', 'text/xml; charset=UTF-8')
        req.add_header('SOAPAction', 'merge')
        
        with urllib.request.urlopen(req, timeout=60) as response:
            response_data = response.read().decode('utf-8')
            
            if 'faultcode' in response_data.lower() or 'faultstring' in response_data.lower():
                import xml.etree.ElementTree as ET
                try:
                    root = ET.fromstring(response_data)
                    fault_string = root.find('.//faultstring')
                    if fault_string is not None:
                        return False, fault_string.text
                except:
                    pass
                return False, "SOAP API error"
            
            return True, None
    
    except Exception as e:
        return False, f"SOAP error: {str(e)}"


def display_group_info(group, contacts_details):
    """Display duplicate group information"""
    master, duplicates = identify_master_record(contacts_details)
    
    print("\n" + "="*80)
    print(f"DUPLICATE GROUP #{group['group_id']}")
    print("="*80)
    print(f"Group Key: {group['group_key'][:50]}...")
    print(f"Records in Group: {group['record_count']}")
    print()
    
    print("📌 MASTER RECORD (will be kept):")
    print(f"  ID: {master['Id']}")
    print(f"  Name: {master.get('FirstName', '')} {master.get('LastName', '')}".strip())
    print(f"  Email: {master.get('Email') or 'No Email'}")
    print(f"  Phone: {master.get('Phone') or 'No Phone'}")
    print(f"  Last Modified: {master.get('LastModifiedDate', 'N/A')}")
    print(f"  Last Modified By: {master.get('LastModifiedByName', 'N/A')}")
    print()
    
    if duplicates:
        print(f"🔄 DUPLICATES TO MERGE ({len(duplicates)} records):")
        for i, dup in enumerate(duplicates, 1):
            print(f"  {i}. ID: {dup['Id']}")
            print(f"     Name: {dup.get('FirstName', '')} {dup.get('LastName', '')}".strip())
            print(f"     Email: {dup.get('Email') or 'No Email'}")
            print(f"     Last Modified: {dup.get('LastModifiedDate', 'N/A')}")
        print()


def merge_group(org_alias, group, contacts_details, dry_run=False):
    """
    Merge a duplicate group.
    
    Returns:
        Tuple of (success: bool, error_message: Optional[str])
    """
    master, duplicates = identify_master_record(contacts_details)
    
    if not duplicates:
        return False, "No duplicate records to merge"
    
    master_id = master['Id']
    duplicate_ids = [d['Id'] for d in duplicates]
    
    if dry_run:
        print(f"  🔍 DRY RUN: Would merge {len(duplicate_ids)} records into {master_id}")
        return True, None
    
    # Get org credentials
    org_info = get_org_credentials(org_alias)
    if not org_info:
        return False, "Failed to get org credentials"
    
    # Perform merge
    success, error = merge_contacts_soap(
        org_alias,
        master_id,
        duplicate_ids,
        org_info['access_token'],
        org_info['instance_url']
    )
    
    return success, error


def interactive_merge(org_alias, groups, dry_run=False):
    """Interactive one-by-one merge process"""
    merged_count = 0
    skipped_count = 0
    failed_count = 0
    merge_results = []
    total_groups = len(groups)
    current_group_num = 0
    
    for group in groups:
        current_group_num += 1
        
        try:
            # Query contact details for this group
            record_ids = [r['Id'] for r in group['records']]
            contacts_details = query_contact_details(org_alias, record_ids)
            
            if not contacts_details:
                print(f"\n⚠️  Warning: Could not retrieve details for group {group['group_id']}")
                print(f"   Skipping this group and continuing to next...\n")
                failed_count += 1
                merge_results.append({
                    'group_id': group['group_id'],
                    'status': 'failed',
                    'error': 'Could not retrieve contact details'
                })
                continue
            
            # Display group info
            print(f"\n{'='*80}")
            print(f"GROUP {current_group_num} of {total_groups}")
            print(f"{'='*80}")
            display_group_info(group, contacts_details)
            
            # Get user choice
            while True:
                print("Options:")
                print("  1. Merge this group")
                print("  2. Skip this group")
                print("  3. Exit")
                choice = input("\nEnter choice (1-3): ").strip()
                
                if choice == '1':
                    # Merge
                    print("\n🔄 Merging contacts...")
                    success, error = merge_group(org_alias, group, contacts_details, dry_run)
                    
                    if success:
                        print("  ✅ Merge successful!")
                        merged_count += 1
                        master, duplicates = identify_master_record(contacts_details)
                        merge_results.append({
                            'group_id': group['group_id'],
                            'status': 'success',
                            'master_id': master['Id'],
                            'merged_ids': [d['Id'] for d in duplicates]
                        })
                        if not dry_run:
                            db_utils.update_duplicate_group_action(group['group_id'], 'merged')
                    else:
                        print(f"  ❌ Merge failed: {error}")
                        failed_count += 1
                        merge_results.append({
                            'group_id': group['group_id'],
                            'status': 'failed',
                            'error': error
                        })
                    break
                
                elif choice == '2':
                    print("  ⏭️  Skipped")
                    skipped_count += 1
                    merge_results.append({
                        'group_id': group['group_id'],
                        'status': 'skipped'
                    })
                    break
                
                elif choice == '3':
                    print("\n👋 Exiting...")
                    return merged_count, skipped_count, failed_count, merge_results
                
                else:
                    print("  ❌ Invalid choice. Please enter 1, 2, or 3.")
        
        except Exception as e:
            print(f"\n⚠️  Error processing group {group['group_id']}: {e}")
            print(f"   Continuing to next group...\n")
            failed_count += 1
            merge_results.append({
                'group_id': group['group_id'],
                'status': 'failed',
                'error': str(e)
            })
            continue
    
    return merged_count, skipped_count, failed_count, merge_results


def batch_merge(org_alias, groups, dry_run=False):
    """Batch merge all groups"""
    merged_count = 0
    failed_count = 0
    merge_results = []
    
    print(f"\n🔄 Processing {len(groups)} duplicate groups in batch mode...")
    
    for i, group in enumerate(groups, 1):
        print(f"\n[{i}/{len(groups)}] Processing group {group['group_id']}...")
        
        # Query contact details
        record_ids = [r['Id'] for r in group['records']]
        contacts_details = query_contact_details(org_alias, record_ids)
        
        if not contacts_details:
            print(f"  ⚠️  Warning: Could not retrieve details, skipping")
            failed_count += 1
            merge_results.append({
                'group_id': group['group_id'],
                'status': 'failed',
                'error': 'Could not retrieve contact details'
            })
            continue
        
        # Merge
        success, error = merge_group(org_alias, group, contacts_details, dry_run)
        
        if success:
            print(f"  ✅ Merged successfully")
            merged_count += 1
            master, duplicates = identify_master_record(contacts_details)
            merge_results.append({
                'group_id': group['group_id'],
                'status': 'success',
                'master_id': master['Id'],
                'merged_ids': [d['Id'] for d in duplicates]
            })
            if not dry_run:
                db_utils.update_duplicate_group_action(group['group_id'], 'merged')
        else:
            print(f"  ❌ Failed: {error}")
            failed_count += 1
            merge_results.append({
                'group_id': group['group_id'],
                'status': 'failed',
                'error': error
            })
    
    return merged_count, 0, failed_count, merge_results


def generate_merge_report(merge_results, org_alias, run_id, merged_count, skipped_count, failed_count):
    """Generate merge operation report"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    report = []
    report.append("="*80)
    report.append("CONTACT MERGE REPORT")
    report.append("="*80)
    report.append("")
    report.append(f"Org: {org_alias}")
    report.append(f"Run ID: {run_id}")
    report.append(f"Report Date: {timestamp}")
    report.append("")
    report.append("="*80)
    report.append("SUMMARY")
    report.append("="*80)
    report.append(f"Total Groups Processed: {len(merge_results)}")
    report.append(f"✅ Successfully Merged: {merged_count}")
    report.append(f"⏭️  Skipped: {skipped_count}")
    report.append(f"❌ Failed: {failed_count}")
    report.append("")
    
    if merge_results:
        report.append("="*80)
        report.append("DETAILED RESULTS")
        report.append("="*80)
        report.append("")
        
        for result in merge_results:
            status = result['status']
            group_id = result['group_id']
            
            if status == 'success':
                report.append(f"✅ Group {group_id}: Merged successfully")
                report.append(f"   Master: {result.get('master_id', 'N/A')}")
                report.append(f"   Merged: {len(result.get('merged_ids', []))} record(s)")
            elif status == 'skipped':
                report.append(f"⏭️  Group {group_id}: Skipped")
            elif status == 'failed':
                report.append(f"❌ Group {group_id}: Failed")
                report.append(f"   Error: {result.get('error', 'Unknown error')}")
            report.append("")
    
    return "\n".join(report)


def main():
    """Main execution function"""
    parser = argparse.ArgumentParser(
        description='Merge duplicate Contact records interactively or in batch'
    )
    parser.add_argument('org_alias', help='Salesforce org alias')
    parser.add_argument('--run-id', type=int, help='Specific run ID to process (default: latest)')
    parser.add_argument('--batch', action='store_true', 
                       help='Process all groups in batch mode (non-interactive)')
    parser.add_argument('--dry-run', action='store_true',
                       help='Dry run mode - show what would be merged without actually merging')
    
    args = parser.parse_args()
    
    # No external dependencies required - uses raw SOAP API
    
    print("="*80)
    print("🔄 CONTACT DUPLICATE MERGE TOOL")
    print("="*80)
    print()
    print("📋 Parameters:")
    print(f"  Org: {args.org_alias}")
    print(f"  Mode: {'Batch' if args.batch else 'Interactive'}")
    print(f"  Dry Run: {'Yes' if args.dry_run else 'No'}")
    if args.run_id:
        print(f"  Run ID: {args.run_id}")
    print()
    
    # Connect to org
    print("🔐 Connecting to org...")
    org_info = get_org_credentials(args.org_alias)
    if not org_info:
        print("\n❌ Failed to connect to org")
        sys.exit(1)
    
    print(f"  ✅ Connected: {org_info['username']}")
    print()
    
    # Initialize database
    db_utils.init_database()
    
    # Get duplicate groups
    print("📥 Retrieving duplicate groups from database...")
    groups = db_utils.get_duplicate_groups(
        run_id=args.run_id,
        object_type='Contact',
        pending_only=True
    )
    
    if not groups:
        print("\n⚠️  No pending duplicate groups found")
        if args.run_id:
            print(f"   (for run ID {args.run_id})")
        sys.exit(0)
    
    print(f"  ✅ Found {len(groups)} duplicate group(s)")
    print()
    
    # Determine run_id if not specified
    run_id = args.run_id if args.run_id else groups[0]['run_id'] if groups else None
    
    # Process merges
    if args.batch:
        merged_count, skipped_count, failed_count, merge_results = batch_merge(
            args.org_alias, groups, args.dry_run
        )
    else:
        merged_count, skipped_count, failed_count, merge_results = interactive_merge(
            args.org_alias, groups, args.dry_run
        )
    
    # Save merge results to database
    if not args.dry_run and merge_results:
        print("\n💾 Saving merge results to database...")
        for result in merge_results:
            if result['status'] == 'success':
                db_utils.save_merge_result(
                    run_id=run_id,
                    group_id=result['group_id'],
                    master_id=result.get('master_id', ''),
                    merged_ids=result.get('merged_ids', []),
                    status='success'
                )
            elif result['status'] == 'failed':
                db_utils.save_merge_result(
                    run_id=run_id,
                    group_id=result['group_id'],
                    master_id='',
                    merged_ids=[],
                    status='failed',
                    error=result.get('error', 'Unknown error')
                )
    
    # Generate and save report
    report_text = generate_merge_report(
        merge_results, args.org_alias, run_id, merged_count, skipped_count, failed_count
    )
    
    print("\n" + report_text)
    
    # Save report to file
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_filename = RESULTS_DIR / f"contact_merge_{timestamp}.txt"
    with open(report_filename, 'w') as f:
        f.write(report_text)
    
    print(f"\n📄 Report saved: {report_filename}")
    print(f"{'='*80}")


if __name__ == '__main__':
    main()
