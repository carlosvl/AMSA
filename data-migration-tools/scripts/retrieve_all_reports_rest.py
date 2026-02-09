#!/usr/bin/env python3
"""
Retrieve all reports from Alianza_Reports folder using REST API.

This script bypasses CLI log file issues by using REST API directly.

Usage:
  python3 retrieve_all_reports_rest.py <org_alias>

Example:
  python3 retrieve_all_reports_rest.py 'AMSA-Royalty-Becky'
"""

import subprocess
import sys
import json
import tempfile
import os
import urllib.request
import urllib.parse
from pathlib import Path

def get_org_info(org_alias):
    """Get org instance URL and access token."""
    # Use temp file to capture sf org display output
    with tempfile.NamedTemporaryFile(mode='w+', suffix='.txt', delete=False) as tmp_file:
        tmp_path = tmp_file.name
    
    try:
        cmd_str = f"sf org display --target-org '{org_alias}' > '{tmp_path}' 2>&1"
        result = subprocess.run(cmd_str, shell=True, timeout=30)
        
        if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            with open(tmp_path, 'r') as f:
                content = f.read()
            
            # Parse the output
            org_info = {}
            for line in content.split('\n'):
                if 'Instance Url' in line or 'Instance Url' in line:
                    parts = line.split()
                    if len(parts) >= 3:
                        org_info['instanceUrl'] = parts[-1].strip()
                elif 'Access Token' in line:
                    parts = line.split()
                    if len(parts) >= 3:
                        org_info['accessToken'] = parts[-1].strip()
                elif 'Api Version' in line or 'Api Version' in line:
                    parts = line.split()
                    if len(parts) >= 3:
                        org_info['apiVersion'] = parts[-1].strip()
            
            if org_info.get('instanceUrl') and org_info.get('accessToken'):
                if 'apiVersion' not in org_info:
                    org_info['apiVersion'] = '65.0'
                return org_info
    finally:
        try:
            os.unlink(tmp_path)
        except:
            pass
    
    return None

def query_reports_rest_api(org_info, folder_name='Alianza_Reports'):
    """Query reports using REST API."""
    instance_url = org_info['instanceUrl']
    access_token = org_info['accessToken']
    api_version = org_info['apiVersion']
    
    # Build SOQL query URL
    query = f"SELECT Id, Name, DeveloperName, FolderName FROM Report WHERE FolderName = '{folder_name}' AND IsDeleted = false ORDER BY Name"
    query_url = f"{instance_url}/services/data/v{api_version}/query/"
    
    params = urllib.parse.urlencode({'q': query})
    full_url = f"{query_url}?{params}"
    
    try:
        req = urllib.request.Request(full_url)
        req.add_header('Authorization', f'Bearer {access_token}')
        req.add_header('Content-Type', 'application/json')
        
        with urllib.request.urlopen(req, timeout=300) as response:
            data = json.loads(response.read().decode())
            if 'records' in data:
                return data['records']
            return []
    except Exception as e:
        print(f"  ❌ REST API error: {e}")
        return []

def retrieve_report(org_alias, report_name):
    """Retrieve a single report using CLI."""
    report_path = f"Report:Alianza_Reports/{report_name}"
    cmd = ['sf', 'project', 'retrieve', 'start', '--metadata', report_path, '--target-org', org_alias]
    
    result = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=300
    )
    
    if result.returncode == 0 and 'Retrieved' in result.stdout:
        return True
    return False

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 retrieve_all_reports_rest.py <org_alias>")
        sys.exit(1)
    
    org_alias = sys.argv[1]
    
    print(f"\n{'='*80}")
    print(f"RETRIEVING ALL REPORTS FROM ALIANZA_REPORTS FOLDER")
    print(f"Org: {org_alias}")
    print(f"{'='*80}\n")
    
    # Get org credentials
    print("📥 Getting org credentials...")
    org_info = get_org_info(org_alias)
    
    if not org_info:
        print("  ❌ Could not get org credentials")
        print("   Please ensure the org is authenticated and accessible")
        sys.exit(1)
    
    print(f"  ✅ Connected to {org_info['instanceUrl']}")
    
    # Query reports using REST API
    print(f"\n📥 Querying reports in Alianza_Reports folder...")
    reports = query_reports_rest_api(org_info)
    
    if not reports:
        print("  ⚠️  No reports found")
        sys.exit(1)
    
    print(f"  ✅ Found {len(reports)} reports\n")
    
    # Show list of reports
    print("Reports found:")
    for i, report in enumerate(reports, 1):
        name = report.get('Name', 'Unknown')
        dev_name = report.get('DeveloperName', name)
        print(f"  {i:3d}. {name} ({dev_name})")
    
    print(f"\n🔄 Retrieving {len(reports)} reports...\n")
    
    successful = []
    failed = []
    
    for i, report in enumerate(reports, 1):
        report_name = report.get('DeveloperName') or report.get('Name', '')
        display_name = report.get('Name', report_name)
        
        print(f"[{i:3d}/{len(reports)}] {display_name}")
        
        if retrieve_report(org_alias, report_name):
            print(f"         ✅ Retrieved")
            successful.append(report_name)
        else:
            print(f"         ❌ Failed")
            failed.append(report_name)
    
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"✅ Successful: {len(successful)}")
    print(f"❌ Failed: {len(failed)}")
    
    if successful:
        print(f"\n✅ Successfully retrieved {len(successful)} reports")
    
    if failed:
        print(f"\n❌ Failed to retrieve {len(failed)} reports:")
        for name in failed[:10]:
            print(f"  - {name}")
        if len(failed) > 10:
            print(f"  ... and {len(failed) - 10} more")
    
    print()

if __name__ == '__main__':
    main()
