#!/usr/bin/env python3
"""
Batch upload Contact files to AMSA Prod using Salesforce CLI
Processes files in batches of 50 with delays between batches
"""
import json
import subprocess
import os
import time
import tempfile

def upload_file_batch_method(org_alias, title, path_on_client, file_path):
    """Upload file using ContentVersion via Tooling API approach"""
    try:
        # Use sf data import for better handling of large files
        # First, try using the REST API composite method
        cmd = [
            'sf', 'data', 'create', 'record',
            '--sobject', 'ContentVersion',
            '--values', f"Title={title}",
            '--values', f"PathOnClient={path_on_client}",
            '--values', f"FirstPublishLocationId=0052I000000k7LHQAY",  # Will be updated later
            '--target-org', org_alias,
            '--json'
        ]
        
        # For large files, we need a different approach
        # Let's use simple-salesforce approach with subprocess
        import base64
        
        # Read file
        with open(file_path, 'rb') as f:
            file_content = f.read()
        
        # Check file size
        file_size_mb = len(file_content) / (1024 * 1024)
        
        if file_size_mb > 25:
            return None, f"File too large: {file_size_mb:.2f} MB (max 25 MB)"
        
        # Encode to base64
        file_base64 = base64.b64encode(file_content).decode('utf-8')
        
        # Create a JSON file with the data
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tmp:
            data = {
                "Title": title,
                "PathOnClient": path_on_client,
                "VersionData": file_base64
            }
            json.dump(data, tmp)
            tmp_file = tmp.name
        
        try:
            # Use sf data create with values from file
            # Actually, let's use curl with sf org display to get the access token
            # Get access token
            token_cmd = ['sf', 'org', 'display', '--target-org', org_alias, '--json']
            token_result = subprocess.run(token_cmd, capture_output=True, text=True, timeout=30)
            
            if token_result.returncode != 0:
                return None, "Failed to get access token"
            
            org_info = json.loads(token_result.stdout)
            access_token = org_info['result']['accessToken']
            instance_url = org_info['result']['instanceUrl']
            
            # Use curl to upload
            curl_cmd = [
                'curl',
                '-X', 'POST',
                f"{instance_url}/services/data/v59.0/sobjects/ContentVersion",
                '-H', f"Authorization: Bearer {access_token}",
                '-H', 'Content-Type: application/json',
                '--data', f'@{tmp_file}',
                '--max-time', '120'
            ]
            
            curl_result = subprocess.run(curl_cmd, capture_output=True, text=True, timeout=130)
            
            if curl_result.returncode == 0:
                response = json.loads(curl_result.stdout)
                if response.get('success'):
                    return response['id'], None
                else:
                    errors = response.get('errors', [])
                    error_msg = '; '.join([str(e) for e in errors])
                    return None, f"Upload failed: {error_msg}"
            else:
                return None, f"Curl failed: {curl_result.stderr}"
        
        finally:
            # Clean up temp file
            if os.path.exists(tmp_file):
                os.remove(tmp_file)
    
    except Exception as e:
        return None, f"Exception: {str(e)}"

def query_content_document_id(org_alias, content_version_id, max_retries=15):
    """Query for ContentDocumentId with extended retries"""
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
            
            # Progressive backoff
            if attempt < max_retries - 1:
                wait_time = min(1 + (attempt * 0.5), 5)  # Max 5 seconds
                time.sleep(wait_time)
        
        except Exception as e:
            if attempt == max_retries - 1:
                return None, str(e)
            time.sleep(2)
    
    return None, "ContentDocument not found after retries"

def create_content_document_link(org_alias, content_doc_id, contact_id, share_type='C'):
    """Create ContentDocumentLink"""
    try:
        cmd = [
            'sf', 'data', 'create', 'record',
            '--sobject', 'ContentDocumentLink',
            '--values', f"ContentDocumentId={content_doc_id} LinkedEntityId={contact_id} ShareType={share_type} Visibility=AllUsers",
            '--target-org', org_alias,
            '--json'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        
        if result.returncode == 0:
            data = json.loads(result.stdout)
            if data.get('status') == 0:
                return data['result']['id'], None
            else:
                error_data = data.get('result', data)
                return None, str(error_data)
        else:
            return None, f"CLI failed: {result.stderr}"
    
    except Exception as e:
        return None, str(e)

def load_progress():
    """Load progress from previous run"""
    if os.path.exists('upload_progress.json'):
        with open('upload_progress.json', 'r') as f:
            return json.load(f)
    return {'completed_files': [], 'failed_files': []}

def save_progress(progress):
    """Save progress"""
    with open('upload_progress.json', 'w') as f:
        json.dump(progress, f, indent=2)

def main():
    org_alias = 'AMSA Prod'
    files_dir = 'downloaded_contact_files'
    batch_size = 50
    batch_delay = 10  # seconds between batches
    
    print(f"🚀 Batch Upload to AMSA Prod")
    print(f"📦 Batch Size: {batch_size} files")
    print(f"⏱️  Delay between batches: {batch_delay}s\n")
    
    # Load data
    with open('contact_file_versions_enriched.json', 'r') as f:
        file_versions = json.load(f)
    
    with open('contact_id_mapping.json', 'r') as f:
        id_mapping = json.load(f)
    
    # Load progress
    progress = load_progress()
    completed = set(progress.get('completed_files', []))
    
    print(f"📊 Total files: {len(file_versions)}")
    print(f"📊 Contacts mapped: {len(id_mapping)}")
    print(f"✅ Already completed: {len(completed)}")
    print(f"\n{'='*80}\n")
    
    # Filter files to process
    files_to_process = [f for f in file_versions if f['Title'] not in completed]
    
    # Results
    results = {
        'uploaded': 0,
        'skipped': 0,
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
        
        for i, file_info in enumerate(batch):
            overall_idx = start_idx + i + 1
            title = file_info['Title']
            original_contact_id = file_info.get('OriginalContactId')
            file_extension = file_info.get('FileExtension', '')
            
            print(f"[{overall_idx}/{len(files_to_process)}] {title[:60]}...")
            
            # Check mapping
            if not original_contact_id or original_contact_id not in id_mapping:
                print(f"  ⏭️  Skipped: No mapping")
                results['skipped'] += 1
                completed.add(title)
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
                results['skipped'] += 1
                completed.add(title)
                continue
            
            # Upload
            file_size_mb = os.path.getsize(filepath) / (1024 * 1024)
            print(f"  📤 Uploading ({file_size_mb:.2f} MB)...")
            
            content_version_id, error = upload_file_batch_method(
                org_alias, title, filename, filepath
            )
            
            if error:
                print(f"  ❌ Failed: {error[:100]}")
                results['failed'] += 1
                results['details'].append({
                    'file': title,
                    'status': 'failed',
                    'reason': error
                })
                continue
            
            print(f"  ✅ ContentVersion: {content_version_id}")
            
            # Get ContentDocumentId
            print(f"  🔍 Getting ContentDocumentId...")
            content_doc_id, error = query_content_document_id(org_alias, content_version_id)
            
            if error:
                print(f"  ⚠️  Link failed: {error[:80]}")
                results['failed'] += 1
                results['details'].append({
                    'file': title,
                    'status': 'failed_link',
                    'content_version_id': content_version_id,
                    'reason': error
                })
                continue
            
            # Create link
            print(f"  🔗 Linking to Contact...")
            link_id, error = create_content_document_link(
                org_alias, content_doc_id, new_contact_id, 'C'
            )
            
            if error:
                print(f"  ⚠️  Link failed: {error[:80]}")
                results['failed'] += 1
                results['details'].append({
                    'file': title,
                    'status': 'failed_link',
                    'content_document_id': content_doc_id,
                    'reason': error
                })
                continue
            
            print(f"  ✅ Success!")
            results['uploaded'] += 1
            completed.add(title)
            results['details'].append({
                'file': title,
                'status': 'success',
                'content_version_id': content_version_id,
                'content_document_id': content_doc_id,
                'link_id': link_id,
                'contact_id': new_contact_id
            })
        
        # Save progress after each batch
        progress['completed_files'] = list(completed)
        save_progress(progress)
        
        # Delay between batches (except last batch)
        if batch_num < total_batches - 1:
            print(f"\n⏸️  Waiting {batch_delay}s before next batch...\n")
            time.sleep(batch_delay)
    
    # Final summary
    print(f"\n{'='*80}")
    print(f"📊 FINAL SUMMARY")
    print(f"{'='*80}")
    print(f"✅ Uploaded & linked: {results['uploaded']}")
    print(f"⏭️  Skipped: {results['skipped']}")
    print(f"❌ Failed: {results['failed']}")
    print(f"{'='*80}\n")
    
    # Save results
    with open('upload_results_batched.json', 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"📄 Results: upload_results_batched.json")
    print(f"📄 Progress: upload_progress.json")

if __name__ == '__main__':
    main()

