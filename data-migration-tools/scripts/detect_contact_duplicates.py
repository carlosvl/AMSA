#!/usr/bin/env python3
"""
Contact Duplicate Detection Tool
Detects duplicate Contact records within a single Salesforce org using full name and email as matching fields.

Usage:
    python3 detect_contact_duplicates.py <org_alias> [--export-json] [--export-csv]

Example:
    python3 detect_contact_duplicates.py "AMSA Prod"
    python3 detect_contact_duplicates.py "AMSA Prod" --export-json
"""
import json
import subprocess
import sys
import argparse
import hashlib
import csv
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple
from collections import defaultdict

import db_utils

BASE_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = BASE_DIR / 'results'
RESULTS_DIR.mkdir(exist_ok=True)


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


def query_all_contacts(org_alias):
    """Query all contacts from the org"""
    print(f"📥 Querying all contacts from {org_alias}...")
    
    query = "SELECT Id, FirstName, LastName, Email, Phone, AccountId, CreatedDate, LastModifiedDate, OwnerId FROM Contact ORDER BY CreatedDate DESC"
    
    try:
        result = subprocess.run(
            ['sf', 'data', 'query', 
             '--query', query,
             '--target-org', org_alias,
             '--json'],
            capture_output=True,
            text=True,
            check=True,
            timeout=300  # Longer timeout for large datasets
        )
        
        data = json.loads(result.stdout)
        contacts = data.get('result', {}).get('records', [])
        
        print(f"  ✅ Found {len(contacts)} contacts")
        return contacts
    
    except Exception as e:
        print(f"  ❌ Error: {e}")
        return []


def normalize_name(first_name, last_name):
    """Normalize full name for comparison"""
    first = (first_name or '').strip().lower()
    last = (last_name or '').strip().lower()
    return f"{first} {last}".strip()


def normalize_email(email):
    """Normalize email for comparison"""
    if not email:
        return None
    return email.strip().lower()


def create_group_key(first_name, last_name, email):
    """Create a unique group key for duplicate matching"""
    # Use normalized values
    name_part = normalize_name(first_name, last_name)
    email_part = normalize_email(email) or ''
    
    # Create hash of the combination
    key_string = f"{name_part}|{email_part}"
    return hashlib.md5(key_string.encode()).hexdigest()


def detect_duplicates(contacts):
    """Detect duplicate contacts by full name and email"""
    print(f"\n🔍 Analyzing {len(contacts)} contacts for duplicates...")
    
    # Group contacts by matching criteria (full name + email)
    groups = defaultdict(list)
    
    for contact in contacts:
        first_name = contact.get('FirstName', '')
        last_name = contact.get('LastName', '')
        email = contact.get('Email')
        
        # Create full name
        full_name = normalize_name(first_name, last_name)
        
        # Create group key
        group_key = create_group_key(first_name, last_name, email)
        
        # Store contact in group
        groups[group_key].append({
            'Id': contact['Id'],
            'FirstName': first_name,
            'LastName': last_name,
            'FullName': f"{first_name} {last_name}".strip(),
            'Email': email,
            'Phone': contact.get('Phone'),
            'AccountId': contact.get('AccountId'),
            'CreatedDate': contact.get('CreatedDate'),
            'LastModifiedDate': contact.get('LastModifiedDate'),
            'OwnerId': contact.get('OwnerId')
        })
    
    # Find groups with duplicates (more than 1 record)
    duplicate_groups = {}
    total_duplicates = 0
    
    for group_key, records in groups.items():
        if len(records) > 1:
            # Sort by LastModifiedDate (most recent first) to identify potential keeper
            records.sort(key=lambda x: x.get('LastModifiedDate') or '', reverse=True)
            
            duplicate_groups[group_key] = {
                'group_key': group_key,
                'full_name': records[0]['FullName'],
                'email': records[0]['Email'],
                'records': records,
                'count': len(records)
            }
            total_duplicates += len(records)
    
    print(f"  📊 Found {len(duplicate_groups)} duplicate groups")
    print(f"  📊 Total duplicate records: {total_duplicates}")
    print(f"  📊 Unique contacts: {len(contacts) - total_duplicates + len(duplicate_groups)}")
    
    return duplicate_groups


def generate_report(duplicate_groups, org_alias):
    """Generate detailed duplicate detection report"""
    total_groups = len(duplicate_groups)
    total_duplicate_records = sum(group['count'] for group in duplicate_groups.values())
    
    report = []
    report.append("="*80)
    report.append("CONTACT DUPLICATE DETECTION REPORT")
    report.append("="*80)
    report.append("")
    report.append(f"Org: {org_alias}")
    report.append(f"Report Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("")
    report.append("="*80)
    report.append("SUMMARY")
    report.append("="*80)
    report.append(f"Total Duplicate Groups: {total_groups}")
    report.append(f"Total Duplicate Records: {total_duplicate_records}")
    report.append(f"Unique Contacts Affected: {total_groups}")
    report.append("")
    
    if duplicate_groups:
        report.append("="*80)
        report.append(f"DUPLICATE GROUPS ({total_groups} groups)")
        report.append("="*80)
        report.append("")
        
        # Sort by count (most duplicates first)
        sorted_groups = sorted(duplicate_groups.values(), key=lambda x: x['count'], reverse=True)
        
        for idx, group in enumerate(sorted_groups[:50], 1):  # Show top 50 groups
            report.append(f"Group {idx}: {group['full_name']} ({group['email'] or 'No Email'})")
            report.append(f"  Duplicate Count: {group['count']}")
            report.append(f"  Records:")
            for record in group['records']:
                report.append(f"    - ID: {record['Id']}")
                report.append(f"      Name: {record['FullName']}")
                report.append(f"      Email: {record['Email'] or 'No Email'}")
                report.append(f"      Created: {record.get('CreatedDate', 'N/A')}")
                report.append(f"      Last Modified: {record.get('LastModifiedDate', 'N/A')}")
            report.append("")
        
        if len(sorted_groups) > 50:
            report.append(f"  ... and {len(sorted_groups) - 50} more duplicate groups")
            report.append("")
    else:
        report.append("✅ No duplicates found!")
        report.append("")
    
    return "\n".join(report)


def show_existing_runs():
    """Display existing duplicate detection runs"""
    runs = db_utils.get_duplicate_detection_runs('Contact')
    
    if not runs:
        print("  📭 No existing duplicate detection runs found")
        return []
    
    print(f"\n  📊 Found {len(runs)} existing duplicate detection run(s):")
    print()
    print("  " + "-"*76)
    print(f"  {'Run ID':<8} {'Date':<20} {'Org':<25} {'Groups':<8} {'Status':<10}")
    print("  " + "-"*76)
    
    for run in runs:
        timestamp = run.get('timestamp', 'N/A')
        if timestamp and timestamp != 'N/A':
            # Format timestamp for display
            try:
                if isinstance(timestamp, str):
                    dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                else:
                    dt = timestamp
                timestamp_str = dt.strftime('%Y-%m-%d %H:%M:%S')
            except:
                timestamp_str = str(timestamp)[:19]
        else:
            timestamp_str = 'N/A'
        
        print(f"  {run['id']:<8} {timestamp_str:<20} {run.get('source_org', 'N/A')[:24]:<25} "
              f"{run.get('matched_count', 0):<8} {run.get('status', 'N/A'):<10}")
    
    print("  " + "-"*76)
    print()
    
    return runs


def prompt_clear_results():
    """Prompt user to clear existing results"""
    runs = show_existing_runs()
    
    if not runs:
        return True  # No existing runs, proceed
    
    print("⚠️  Existing duplicate detection results found in database.")
    print()
    print("Options:")
    print("  1. Clear ALL existing results and run fresh detection")
    print("  2. Clear specific run (you'll be prompted for run ID)")
    print("  3. Keep existing results and add new detection run")
    print("  4. Exit")
    
    while True:
        choice = input("\nEnter choice (1-4): ").strip()
        
        if choice == '1':
            # Clear all
            confirm = input("  ⚠️  Are you sure you want to delete ALL duplicate detection results? (yes/no): ").strip().lower()
            if confirm in ['yes', 'y']:
                print("\n🗑️  Clearing all duplicate detection results...")
                runs_deleted, groups_deleted, records_deleted = db_utils.delete_all_duplicate_groups('Contact')
                print(f"  ✅ Deleted {runs_deleted} run(s), {groups_deleted} group(s), {records_deleted} record(s)")
                return True
            else:
                print("  ⏭️  Cancelled. Keeping existing results.")
                return False
        
        elif choice == '2':
            # Clear specific run
            try:
                run_id_input = input("  Enter run ID to delete: ").strip()
                run_id = int(run_id_input)
                
                # Verify run exists
                if not any(r['id'] == run_id for r in runs):
                    print(f"  ❌ Run ID {run_id} not found")
                    continue
                
                confirm = input(f"  ⚠️  Delete run {run_id}? (yes/no): ").strip().lower()
                if confirm in ['yes', 'y']:
                    print(f"\n🗑️  Clearing run {run_id}...")
                    groups_deleted, records_deleted = db_utils.delete_duplicate_groups_by_run_id(run_id)
                    print(f"  ✅ Deleted {groups_deleted} group(s), {records_deleted} record(s)")
                    return True
                else:
                    print("  ⏭️  Cancelled.")
                    return False
            except ValueError:
                print("  ❌ Invalid run ID. Please enter a number.")
                continue
        
        elif choice == '3':
            # Keep existing, proceed
            print("  ✅ Keeping existing results. New detection will be added.")
            return True
        
        elif choice == '4':
            # Exit
            print("\n👋 Exiting...")
            sys.exit(0)
        
        else:
            print("  ❌ Invalid choice. Please enter 1, 2, 3, or 4.")


def main():
    """Main execution function"""
    parser = argparse.ArgumentParser(
        description='Detect duplicate Contact records by full name and email'
    )
    parser.add_argument('org_alias', help='Salesforce org alias')
    parser.add_argument('--export-json', action='store_true', 
                       help='Export results to JSON file')
    parser.add_argument('--export-csv', action='store_true',
                       help='Export results to CSV file')
    parser.add_argument('--clear-all', action='store_true',
                       help='Clear all existing duplicate detection results before running')
    parser.add_argument('--clear-run', type=int, metavar='RUN_ID',
                       help='Clear specific run ID before running')
    parser.add_argument('--no-prompt', action='store_true',
                       help='Skip prompts and run detection (keeps existing results)')
    
    args = parser.parse_args()
    
    print("="*80)
    print("🔍 CONTACT DUPLICATE DETECTION TOOL")
    print("="*80)
    print()
    print("📋 Parameters:")
    print(f"  Org: {args.org_alias}")
    print(f"  Matching Fields: Full Name + Email")
    print()
    
    # Connect to org
    print("🔐 Connecting to org...")
    org_info = get_org_credentials(args.org_alias)
    
    if not org_info:
        print("\n❌ Failed to connect to org")
        sys.exit(1)
    
    print(f"  ✅ Connected: {org_info['username']} ({org_info['instance_url']})")
    print()
    
    # Initialize database
    db_utils.init_database()
    
    # Handle clearing results
    if args.clear_all:
        print("🗑️  Clearing all existing duplicate detection results...")
        runs_deleted, groups_deleted, records_deleted = db_utils.delete_all_duplicate_groups('Contact')
        print(f"  ✅ Deleted {runs_deleted} run(s), {groups_deleted} group(s), {records_deleted} record(s)")
        print()
    elif args.clear_run:
        print(f"🗑️  Clearing run {args.clear_run}...")
        groups_deleted, records_deleted = db_utils.delete_duplicate_groups_by_run_id(args.clear_run)
        print(f"  ✅ Deleted {groups_deleted} group(s), {records_deleted} record(s)")
        print()
    elif not args.no_prompt:
        # Interactive prompt
        should_proceed = prompt_clear_results()
        if not should_proceed:
            print("\n👋 Exiting without running detection.")
            sys.exit(0)
        print()
    
    # Query contacts
    contacts = query_all_contacts(args.org_alias)
    if not contacts:
        print("\n⚠️  No contacts found in org")
        sys.exit(0)
    
    # Detect duplicates
    duplicate_groups = detect_duplicates(contacts)
    
    # Create comparison run record
    run_id = db_utils.create_comparison_run(
        run_type='contact_duplicate_detection',
        source_org=args.org_alias,
        notes=f"Duplicate detection using Full Name + Email matching"
    )
    
    # Save duplicate groups to database
    print(f"\n💾 Saving results to database...")
    saved_groups = 0
    for group_key, group_data in duplicate_groups.items():
        # Mark the most recently modified record as potential keeper
        records = group_data['records']
        for i, record in enumerate(records):
            record['is_keeper'] = 1 if i == 0 else 0  # First record (most recent) is keeper
        
        db_utils.save_duplicate_group(
            run_id=run_id,
            object_type='Contact',
            group_key=group_key,
            records=records,
            action='pending'
        )
        saved_groups += 1
    
    print(f"  ✅ Saved {saved_groups} duplicate groups to database")
    
    # Update run statistics
    db_utils.update_comparison_run(
        run_id=run_id,
        total_source_records=len(contacts),
        matched_count=len(duplicate_groups),
        unmatched_count=len(contacts) - sum(g['count'] for g in duplicate_groups.values()) + len(duplicate_groups),
        status='completed'
    )
    
    # Generate report
    report_text = generate_report(duplicate_groups, args.org_alias)
    
    # Display summary
    print("\n" + report_text)
    
    # Save results
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Save detailed JSON
    if args.export_json:
        json_filename = RESULTS_DIR / f"contact_duplicates_{timestamp}.json"
        with open(json_filename, 'w') as f:
            json.dump({
                'metadata': {
                    'org_alias': args.org_alias,
                    'run_id': run_id,
                    'timestamp': timestamp,
                    'matching_fields': ['FullName', 'Email']
                },
                'summary': {
                    'total_contacts': len(contacts),
                    'duplicate_groups': len(duplicate_groups),
                    'total_duplicate_records': sum(g['count'] for g in duplicate_groups.values())
                },
                'duplicate_groups': duplicate_groups
            }, f, indent=2)
        print(f"\n📄 JSON results saved: {json_filename}")
    
    # Save report text
    report_filename = RESULTS_DIR / f"contact_duplicates_{timestamp}.txt"
    with open(report_filename, 'w') as f:
        f.write(report_text)
    print(f"📄 Report saved: {report_filename}")
    
    # Save CSV if requested
    if args.export_csv:
        csv_filename = RESULTS_DIR / f"contact_duplicates_{timestamp}.csv"
        with open(csv_filename, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Group Key', 'Full Name', 'Email', 'Record ID', 'First Name', 
                           'Last Name', 'Phone', 'Created Date', 'Last Modified Date', 'Is Keeper'])
            
            for group_key, group_data in duplicate_groups.items():
                for record in group_data['records']:
                    writer.writerow([
                        group_key,
                        group_data['full_name'],
                        group_data['email'] or '',
                        record['Id'],
                        record['FirstName'] or '',
                        record['LastName'] or '',
                        record.get('Phone') or '',
                        record.get('CreatedDate') or '',
                        record.get('LastModifiedDate') or '',
                        'Yes' if record.get('is_keeper') else 'No'
                    ])
        print(f"📄 CSV results saved: {csv_filename}")
    
    print(f"\n{'='*80}")
    print(f"✅ Duplicate detection complete!")
    print(f"   Run ID: {run_id}")
    print(f"   Database: {db_utils.DB_PATH}")
    print(f"{'='*80}")


if __name__ == '__main__':
    main()
