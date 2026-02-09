#!/usr/bin/env python3
"""
Upload Contact files to AMSA Prod org
"""
import json
import subprocess
import urllib.request
import urllib.parse
import os
import base64
import time
from pathlib import Path

def get_access_token_and_instance(org_alias):
    """Get access token and instance URL from Salesforce CLI"""
    try:
        result = subprocess.run(
            ['sf', 'org', 'display', '--target-org', org_alias, '--json'],
            capture_output=True,
            text=True,
            check=True
        )
        org_info = json.loads(result.stdout)
        return (
            org_info['result']['accessToken'],
            org_info['result']['instanceUrl']
        )
    except Exception as e:
        print(f"Error getting org info: {e}")
        return None, None

def upload_file_to_salesforce(access_token, instance_url, filepath, title, path_on_client):
    """Upload a file as ContentVersion to Salesforce"""
    try:
        # Read file and encode as base64
        with open(filepath, 'rb') as f:
            file_data = base64.b64encode(f.read()).decode('utf-8')
        
        # Create ContentVersion
        url = f"{instance_url}/services/data/v59.0/sobjects/ContentVersion"
        
        payload = {
            "Title": title,
            "PathOnClient": path_on_client,
            "VersionData": file_data
        }
        
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            },
            method='POST'
        )
        
        with urllib.request.urlopen(request) as response:
            result = json.loads(response.read().decode('utf-8'))
            if result.get('success'):
                return result.get('id'), None
            else:
                errors = result.get('errors', [])
                error_msg = '; '.join([e.get('message', str(e)) for e in errors])
                return None, f"Upload failed: {error_msg}"
    
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        try:
            error_data = json.loads(error_body)
            errors = error_data if isinstance(error_data, list) else [error_data]
            error_msg = '; '.join([err.get('message', str(err)) for err in errors])
            return None, f"HTTP {e.code}: {error_msg}"
        except:
            return None, f"HTTP {e.code}: {error_body}"
    except Exception as e:
        return None, str(e)

def get_content_document_id(access_token, instance_url, content_version_id, max_retries=5):
    """Get ContentDocumentId from ContentVersionId with retry logic"""
    for attempt in range(max_retries):
        try:
            query = f"SELECT ContentDocumentId FROM ContentVersion WHERE Id = '{content_version_id}'"
            encoded_query = urllib.parse.quote(query)
            url = f"{instance_url}/services/data/v59.0/query/?q={encoded_query}"
            
            request = urllib.request.Request(url)
            request.add_header('Authorization', f'Bearer {access_token}')
            
            with urllib.request.urlopen(request) as response:
                result = json.loads(response.read().decode('utf-8'))
                if result.get('records') and result['records'][0].get('ContentDocumentId'):
                    return result['records'][0]['ContentDocumentId'], None
            
            # If no ContentDocument found yet, wait and retry
            if attempt < max_retries - 1:
                time.sleep(0.5)  # Wait 500ms before retrying
            
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(0.5)
            else:
                return None, str(e)
    
    return None, "No ContentDocument found after retries"

def create_content_document_link(access_token, instance_url, content_document_id, linked_entity_id, share_type='C'):
    """Create ContentDocumentLink to link file to a record"""
    try:
        url = f"{instance_url}/services/data/v59.0/sobjects/ContentDocumentLink"
        
        payload = {
            "ContentDocumentId": content_document_id,
            "LinkedEntityId": linked_entity_id,
            "ShareType": share_type,
            "Visibility": "AllUsers"
        }
        
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'Authorization': f'Bearer {access_token}',
                'Content-Type': 'application/json'
            },
            method='POST'
        )
        
        with urllib.request.urlopen(request) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result.get('id'), None
    
    except Exception as e:
        return None, str(e)

def main():
    org_alias = 'AMSA Prod'
    files_dir = 'downloaded_contact_files'
    
    print(f"🔐 Authenticating with {org_alias}...")
    access_token, instance_url = get_access_token_and_instance(org_alias)
    
    if not access_token:
        print("❌ Failed to get access token")
        return
    
    print(f"✅ Connected to: {instance_url}\n")
    
    # Load enriched file versions
    with open('contact_file_versions_enriched.json', 'r') as f:
        file_versions = json.load(f)
    
    # Load Contact ID mapping
    with open('contact_id_mapping.json', 'r') as f:
        id_mapping = json.load(f)
    
    print(f"📂 Found {len(file_versions)} files to upload")
    print(f"📊 Contact mapping: {len(id_mapping)} contacts mapped")
    print(f"\n{'='*80}\n")
    
    # Track results
    results = {
        'uploaded': 0,
        'skipped_no_mapping': 0,
        'skipped_file_not_found': 0,
        'failed': 0,
        'details': []
    }
    
    for i, file_info in enumerate(file_versions, 1):
        title = file_info['Title']
        original_contact_id = file_info.get('OriginalContactId')
        file_extension = file_info.get('FileExtension', '')
        
        print(f"[{i}/{len(file_versions)}] {title}")
        
        # Check if we have a mapping for this contact
        if not original_contact_id or original_contact_id not in id_mapping:
            print(f"  ⏭️  Skipped: No Contact mapping found")
            results['skipped_no_mapping'] += 1
            results['details'].append({
                'file': title,
                'status': 'skipped',
                'reason': 'No Contact mapping',
                'original_contact_id': original_contact_id
            })
            continue
        
        new_contact_id = id_mapping[original_contact_id]
        
        # Find the file on disk
        if file_extension and not title.endswith(f'.{file_extension}'):
            filename = f"{title}.{file_extension}"
        else:
            filename = title
        
        filepath = os.path.join(files_dir, filename)
        
        if not os.path.exists(filepath):
            print(f"  ⏭️  Skipped: File not found on disk")
            results['skipped_file_not_found'] += 1
            results['details'].append({
                'file': title,
                'status': 'skipped',
                'reason': 'File not found',
                'expected_path': filepath
            })
            continue
        
        # Upload file
        print(f"  📤 Uploading to Contact {new_contact_id}...")
        
        content_version_id, error = upload_file_to_salesforce(
            access_token, instance_url, filepath, title, filename
        )
        
        if error:
            print(f"  ❌ Upload failed: {error}")
            results['failed'] += 1
            results['details'].append({
                'file': title,
                'status': 'failed',
                'reason': f'Upload error: {error}',
                'contact_id': new_contact_id
            })
            continue
        
        print(f"  ✅ Uploaded ContentVersion: {content_version_id}")
        
        # Get ContentDocumentId
        content_document_id, error = get_content_document_id(
            access_token, instance_url, content_version_id
        )
        
        if error:
            print(f"  ⚠️  Warning: Could not get ContentDocumentId: {error}")
            results['failed'] += 1
            results['details'].append({
                'file': title,
                'status': 'failed',
                'reason': f'Get ContentDocumentId error: {error}',
                'content_version_id': content_version_id
            })
            continue
        
        # Create ContentDocumentLink
        link_id, error = create_content_document_link(
            access_token, instance_url, content_document_id, new_contact_id, 'C'
        )
        
        if error:
            print(f"  ⚠️  Warning: Could not link to Contact: {error}")
            results['failed'] += 1
            results['details'].append({
                'file': title,
                'status': 'failed',
                'reason': f'Link creation error: {error}',
                'content_document_id': content_document_id,
                'contact_id': new_contact_id
            })
            continue
        
        print(f"  ✅ Linked to Contact (ShareType: Collaborator)")
        results['uploaded'] += 1
        results['details'].append({
            'file': title,
            'status': 'success',
            'content_version_id': content_version_id,
            'content_document_id': content_document_id,
            'link_id': link_id,
            'contact_id': new_contact_id,
            'original_contact_id': original_contact_id
        })
        print()
    
    # Summary
    print(f"\n{'='*80}")
    print(f"📊 UPLOAD SUMMARY")
    print(f"{'='*80}")
    print(f"✅ Successfully uploaded: {results['uploaded']}")
    print(f"⏭️  Skipped (no contact mapping): {results['skipped_no_mapping']}")
    print(f"⏭️  Skipped (file not found): {results['skipped_file_not_found']}")
    print(f"❌ Failed: {results['failed']}")
    print(f"{'='*80}\n")
    
    # Save detailed results
    with open('upload_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"📄 Detailed results saved to: upload_results.json")
    
    # Create summary report
    with open('upload_summary_report.txt', 'w') as f:
        f.write(f"File Upload Summary - AMSA Prod\n")
        f.write(f"{'='*80}\n\n")
        f.write(f"Organization: {org_alias}\n")
        f.write(f"Total Files Processed: {len(file_versions)}\n")
        f.write(f"Successfully Uploaded: {results['uploaded']}\n")
        f.write(f"Skipped (no contact mapping): {results['skipped_no_mapping']}\n")
        f.write(f"Skipped (file not found): {results['skipped_file_not_found']}\n")
        f.write(f"Failed: {results['failed']}\n\n")
        f.write(f"{'='*80}\n")
        f.write(f"Detailed Results:\n")
        f.write(f"{'='*80}\n\n")
        
        for detail in results['details']:
            f.write(f"File: {detail['file']}\n")
            f.write(f"Status: {detail['status']}\n")
            if detail['status'] == 'success':
                f.write(f"Contact ID: {detail['contact_id']}\n")
                f.write(f"ContentDocumentId: {detail['content_document_id']}\n")
            else:
                f.write(f"Reason: {detail['reason']}\n")
            f.write(f"\n")
    
    print(f"📄 Summary report saved to: upload_summary_report.txt")

if __name__ == '__main__':
    main()

