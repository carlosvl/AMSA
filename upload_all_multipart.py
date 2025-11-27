#!/usr/bin/env python3
"""
Upload all Contact files to AMSA Prod using multipart method
Processes in batches with progress tracking
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

def load_progress():
    """Load progress from previous run"""
    if os.path.exists('upload_progress_multipart.json'):
        with open('upload_progress_multipart.json', 'r') as f:
            return json.load(f)
    return {'completed': {}, 'failed': {}}

def save_progress(progress):
    """Save progress"""
    with open('upload_progress_multipart.json', 'w') as f:
        json.dump(progress, f, indent=2)

def main():
    org_alias = 'AMSA Prod'
    files_dir = 'downloaded_contact_files'
    batch_size = 50
    batch_delay = 5  # seconds between batches
    
    print(f"{'='*80}")
    print(f"🚀 FULL UPLOAD - Multipart Method (PROVEN WORKING)")
    print(f"{'='*80}")
    print(f"📦 Batch Size: {batch_size} files")
    print(f"⏱️  Delay between batches: {batch_delay}s\n")
    
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
    
    # Load progress
    progress = load_progress()
    completed = progress.get('completed', {})
    failed = progress.get('failed', {})
    
    print(f"📊 Total files: {len(file_versions)}")
    print(f"📊 Contacts mapped: {len(id_mapping)}")
    print(f"✅ Already completed: {len(completed)}")
    print(f"❌ Previously failed: {len(failed)}")
    print(f"\n{'='*80}\n")
    
    # Filter files to process
    files_to_process = []
    for file_info in file_versions:
        title = file_info['Title']
        
        # Skip if already completed
        if title in completed:
            continue
        
        # Check mapping
        original_contact_id = file_info.get('OriginalContactId')
        if not original_contact_id or original_contact_id not in id_mapping:
            continue
        
        # Check file exists
        file_extension = file_info.get('FileExtension', '')
        if file_extension and not title.endswith(f'.{file_extension}'):
            filename = f"{title}.{file_extension}"
        else:
            filename = title
        
        filepath = os.path.join(files_dir, filename)
        if not os.path.exists(filepath):
            continue
        
        # Check file size (max 25 MB for Salesforce)
        file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
        if file_size_mb > 25:
            print(f"⏭️  Skipping {title} - too large ({file_size_mb:.2f} MB)")
            continue
        
        files_to_process.append({
            'info': file_info,
            'path': filepath,
            'contact_id': id_mapping[original_contact_id]
        })
    
    if len(files_to_process) == 0:
        print("✅ All files already processed!")
        return
    
    print(f"📋 Files to upload: {len(files_to_process)}\n")
    
    # Results
    results = {
        'uploaded': 0,
        'failed': 0,
        'details': []
    }
    
    # Process in batches
    total_batches = (len(files_to_process) + batch_size - 1) // batch_size
    
    for batch_num in range(total_batches):
        start_idx = batch_num * batch_size
        end_idx = min(start_idx + batch_size, len(files_to_process))
        batch = files_to_process[start_idx:end_idx]
        
        print(f"{'='*80}")
        print(f"📦 BATCH {batch_num + 1}/{total_batches} ({len(batch)} files)")
        print(f"{'='*80}\n")
        
        for i, file_data in enumerate(batch):
            overall_idx = start_idx + i + 1
            title = file_data['info']['Title']
            filepath = file_data['path']
            contact_id = file_data['contact_id']
            
            file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
            
            print(f"[{overall_idx}/{len(files_to_process)}] {title[:65]}")
            print(f"  📤 Uploading ({file_size_mb:.2f} MB)...")
            
            # Upload
            content_version_id, error = upload_file_multipart(
                access_token, instance_url, filepath, title, contact_id
            )
            
            if error:
                print(f"  ❌ Failed: {error[:100]}")
                results['failed'] += 1
                failed[title] = {
                    'reason': error,
                    'contact_id': contact_id
                }
                results['details'].append({
                    'file': title,
                    'status': 'failed',
                    'reason': error
                })
                continue
            
            print(f"  ✅ ContentVersion: {content_version_id}")
            
            # Wait for ContentDocument
            print(f"  ⏳ Getting ContentDocument...")
            content_doc_id, error = wait_for_content_document(
                access_token, instance_url, content_version_id, max_wait=30
            )
            
            if error:
                print(f"  ⚠️  Warning: {error}")
                results['failed'] += 1
                failed[title] = {
                    'reason': error,
                    'content_version_id': content_version_id
                }
                results['details'].append({
                    'file': title,
                    'status': 'failed_doc',
                    'content_version_id': content_version_id,
                    'reason': error
                })
                continue
            
            print(f"  ✅ SUCCESS! Document: {content_doc_id}")
            results['uploaded'] += 1
            completed[title] = {
                'content_version_id': content_version_id,
                'content_document_id': content_doc_id,
                'contact_id': contact_id,
                'timestamp': time.time()
            }
            results['details'].append({
                'file': title,
                'status': 'success',
                'content_version_id': content_version_id,
                'content_document_id': content_doc_id,
                'contact_id': contact_id
            })
            print()
        
        # Save progress after each batch
        progress['completed'] = completed
        progress['failed'] = failed
        save_progress(progress)
        
        print(f"💾 Progress saved ({len(completed)} completed, {len(failed)} failed)")
        
        # Delay between batches (except last)
        if batch_num < total_batches - 1:
            print(f"⏸️  Waiting {batch_delay}s before next batch...\n")
            time.sleep(batch_delay)
    
    # Final summary
    print(f"\n{'='*80}")
    print(f"📊 FINAL SUMMARY")
    print(f"{'='*80}")
    print(f"✅ Successfully uploaded & linked: {results['uploaded']}")
    print(f"❌ Failed: {results['failed']}")
    print(f"📁 Total completed (including previous): {len(completed)}")
    print(f"{'='*80}\n")
    
    # Save final results
    with open('upload_results_multipart_final.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"📄 Results: upload_results_multipart_final.json")
    print(f"📄 Progress: upload_progress_multipart.json")
    
    # Create summary report
    with open('upload_summary_final.txt', 'w') as f:
        f.write(f"Contact Files Upload - FINAL SUMMARY\n")
        f.write(f"{'='*80}\n\n")
        f.write(f"Organization: AMSA Prod\n")
        f.write(f"Method: Multipart Upload\n")
        f.write(f"Date: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"Total Files Processed: {len(files_to_process)}\n")
        f.write(f"Successfully Uploaded: {results['uploaded']}\n")
        f.write(f"Failed: {results['failed']}\n")
        f.write(f"Total Completed (all time): {len(completed)}\n\n")
        f.write(f"{'='*80}\n")
        f.write(f"Successfully Uploaded Files:\n")
        f.write(f"{'='*80}\n\n")
        
        for title, data in completed.items():
            f.write(f"✅ {title}\n")
            f.write(f"   Contact: {data['contact_id']}\n")
            f.write(f"   Document: {data['content_document_id']}\n\n")
        
        if failed:
            f.write(f"\n{'='*80}\n")
            f.write(f"Failed Files:\n")
            f.write(f"{'='*80}\n\n")
            
            for title, data in failed.items():
                f.write(f"❌ {title}\n")
                f.write(f"   Reason: {data['reason']}\n\n")
    
    print(f"📄 Summary report: upload_summary_final.txt\n")
    
    if results['uploaded'] > 0:
        print(f"🎉 SUCCESS! {results['uploaded']} files uploaded and linked to contacts!")
    
    if len(completed) == len(file_versions):
        print(f"✨ ALL FILES COMPLETED! ✨")

if __name__ == '__main__':
    main()

