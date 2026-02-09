#!/usr/bin/env python3
"""
Upsert Mexico_Seminars__c records from source org to target org.

This script:
1. Queries all Mexico_Seminars__c records from source org
2. Maps Applicant__c (Contact) and Symposium__c (Campaign) using existing mappings
3. Upserts records to target org using ExternalID__c field

Mexico_Seminars__c has a Master-Detail relationship to Contact (Applicant__c)
and a Lookup to Campaign (Symposium__c).

Usage:
  python3 upsert_mexico_seminars.py <source_org> <target_org> [--dry-run]

Example:
  python3 upsert_mexico_seminars.py "AMSA-Royalty-Prod" "AMSA Prod"
"""

import json
import subprocess
import sys
import time
import argparse
from datetime import datetime
from pathlib import Path
from typing import List, Dict
import urllib.request
import urllib.error
import urllib.parse

import db_utils

BASE_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = BASE_DIR / 'results'


def run_soql(org_alias: str, query: str):
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


def get_org_credentials(org_alias: str):
    """Get access token and instance URL from sf org display."""
    try:
        result = subprocess.run(
            ['sf', 'org', 'display', '--target-org', org_alias, '--json'],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"❌ Failed to get org info for {org_alias}:")
            print(result.stderr.strip())
            return None, None

        data = json.loads(result.stdout)
        info = data.get('result', {})
        return info.get('accessToken'), info.get('instanceUrl')
    except Exception as e:
        print(f"❌ Error getting org credentials for {org_alias}: {e}")
        return None, None


def load_mappings():
    """Load Contact and Campaign ID mappings from database."""
    print("📂 Loading ID mappings from database...")
    
    contact_map = db_utils.get_id_mappings('Contact')
    campaign_map = db_utils.get_id_mappings('Campaign')
    
    print(f"  ✅ Contact mappings:  {len(contact_map)} entries")
    print(f"  ✅ Campaign mappings: {len(campaign_map)} entries")
    
    return contact_map, campaign_map


def query_source_records(org_alias: str):
    """Query all Mexico_Seminars__c records from source org."""
    print(f"📥 Querying ALL Mexico_Seminars__c from {org_alias}...")

    query = """
        SELECT Id, Name, Applicant__c, Symposium__c, Application_Stage__c, 
               Application_Number__c, Application_Notes__c, App_Date__c,
               OMI_App_Date_I__c, Budgeted_Cost__c, Actual_Cost__c, Actual_Cost_MXP__c,
               Purchase_Date__c, EI__c, SI__c, Flight__c, Flight_Cost__c,
               Rejection_Reason__c, Participation_Result__c, Item_ID__c,
               CreatedDate, LastModifiedDate
        FROM Mexico_Seminars__c
    """

    records = run_soql(org_alias, query)
    print(f"  ✅ Retrieved {len(records)} Mexico_Seminars__c records")
    return records


def prepare_upsert_records(source_records: List[Dict], contact_map: Dict, campaign_map: Dict):
    """Prepare records for upsert by mapping IDs and adding ExternalID__c."""
    upsert_records = []
    unmapped = []

    for rec in source_records:
        source_id = rec.get('Id')
        src_applicant = rec.get('Applicant__c')
        src_symposium = rec.get('Symposium__c')

        if not src_applicant:
            unmapped.append({
                'id': source_id,
                'reason': 'Missing Applicant__c'
            })
            continue

        # Map Applicant (Contact) - required for Master-Detail
        if src_applicant not in contact_map:
            unmapped.append({
                'id': source_id,
                'applicant': src_applicant,
                'reason': 'Applicant not mapped'
            })
            continue

        tgt_applicant = contact_map[src_applicant]

        # Map Symposium (Campaign) if present
        tgt_symposium = None
        if src_symposium:
            if src_symposium not in campaign_map:
                unmapped.append({
                    'id': source_id,
                    'symposium': src_symposium,
                    'reason': 'Symposium not mapped'
                })
                continue
            tgt_symposium = campaign_map[src_symposium]

        # Build upsert record
        upsert_rec = {
            'ExternalID__c': source_id,
            'Applicant__c': tgt_applicant,
        }

        # Add Symposium__c if present
        if tgt_symposium:
            upsert_rec['Symposium__c'] = tgt_symposium

        # Copy all other fields
        field_mappings = {
            'Application_Stage__c': 'Application_Stage__c',
            'Application_Number__c': 'Application_Number__c',
            'Application_Notes__c': 'Application_Notes__c',
            'App_Date__c': 'App_Date__c',
            'OMI_App_Date_I__c': 'OMI_App_Date_I__c',
            'Budgeted_Cost__c': 'Budgeted_Cost__c',
            'Actual_Cost__c': 'Actual_Cost__c',
            'Actual_Cost_MXP__c': 'Actual_Cost_MXP__c',
            'Purchase_Date__c': 'Purchase_Date__c',
            'EI__c': 'EI__c',
            'SI__c': 'SI__c',
            'Flight__c': 'Flight__c',
            'Flight_Cost__c': 'Flight_Cost__c',
            'Rejection_Reason__c': 'Rejection_Reason__c',
            'Participation_Result__c': 'Participation_Result__c',
            'Item_ID__c': 'Item_ID__c',
        }

        for src_field, tgt_field in field_mappings.items():
            value = rec.get(src_field)
            if value is not None:
                upsert_rec[tgt_field] = value

        upsert_records.append(upsert_rec)

    return upsert_records, unmapped


def upsert_records_rest(target_org: str, records: List[Dict], dry_run: bool = False):
    """Upsert records using REST API with ExternalID__c."""
    
    if dry_run:
        print("  🔍 DRY RUN - No records will be created/updated")
        return {
            'success': len(records),
            'failed': 0,
            'created': 0,
            'updated': 0,
            'errors': [],
            'dry_run': True
        }

    # Get org credentials
    access_token, instance_url = get_org_credentials(target_org)
    if not access_token:
        raise Exception("Failed to get org credentials")

    success = 0
    failed = 0
    created = 0
    updated = 0
    errors = []

    print(f"  🔄 Upserting {len(records)} records...")

    for i, rec in enumerate(records, 1):
        external_id = rec.get('ExternalID__c')
        
        # Use PATCH to upsert endpoint
        url = f"{instance_url}/services/data/v59.0/sobjects/Mexico_Seminars__c/ExternalID__c/{external_id}"
        
        # Remove ExternalID__c from payload (it's in the URL)
        payload = {k: v for k, v in rec.items() if k != 'ExternalID__c'}
        
        data_bytes = json.dumps(payload).encode('utf-8')

        req = urllib.request.Request(url, data=data_bytes, method='PATCH')
        req.add_header('Authorization', f'Bearer {access_token}')
        req.add_header('Content-Type', 'application/json')

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status == 201:
                    success += 1
                    created += 1
                elif resp.status == 204:
                    success += 1
                    updated += 1
                else:
                    success += 1
                    updated += 1
                    
        except urllib.error.HTTPError as e:
            if e.code == 201:
                success += 1
                created += 1
            else:
                failed += 1
                try:
                    err_body = e.read().decode('utf-8')
                    err_data = json.loads(err_body)
                except:
                    err_data = [{'message': str(e)}]
                errors.append({
                    'external_id': external_id,
                    'status': e.code,
                    'error': err_data
                })
        except Exception as e:
            failed += 1
            errors.append({
                'external_id': external_id,
                'error': str(e)
            })

        if i % 25 == 0:
            print(f"  Progress: {i}/{len(records)} (success={success}, created={created}, updated={updated}, failed={failed})")
        
        # Rate limiting
        if i % 100 == 0:
            time.sleep(1)
        elif i % 10 == 0:
            time.sleep(0.1)

    return {
        'success': success,
        'failed': failed,
        'created': created,
        'updated': updated,
        'errors': errors
    }


def main():
    print("=" * 80)
    print("🇲🇽 UPSERT MEXICO SEMINARS (SATELLITE SYMPOSIUM) RECORDS")
    print("=" * 80)
    print()

    parser = argparse.ArgumentParser(
        description='Upsert Mexico_Seminars__c records from source to target org'
    )
    parser.add_argument('source_org', help='Source org alias')
    parser.add_argument('target_org', help='Target org alias')
    parser.add_argument('--dry-run', action='store_true',
                        help='Simulate upsert without making changes')
    
    args = parser.parse_args()

    source_org = args.source_org
    target_org = args.target_org
    dry_run = args.dry_run

    print("📋 Parameters:")
    print(f"  Source Org: {source_org}")
    print(f"  Target Org: {target_org}")
    if dry_run:
        print(f"  Mode: DRY RUN (no changes will be made)")
    print()

    # Load mappings
    contact_map, campaign_map = load_mappings()
    if not contact_map:
        print("❌ No Contact mappings found in database")
        print("   Run compare_contacts.py first!")
        sys.exit(1)
    print()

    # Query source records
    source_records = query_source_records(source_org)
    if not source_records:
        print("❌ No records found in source org")
        sys.exit(1)
    print()

    # Prepare upsert records
    print("🔄 Preparing records for upsert...")
    upsert_records, unmapped = prepare_upsert_records(source_records, contact_map, campaign_map)
    print(f"  ✅ Prepared {len(upsert_records)} records for upsert")
    if unmapped:
        print(f"  ⚠️  {len(unmapped)} records skipped (unmapped)")
    print()

    if not upsert_records:
        print("❌ No records to upsert!")
        sys.exit(0)

    # Upsert records
    print(f"🔄 Upserting {len(upsert_records)} records to {target_org}...")
    result = upsert_records_rest(target_org, upsert_records, dry_run)

    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    json_path = RESULTS_DIR / f'mexico_seminars_upsert_{timestamp}.json'
    json_path.write_text(
        json.dumps(
            {
                'metadata': {
                    'source_org': source_org,
                    'target_org': target_org,
                    'timestamp': timestamp,
                    'dry_run': dry_run
                },
                'summary': {
                    'total_source_records': len(source_records),
                    'prepared_for_upsert': len(upsert_records),
                    'unmapped': len(unmapped),
                    'success': result['success'],
                    'failed': result['failed'],
                    'created': result.get('created', 0),
                    'updated': result.get('updated', 0),
                },
                'unmapped_records': unmapped,
                'errors': result['errors'],
            },
            indent=2,
        )
    )

    print()
    print("=" * 80)
    print("📊 UPSERT SUMMARY")
    print("=" * 80)
    print(f"Total source records:  {len(source_records)}")
    print(f"Prepared for upsert:   {len(upsert_records)}")
    print(f"Unmapped (skipped):    {len(unmapped)}")
    print(f"Success:               {result['success']}")
    print(f"  Created:             {result.get('created', 0)}")
    print(f"  Updated:             {result.get('updated', 0)}")
    print(f"Failed:                {result['failed']}")
    if dry_run:
        print(f"\n⚠️  DRY RUN - No changes were made")
    print("=" * 80)
    print(f"\n📄 Results saved to: {json_path}")

    if unmapped:
        unmapped_path = RESULTS_DIR / f'mexico_seminars_unmapped_{timestamp}.json'
        unmapped_path.write_text(json.dumps(unmapped, indent=2))
        print(f"📄 Unmapped records saved to: {unmapped_path}")


if __name__ == '__main__':
    main()
