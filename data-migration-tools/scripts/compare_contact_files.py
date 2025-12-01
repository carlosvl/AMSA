#!/usr/bin/env python3
"""
Contact Files Comparison Tool
Identifies files attached to contacts in source org that are missing in target org
"""
import json
import subprocess
import sys
from datetime import datetime
from collections import defaultdict

def query_contact_files(org_alias, org_name, contact_ids=None):
    """Query all files linked to specific contacts in an org"""
    print(f"📥 Querying files from {org_name}...")
    
    if not contact_ids or len(contact_ids) == 0:
        print(f"  ⚠️  No contact IDs provided")
        return {}
    
    # Query in batches (SOQL IN clause limit is 4000)
    batch_size = 200
    all_links = []
    
    for i in range(0, len(contact_ids), batch_size):
        batch = contact_ids[i:i+batch_size]
        ids_str = "','".join(batch)
        
        # Query ContentDocumentLinks for specific contacts
        query = f"SELECT ContentDocumentId, LinkedEntityId FROM ContentDocumentLink WHERE LinkedEntityId IN ('{ids_str}')"
        
        if i == 0:
            print(f"  📊 Querying in batches of {batch_size}...")
        
        if (i // batch_size) % 5 == 0 and i > 0:
            print(f"  Progress: {i}/{len(contact_ids)} contacts processed...")
        
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
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                batch_links = data.get('result', {}).get('records', [])
                all_links.extend(batch_links)
            else:
                print(f"  ⚠️  Batch {i//batch_size + 1} failed: {result.stderr[:100]}")
        
        except Exception as e:
            print(f"  ⚠️  Batch error: {str(e)[:100]}")
            continue
    
    print(f"  ✅ Found {len(all_links)} file-contact links")
    
    # Get unique ContentDocument IDs
    doc_ids = list(set([link['ContentDocumentId'] for link in all_links]))
    print(f"  📊 Querying details for {len(doc_ids)} unique documents...")
    
    # Query ContentDocument details in batches
    all_docs = {}
    for i in range(0, len(doc_ids), batch_size):
        batch = doc_ids[i:i+batch_size]
        ids_str = "','".join(batch)
        
        doc_query = f"SELECT Id, Title, FileType, ContentSize, CreatedDate, LatestPublishedVersionId FROM ContentDocument WHERE Id IN ('{ids_str}')"
        
        try:
            result = subprocess.run(
                ['sf', 'data', 'query',
                 '--query', doc_query,
                 '--target-org', org_alias,
                 '--json'],
                capture_output=True,
                text=True,
                timeout=120
            )
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                docs = data.get('result', {}).get('records', [])
                for doc in docs:
                    all_docs[doc['Id']] = doc
        
        except Exception as e:
            continue
    
    # Organize by contact
    files_by_contact = defaultdict(list)
    
    for link in all_links:
        contact_id = link.get('LinkedEntityId')
        doc_id = link.get('ContentDocumentId')
        
        # Get ContentDocument details
        content_doc = all_docs.get(doc_id, {})
        
        if content_doc:
            file_info = {
                'ContentDocumentId': doc_id,
                'Title': content_doc.get('Title', 'Unknown'),
                'FileType': content_doc.get('FileType', ''),
                'ContentSize': content_doc.get('ContentSize', 0),
                'CreatedDate': content_doc.get('CreatedDate', ''),
                'LatestPublishedVersionId': content_doc.get('LatestPublishedVersionId', '')
            }
            
            files_by_contact[contact_id].append(file_info)
    
    return files_by_contact

def load_contact_mapping():
    """Load the most recent contact ID mapping"""
    import os
    import glob
    
    # Find most recent contact comparison file
    pattern = '../results/contact_comparison_*.json'
    files = glob.glob(pattern)
    
    if not files:
        print("❌ No contact comparison results found!")
        print("   Please run compare_contacts.py first")
        return None
    
    # Get most recent file
    latest_file = max(files, key=os.path.getmtime)
    
    print(f"📂 Loading contact mapping from: {os.path.basename(latest_file)}")
    
    try:
        with open(latest_file, 'r') as f:
            data = json.load(f)
        
        # Build mapping from results
        mapping = {}
        
        # Add ExternalID matches
        for match in data['results']['matched_by_external_id']:
            mapping[match['source_id']] = match['target_id']
        
        # Add email matches
        for match in data['results']['matched_by_email']:
            mapping[match['source_id']] = match['target_id']
        
        print(f"  ✅ Loaded mapping for {len(mapping)} contacts")
        return mapping
    
    except Exception as e:
        print(f"  ❌ Error loading mapping: {e}")
        return None

def compare_files(source_files, target_files, contact_mapping):
    """Compare files between source and target orgs"""
    print(f"\n🔍 Comparing files...")
    
    results = {
        'contacts_with_files_in_source': 0,
        'contacts_with_files_in_target': 0,
        'contacts_missing_files': 0,
        'total_files_in_source': 0,
        'total_files_in_target': 0,
        'missing_files': [],
        'contacts_not_in_target': []
    }
    
    # Check each source contact
    for source_contact_id, source_file_list in source_files.items():
        results['total_files_in_source'] += len(source_file_list)
        results['contacts_with_files_in_source'] += 1
        
        # Check if contact exists in target
        target_contact_id = contact_mapping.get(source_contact_id)
        
        if not target_contact_id:
            results['contacts_not_in_target'].append({
                'source_contact_id': source_contact_id,
                'file_count': len(source_file_list),
                'files': source_file_list
            })
            continue
        
        # Get target files for this contact
        target_file_list = target_files.get(target_contact_id, [])
        
        if target_file_list:
            results['contacts_with_files_in_target'] += 1
            results['total_files_in_target'] += len(target_file_list)
        
        # Compare files by title and approximate size
        target_file_titles = {f['Title'].lower(): f for f in target_file_list}
        
        missing = []
        for source_file in source_file_list:
            source_title = source_file['Title'].lower()
            
            # Check if file exists in target
            if source_title not in target_file_titles:
                missing.append(source_file)
            else:
                # File with same title exists, could check size too
                target_file = target_file_titles[source_title]
                size_diff = abs(source_file['ContentSize'] - target_file['ContentSize'])
                
                # If size differs by more than 1KB, might be different file
                if size_diff > 1024:
                    missing.append({
                        **source_file,
                        'note': f'Size mismatch: source={source_file["ContentSize"]}, target={target_file["ContentSize"]}'
                    })
        
        if missing:
            results['contacts_missing_files'] += 1
            results['missing_files'].append({
                'source_contact_id': source_contact_id,
                'target_contact_id': target_contact_id,
                'missing_count': len(missing),
                'files': missing
            })
    
    return results

def generate_report(results, source_org, target_org):
    """Generate detailed comparison report"""
    report = []
    report.append("="*80)
    report.append("CONTACT FILES COMPARISON REPORT")
    report.append("="*80)
    report.append("")
    report.append(f"Source Org: {source_org}")
    report.append(f"Target Org: {target_org}")
    report.append(f"Report Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append("")
    report.append("="*80)
    report.append("SUMMARY")
    report.append("="*80)
    report.append(f"Source Contacts with Files: {results['contacts_with_files_in_source']}")
    report.append(f"Total Files in Source: {results['total_files_in_source']}")
    report.append(f"Target Contacts with Files: {results['contacts_with_files_in_target']}")
    report.append(f"Total Files in Target: {results['total_files_in_target']}")
    report.append("")
    report.append(f"📊 Contacts Missing Files: {results['contacts_missing_files']}")
    report.append(f"📊 Contacts Not in Target: {len(results['contacts_not_in_target'])}")
    
    # Calculate missing file count
    total_missing = sum(c['missing_count'] for c in results['missing_files'])
    report.append(f"📊 Total Missing Files: {total_missing}")
    report.append("")
    
    # Missing files details
    if results['missing_files']:
        report.append("="*80)
        report.append(f"CONTACTS WITH MISSING FILES ({len(results['missing_files'])} contacts)")
        report.append("="*80)
        report.append("")
        
        for item in results['missing_files'][:50]:  # Show first 50
            report.append(f"📁 Source Contact: {item['source_contact_id']}")
            report.append(f"   Target Contact: {item['target_contact_id']}")
            report.append(f"   Missing Files: {item['missing_count']}")
            report.append("")
            
            for file in item['files'][:10]:  # Show first 10 files per contact
                size_mb = file['ContentSize'] / (1024 * 1024)
                report.append(f"   ❌ {file['Title']}")
                report.append(f"      Type: {file['FileType']} | Size: {size_mb:.2f} MB")
                report.append(f"      Created: {file['CreatedDate']}")
                if 'note' in file:
                    report.append(f"      Note: {file['note']}")
                report.append("")
            
            if len(item['files']) > 10:
                report.append(f"   ... and {len(item['files']) - 10} more files")
                report.append("")
        
        if len(results['missing_files']) > 50:
            report.append(f"... and {len(results['missing_files']) - 50} more contacts with missing files")
            report.append("")
    
    # Contacts not in target
    if results['contacts_not_in_target']:
        report.append("="*80)
        report.append(f"CONTACTS NOT IN TARGET ORG ({len(results['contacts_not_in_target'])} contacts)")
        report.append("="*80)
        report.append("")
        
        for item in results['contacts_not_in_target'][:20]:
            report.append(f"❌ Source Contact: {item['source_contact_id']}")
            report.append(f"   Files Count: {item['file_count']}")
            report.append("")
    
    return "\n".join(report)

def main():
    """Main execution"""
    print("="*80)
    print("📎 CONTACT FILES COMPARISON TOOL")
    print("="*80)
    print()
    
    # Get parameters
    if len(sys.argv) >= 3:
        source_org = sys.argv[1]
        target_org = sys.argv[2]
    else:
        print("❌ Missing parameters!")
        print("\nUsage:")
        print("  python3 compare_contact_files.py <source_org> <target_org>")
        print("\nExample:")
        print("  python3 compare_contact_files.py 'AMSA-Royalty-Prod' 'AMSA Prod'")
        sys.exit(1)
    
    print("📋 Parameters:")
    print(f"  Source Org: {source_org}")
    print(f"  Target Org: {target_org}")
    print()
    
    # Load contact mapping
    contact_mapping = load_contact_mapping()
    if not contact_mapping:
        sys.exit(1)
    print()
    
    # Get lists of contact IDs
    source_contact_ids = list(contact_mapping.keys())
    target_contact_ids = list(contact_mapping.values())
    
    print(f"📊 Will query files for {len(source_contact_ids)} contacts")
    print()
    
    # Query files from both orgs
    source_files = query_contact_files(source_org, "Source", source_contact_ids)
    print()
    target_files = query_contact_files(target_org, "Target", target_contact_ids)
    print()
    
    if not source_files:
        print("⚠️  No files found in source org")
        sys.exit(0)
    
    # Compare files
    results = compare_files(source_files, target_files, contact_mapping)
    
    # Generate report
    report_text = generate_report(results, source_org, target_org)
    print("\n" + report_text)
    
    # Save results
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    # Save detailed JSON
    json_filename = f"../results/files_comparison_{timestamp}.json"
    with open(json_filename, 'w') as f:
        json.dump({
            'metadata': {
                'source_org': source_org,
                'target_org': target_org,
                'timestamp': timestamp
            },
            'results': results
        }, f, indent=2)
    
    # Save report
    report_filename = f"../results/files_comparison_{timestamp}.txt"
    with open(report_filename, 'w') as f:
        f.write(report_text)
    
    print(f"\n{'='*80}")
    print(f"📄 Results saved:")
    print(f"  - {json_filename}")
    print(f"  - {report_filename}")
    print(f"{'='*80}")

if __name__ == '__main__':
    main()

