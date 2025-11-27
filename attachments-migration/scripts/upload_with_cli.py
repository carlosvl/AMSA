#!/usr/bin/env python3
"""
Upload Contact files to AMSA Prod using Salesforce CLI
"""
import json
import subprocess
import os
import time
import base64

def create_content_version_with_cli(org_alias, title, path_on_client, file_path):
    """Create ContentVersion using SF CLI"""
    try:
        # Read and encode file
        with open(file_path, 'rb') as f:
            file_data = base64.b64encode(f.read()).decode('utf-8')
        
        # Create using SF CLI
        cmd = [
            'sf', 'data', 'create', 'record',
            '--sobject', 'ContentVersion',
            '--values', f"Title='{title}' PathOnClient='{path_on_client}' VersionData='{file_data}'",
            '--target-org', org_alias,
            '--json'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data.get('status') == 0:
                return data['result']['id'], None
            else:
                return None, f"CLI Error: {data.get('message', 'Unknown error')}"
        else:
            return None, f"CLI failed: {result.stderr}"
    
    except subprocess.TimeoutExpired:
        return None, "Upload timeout (60s)"
    except Exception as e:
        return None, str(e)

def query_content_document_id(org_alias, content_version_id, max_retries=10):
    """Query for ContentDocumentId with retries"""
    for attempt in range(max_retries):
        try:
            cmd = [
                'sf', 'data', 'query',
                '--query', f"SELECT ContentDocumentId FROM ContentVersion WHERE Id = '{content_version_id}'",
                '--target-org', org_alias,
                '--json'
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                records = data.get('result', {}).get('records', [])
                if records and records[0].get('ContentDocumentId'):
                    return records[0]['ContentDocumentId'], None
            
            # Wait before retry
            if attempt < max_retries - 1:
                time.sleep(1)
        
        except Exception as e:
            if attempt == max_retries - 1:
                return None, str(e)
            time.sleep(1)
    
    return None, "ContentDocument not found after retries"

def create_content_document_link(org_alias, content_doc_id, contact_id, share_type='C'):
    """Create ContentDocumentLink using SF CLI"""
    try:
        cmd = [
            'sf', 'data', 'create', 'record',
            '--sobject', 'ContentDocumentLink',
            '--values', f"ContentDocumentId='{content_doc_id}' LinkedEntityId='{contact_id}' ShareType='{share_type}' Visibility='AllUsers'",
            '--target-org', org_alias,
            '--json'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data.get('status') == 0:
                return data['result']['id'], None
            else:
                return None, f"Link creation failed: {data.get('message', 'Unknown')}"
        else:
            return None, f"CLI failed: {result.stderr}"
    
    except Exception as e:
        return None, str(e)

def main():
    org_alias = 'AMSA Prod'
    files_dir = 'downloaded_contact_files'
    
    print(f"🚀 Starting file upload using Salesforce CLI")
    print(f"📂 Target Org: {org_alias}\n")
    
    # Load data
    with open('contact_file_versions_enriched.json', 'r') as f:
        file_versions = json.load(f)
    
    with open('contact_id_mapping.json', 'r') as f:
        id_mapping = json.load(f)
    
    print(f"📊 Files to upload: {len(file_versions)}")
    print(f"📊 Contacts mapped: {len(id_mapping)}")
    print(f"\n{'='*80}\n")
    
    # Results tracking
    results = {
        'uploaded': 0,
        'skipped_no_mapping': 0,
        'skipped_file_not_found': 0,
        'failed_upload': 0,
        'failed_link': 0,
        'details': []
    }
    
    # Process files
    for i, file_info in enumerate(file_versions, 1):
        title = file_info['Title']
        original_contact_id = file_info.get('OriginalContactId')
        file_extension = file_info.get('FileExtension', '')
        
        print(f"[{i}/{len(file_versions)}] {title}")
        
        # Check mapping
        if not original_contact_id or original_contact_id not in id_mapping:
            print(f"  ⏭️  Skipped: No Contact mapping")
            results['skipped_no_mapping'] += 1
            results['details'].append({
                'file': title,
                'status': 'skipped',
                'reason': 'No Contact mapping'
            })
            continue
        
        new_contact_id = id_mapping[original_contact_id]
        
        # Find file
        if file_extension and not title.endswith(f'.{file_extension}'):
            filename = f"{title}.{file_extension}"
        else:
            filename = title
        
        filepath = os.path.join(files_dir, filename)
        
        if not os.path.exists(filepath):
            print(f"  ⏭️  Skipped: File not found")
            results['skipped_file_not_found'] += 1
            results['details'].append({
                'file': title,
                'status': 'skipped',
                'reason': 'File not found'
            })
            continue
        
        # Get file size
        file_size = os.path.getsize(filepath)
        size_mb = file_size / (1024 * 1024)
        
        # Skip very large files (>25MB Salesforce limit)
        if size_mb > 25:
            print(f"  ⏭️  Skipped: File too large ({size_mb:.2f} MB, max 25 MB)")
            results['skipped_file_not_found'] += 1
            results['details'].append({
                'file': title,
                'status': 'skipped',
                'reason': f'File too large: {size_mb:.2f} MB'
            })
            continue
        
        print(f"  📤 Uploading ({size_mb:.2f} MB) to Contact {new_contact_id}...")
        
        # Upload ContentVersion
        content_version_id, error = create_content_version_with_cli(
            org_alias, title, filename, filepath
        )
        
        if error:
            print(f"  ❌ Upload failed: {error}")
            results['failed_upload'] += 1
            results['details'].append({
                'file': title,
                'status': 'failed_upload',
                'reason': error,
                'contact_id': new_contact_id
            })
            continue
        
        print(f"  ✅ Uploaded ContentVersion: {content_version_id}")
        
        # Get ContentDocumentId
        print(f"  🔍 Getting ContentDocumentId...")
        content_doc_id, error = query_content_document_id(org_alias, content_version_id)
        
        if error:
            print(f"  ❌ Failed to get ContentDocumentId: {error}")
            results['failed_link'] += 1
            results['details'].append({
                'file': title,
                'status': 'failed_link',
                'reason': error,
                'content_version_id': content_version_id
            })
            continue
        
        print(f"  ✅ ContentDocumentId: {content_doc_id}")
        
        # Create link
        print(f"  🔗 Linking to Contact...")
        link_id, error = create_content_document_link(
            org_alias, content_doc_id, new_contact_id, 'C'
        )
        
        if error:
            print(f"  ❌ Link creation failed: {error}")
            results['failed_link'] += 1
            results['details'].append({
                'file': title,
                'status': 'failed_link',
                'reason': error,
                'content_document_id': content_doc_id,
                'contact_id': new_contact_id
            })
            continue
        
        print(f"  ✅ Linked! (ShareType: Collaborator)")
        results['uploaded'] += 1
        results['details'].append({
            'file': title,
            'status': 'success',
            'content_version_id': content_version_id,
            'content_document_id': content_doc_id,
            'link_id': link_id,
            'contact_id': new_contact_id
        })
        print()
    
    # Summary
    print(f"\n{'='*80}")
    print(f"📊 UPLOAD SUMMARY")
    print(f"{'='*80}")
    print(f"✅ Successfully uploaded & linked: {results['uploaded']}")
    print(f"⏭️  Skipped (no mapping): {results['skipped_no_mapping']}")
    print(f"⏭️  Skipped (file issues): {results['skipped_file_not_found']}")
    print(f"❌ Failed upload: {results['failed_upload']}")
    print(f"❌ Failed link: {results['failed_link']}")
    print(f"{'='*80}\n")
    
    # Save results
    with open('upload_results_cli.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"📄 Results saved to: upload_results_cli.json")
    
    # Create report
    with open('upload_summary_cli.txt', 'w') as f:
        f.write(f"File Upload Summary (CLI Method) - AMSA Prod\n")
        f.write(f"{'='*80}\n\n")
        f.write(f"Total Files: {len(file_versions)}\n")
        f.write(f"Successfully Uploaded: {results['uploaded']}\n")
        f.write(f"Skipped (no mapping): {results['skipped_no_mapping']}\n")
        f.write(f"Skipped (file issues): {results['skipped_file_not_found']}\n")
        f.write(f"Failed Upload: {results['failed_upload']}\n")
        f.write(f"Failed Link: {results['failed_link']}\n\n")
        
        # Success list
        f.write(f"{'='*80}\n")
        f.write(f"Successfully Uploaded Files:\n")
        f.write(f"{'='*80}\n\n")
        for detail in [d for d in results['details'] if d['status'] == 'success']:
            f.write(f"✅ {detail['file']}\n")
            f.write(f"   Contact: {detail['contact_id']}\n")
            f.write(f"   Document: {detail['content_document_id']}\n\n")
        
        # Failures
        if results['failed_upload'] + results['failed_link'] > 0:
            f.write(f"\n{'='*80}\n")
            f.write(f"Failed Uploads:\n")
            f.write(f"{'='*80}\n\n")
            for detail in [d for d in results['details'] if d['status'].startswith('failed')]:
                f.write(f"❌ {detail['file']}\n")
                f.write(f"   Reason: {detail['reason']}\n\n")
    
    print(f"📄 Report saved to: upload_summary_cli.txt")

if __name__ == '__main__':
    main()

