#!/usr/bin/env python3
"""
Migrate Missing Files - Targeted Migration
Downloads and uploads only the files identified as missing in comparison results
"""
import json
import subprocess
import os
import sys
import time
import mimetypes
import uuid
import tempfile

def get_org_credentials(org_alias):
    """Get access token and instance URL"""
    try:
        result = subprocess.run(
            ['sf', 'org', 'display', '--target-org', org_alias, '--json'],
            capture_output=True,
            text=True,
            check=True,
            timeout=30
        )
        data = json.loads(result.stdout)
        return (
            data['result']['accessToken'],
            data['result']['instanceUrl']
        )
    except Exception as e:
        print(f"❌ Error getting credentials: {e}")
        return None, None

def download_file_from_source(access_token, instance_url, content_document_id, output_dir):
    """Download a file from source org using ContentDocument ID"""
    import urllib.request
    import urllib.parse
    
    try:
        # First, get the LatestPublishedVersionId
        query = f"SELECT LatestPublishedVersionId, Title, FileExtension FROM ContentDocument WHERE Id = '{content_document_id}'"
        encoded = urllib.parse.quote(query)
        url = f"{instance_url}/services/data/v59.0/query/?q={encoded}"
        
        request = urllib.request.Request(url)
        request.add_header('Authorization', f'Bearer {access_token}')
        
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode('utf-8'))
            records = data.get('records', [])
            
            if not records:
                return None, "ContentDocument not found"
            
            version_id = records[0].get('LatestPublishedVersionId')
            title = records[0].get('Title', 'Unknown')
            file_extension = records[0].get('FileExtension', '')
            
            if not version_id:
                return None, "No version ID found"
        
        # Download the file content
        url = f"{instance_url}/services/data/v59.0/sobjects/ContentVersion/{version_id}/VersionData"
        
        request = urllib.request.Request(url)
        request.add_header('Authorization', f'Bearer {access_token}')
        
        with urllib.request.urlopen(request, timeout=120) as response:
            file_content = response.read()
        
        # Save to temp file
        if file_extension and not title.endswith(f'.{file_extension}'):
            filename = f"{title}.{file_extension}"
        else:
            filename = title
        
        # Sanitize filename
        import re
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        filename = filename.strip('. ')[:200]
        
        filepath = os.path.join(output_dir, filename)
        
        with open(filepath, 'wb') as f:
            f.write(file_content)
        
        return filepath, None
    
    except Exception as e:
        return None, str(e)

def upload_file_multipart(access_token, instance_url, file_path, title, contact_id):
    """Upload file using multipart/form-data - THE PROVEN METHOD"""
    import urllib.request
    
    try:
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
        
        # Part 1: JSON metadata
        entity_data = {
            "Title": title,
            "PathOnClient": os.path.basename(file_path),
            "FirstPublishLocationId": contact_id  # Auto-links to Contact
        }
        
        parts.append(f'--{boundary}'.encode())
        parts.append(b'Content-Disposition: form-data; name="entity_content"')
        parts.append(b'Content-Type: application/json')
        parts.append(b'')
        parts.append(json.dumps(entity_data).encode())
        
        # Part 2: File content
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

def load_comparison_results(results_file):
    """Load file comparison results"""
    try:
        with open(results_file, 'r') as f:
            data = json.load(f)
        return data
    except Exception as e:
        print(f"❌ Error loading results: {e}")
        return None

def main():
    """Main execution"""
    print("="*80)
    print("🎯 TARGETED FILE MIGRATION - Missing Files Only")
    print("="*80)
    print()
    
    # Get parameters
    if len(sys.argv) >= 4:
        comparison_file = sys.argv[1]
        source_org = sys.argv[2]
        target_org = sys.argv[3]
        batch_size = int(sys.argv[4]) if len(sys.argv) > 4 else 50
    else:
        print("❌ Missing parameters!")
        print("\nUsage:")
        print("  python3 migrate_missing_files.py <comparison_file> <source_org> <target_org> [batch_size]")
        print("\nExample:")
        print("  python3 migrate_missing_files.py ../results/files_comparison_20251201_170046.json 'AMSA-Royalty-Prod' 'AMSA Prod' 50")
        sys.exit(1)
    
    print("📋 Parameters:")
    print(f"  Comparison File: {comparison_file}")
    print(f"  Source Org: {source_org}")
    print(f"  Target Org: {target_org}")
    print(f"  Batch Size: {batch_size}")
    print()
    
    # Load comparison results
    print("📂 Loading comparison results...")
    comparison_data = load_comparison_results(comparison_file)
    
    if not comparison_data:
        sys.exit(1)
    
    missing_files_data = comparison_data['results']['missing_files']
    
    # Build file list
    files_to_migrate = []
    for contact_data in missing_files_data:
        source_contact_id = contact_data['source_contact_id']
        target_contact_id = contact_data['target_contact_id']
        
        for file_info in contact_data['files']:
            files_to_migrate.append({
                'source_contact_id': source_contact_id,
                'target_contact_id': target_contact_id,
                'content_document_id': file_info['ContentDocumentId'],
                'title': file_info['Title'],
                'file_type': file_info.get('FileType', ''),
                'size': file_info.get('ContentSize', 0)
            })
    
    print(f"  ✅ Found {len(files_to_migrate)} missing files across {len(missing_files_data)} contacts")
    print()
    
    # Get credentials
    print("🔐 Authenticating to both orgs...")
    source_token, source_url = get_org_credentials(source_org)
    target_token, target_url = get_org_credentials(target_org)
    
    if not source_token or not target_token:
        print("❌ Failed to authenticate")
        sys.exit(1)
    
    print(f"  ✅ Source: {source_url}")
    print(f"  ✅ Target: {target_url}")
    print()
    
    # Create temp directory for downloads
    temp_dir = tempfile.mkdtemp(prefix='sf_migration_')
    print(f"📁 Temp directory: {temp_dir}")
    print()
    
    # Results tracking
    results = {
        'total': len(files_to_migrate),
        'success': 0,
        'failed': 0,
        'skipped': 0,
        'details': []
    }
    
    # Process files in batches
    total_batches = (len(files_to_migrate) + batch_size - 1) // batch_size
    
    try:
        for batch_num in range(total_batches):
            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, len(files_to_migrate))
            batch = files_to_migrate[start_idx:end_idx]
            
            print(f"{'='*80}")
            print(f"📦 BATCH {batch_num + 1}/{total_batches} ({len(batch)} files)")
            print(f"{'='*80}\n")
            
            for i, file_data in enumerate(batch):
                overall_idx = start_idx + i + 1
                title = file_data['title']
                content_doc_id = file_data['content_document_id']
                target_contact_id = file_data['target_contact_id']
                
                size_mb = file_data['size'] / (1024 * 1024)
                
                print(f"[{overall_idx}/{len(files_to_migrate)}] {title[:65]}")
                
                # Skip if too large
                if size_mb > 25:
                    print(f"  ⏭️  Skipped: Too large ({size_mb:.2f} MB)")
                    results['skipped'] += 1
                    continue
                
                # Step 1: Download from source
                print(f"  📥 Downloading from source ({size_mb:.2f} MB)...")
                filepath, error = download_file_from_source(
                    source_token, source_url, content_doc_id, temp_dir
                )
                
                if error:
                    print(f"  ❌ Download failed: {error[:80]}")
                    results['failed'] += 1
                    results['details'].append({
                        'file': title,
                        'status': 'download_failed',
                        'reason': error
                    })
                    continue
                
                print(f"  ✅ Downloaded")
                
                # Step 2: Upload to target
                print(f"  📤 Uploading to target...")
                content_version_id, error = upload_file_multipart(
                    target_token, target_url, filepath, title, target_contact_id
                )
                
                if error:
                    print(f"  ❌ Upload failed: {error[:80]}")
                    results['failed'] += 1
                    results['details'].append({
                        'file': title,
                        'status': 'upload_failed',
                        'reason': error
                    })
                    # Clean up downloaded file
                    if os.path.exists(filepath):
                        os.remove(filepath)
                    continue
                
                print(f"  ✅ Uploaded: {content_version_id}")
                
                # Step 3: Wait for ContentDocument
                print(f"  ⏳ Verifying...")
                content_doc_id_target, error = wait_for_content_document(
                    target_token, target_url, content_version_id, max_wait=30
                )
                
                if error:
                    print(f"  ⚠️  Verification warning: {error[:60]}")
                    # Still count as success since file uploaded
                    results['success'] += 1
                    results['details'].append({
                        'file': title,
                        'status': 'success_no_verify',
                        'content_version_id': content_version_id,
                        'contact_id': target_contact_id
                    })
                else:
                    print(f"  ✅ SUCCESS! Document: {content_doc_id_target}")
                    results['success'] += 1
                    results['details'].append({
                        'file': title,
                        'status': 'success',
                        'content_version_id': content_version_id,
                        'content_document_id': content_doc_id_target,
                        'contact_id': target_contact_id
                    })
                
                # Clean up downloaded file
                if os.path.exists(filepath):
                    os.remove(filepath)
                
                print()
            
            # Delay between batches
            if batch_num < total_batches - 1:
                print(f"⏸️  Waiting 5s before next batch...\n")
                time.sleep(5)
    
    finally:
        # Clean up temp directory
        try:
            if os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir)
                print(f"\n🧹 Cleaned up temp directory")
        except:
            pass
    
    # Final summary
    print(f"\n{'='*80}")
    print(f"📊 MIGRATION SUMMARY")
    print(f"{'='*80}")
    print(f"Total Files: {results['total']}")
    print(f"✅ Successful: {results['success']}")
    print(f"⏭️  Skipped: {results['skipped']}")
    print(f"❌ Failed: {results['failed']}")
    print(f"📈 Success Rate: {results['success']/results['total']*100:.1f}%")
    print(f"{'='*80}\n")
    
    # Save results
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    results_file = f"../results/missing_files_migration_{timestamp}.json"
    
    with open(results_file, 'w') as f:
        json.dump({
            'metadata': {
                'source_org': source_org,
                'target_org': target_org,
                'comparison_file': comparison_file,
                'timestamp': timestamp
            },
            'results': results
        }, f, indent=2)
    
    print(f"📄 Results saved to: {results_file}")
    
    # Generate summary report
    report_file = f"../results/missing_files_migration_{timestamp}.txt"
    with open(report_file, 'w') as f:
        f.write(f"Missing Files Migration Report\n")
        f.write(f"{'='*80}\n\n")
        f.write(f"Source Org: {source_org}\n")
        f.write(f"Target Org: {target_org}\n")
        f.write(f"Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write(f"Total Files: {results['total']}\n")
        f.write(f"Successful: {results['success']}\n")
        f.write(f"Skipped: {results['skipped']}\n")
        f.write(f"Failed: {results['failed']}\n\n")
        f.write(f"{'='*80}\n")
        f.write(f"Successful Files:\n")
        f.write(f"{'='*80}\n\n")
        
        for detail in [d for d in results['details'] if d['status'].startswith('success')]:
            f.write(f"✅ {detail['file']}\n")
            f.write(f"   Contact: {detail['contact_id']}\n")
            if 'content_document_id' in detail:
                f.write(f"   Document: {detail['content_document_id']}\n")
            f.write(f"\n")
        
        if results['failed'] > 0:
            f.write(f"\n{'='*80}\n")
            f.write(f"Failed Files:\n")
            f.write(f"{'='*80}\n\n")
            
            for detail in [d for d in results['details'] if 'failed' in d['status']]:
                f.write(f"❌ {detail['file']}\n")
                f.write(f"   Status: {detail['status']}\n")
                f.write(f"   Reason: {detail['reason']}\n\n")
    
    print(f"📄 Report saved to: {report_file}")
    
    if results['success'] > 0:
        print(f"\n🎉 Successfully migrated {results['success']} files!")

if __name__ == '__main__':
    from datetime import datetime
    main()



