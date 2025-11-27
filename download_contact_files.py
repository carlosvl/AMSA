#!/usr/bin/env python3
"""
Download Contact-related files from Salesforce
"""
import json
import subprocess
import urllib.request
import os
from pathlib import Path
import re

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

def sanitize_filename(filename):
    """Remove or replace invalid characters in filename"""
    # Replace invalid characters with underscore
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    # Remove leading/trailing spaces and dots
    filename = filename.strip('. ')
    # Limit filename length
    if len(filename) > 200:
        filename = filename[:200]
    return filename

def download_file(access_token, instance_url, content_version_id, title, file_extension, output_dir):
    """Download a single file from Salesforce"""
    # Create safe filename
    safe_title = sanitize_filename(title)
    if file_extension and not safe_title.endswith(f'.{file_extension}'):
        filename = f"{safe_title}.{file_extension}"
    else:
        filename = safe_title
    
    filepath = os.path.join(output_dir, filename)
    
    # Check if file already exists
    if os.path.exists(filepath):
        print(f"  ⏭️  Already exists: {filename}")
        return True
    
    # Download file using REST API
    url = f"{instance_url}/services/data/v59.0/sobjects/ContentVersion/{content_version_id}/VersionData"
    
    try:
        request = urllib.request.Request(url)
        request.add_header('Authorization', f'Bearer {access_token}')
        request.add_header('Content-Type', 'application/octet-stream')
        
        with urllib.request.urlopen(request) as response:
            # Write file
            with open(filepath, 'wb') as f:
                f.write(response.read())
        
        # Get file size
        file_size = os.path.getsize(filepath)
        size_kb = file_size / 1024
        if size_kb > 1024:
            size_str = f"{size_kb/1024:.2f} MB"
        else:
            size_str = f"{size_kb:.2f} KB"
        
        print(f"  ✅ Downloaded: {filename} ({size_str})")
        return True
    except Exception as e:
        print(f"  ❌ Error downloading {filename}: {e}")
        return False

def main():
    org_alias = 'AMSA-Royalty-Prod'
    output_dir = 'downloaded_contact_files'
    
    print(f"🔐 Authenticating with {org_alias}...")
    access_token, instance_url = get_access_token_and_instance(org_alias)
    
    if not access_token:
        print("❌ Failed to get access token")
        return
    
    print(f"✅ Connected to: {instance_url}\n")
    
    # Load contact file versions
    with open('contact_file_versions.json', 'r') as f:
        files = json.load(f)
    
    print(f"📥 Downloading {len(files)} files to {output_dir}/\n")
    
    # Create output directory
    Path(output_dir).mkdir(exist_ok=True)
    
    # Download files
    success_count = 0
    fail_count = 0
    
    for i, file_info in enumerate(files, 1):
        content_version_id = file_info['Id']
        title = file_info['Title']
        file_extension = file_info.get('FileExtension', '')
        
        print(f"[{i}/{len(files)}] {title}")
        
        if download_file(access_token, instance_url, content_version_id, title, file_extension, output_dir):
            success_count += 1
        else:
            fail_count += 1
    
    print(f"\n{'='*60}")
    print(f"✅ Successfully downloaded: {success_count} files")
    print(f"❌ Failed: {fail_count} files")
    print(f"📁 Files saved to: {os.path.abspath(output_dir)}/")
    print(f"{'='*60}")
    
    # Create a summary report
    with open('download_summary.txt', 'w') as f:
        f.write(f"Contact Files Download Summary\n")
        f.write(f"{'='*60}\n\n")
        f.write(f"Organization: {org_alias}\n")
        f.write(f"Date Range: After August 1, 2025\n")
        f.write(f"Total Files: {len(files)}\n")
        f.write(f"Successfully Downloaded: {success_count}\n")
        f.write(f"Failed: {fail_count}\n")
        f.write(f"Output Directory: {os.path.abspath(output_dir)}/\n\n")
        f.write(f"{'='*60}\n")
        f.write(f"File List:\n")
        f.write(f"{'='*60}\n\n")
        
        for i, file_info in enumerate(files, 1):
            title = file_info['Title']
            ext = file_info.get('FileExtension', 'unknown')
            size = file_info.get('ContentSize', 0)
            created = file_info.get('CreatedDate', '')
            
            size_kb = size / 1024
            if size_kb > 1024:
                size_str = f"{size_kb/1024:.2f} MB"
            else:
                size_str = f"{size_kb:.2f} KB"
            
            f.write(f"{i}. {title}\n")
            f.write(f"   Extension: {ext} | Size: {size_str} | Created: {created}\n\n")
    
    print(f"\n📄 Summary report saved to: download_summary.txt")

if __name__ == '__main__':
    main()

