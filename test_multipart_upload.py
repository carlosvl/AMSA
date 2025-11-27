#!/usr/bin/env python3
"""
Test multipart file upload to Salesforce - 3 files only
"""
import json
import subprocess
import os
import time
import mimetypes
import uuid

def get_org_credentials(org_alias):
    """Get access token and instance URL"""
    try:
        result = subprocess.run(
            ['sf', 'org', 'display', '--target-org', org_alias, '--json'],
            capture_output=True,
            text=True,
            check=True
        )
        data = json.loads(result.stdout)
        return (
            data['result']['accessToken'],
            data['result']['instanceUrl']
        )
    except Exception as e:
        print(f"Error: {e}")
        return None, None

def upload_file_multipart(access_token, instance_url, file_path, title, contact_id):
    """Upload file using multipart/form-data"""
    import urllib.request
    import urllib.parse
    
    # Detect mime type
    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type:
        mime_type = 'application/octet-stream'
    
    # Read file
    with open(file_path, 'rb') as f:
        file_content = f.read()
    
    # Create multipart boundary
    boundary = f'----Boundary{uuid.uuid4().hex}'
    
    # Build multipart body
    parts = []
    
    # Add entity_content part (JSON metadata)
    entity_data = {
        "Title": title,
        "PathOnClient": os.path.basename(file_path),
        "FirstPublishLocationId": contact_id  # Publish directly to Contact
    }
    
    parts.append(f'--{boundary}'.encode())
    parts.append(b'Content-Disposition: form-data; name="entity_content"')
    parts.append(b'Content-Type: application/json')
    parts.append(b'')
    parts.append(json.dumps(entity_data).encode())
    
    # Add VersionData part (file content)
    parts.append(f'--{boundary}'.encode())
    parts.append(f'Content-Disposition: form-data; name="VersionData"; filename="{os.path.basename(file_path)}"'.encode())
    parts.append(f'Content-Type: {mime_type}'.encode())
    parts.append(b'')
    parts.append(file_content)
    
    # End boundary
    parts.append(f'--{boundary}--'.encode())
    parts.append(b'')
    
    # Join all parts
    body = b'\r\n'.join(parts)
    
    # Make request
    url = f"{instance_url}/services/data/v59.0/sobjects/ContentVersion"
    
    try:
        request = urllib.request.Request(url, data=body)
        request.add_header('Authorization', f'Bearer {access_token}')
        request.add_header('Content-Type', f'multipart/form-data; boundary={boundary}')
        request.add_header('Content-Length', str(len(body)))
        
        with urllib.request.urlopen(request, timeout=120) as response:
            result = json.loads(response.read().decode('utf-8'))
            if result.get('success'):
                return result['id'], None
            else:
                errors = result.get('errors', [])
                return None, str(errors)
    
    except urllib.error.HTTPError as e:
        error_body = e.read().decode('utf-8')
        return None, f"HTTP {e.code}: {error_body}"
    except Exception as e:
        return None, str(e)

def wait_for_content_document(access_token, instance_url, content_version_id, max_wait=30):
    """Wait for ContentDocument to be created"""
    import urllib.request
    import urllib.parse
    
    start_time = time.time()
    
    while time.time() - start_time < max_wait:
        try:
            query = f"SELECT ContentDocumentId FROM ContentVersion WHERE Id = '{content_version_id}'"
            encoded = urllib.parse.quote(query)
            url = f"{instance_url}/services/data/v59.0/query/?q={encoded}"
            
            request = urllib.request.Request(url)
            request.add_header('Authorization', f'Bearer {access_token}')
            
            with urllib.request.urlopen(request, timeout=10) as response:
                data = json.loads(response.read().decode('utf-8'))
                records = data.get('records', [])
                if records and records[0].get('ContentDocumentId'):
                    return records[0]['ContentDocumentId'], None
            
            time.sleep(2)
        
        except Exception as e:
            time.sleep(2)
    
    return None, "Timeout waiting for ContentDocument"

def verify_file_linked(access_token, instance_url, content_doc_id, contact_id):
    """Verify ContentDocumentLink exists"""
    import urllib.request
    import urllib.parse
    
    try:
        query = f"SELECT Id FROM ContentDocumentLink WHERE ContentDocumentId = '{content_doc_id}' AND LinkedEntityId = '{contact_id}'"
        encoded = urllib.parse.quote(query)
        url = f"{instance_url}/services/data/v59.0/query/?q={encoded}"
        
        request = urllib.request.Request(url)
        request.add_header('Authorization', f'Bearer {access_token}')
        
        with urllib.request.urlopen(request, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
            if data.get('totalSize', 0) > 0:
                return True, data['records'][0]['Id']
            return False, "Link not found"
    
    except Exception as e:
        return False, str(e)

def main():
    org_alias = 'AMSA Prod'
    files_dir = 'downloaded_contact_files'
    test_count = 3
    
    print(f"🧪 TEST UPLOAD - Multipart Method")
    print(f"📂 Testing with {test_count} files\n")
    
    # Get credentials
    print("🔐 Authenticating...")
    access_token, instance_url = get_org_credentials(org_alias)
    if not access_token:
        print("❌ Failed to authenticate")
        return
    
    print(f"✅ Connected to: {instance_url}\n")
    
    # Load data
    with open('contact_file_versions_enriched.json', 'r') as f:
        file_versions = json.load(f)
    
    with open('contact_id_mapping.json', 'r') as f:
        id_mapping = json.load(f)
    
    # Get test files (first 3 that have mapping and exist)
    test_files = []
    for file_info in file_versions:
        if len(test_files) >= test_count:
            break
        
        original_contact_id = file_info.get('OriginalContactId')
        if not original_contact_id or original_contact_id not in id_mapping:
            continue
        
        title = file_info['Title']
        file_extension = file_info.get('FileExtension', '')
        
        if file_extension and not title.endswith(f'.{file_extension}'):
            filename = f"{title}.{file_extension}"
        else:
            filename = title
        
        filepath = os.path.join(files_dir, filename)
        if os.path.exists(filepath):
            test_files.append({
                'info': file_info,
                'path': filepath,
                'contact_id': id_mapping[original_contact_id]
            })
    
    print(f"{'='*80}")
    print(f"Testing with {len(test_files)} files:")
    for i, f in enumerate(test_files, 1):
        size_mb = os.path.getsize(f['path']) / (1024 * 1024)
        print(f"  {i}. {f['info']['Title']} ({size_mb:.2f} MB)")
    print(f"{'='*80}\n")
    
    # Upload test files
    results = []
    
    for i, test_file in enumerate(test_files, 1):
        title = test_file['info']['Title']
        filepath = test_file['path']
        contact_id = test_file['contact_id']
        
        print(f"[{i}/{len(test_files)}] {title}")
        
        file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
        print(f"  📤 Uploading ({file_size_mb:.2f} MB) via multipart...")
        
        # Upload
        content_version_id, error = upload_file_multipart(
            access_token, instance_url, filepath, title, contact_id
        )
        
        if error:
            print(f"  ❌ Upload failed: {error}")
            results.append({
                'file': title,
                'status': 'failed',
                'error': error
            })
            continue
        
        print(f"  ✅ Uploaded! ContentVersion: {content_version_id}")
        
        # Wait for ContentDocument
        print(f"  ⏳ Waiting for ContentDocument...")
        content_doc_id, error = wait_for_content_document(
            access_token, instance_url, content_version_id, max_wait=30
        )
        
        if error:
            print(f"  ⚠️  {error}")
            results.append({
                'file': title,
                'status': 'uploaded_no_doc',
                'content_version_id': content_version_id,
                'error': error
            })
            continue
        
        print(f"  ✅ ContentDocument: {content_doc_id}")
        
        # Verify link
        print(f"  🔍 Verifying link to Contact...")
        linked, link_result = verify_file_linked(
            access_token, instance_url, content_doc_id, contact_id
        )
        
        if linked:
            print(f"  ✅ SUCCESS! File linked to Contact")
            results.append({
                'file': title,
                'status': 'success',
                'content_version_id': content_version_id,
                'content_document_id': content_doc_id,
                'contact_id': contact_id,
                'link_id': link_result
            })
        else:
            print(f"  ⚠️  Link verification: {link_result}")
            results.append({
                'file': title,
                'status': 'uploaded_no_link',
                'content_version_id': content_version_id,
                'content_document_id': content_doc_id,
                'contact_id': contact_id,
                'error': link_result
            })
        
        print()
    
    # Summary
    print(f"{'='*80}")
    print(f"🧪 TEST RESULTS")
    print(f"{'='*80}")
    
    successful = [r for r in results if r['status'] == 'success']
    failed = [r for r in results if r['status'] != 'success']
    
    print(f"✅ Successful: {len(successful)}/{len(results)}")
    print(f"❌ Failed: {len(failed)}/{len(results)}")
    
    if successful:
        print(f"\n✅ Successfully uploaded files:")
        for r in successful:
            print(f"  • {r['file']}")
            print(f"    → ContentDocument: {r['content_document_id']}")
            print(f"    → Contact: {r['contact_id']}")
    
    if failed:
        print(f"\n❌ Failed files:")
        for r in failed:
            print(f"  • {r['file']}")
            print(f"    → Status: {r['status']}")
            print(f"    → Error: {r.get('error', 'Unknown')}")
    
    print(f"\n{'='*80}")
    
    # Save results
    with open('test_upload_results.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"📄 Results saved to: test_upload_results.json")
    
    if len(successful) > 0:
        print(f"\n✅ TEST PASSED! Multipart upload works!")
        print(f"💡 Ready to process all {len(file_versions)} files with this method.")
    else:
        print(f"\n⚠️  TEST FAILED - Need to investigate issues")

if __name__ == '__main__':
    main()

