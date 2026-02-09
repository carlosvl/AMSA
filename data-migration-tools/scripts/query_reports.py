#!/usr/bin/env python3
"""
Salesforce Reports Query Tool
Queries and lists Salesforce reports, including those in private folders.

This script can:
1. List all reports accessible to the user (including private folder reports)
2. Filter reports by folder name
3. Export report metadata to JSON
4. Show folder sharing information

Usage:
  python3 query_reports.py <org_alias> [--folder FOLDER_NAME] [--export-json] [--private-only]

Example:
  python3 query_reports.py 'AMSA Prod' --folder 'Alianza Reports'
  python3 query_reports.py 'AMSA Prod' --private-only
  python3 query_reports.py 'AMSA Prod' --export-json
"""

import json
import subprocess
import sys
import argparse
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

BASE_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = BASE_DIR / 'results'
RESULTS_DIR.mkdir(exist_ok=True)


def run_soql(org_alias: str, query: str) -> List[Dict]:
    """Run a SOQL query and return list of records (or [])."""
    result = subprocess.run(
        [
            'sf', 'data', 'query',
            '--query', query,
            '--target-org', org_alias,
            '--json',
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )

    if result.returncode != 0:
        print(f"  ❌ SOQL error for org {org_alias}:")
        print(result.stderr.strip())
        return []

    try:
        data = json.loads(result.stdout)
        return data.get('result', {}).get('records', [])
    except Exception as e:
        print(f"  ❌ Failed to parse SOQL JSON for org {org_alias}: {e}")
        return []


def query_reports_via_metadata(org_alias: str, folder_name: Optional[str] = None) -> List[Dict]:
    """
    Query reports using Metadata API via Salesforce CLI.
    This method works even if SOQL access to Report object is restricted.
    
    Args:
        org_alias: Salesforce org alias
        folder_name: Optional folder name to filter by
        
    Returns:
        List of report metadata
    """
    print(f"📥 Querying reports via Metadata API from {org_alias}...")
    
    try:
        # List all reports using metadata API
        cmd = [
            'sf', 'org', 'list', 'metadata',
            '--metadata-type', 'Report',
            '--target-org', org_alias,
            '--json'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        
        if result.returncode != 0:
            print(f"  ⚠️  Metadata API query failed: {result.stderr.strip()}")
            return []
        
        data = json.loads(result.stdout)
        metadata_list = data.get('result', [])
        
        # Convert to report-like format
        reports = []
        for item in metadata_list:
            full_name = item.get('fullName', '')
            # Format: FolderName/ReportName
            if '/' in full_name:
                folder, report_name = full_name.split('/', 1)
                if folder_name and folder != folder_name:
                    continue
                reports.append({
                    'Name': report_name,
                    'DeveloperName': report_name,
                    'FolderName': folder,
                    'Id': item.get('id', ''),
                    'Format': 'Unknown',  # Not available via metadata list
                    'ReportType': 'Unknown',
                    'CreatedDate': None,
                    'LastModifiedDate': None
                })
        
        print(f"  ✅ Found {len(reports)} reports via Metadata API")
        return reports
        
    except Exception as e:
        print(f"  ⚠️  Error querying via Metadata API: {e}")
        return []


def query_reports(org_alias: str, folder_name: Optional[str] = None, private_only: bool = False) -> List[Dict]:
    """
    Query Salesforce reports.
    Tries SOQL first, falls back to Metadata API if SOQL fails.
    
    Args:
        org_alias: Salesforce org alias
        folder_name: Optional folder name to filter by
        private_only: If True, only return reports in private folders
        
    Returns:
        List of report records
    """
    print(f"📥 Querying reports from {org_alias}...")
    
    # Try SOQL first
    query = """
        SELECT Id, Name, DeveloperName, FolderName, Format, ReportType,
               CreatedDate, CreatedBy.Name, LastModifiedDate, LastModifiedBy.Name,
               Description, IsDeleted
        FROM Report
        WHERE IsDeleted = false
    """
    
    # Add folder filter if specified
    if folder_name:
        query += f" AND FolderName = '{folder_name}'"
    
    query += " ORDER BY FolderName, Name"
    
    reports = run_soql(org_alias, query)
    
    # If SOQL returned empty and we got an error, try Metadata API
    if not reports:
        print("  ⚠️  SOQL query returned no results, trying Metadata API...")
        reports = query_reports_via_metadata(org_alias, folder_name)
    
    # Filter for private folders if requested
    if private_only and reports:
        # Get all report folders to identify private ones
        folders = query_report_folders(org_alias)
        private_folder_names = {
            f['DeveloperName'] for f in folders 
            if not f.get('AccessType') or f.get('AccessType') == 'Private'
        }
        
        reports = [
            r for r in reports 
            if r.get('FolderName') in private_folder_names
        ]
    
    print(f"  ✅ Found {len(reports)} reports")
    return reports


def query_report_folders(org_alias: str) -> List[Dict]:
    """
    Query Salesforce report folders to get sharing information.
    
    Args:
        org_alias: Salesforce org alias
        
    Returns:
        List of report folder records
    """
    print(f"📥 Querying report folders from {org_alias}...")
    
    query = """
        SELECT Id, Name, DeveloperName, AccessType, CreatedDate, CreatedBy.Name
        FROM ReportFolder
        ORDER BY Name
    """
    
    folders = run_soql(org_alias, query)
    print(f"  ✅ Found {len(folders)} report folders")
    return folders


def query_folder_shares(org_alias: str, folder_id: str) -> List[Dict]:
    """
    Query folder sharing information for a specific folder.
    Note: This requires querying FolderShare or using Metadata API.
    For now, we'll use a workaround with SOQL if available.
    """
    # Folder sharing is typically accessed via Metadata API or Tooling API
    # For SOQL, we can try to query FolderShare if available
    query = f"""
        SELECT Id, UserOrGroupId, AccessLevel
        FROM FolderShare
        WHERE ParentId = '{folder_id}'
    """
    
    shares = run_soql(org_alias, query)
    return shares


def display_reports(reports: List[Dict], folders: List[Dict] = None):
    """Display reports in a formatted way."""
    if not reports:
        print("\n  No reports found.")
        return
    
    # Group by folder
    reports_by_folder = {}
    for report in reports:
        folder_name = report.get('FolderName', 'Unfiled Public Reports')
        if folder_name not in reports_by_folder:
            reports_by_folder[folder_name] = []
        reports_by_folder[folder_name].append(report)
    
    # Create folder access map
    folder_access = {}
    if folders:
        for folder in folders:
            folder_access[folder.get('DeveloperName')] = {
                'name': folder.get('Name'),
                'access_type': folder.get('AccessType', 'Unknown'),
                'id': folder.get('Id')
            }
    
    print("\n" + "="*80)
    print("SALESFORCE REPORTS")
    print("="*80)
    
    for folder_name, folder_reports in sorted(reports_by_folder.items()):
        folder_info = folder_access.get(folder_name, {})
        access_type = folder_info.get('access_type', 'Unknown')
        
        print(f"\n📁 Folder: {folder_info.get('name', folder_name)}")
        print(f"   Developer Name: {folder_name}")
        print(f"   Access Type: {access_type}")
        print(f"   Reports: {len(folder_reports)}")
        print("-" * 80)
        
        for report in folder_reports:
            print(f"  📊 {report.get('Name')}")
            print(f"     ID: {report.get('Id')}")
            print(f"     Developer Name: {report.get('DeveloperName', 'N/A')}")
            print(f"     Type: {report.get('ReportType', 'N/A')}")
            print(f"     Format: {report.get('Format', 'N/A')}")
            print(f"     Created: {report.get('CreatedDate', 'N/A')}")
            if report.get('Description'):
                print(f"     Description: {report.get('Description')}")
            print()


def export_reports_json(reports: List[Dict], folders: List[Dict] = None, org_alias: str = None):
    """Export reports to JSON file."""
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"reports_{org_alias or 'default'}_{timestamp}.json"
    filepath = RESULTS_DIR / filename
    
    export_data = {
        'export_date': datetime.now().isoformat(),
        'org_alias': org_alias,
        'total_reports': len(reports),
        'reports': reports,
        'folders': folders or []
    }
    
    filepath.write_text(json.dumps(export_data, indent=2, default=str))
    print(f"\n📄 Exported reports to: {filepath}")
    return filepath


def main():
    parser = argparse.ArgumentParser(
        description='Query Salesforce reports, including those in private folders'
    )
    parser.add_argument('org_alias', help='Salesforce org alias')
    parser.add_argument(
        '--folder',
        help='Filter by folder name (exact match)'
    )
    parser.add_argument(
        '--private-only',
        action='store_true',
        help='Only show reports in private folders'
    )
    parser.add_argument(
        '--export-json',
        action='store_true',
        help='Export results to JSON file'
    )
    parser.add_argument(
        '--list-folders',
        action='store_true',
        help='List all report folders with access information'
    )
    
    args = parser.parse_args()
    
    try:
        # Query report folders first if needed
        folders = None
        if args.private_only or args.list_folders:
            folders = query_report_folders(args.org_alias)
            
            if args.list_folders:
                print("\n" + "="*80)
                print("REPORT FOLDERS")
                print("="*80)
                for folder in folders:
                    print(f"\n📁 {folder.get('Name')}")
                    print(f"   Developer Name: {folder.get('DeveloperName')}")
                    print(f"   Access Type: {folder.get('AccessType', 'Unknown')}")
                    print(f"   ID: {folder.get('Id')}")
                    print(f"   Created: {folder.get('CreatedDate', 'N/A')}")
                print()
        
        # Query reports
        reports = query_reports(
            args.org_alias,
            folder_name=args.folder,
            private_only=args.private_only
        )
        
        # Display results
        display_reports(reports, folders)
        
        # Export if requested
        if args.export_json:
            export_reports_json(reports, folders, args.org_alias)
        
        print(f"\n✅ Query completed successfully")
        
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
