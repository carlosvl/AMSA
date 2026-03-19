#!/usr/bin/env python3
"""
Salesforce Duplicate Seminar Application Remover (SFDX Version)

This script identifies and removes duplicate Seminar_Application__c records
using SFDX authentication credentials.

Author: Generated for AMSA
Date: 2025-12-12
"""

import sys
import json
import csv
import logging
import subprocess
from datetime import datetime
from typing import List, Dict, Tuple
from collections import defaultdict

try:
    from simple_salesforce import Salesforce
except ImportError:
    print("ERROR: simple-salesforce library not found.")
    print("Please install it using: pip install simple-salesforce")
    sys.exit(1)


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'duplicate_removal_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class DuplicateRemover:
    """Handles identification and removal of duplicate Seminar Application records."""
    
    def __init__(self, sf: Salesforce):
        """
        Initialize the duplicate remover.
        
        Args:
            sf: Authenticated Salesforce connection
        """
        self.sf = sf
        self.all_records = []
        self.duplicate_groups = []
        self.records_to_delete = []
        self.records_to_keep = []
        
    def fetch_all_records(self) -> List[Dict]:
        """
        Query all Seminar_Application__c records from Salesforce.
        
        Returns:
            List of record dictionaries
        """
        logger.info("Fetching all Seminar_Application__c records...")
        
        query = """
            SELECT Id, Name, Applicant__c, Application_Stage__c, 
                   App_Date__c, LastModifiedDate
            FROM Seminar_Application__c
            ORDER BY Applicant__c, Application_Stage__c, App_Date__c
        """
        
        try:
            result = self.sf.query_all(query)
            self.all_records = result['records']
            logger.info(f"Successfully fetched {len(self.all_records)} records")
            return self.all_records
        except Exception as e:
            logger.error(f"Error fetching records: {str(e)}")
            raise
    
    def identify_duplicates(self) -> Tuple[List[List[Dict]], int]:
        """
        Identify duplicate records based on Applicant, Application Stage, and App. Date.
        
        Returns:
            Tuple of (duplicate_groups, total_duplicates_to_delete)
        """
        logger.info("Identifying duplicate records...")
        
        # Group records by the combination of key fields
        grouped = defaultdict(list)
        
        for record in self.all_records:
            # Create a key from the three fields
            # Handle None values by converting to string
            applicant = record.get('Applicant__c') or 'NULL'
            stage = record.get('Application_Stage__c') or 'NULL'
            app_date = record.get('App_Date__c') or 'NULL'
            
            key = (applicant, stage, app_date)
            grouped[key].append(record)
        
        # Find groups with duplicates (2+ records)
        self.duplicate_groups = []
        total_duplicates = 0
        
        for key, records in grouped.items():
            if len(records) > 1:
                # Sort by LastModifiedDate (most recent first)
                sorted_records = sorted(
                    records,
                    key=lambda x: x.get('LastModifiedDate', ''),
                    reverse=True
                )
                
                self.duplicate_groups.append(sorted_records)
                # All but the first (most recent) will be deleted
                total_duplicates += len(sorted_records) - 1
                
                # Track which to keep and which to delete
                self.records_to_keep.append(sorted_records[0])
                self.records_to_delete.extend(sorted_records[1:])
        
        logger.info(f"Found {len(self.duplicate_groups)} duplicate groups")
        logger.info(f"Total records to delete: {total_duplicates}")
        
        return self.duplicate_groups, total_duplicates
    
    def generate_report(self, filename: str = None) -> str:
        """
        Generate a CSV report of duplicates.
        
        Args:
            filename: Optional custom filename for the report
            
        Returns:
            Path to the generated report file
        """
        if filename is None:
            filename = f'duplicate_report_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        
        logger.info(f"Generating duplicate report: {filename}")
        
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            fieldnames = [
                'Group_Number',
                'Record_ID',
                'Record_Name',
                'Applicant_ID',
                'Application_Stage',
                'App_Date',
                'Last_Modified_Date',
                'Action'
            ]
            
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            
            for group_num, group in enumerate(self.duplicate_groups, 1):
                for idx, record in enumerate(group):
                    writer.writerow({
                        'Group_Number': group_num,
                        'Record_ID': record.get('Id', ''),
                        'Record_Name': record.get('Name', ''),
                        'Applicant_ID': record.get('Applicant__c', ''),
                        'Application_Stage': record.get('Application_Stage__c', ''),
                        'App_Date': record.get('App_Date__c', ''),
                        'Last_Modified_Date': record.get('LastModifiedDate', ''),
                        'Action': 'KEEP (Most Recent)' if idx == 0 else 'DELETE'
                    })
        
        logger.info(f"Report saved to: {filename}")
        return filename
    
    def delete_duplicates(self, dry_run: bool = True) -> Dict[str, int]:
        """
        Delete duplicate records from Salesforce.
        
        Args:
            dry_run: If True, only simulate deletion without actually deleting
            
        Returns:
            Dictionary with deletion statistics
        """
        stats = {
            'total_to_delete': len(self.records_to_delete),
            'successful': 0,
            'failed': 0,
            'errors': []
        }
        
        if dry_run:
            logger.info("DRY RUN MODE - No records will be deleted")
            logger.info(f"Would delete {stats['total_to_delete']} records")
            return stats
        
        logger.warning(f"DELETING {stats['total_to_delete']} duplicate records...")
        
        for record in self.records_to_delete:
            record_id = record.get('Id')
            record_name = record.get('Name', 'Unknown')
            
            try:
                self.sf.Seminar_Application__c.delete(record_id)
                stats['successful'] += 1
                logger.info(f"Deleted record {record_name} (ID: {record_id})")
            except Exception as e:
                stats['failed'] += 1
                error_msg = f"Failed to delete {record_name} (ID: {record_id}): {str(e)}"
                stats['errors'].append(error_msg)
                logger.error(error_msg)
        
        logger.info(f"Deletion complete: {stats['successful']} successful, {stats['failed']} failed")
        
        return stats
    
    def print_summary(self):
        """Print a summary of duplicates found."""
        print("\n" + "="*80)
        print("DUPLICATE DETECTION SUMMARY")
        print("="*80)
        print(f"Total records scanned: {len(self.all_records)}")
        print(f"Duplicate groups found: {len(self.duplicate_groups)}")
        print(f"Records to keep: {len(self.records_to_keep)}")
        print(f"Records to delete: {len(self.records_to_delete)}")
        print("="*80)
        
        if self.duplicate_groups:
            print("\nSample duplicate groups (first 5):")
            for idx, group in enumerate(self.duplicate_groups[:5], 1):
                print(f"\n  Group {idx}:")
                print(f"    Applicant: {group[0].get('Applicant__c', 'N/A')}")
                print(f"    Stage: {group[0].get('Application_Stage__c', 'N/A')}")
                print(f"    App Date: {group[0].get('App_Date__c', 'N/A')}")
                print(f"    Duplicate count: {len(group)}")
                for rec_idx, rec in enumerate(group):
                    action = "KEEP" if rec_idx == 0 else "DELETE"
                    print(f"      - {rec.get('Name')} (Modified: {rec.get('LastModifiedDate')}) [{action}]")
        print()


def get_sfdx_orgs() -> Dict:
    """
    Get list of authenticated SFDX orgs.
    
    Returns:
        Dictionary of org information from SFDX
    """
    try:
        result = subprocess.run(
            ['sf', 'org', 'list', '--json'],
            capture_output=True,
            text=True,
            check=True
        )
        return json.loads(result.stdout)
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to get SFDX orgs: {e}")
        raise
    except FileNotFoundError:
        logger.error("SFDX CLI not found. Please install Salesforce CLI.")
        raise


def connect_with_sfdx(org_alias: str = None) -> Salesforce:
    """
    Connect to Salesforce using SFDX credentials.
    
    Args:
        org_alias: Org alias or username. If None, uses default org.
        
    Returns:
        Authenticated Salesforce connection
    """
    logger.info(f"Connecting to Salesforce using SFDX (org: {org_alias or 'default'})...")
    
    # Get org information from SFDX
    orgs_data = get_sfdx_orgs()
    
    # Combine all orgs
    all_orgs = orgs_data['result'].get('nonScratchOrgs', [])
    
    # Find the target org
    target_org = None
    if org_alias:
        for org in all_orgs:
            if org.get('alias') == org_alias or org.get('username') == org_alias:
                target_org = org
                break
        if not target_org:
            raise ValueError(f"Org '{org_alias}' not found in authenticated orgs")
    else:
        # Use default org
        for org in all_orgs:
            if org.get('isDefaultUsername'):
                target_org = org
                break
        if not target_org and all_orgs:
            target_org = all_orgs[0]  # Use first org if no default
    
    if not target_org:
        raise ValueError("No authenticated orgs found. Please run 'sf org login web'")
    
    # Check connection status
    if target_org.get('connectedStatus') != 'Connected':
        logger.warning(f"Org connection status: {target_org.get('connectedStatus')}")
        raise ValueError(f"Org is not connected. Please re-authenticate: sf org login web --alias {target_org.get('alias')}")
    
    logger.info(f"Using org: {target_org.get('alias')} ({target_org.get('username')})")
    logger.info(f"Instance URL: {target_org.get('instanceUrl')}")
    
    # Create Salesforce connection using access token
    sf = Salesforce(
        instance_url=target_org['instanceUrl'],
        session_id=target_org['accessToken'],
        version='65.0'
    )
    
    logger.info("Successfully connected to Salesforce via SFDX")
    return sf


def list_available_orgs():
    """List all available SFDX orgs."""
    try:
        orgs_data = get_sfdx_orgs()
        all_orgs = orgs_data['result'].get('nonScratchOrgs', [])
        
        print("\n" + "="*80)
        print("AVAILABLE SALESFORCE ORGS")
        print("="*80)
        
        if not all_orgs:
            print("No authenticated orgs found.")
            print("\nTo authenticate, run: sf org login web")
            return
        
        for org in all_orgs:
            alias = org.get('alias', 'No alias')
            username = org.get('username', 'Unknown')
            status = org.get('connectedStatus', 'Unknown')
            is_default = ' (DEFAULT)' if org.get('isDefaultUsername') else ''
            is_sandbox = ' [Sandbox]' if org.get('isSandbox') else ' [Production]'
            
            print(f"\nAlias: {alias}{is_default}")
            print(f"  Username: {username}")
            print(f"  Status: {status}")
            print(f"  Type: {is_sandbox}")
            print(f"  Instance: {org.get('instanceUrl', 'Unknown')}")
        
        print("\n" + "="*80 + "\n")
        
    except Exception as e:
        logger.error(f"Error listing orgs: {e}")
        sys.exit(1)


def main():
    """Main execution function."""
    print("\n" + "="*80)
    print("SALESFORCE DUPLICATE SEMINAR APPLICATION REMOVER (SFDX)")
    print("="*80 + "\n")
    
    # Parse command line arguments
    dry_run = True
    org_alias = None
    
    if '--list-orgs' in sys.argv:
        list_available_orgs()
        return
    
    if '--execute' in sys.argv:
        dry_run = False
        logger.warning("EXECUTE MODE ENABLED - Records will be deleted!")
    
    if '--org' in sys.argv:
        try:
            org_idx = sys.argv.index('--org')
            org_alias = sys.argv[org_idx + 1]
        except (ValueError, IndexError):
            logger.error("--org flag requires an org alias or username")
            sys.exit(1)
    
    if '--help' in sys.argv or '-h' in sys.argv:
        print("Usage: python remove_duplicate_seminar_applications_sfdx.py [OPTIONS]")
        print("\nOptions:")
        print("  --list-orgs          List all available SFDX authenticated orgs")
        print("  --org <alias>        Use specific org (alias or username)")
        print("  --execute            Execute deletion (dry-run by default)")
        print("  --help, -h           Show this help message")
        print("\nExamples:")
        print("  python remove_duplicate_seminar_applications_sfdx.py --list-orgs")
        print("  python remove_duplicate_seminar_applications_sfdx.py --org 'AMSA Prod'")
        print("  python remove_duplicate_seminar_applications_sfdx.py --org 'AMSA Prod' --execute")
        return
    
    try:
        # Connect to Salesforce using SFDX
        sf = connect_with_sfdx(org_alias)
        
        # Initialize remover and process
        remover = DuplicateRemover(sf)
        
        # Step 1: Fetch all records
        remover.fetch_all_records()
        
        # Step 2: Identify duplicates
        duplicate_groups, total_to_delete = remover.identify_duplicates()
        
        if total_to_delete == 0:
            print("\n✓ No duplicates found! All records are unique.")
            return
        
        # Step 3: Print summary
        remover.print_summary()
        
        # Step 4: Generate CSV report
        report_file = remover.generate_report()
        print(f"\n✓ Duplicate report saved to: {report_file}")
        
        # Step 5: Delete duplicates (if not dry run)
        if dry_run:
            print("\n" + "="*80)
            print("DRY RUN MODE - No records were deleted")
            print("="*80)
            print("\nTo actually delete the duplicate records, run:")
            if org_alias:
                print(f"  python remove_duplicate_seminar_applications_sfdx.py --org '{org_alias}' --execute")
            else:
                print("  python remove_duplicate_seminar_applications_sfdx.py --execute")
            print("\nWARNING: This action cannot be undone. Review the report first!")
        else:
            print("\n" + "="*80)
            print("WARNING: You are about to delete duplicate records!")
            print("="*80)
            print(f"\nRecords to delete: {total_to_delete}")
            print("\nThis action CANNOT be undone!")
            
            response = input("\nType 'DELETE' to confirm: ")
            
            if response == 'DELETE':
                stats = remover.delete_duplicates(dry_run=False)
                print("\n" + "="*80)
                print("DELETION COMPLETE")
                print("="*80)
                print(f"Successfully deleted: {stats['successful']}")
                print(f"Failed: {stats['failed']}")
                
                if stats['errors']:
                    print("\nErrors:")
                    for error in stats['errors']:
                        print(f"  - {error}")
            else:
                print("\nDeletion cancelled.")
    
    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")
        sys.exit(1)
    
    print("\n✓ Process completed successfully!\n")


if __name__ == '__main__':
    main()



