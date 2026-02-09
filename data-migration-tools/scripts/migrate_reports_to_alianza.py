#!/usr/bin/env python3
"""
Migrate Reports from Private Folder to Alianza_Reports Folder

This script:
1. Queries all reports from the source org (AMSA-Royalty-Becky)
2. Identifies reports in private/user folders
3. Retrieves report metadata files
4. Moves them to force-app/main/default/reports/Alianza_Reports/
5. Updates folder references in metadata

Usage:
  python3 migrate_reports_to_alianza.py <source_org> [--dry-run] [--target-folder FOLDER_NAME]

Example:
  python3 migrate_reports_to_alianza.py 'AMSA-Royalty-Becky'
  python3 migrate_reports_to_alianza.py 'AMSA-Royalty-Becky' --dry-run
"""

import json
import subprocess
import sys
import argparse
import shutil
import xml.etree.ElementTree as ET
import os
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Tuple

# Set SF_LOG_PATH to a writable location to avoid permission issues
os.environ['SF_LOG_PATH'] = '/tmp/sf.log'

try:
    from simple_salesforce import Salesforce
    HAS_SIMPLE_SALESFORCE = True
except ImportError:
    HAS_SIMPLE_SALESFORCE = False
    Salesforce = None  # Placeholder for type hints
    # Will use REST API directly if simple-salesforce is not available

BASE_DIR = Path(__file__).resolve().parents[2]
REPORTS_DIR = BASE_DIR / 'force-app' / 'main' / 'default' / 'reports'
ALIANZA_REPORTS_DIR = REPORTS_DIR / 'Alianza_Reports'
ALIANZA_FOLDER_META = REPORTS_DIR / 'Alianza_Reports.reportFolder-meta.xml'

RESULTS_DIR = BASE_DIR / 'data-migration-tools' / 'results'
RESULTS_DIR.mkdir(exist_ok=True, parents=True)


def get_sfdx_orgs() -> Dict:
    """Get list of authenticated SFDX orgs."""
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w+', suffix='.json', delete=False) as tmp_file:
        tmp_path = tmp_file.name
    
    try:
        # Use shell redirection to temp file to avoid log file issues
        cmd_str = f"sf org list --json > '{tmp_path}' 2>&1"
        result = subprocess.run(cmd_str, shell=True, timeout=30)
        
        # Read from temp file and try to parse JSON
        if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            with open(tmp_path, 'r') as f:
                content = f.read()
            
            # Look for JSON in the content (might have error messages before it)
            json_start = content.find('{')
            if json_start >= 0:
                try:
                    data = json.loads(content[json_start:])
                    return data
                except json.JSONDecodeError:
                    pass
        return {}
    except Exception:
        return {}
    finally:
        try:
            os.unlink(tmp_path)
        except:
            pass


def connect_to_salesforce(org_alias: str):
    """Connect to Salesforce using SFDX credentials."""
    if not HAS_SIMPLE_SALESFORCE:
        return None
    
    orgs_data = get_sfdx_orgs()
    all_orgs = orgs_data.get('result', {}).get('nonScratchOrgs', []) + orgs_data.get('result', {}).get('other', [])
    
    # Find the target org
    target_org = None
    for org in all_orgs:
        if org.get('alias') == org_alias or org.get('username') == org_alias:
            target_org = org
            break
    
    if not target_org:
        print(f"  ❌ Org '{org_alias}' not found in authenticated orgs")
        return None
    
    if target_org.get('connectedStatus') != 'Connected':
        print(f"  ❌ Org is not connected. Status: {target_org.get('connectedStatus')}")
        return None
    
    try:
        sf = Salesforce(
            instance_url=target_org['instanceUrl'],
            session_id=target_org['accessToken'],
            version='65.0'
        )
        return sf
    except Exception as e:
        print(f"  ❌ Failed to connect: {e}")
        return None


def run_soql_rest_api(org_alias: str, query: str) -> List[Dict]:
    """Run SOQL query using REST API directly."""
    import urllib.request
    import urllib.parse
    
    org_info = get_org_credentials(org_alias)
    if not org_info:
        print(f"  ⚠️  Could not get org credentials")
        return []
    
    instance_url = org_info.get('instanceUrl', '')
    access_token = org_info.get('accessToken', '')
    
    if not instance_url or not access_token:
        print(f"  ⚠️  Missing instance URL or access token")
        return []
    
    # Build REST API URL
    api_version = org_info.get('apiVersion', '65.0')
    query_url = f"{instance_url}/services/data/v{api_version}/query/"
    
    # URL encode the query
    params = urllib.parse.urlencode({'q': query})
    full_url = f"{query_url}?{params}"
    
    try:
        req = urllib.request.Request(full_url)
        req.add_header('Authorization', f'Bearer {access_token}')
        req.add_header('Content-Type', 'application/json')
        
        with urllib.request.urlopen(req, timeout=300) as response:
            data = json.loads(response.read().decode())
            records = data.get('records', [])
            if 'errorCode' in data:
                print(f"  ⚠️  REST API error: {data.get('message', 'Unknown error')}")
                return []
            return records
    except urllib.error.HTTPError as e:
        error_body = e.read().decode() if e.fp else "No error details"
        print(f"  ⚠️  REST API HTTP error {e.code}: {error_body[:200]}")
        return []
    except Exception as e:
        print(f"  ⚠️  REST API query error: {e}")
        return []


def run_soql(org_alias: str, query: str) -> List[Dict]:
    """Run a SOQL query and return list of records (or [])."""
    if HAS_SIMPLE_SALESFORCE:
        # Use simple-salesforce if available
        sf = connect_to_salesforce(org_alias)
        if not sf:
            return []
        
        try:
            result = sf.query(query)
            return result.get('records', [])
        except Exception as e:
            print(f"  ⚠️  SOQL query error: {e}")
            return []
    else:
        # Fall back to direct REST API
        print(f"  📡 Using REST API (simple-salesforce not available)")
        return run_soql_rest_api(org_alias, query)

    # Function now uses simple-salesforce directly, so this code is not needed
    # But keeping for compatibility
    return []

    # If we get here, try parsing again (shouldn't happen, but safety check)
    try:
        data = json.loads(result.stdout)
        return data.get('result', {}).get('records', [])
    except Exception as e:
        print(f"  ❌ Failed to parse SOQL JSON for org {org_alias}: {e}")
        return []


def get_org_credentials(org_alias: str) -> Optional[Dict]:
    """Get org credentials using sf org list (more reliable than org display)."""
    # Try sf org list first - it seems to work better with log file issues
    orgs_data = get_sfdx_orgs()
    all_orgs = orgs_data.get('result', {}).get('nonScratchOrgs', []) + orgs_data.get('result', {}).get('other', [])
    
    # Find the target org
    target_org = None
    for org in all_orgs:
        if org.get('alias') == org_alias or org.get('username') == org_alias:
            target_org = org
            break
    
    if target_org and target_org.get('instanceUrl') and target_org.get('accessToken'):
        return {
            'instanceUrl': target_org['instanceUrl'],
            'accessToken': target_org['accessToken'],
            'apiVersion': target_org.get('instanceApiVersion', '65.0')
        }
    
    return None


def query_reports_in_private_folders(org_alias: str) -> List[Dict]:
    """
    Query reports that are in private/user folders.
    
    Returns reports that are NOT in public folders or shared folders.
    """
    print(f"📥 Querying reports from {org_alias}...")
    
    # Query all reports
    query = """
        SELECT Id, Name, DeveloperName, FolderName, Format, ReportType,
               CreatedDate, CreatedBy.Name, LastModifiedDate, LastModifiedBy.Name,
               Description, IsDeleted
        FROM Report
        WHERE IsDeleted = false
        ORDER BY FolderName, Name
    """
    
    all_reports = run_soql(org_alias, query)
    print(f"  Found {len(all_reports)} total reports via SOQL")
    
    if not all_reports:
        print("  ⚠️  No reports found via SOQL, trying Metadata API...")
        return query_reports_via_metadata(org_alias)
    
    # Query report folders to identify private ones
    print(f"📥 Querying report folders from {org_alias}...")
    folders_query = """
        SELECT Id, Name, DeveloperName, AccessType, CreatedDate, CreatedBy.Name
        FROM ReportFolder
        ORDER BY Name
    """
    
    folders = run_soql(org_alias, folders_query)
    folder_map = {f['DeveloperName']: f for f in folders}
    
    # Identify private folders (AccessType = 'Private' or user's personal folder)
    private_folder_names = set()
    for folder in folders:
        access_type = folder.get('AccessType', '')
        folder_name = folder.get('DeveloperName', '')
        
        # Private folders or user's personal folder
        if access_type == 'Private' or not access_type:
            private_folder_names.add(folder_name)
    
    # Filter reports in private folders
    private_reports = [
        r for r in all_reports 
        if r.get('FolderName') in private_folder_names
    ]
    
    print(f"  ✅ Found {len(all_reports)} total reports")
    print(f"  ✅ Found {len(private_reports)} reports in private/user folders")
    
    return private_reports


def query_reports_via_metadata(org_alias: str) -> List[Dict]:
    """Query reports using Metadata API as fallback."""
    print(f"📥 Querying reports via Metadata API from {org_alias}...")
    
    try:
        cmd = [
            'sf', 'org', 'list', 'metadata',
            '--metadata-type', 'Report',
            '--target-org', org_alias,
            '--json'
        ]
        
        result = subprocess.run(
            cmd, 
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,  # Suppress stderr to avoid log file issues
            text=True, 
            timeout=300
        )
        
        if result.returncode != 0:
            print(f"  ⚠️  Metadata API query failed")
            if result.stderr:
                print(f"  Error: {result.stderr.strip()}")
            return []
        
        data = json.loads(result.stdout)
        metadata_list = data.get('result', [])
        
        reports = []
        for item in metadata_list:
            full_name = item.get('fullName', '')
            if '/' in full_name:
                folder, report_name = full_name.split('/', 1)
                # Assume private if folder name contains user info or is not "Alianza_Reports"
                if folder != 'Alianza_Reports':
                    reports.append({
                        'Name': report_name,
                        'DeveloperName': report_name,
                        'FolderName': folder,
                        'Id': item.get('id', ''),
                        'fullName': full_name
                    })
        
        return reports
        
    except Exception as e:
        print(f"  ⚠️  Error querying via Metadata API: {e}")
        return []


def retrieve_all_reports(org_alias: str, temp_dir: Path) -> Dict[str, Path]:
    """
    Retrieve all reports from the org and return a map of fullName -> file path.
    
    Args:
        org_alias: Source org alias
        temp_dir: Temporary directory for retrieval
        
    Returns:
        Dictionary mapping report fullName to file path
    """
    print(f"📥 Retrieving all reports from {org_alias}...")
    
    report_map = {}
    
    try:
        # Retrieve all reports at once
        cmd = [
            'sf', 'project', 'retrieve', 'start',
            '--metadata', 'Report:*',
            '--target-org', org_alias,
            '--json'
        ]
        
        result = subprocess.run(
            cmd, 
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,  # Suppress stderr to avoid log file issues
            text=True, 
            timeout=600, 
            cwd=temp_dir
        )
        
        if result.returncode != 0:
            print(f"  ⚠️  Bulk retrieve failed")
            if result.stderr:
                print(f"  Error: {result.stderr.strip()}")
            print(f"  Trying individual retrievals...")
            return {}
        
        # Find all retrieved report files
        reports_base = BASE_DIR / 'force-app' / 'main' / 'default' / 'reports'
        if reports_base.exists():
            for report_file in reports_base.rglob('*.report-meta.xml'):
                # Extract folder and report name from path
                # Path format: reports/FolderName/ReportName.report-meta.xml
                relative_path = report_file.relative_to(reports_base)
                if len(relative_path.parts) == 2:
                    folder_name = relative_path.parts[0]
                    report_name = relative_path.stem.replace('.report-meta', '')
                    full_name = f"{folder_name}/{report_name}"
                    report_map[full_name] = report_file
        
        print(f"  ✅ Retrieved {len(report_map)} report files")
        return report_map
        
    except Exception as e:
        print(f"  ⚠️  Error retrieving reports: {e}")
        return {}


def retrieve_report_metadata(org_alias: str, report_full_name: str, report_map: Dict[str, Path]) -> Optional[Path]:
    """
    Get the path to a retrieved report metadata file.
    
    Args:
        org_alias: Source org alias (for fallback individual retrieval)
        report_full_name: Full name like "FolderName/ReportName"
        report_map: Map of fullName -> file path from bulk retrieval
        
    Returns:
        Path to the report metadata file, or None if not found
    """
    # First try the bulk retrieval map
    if report_full_name in report_map:
        return report_map[report_full_name]
    
    # Fallback: try individual retrieval
    try:
        cmd = [
            'sf', 'project', 'retrieve', 'start',
            '--metadata', f'Report:{report_full_name}',
            '--target-org', org_alias,
            '--json'
        ]
        
        result = subprocess.run(
            cmd, 
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,  # Suppress stderr to avoid log file issues
            text=True, 
            timeout=300
        )
        
        if result.returncode == 0:
            # Find the retrieved file
            report_parts = report_full_name.split('/')
            if len(report_parts) == 2:
                folder_name, report_name = report_parts
                retrieved_path = BASE_DIR / 'force-app' / 'main' / 'default' / 'reports' / folder_name / f'{report_name}.report-meta.xml'
                
                if retrieved_path.exists():
                    return retrieved_path
        
        return None
        
    except Exception as e:
        return None


def normalize_report_name(name: str) -> str:
    """
    Normalize report name to match Salesforce DeveloperName format.
    Removes special characters and converts to a format that matches file names.
    """
    # Replace spaces and special chars with underscores, remove invalid chars
    normalized = name.replace(' ', '_').replace('-', '_')
    # Remove any remaining invalid characters for file names
    normalized = ''.join(c for c in normalized if c.isalnum() or c in ['_'])
    return normalized


def find_report_file(report_map: Dict[str, Path], folder_name: str, report_name: str, report_dev_name: str) -> Optional[Path]:
    """
    Find a report file in the retrieved map, trying multiple name variations.
    """
    # Try exact match first
    full_name = f"{folder_name}/{report_dev_name}"
    if full_name in report_map:
        return report_map[full_name]
    
    # Try with report name instead of dev name
    full_name2 = f"{folder_name}/{report_name}"
    if full_name2 in report_map:
        return report_map[full_name2]
    
    # Try normalized versions
    normalized_dev = normalize_report_name(report_dev_name)
    normalized_name = normalize_report_name(report_name)
    
    full_name3 = f"{folder_name}/{normalized_dev}"
    if full_name3 in report_map:
        return report_map[full_name3]
    
    full_name4 = f"{folder_name}/{normalized_name}"
    if full_name4 in report_map:
        return report_map[full_name4]
    
    # Try case-insensitive search
    folder_lower = folder_name.lower()
    dev_lower = report_dev_name.lower()
    name_lower = report_name.lower()
    
    for key, path in report_map.items():
        key_parts = key.split('/')
        if len(key_parts) == 2:
            key_folder, key_report = key_parts
            if (key_folder.lower() == folder_lower and 
                (key_report.lower() == dev_lower or key_report.lower() == name_lower)):
                return path
    
    return None


def update_report_folder_reference(report_path: Path, target_folder: str = 'Alianza_Reports') -> bool:
    """
    Update the report metadata to reference the correct folder.
    Note: Reports don't explicitly reference folders in their XML,
    but we ensure the file is in the correct location.
    """
    try:
        tree = ET.parse(report_path)
        root = tree.getroot()
        
        # Reports don't have explicit folder references in the XML
        # The folder is determined by the file location
        # So we just need to ensure the file is in the right place
        
        return True
    except Exception as e:
        print(f"    ⚠️  Error updating report metadata: {e}")
        return False


def migrate_reports(
    org_alias: str,
    target_folder: str = 'Alianza_Reports',
    dry_run: bool = False
) -> Tuple[List[str], List[str]]:
    """
    Migrate reports from private folders to Alianza_Reports folder.
    
    Returns:
        Tuple of (successful_migrations, failed_migrations)
    """
    print(f"\n{'='*80}")
    print(f"MIGRATING REPORTS FROM {org_alias}")
    print(f"Target Folder: {target_folder}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"{'='*80}\n")
    
    # Ensure target directory exists
    target_dir = REPORTS_DIR / target_folder
    if not dry_run:
        target_dir.mkdir(exist_ok=True, parents=True)
    
    # Query reports in private folders
    private_reports = query_reports_in_private_folders(org_alias)
    
    if not private_reports:
        print("\n  ℹ️  No reports found in private/user folders.")
        return [], []
    
    print(f"\n📋 Found {len(private_reports)} reports to migrate:")
    for report in private_reports:
        folder = report.get('FolderName', 'Unknown')
        name = report.get('Name', report.get('DeveloperName', 'Unknown'))
        print(f"  - {folder}/{name}")
    
    successful = []
    failed = []
    
    # Retrieve all reports first (more efficient than individual retrievals)
    report_map = {}
    if not dry_run:
        temp_dir = RESULTS_DIR / 'temp_reports'
        temp_dir.mkdir(exist_ok=True, parents=True)
        report_map = retrieve_all_reports(org_alias, temp_dir)
    
    print(f"\n🔄 Starting migration...\n")
    
    for i, report in enumerate(private_reports, 1):
        folder_name = report.get('FolderName', 'Unknown')
        report_name = report.get('Name', report.get('DeveloperName', 'Unknown'))
        report_dev_name = report.get('DeveloperName', report_name)
        full_name = f"{folder_name}/{report_dev_name}"
        
        print(f"[{i}/{len(private_reports)}] Processing: {full_name}")
        
        # Check if report already exists in target folder
        target_file = target_dir / f'{report_dev_name}.report-meta.xml'
        if target_file.exists():
            print(f"    ⚠️  Report already exists in {target_folder}, skipping...")
            failed.append(f"{full_name} (already exists)")
            continue
        
        if dry_run:
            print(f"    ✅ Would migrate to: {target_file}")
            successful.append(full_name)
            continue
        
        # Get report metadata file path
        retrieved_path = find_report_file(report_map, folder_name, report_name, report_dev_name)
        
        # If not found in bulk retrieval, try individual retrieval
        if not retrieved_path:
            retrieved_path = retrieve_report_metadata(org_alias, full_name, report_map)
        
        if not retrieved_path or not retrieved_path.exists():
            print(f"    ❌ Failed to retrieve report metadata")
            failed.append(full_name)
            continue
        
        try:
            # Copy file to target directory
            shutil.copy2(retrieved_path, target_file)
            
            # Update folder reference if needed
            update_report_folder_reference(target_file, target_folder)
            
            print(f"    ✅ Migrated to: {target_file}")
            successful.append(full_name)
            
            # Clean up retrieved file from original location (only if it's not in the target)
            if retrieved_path != target_file:
                try:
                    retrieved_path.unlink()
                    # Also try to remove empty folder
                    retrieved_folder = retrieved_path.parent
                    if retrieved_folder.exists() and not any(retrieved_folder.iterdir()):
                        retrieved_folder.rmdir()
                except:
                    pass  # Ignore cleanup errors
            
        except Exception as e:
            print(f"    ❌ Error moving file: {e}")
            failed.append(full_name)
    
    # Clean up temp directory
    if not dry_run:
        temp_dir = RESULTS_DIR / 'temp_reports'
        if temp_dir.exists():
            try:
                shutil.rmtree(temp_dir)
            except:
                pass
    
    return successful, failed


def main():
    parser = argparse.ArgumentParser(
        description='Migrate reports from private/user folders to Alianza_Reports folder'
    )
    parser.add_argument(
        'source_org',
        help='Source Salesforce org alias (e.g., AMSA-Royalty-Becky)'
    )
    parser.add_argument(
        '--target-folder',
        default='Alianza_Reports',
        help='Target folder name (default: Alianza_Reports)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Show what would be migrated without actually migrating'
    )
    
    args = parser.parse_args()
    
    try:
        successful, failed = migrate_reports(
            args.source_org,
            target_folder=args.target_folder,
            dry_run=args.dry_run
        )
        
        print(f"\n{'='*80}")
        print("MIGRATION SUMMARY")
        print(f"{'='*80}")
        print(f"✅ Successful: {len(successful)}")
        print(f"❌ Failed: {len(failed)}")
        
        if successful:
            print(f"\n✅ Successfully migrated reports:")
            for report in successful:
                print(f"  - {report}")
        
        if failed:
            print(f"\n❌ Failed reports:")
            for report in failed:
                print(f"  - {report}")
        
        if args.dry_run:
            print(f"\n⚠️  This was a DRY RUN. No files were actually migrated.")
            print(f"   Run without --dry-run to perform the actual migration.")
        
        print()
        
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
