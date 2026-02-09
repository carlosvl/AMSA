#!/usr/bin/env python3
"""
Retrieve all reports from Alianza_Reports folder in Salesforce org.

This script:
1. Queries all reports in the Alianza_Reports folder
2. Retrieves their metadata files
3. Saves them to force-app/main/default/reports/Alianza_Reports/

Usage:
  python3 retrieve_all_alianza_reports.py <org_alias>

Example:
  python3 retrieve_all_alianza_reports.py 'AMSA-Royalty-Becky'
"""

import subprocess
import sys
import json
import tempfile
import os
from pathlib import Path

def run_sf_command(cmd, org_alias):
    """Run a Salesforce CLI command and return output."""
    full_cmd = cmd + ['--target-org', org_alias]
    result = subprocess.run(
        full_cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=300
    )
    return result.stdout, result.stderr, result.returncode

def get_reports_list(org_alias):
    """Get list of all reports in Alianza_Reports folder using SOQL."""
    print(f"📥 Querying reports from {org_alias}...")
    
    # Use a temp file to capture output
    with tempfile.NamedTemporaryFile(mode='w+', suffix='.json', delete=False) as tmp_file:
        tmp_path = tmp_file.name
    
    try:
        # Query reports - use shell to redirect output
        query = "SELECT Id, Name, DeveloperName FROM Report WHERE FolderName = 'Alianza_Reports' AND IsDeleted = false ORDER BY Name"
        cmd_str = f"sf data query --query \"{query}\" --target-org '{org_alias}' --json > '{tmp_path}' 2>&1"
        result = subprocess.run(cmd_str, shell=True, timeout=300)
        
        # Read results
        if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            with open(tmp_path, 'r') as f:
                content = f.read()
            
            # Try to find JSON in the output
            json_start = content.find('{')
            if json_start >= 0:
                try:
                    data = json.loads(content[json_start:])
                    records = data.get('result', {}).get('records', [])
                    print(f"  ✅ Found {len(records)} reports")
                    return records
                except json.JSONDecodeError:
                    pass
        
        print(f"  ⚠️  Could not parse query results")
        return []
    finally:
        try:
            os.unlink(tmp_path)
        except:
            pass

def retrieve_report(org_alias, report_name):
    """Retrieve a single report metadata."""
    report_path = f"Report:Alianza_Reports/{report_name}"
    stdout, stderr, returncode = run_sf_command(
        ['sf', 'project', 'retrieve', 'start', '--metadata', report_path],
        org_alias
    )
    
    if returncode == 0 and 'Retrieved' in stdout:
        return True
    elif 'Nothing retrieved' in stdout:
        return False
    else:
        return None

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 retrieve_all_alianza_reports.py <org_alias>")
        sys.exit(1)
    
    org_alias = sys.argv[1]
    
    print(f"\n{'='*80}")
    print(f"RETRIEVING ALL REPORTS FROM ALIANZA_REPORTS FOLDER")
    print(f"Org: {org_alias}")
    print(f"{'='*80}\n")
    
    # Get list of reports
    reports = get_reports_list(org_alias)
    
    if not reports:
        print("\n⚠️  No reports found. Trying alternative method...")
        print("   Attempting to retrieve all reports using wildcard...")
        
        # Try retrieving the entire folder
        stdout, stderr, returncode = run_sf_command(
            ['sf', 'project', 'retrieve', 'start', '--metadata', 'Report:Alianza_Reports/*'],
            org_alias
        )
        
        if returncode == 0:
            print("✅ Retrieved reports using wildcard")
        else:
            print("❌ Wildcard retrieval failed")
            print("   Please check the folder name in Salesforce")
        return
    
    print(f"\n🔄 Retrieving {len(reports)} reports...\n")
    
    successful = []
    failed = []
    skipped = []
    
    for i, report in enumerate(reports, 1):
        report_name = report.get('DeveloperName') or report.get('Name', '')
        display_name = report.get('Name', report_name)
        
        print(f"[{i}/{len(reports)}] {display_name} ({report_name})")
        
        result = retrieve_report(org_alias, report_name)
        
        if result is True:
            print(f"    ✅ Retrieved")
            successful.append(report_name)
        elif result is False:
            print(f"    ⚠️  Nothing retrieved (may already exist)")
            skipped.append(report_name)
        else:
            print(f"    ❌ Failed")
            failed.append(report_name)
    
    print(f"\n{'='*80}")
    print("SUMMARY")
    print(f"{'='*80}")
    print(f"✅ Successful: {len(successful)}")
    print(f"⚠️  Skipped: {len(skipped)}")
    print(f"❌ Failed: {len(failed)}")
    
    if successful:
        print(f"\n✅ Successfully retrieved reports:")
        for name in successful:
            print(f"  - {name}")
    
    if failed:
        print(f"\n❌ Failed reports:")
        for name in failed:
            print(f"  - {name}")
    
    print()

if __name__ == '__main__':
    main()
