#!/usr/bin/env python3
"""
Retrieve all reports from Alianza_Reports folder.

Usage:
  python3 retrieve_all_reports.py
"""

import subprocess
import sys
from pathlib import Path

ORG_ALIAS = 'AMSA-Royalty-Becky'
REPORTS_DIR = Path('force-app/main/default/reports/Alianza_Reports')

def get_report_list():
    """Get list of reports from Salesforce."""
    print("📥 Getting list of reports from Salesforce...")
    
    cmd = [
        'sf', 'data', 'query',
        '--query', "SELECT DeveloperName FROM Report WHERE FolderName = 'Alianza Reports' AND IsDeleted = false ORDER BY Name",
        '--target-org', ORG_ALIAS,
        '--result-format', 'csv'
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    
    if result.returncode != 0:
        print(f"❌ Error querying reports: {result.stderr}")
        return []
    
    # Parse CSV - skip header and filter valid report names
    reports = []
    for line in result.stdout.split('\n'):
        line = line.strip()
        if line and line != 'DeveloperName' and not line.startswith('Querying') and not line.startswith('done'):
            # Extract just the developer name (first column)
            parts = line.split(',')
            if parts:
                report_name = parts[0].strip().strip('"')
                if report_name and report_name.replace('_', '').replace('X', '').replace('1', '').replace('2', '').replace('3', '').replace('4', '').replace('5', '').replace('6', '').replace('7', '').replace('8', '').replace('9', '').replace('0', '').isalnum():
                    reports.append(report_name)
    
    print(f"  ✅ Found {len(reports)} reports")
    return reports

def retrieve_report(report_name):
    """Retrieve a single report."""
    cmd = [
        'sf', 'project', 'retrieve', 'start',
        '--metadata', f'Report:Alianza_Reports/{report_name}',
        '--target-org', ORG_ALIAS
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return result.returncode == 0

def main():
    print("="*80)
    print("RETRIEVING ALL REPORTS FROM ALIANZA_REPORTS FOLDER")
    print("="*80)
    print()
    
    # Get initial count
    initial_count = len(list(REPORTS_DIR.glob('*.report-meta.xml'))) if REPORTS_DIR.exists() else 0
    print(f"Current reports in folder: {initial_count}")
    print()
    
    # Get list of reports
    reports = get_report_list()
    
    if not reports:
        print("❌ No reports found")
        sys.exit(1)
    
    print(f"\n🔄 Retrieving {len(reports)} reports...")
    print("(This will take several minutes)")
    print()
    
    successful = 0
    failed = 0
    
    for i, report_name in enumerate(reports, 1):
        # Show progress every 10 reports
        if i % 10 == 0:
            current_count = len(list(REPORTS_DIR.glob('*.report-meta.xml'))) if REPORTS_DIR.exists() else 0
            new_reports = current_count - initial_count
            print(f"[{i}/{len(reports)}] Progress: {new_reports} new reports retrieved...")
        
        if retrieve_report(report_name):
            successful += 1
        else:
            failed += 1
    
    # Final count
    final_count = len(list(REPORTS_DIR.glob('*.report-meta.xml'))) if REPORTS_DIR.exists() else 0
    retrieved = final_count - initial_count
    
    print()
    print("="*80)
    print("SUMMARY")
    print("="*80)
    print(f"Initial reports: {initial_count}")
    print(f"Final reports: {final_count}")
    print(f"New reports retrieved: {retrieved}")
    print(f"✅ Successful retrievals: {successful}")
    print(f"❌ Failed retrievals: {failed}")
    print()

if __name__ == '__main__':
    main()
