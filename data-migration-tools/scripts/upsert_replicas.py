#!/usr/bin/env python3
"""
Upsert Replica__c records from source org to target org.

This script:
1. Queries all Replica__c records from source org
2. Maps Replica__c (Contact lookup field) using existing mappings
3. Upserts records to target org using ExternalID__c field

Replica__c has a Lookup relationship to Contact via the Replica__c field.

Usage:
  python3 upsert_replicas.py <source_org> <target_org> [--dry-run]

Example:
  python3 upsert_replicas.py "AMSA-Royalty-Prod" "AMSA Prod"
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
    """Load Contact ID mappings from database."""
    print("📂 Loading ID mappings from database...")
    
    contact_map = db_utils.get_id_mappings('Contact')
    
    print(f"  ✅ Contact mappings:  {len(contact_map)} entries")
    
    return contact_map


def query_source_replicas(org_alias: str):
    """Query all Replica__c records from source org."""
    print(f"📥 Querying ALL Replica__c from {org_alias}...")

    query = """
        SELECT Id, Name, Replica__c, Date__c, End_date__c, 
               Place__c, Type_of_replica__c, Nu__c, Other__c,
               CreatedDate, LastModifiedDate
        FROM Replica__c
    """

    records = run_soql(org_alias, query)
    print(f"  ✅ Retrieved {len(records)} Replica__c records")
    return records


def prepare_upsert_records(source_records: List[Dict], contact_map: Dict):
    """Prepare records for upsert by mapping IDs and adding ExternalID__c."""
    upsert_records = []
    unmapped = []

    for rec in source_records:
        source_id = rec.get('Id')
        src_contact = rec.get('Replica__c')  # This is the Contact lookup field

        if not src_contact:
            unmapped.append({
                'id': source_id,
                'reason': 'Missing Replica__c (Contact)'
            })
            continue

        # Map Contact
        if src_contact not in contact_map:
            unmapped.append({
                'id': source_id,
                'contact': src_contact,
                'reason': 'Contact not mapped'
            })
            continue

        tgt_contact = contact_map[src_contact]

        # Build upsert record
        upsert_rec = {
            'ExternalID__c': source_id,
            'Replica__c': tgt_contact,  # Contact lookup field
        }

        # Copy all other fields
        field_mappings = {
            'Date__c': 'Date__c',
            'End_date__c': 'End_date__c',
            'Place__c': 'Place__c',
            'Type_of_replica__c': 'Type_of_replica__c',
            'Nu__c': 'Nu__c',
            'Other__c': 'Other__c',
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
        url = f"{instance_url}/services/data/v59.0/sobjects/Replica__c/ExternalID__c/{external_id}"
        
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
    print("🔄 UPSERT REPLICA RECORDS")
    print("=" * 80)
    print()

    parser = argparse.ArgumentParser(
        description='Upsert Replica__c records from source to target org'
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
    contact_map = load_mappings()
    if not contact_map:
        print("❌ No Contact mappings found in database")
        print("   Run compare_contacts.py first!")
        sys.exit(1)
    print()

    # Query source records
    source_records = query_source_replicas(source_org)
    if not source_records:
        print("❌ No records found in source org")
        sys.exit(1)
    print()

    # Prepare upsert records
    print("🔄 Preparing records for upsert...")
    upsert_records, unmapped = prepare_upsert_records(source_records, contact_map)
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
    json_path = RESULTS_DIR / f'replica_upsert_{timestamp}.json'
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
        unmapped_path = RESULTS_DIR / f'replica_unmapped_{timestamp}.json'
        unmapped_path.write_text(json.dumps(unmapped, indent=2))
        print(f"📄 Unmapped records saved to: {unmapped_path}")


if __name__ == '__main__':
    main()
