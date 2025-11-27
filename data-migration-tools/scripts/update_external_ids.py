#!/usr/bin/env python3
"""
Update ExternalID__c field for matched contacts
Takes comparison results and updates target org Contact.ExternalID__c
"""
import json
import subprocess
import sys
import csv
import tempfile
import os
from datetime import datetime

def load_comparison_results(results_file):
    """Load comparison results JSON"""
    try:
        with open(results_file, 'r') as f:
            data = json.load(f)
        return data
    except Exception as e:
        print(f"❌ Error loading results: {e}")
        return None

def prepare_updates(comparison_data):
    """Prepare update records from comparison data"""
    matched_by_email = comparison_data['results']['matched_by_email']
    
    updates = []
    for match in matched_by_email:
        # Only update if ExternalID__c is not already set or is different
        current_external_id = match.get('target_external_id')
        source_id = match['source_id']
        
        # Skip if already correctly set
        if current_external_id == source_id:
            continue
        
        updates.append({
            'Id': match['target_id'],
            'ExternalID__c': source_id
        })
    
    return updates

def update_contacts_bulk(org_alias, updates):
    """Update contacts using bulk CSV import"""
    if not updates:
        print("⚠️  No updates needed - all ExternalID__c values already set correctly")
        return True
    
    print(f"📝 Preparing to update {len(updates)} contacts...")
    
    # Create temporary CSV file
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as csvfile:
        csv_path = csvfile.name
        
        writer = csv.DictWriter(csvfile, fieldnames=['Id', 'ExternalID__c'])
        writer.writeheader()
        writer.writerows(updates)
    
    try:
        print(f"📤 Uploading updates to {org_alias}...")
        
        # Use sf data upsert command
        result = subprocess.run(
            ['sf', 'data', 'upsert', 'bulk',
             '--sobject', 'Contact',
             '--file', csv_path,
             '--external-id', 'Id',
             '--target-org', org_alias,
             '--wait', '10',
             '--json'],
            capture_output=True,
            text=True,
            timeout=300
        )
        
        # Parse result
        if result.returncode == 0:
            data = json.loads(result.stdout)
            job_info = data.get('result', {})
            
            print(f"✅ Bulk job completed!")
            print(f"  Job ID: {job_info.get('jobInfo', {}).get('id', 'N/A')}")
            print(f"  Records Processed: {job_info.get('jobInfo', {}).get('numberRecordsProcessed', 0)}")
            print(f"  Records Failed: {job_info.get('jobInfo', {}).get('numberRecordsFailed', 0)}")
            
            return True
        else:
            print(f"❌ Bulk update failed: {result.stderr}")
            return False
    
    except Exception as e:
        print(f"❌ Error during update: {e}")
        return False
    
    finally:
        # Clean up temp file
        if os.path.exists(csv_path):
            os.remove(csv_path)

def update_contacts_individual(org_alias, updates, batch_size=200):
    """Update contacts one by one (fallback method)"""
    if not updates:
        print("⚠️  No updates needed")
        return True
    
    print(f"📝 Updating {len(updates)} contacts individually...")
    
    success_count = 0
    fail_count = 0
    failed_records = []
    
    for i, update in enumerate(updates, 1):
        contact_id = update['Id']
        external_id = update['ExternalID__c']
        
        if i % 50 == 0:
            print(f"  Progress: {i}/{len(updates)} ({success_count} success, {fail_count} failed)")
        
        try:
            result = subprocess.run(
                ['sf', 'data', 'update', 'record',
                 '--sobject', 'Contact',
                 '--record-id', contact_id,
                 '--values', f"ExternalID__c={external_id}",
                 '--target-org', org_alias,
                 '--json'],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                success_count += 1
            else:
                fail_count += 1
                failed_records.append({
                    'Id': contact_id,
                    'ExternalID__c': external_id,
                    'error': result.stderr
                })
        
        except Exception as e:
            fail_count += 1
            failed_records.append({
                'Id': contact_id,
                'ExternalID__c': external_id,
                'error': str(e)
            })
    
    print(f"\n✅ Update complete!")
    print(f"  Success: {success_count}")
    print(f"  Failed: {fail_count}")
    
    if failed_records:
        # Save failed records
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        failed_file = f"../results/failed_updates_{timestamp}.json"
        with open(failed_file, 'w') as f:
            json.dump(failed_records, f, indent=2)
        print(f"  Failed records saved to: {failed_file}")
    
    return fail_count == 0

def main():
    """Main execution"""
    print("="*80)
    print("🔄 UPDATE ExternalID__c TOOL")
    print("="*80)
    print()
    
    # Get parameters
    if len(sys.argv) >= 3:
        results_file = sys.argv[1]
        target_org = sys.argv[2]
        method = 'bulk'
        skip_confirm = False
        
        # Parse optional arguments
        for arg in sys.argv[3:]:
            if arg in ['bulk', 'individual']:
                method = arg
            elif arg in ['--yes', '-y']:
                skip_confirm = True
    else:
        print("❌ Missing parameters!")
        print("\nUsage:")
        print("  python3 update_external_ids.py <results_file> <target_org> [method] [--yes]")
        print("\nExample:")
        print("  python3 update_external_ids.py ../results/contact_comparison_20251127_092915.json 'AMSA Prod' bulk --yes")
        print("\nMethods:")
        print("  bulk       - Use bulk API (faster, recommended)")
        print("  individual - Update one by one (slower, more reliable for small sets)")
        print("\nFlags:")
        print("  --yes, -y  - Skip confirmation prompt")
        sys.exit(1)
    
    # Display parameters
    print("📋 Parameters:")
    print(f"  Results File: {results_file}")
    print(f"  Target Org: {target_org}")
    print(f"  Method: {method}")
    print()
    
    # Load comparison results
    print("📂 Loading comparison results...")
    comparison_data = load_comparison_results(results_file)
    
    if not comparison_data:
        sys.exit(1)
    
    metadata = comparison_data.get('metadata', {})
    print(f"  ✅ Loaded results from {metadata.get('timestamp', 'unknown')}")
    print(f"  Source: {metadata.get('source_org', 'unknown')}")
    print(f"  Target: {metadata.get('target_org', 'unknown')}")
    print()
    
    # Prepare updates
    print("🔧 Preparing updates...")
    updates = prepare_updates(comparison_data)
    
    matched_by_email_count = len(comparison_data['results']['matched_by_email'])
    print(f"  Total contacts matched by email: {matched_by_email_count}")
    print(f"  Contacts needing ExternalID__c update: {len(updates)}")
    print()
    
    if len(updates) == 0:
        print("✅ All contacts already have correct ExternalID__c values!")
        sys.exit(0)
    
    # Confirm update
    if not skip_confirm:
        print("⚠️  This will update ExternalID__c for contacts in the target org.")
        try:
            response = input("Continue? (yes/no): ").strip().lower()
            if response not in ['yes', 'y']:
                print("❌ Update cancelled by user")
                sys.exit(0)
        except (EOFError, KeyboardInterrupt):
            print("\n❌ Update cancelled")
            sys.exit(0)
        print()
    else:
        print("⚠️  Skipping confirmation (--yes flag)")
        print()
    
    # Perform update
    if method == 'bulk':
        success = update_contacts_bulk(target_org, updates)
    else:
        success = update_contacts_individual(target_org, updates)
    
    if success:
        print("\n✅ ExternalID__c update completed successfully!")
        
        # Save update summary
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        summary_file = f"../results/external_id_update_{timestamp}.json"
        
        summary = {
            'timestamp': timestamp,
            'target_org': target_org,
            'source_results_file': results_file,
            'method': method,
            'total_updates': len(updates),
            'updates': updates
        }
        
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        print(f"📄 Update summary saved to: {summary_file}")
    else:
        print("\n⚠️  Update completed with errors. Review logs above.")
        sys.exit(1)

if __name__ == '__main__':
    main()

