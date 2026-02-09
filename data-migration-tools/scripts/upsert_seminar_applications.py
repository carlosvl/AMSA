#!/usr/bin/env python3
"""
Upsert Seminar_Application__c records from source org to target org.

This script:
1. Queries all Seminar_Application__c records from source org
2. Maps Applicant__c (Contact) and Seminar__c (Campaign) using existing mappings
3. Upserts records to target org using ExternalID__c field

Usage:
  python3 upsert_seminar_applications.py <source_org> <target_org>

Example:
  python3 upsert_seminar_applications.py "AMSA-Royalty-Prod" "AMSA Prod"
"""

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / 'data'
RESULTS_DIR = BASE_DIR / 'results'

CONTACT_MAPPING_PATH = DATA_DIR / 'contact_id_mapping.json'
CAMPAIGN_MAPPING_PATH = DATA_DIR / 'campaign_id_mapping.json'


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


def load_mappings():
    """Load Contact and Campaign ID mappings."""
    if not CONTACT_MAPPING_PATH.exists():
        print(f"❌ Contact mapping file not found: {CONTACT_MAPPING_PATH}")
        return None, None
    if not CAMPAIGN_MAPPING_PATH.exists():
        print(f"❌ Campaign mapping file not found: {CAMPAIGN_MAPPING_PATH}")
        return None, None

    contact_map = json.loads(CONTACT_MAPPING_PATH.read_text())
    campaign_map = json.loads(CAMPAIGN_MAPPING_PATH.read_text())

    print(f"📂 Loaded contact mapping:  {len(contact_map)} entries")
    print(f"📂 Loaded campaign mapping: {len(campaign_map)} entries")
    return contact_map, campaign_map


def query_all_applications(org_alias: str):
    """Query all Seminar_Application__c records from an org."""
    print(f"📥 Querying ALL Seminar_Application__c from {org_alias}...")

    # Query all relevant fields
    query = (
        "SELECT Id, Applicant__c, Seminar__c, Application_Stage__c, "
        "App_Date__c, Alianza_App_Date_II__c, Budgeted_Cost__c, "
        "Actual_Cost__c, Actual_Cost_MXP__c, Purchase_Date__c, "
        "Sponsor__c, Fellow_Contribution__c, Application_Number__c, "
        "Application_Notes__c, Rejection_Reason__c, Item_ID__c, "
        "CV__c, Diplomas__c, Flight__c, Flight_Commitment__c, "
        "Flight_Cost__c, Interview_date__c, Invitation_Letter__c, "
        "Invoice__c, CreatedDate, LastModifiedDate "
        "FROM Seminar_Application__c"
    )

    records = run_soql(org_alias, query)
    print(f"  ✅ Retrieved {len(records)} Seminar_Application__c records")
    return records


def prepare_upsert_records(source_records, contact_map, campaign_map):
    """Prepare records for upsert by mapping IDs and adding ExternalID__c."""
    upsert_records = []
    unmapped = []

    for rec in source_records:
        source_id = rec.get('Id')
        src_applicant = rec.get('Applicant__c')
        src_seminar = rec.get('Seminar__c')

        if not src_applicant:
            unmapped.append({
                'id': source_id,
                'reason': 'Missing Applicant__c'
            })
            continue

        # Map Applicant (Contact)
        if src_applicant not in contact_map:
            unmapped.append({
                'id': source_id,
                'applicant': src_applicant,
                'reason': 'Applicant not mapped'
            })
            continue

        tgt_applicant = contact_map[src_applicant]

        # Map Seminar (Campaign) if present
        tgt_seminar = None
        if src_seminar:
            if src_seminar not in campaign_map:
                unmapped.append({
                    'id': source_id,
                    'seminar': src_seminar,
                    'reason': 'Seminar not mapped'
                })
                continue
            tgt_seminar = campaign_map[src_seminar]

        # Build upsert record
        upsert_rec = {
            'ExternalID__c': source_id,  # Use source ID as external ID
            'Applicant__c': tgt_applicant,
        }

        # Add Seminar if present
        if tgt_seminar:
            upsert_rec['Seminar__c'] = tgt_seminar

        # Copy all other fields
        field_mappings = {
            'Application_Stage__c': 'Application_Stage__c',
            'App_Date__c': 'App_Date__c',
            'Alianza_App_Date_II__c': 'Alianza_App_Date_II__c',
            'Budgeted_Cost__c': 'Budgeted_Cost__c',
            'Actual_Cost__c': 'Actual_Cost__c',
            'Actual_Cost_MXP__c': 'Actual_Cost_MXP__c',
            'Purchase_Date__c': 'Purchase_Date__c',
            'Sponsor__c': 'Sponsor__c',
            'Fellow_Contribution__c': 'Fellow_Contribution__c',
            'Application_Number__c': 'Application_Number__c',
            'Application_Notes__c': 'Application_Notes__c',
            'Rejection_Reason__c': 'Rejection_Reason__c',
            'Item_ID__c': 'Item_ID__c',
            'CV__c': 'CV__c',
            'Diplomas__c': 'Diplomas__c',
            'Flight__c': 'Flight__c',
            'Flight_Commitment__c': 'Flight_Commitment__c',
            'Flight_Cost__c': 'Flight_Cost__c',
            'Interview_date__c': 'Interview_date__c',
            'Invitation_Letter__c': 'Invitation_Letter__c',
            'Invoice__c': 'Invoice__c',
        }

        for src_field, tgt_field in field_mappings.items():
            value = rec.get(src_field)
            if value is not None:
                upsert_rec[tgt_field] = value

        upsert_records.append(upsert_rec)

    return upsert_records, unmapped


def upsert_records_rest(target_org: str, records: List[Dict]):
    """Upsert records using REST API with composite key lookup (Applicant + Seminar)."""
    import urllib.request
    import urllib.error

    # Get org credentials
    result = subprocess.run(
        ['sf', 'org', 'display', '--target-org', target_org, '--json'],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise Exception(f"Failed to get org info: {result.stderr}")

    data = json.loads(result.stdout)
    info = data.get('result', {})
    access_token = info.get('accessToken')
    instance_url = info.get('instanceUrl')

    success = 0
    failed = 0
    created = 0
    updated = 0
    errors = []

    # First, query existing records to build a lookup map
    print("  📥 Querying existing records in target org...")
    existing_query = "SELECT Id, Applicant__c, Seminar__c FROM Seminar_Application__c"
    query_url = f"{instance_url}/services/data/v59.0/query/?q={urllib.parse.quote(existing_query)}"
    req = urllib.request.Request(query_url)
    req.add_header('Authorization', f'Bearer {access_token}')
    
    existing_map = {}  # key: "Applicant__c|Seminar__c" -> Id
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            query_data = json.loads(resp.read().decode('utf-8'))
            for rec in query_data.get('records', []):
                applicant = rec.get('Applicant__c', '')
                seminar = rec.get('Seminar__c', '') or 'NULL'
                key = f"{applicant}|{seminar}"
                existing_map[key] = rec.get('Id')
            # Handle pagination
            while query_data.get('nextRecordsUrl'):
                next_url = f"{instance_url}{query_data['nextRecordsUrl']}"
                req = urllib.request.Request(next_url)
                req.add_header('Authorization', f'Bearer {access_token}')
                with urllib.request.urlopen(req, timeout=60) as resp:
                    query_data = json.loads(resp.read().decode('utf-8'))
                    for rec in query_data.get('records', []):
                        applicant = rec.get('Applicant__c', '')
                        seminar = rec.get('Seminar__c', '') or 'NULL'
                        key = f"{applicant}|{seminar}"
                        existing_map[key] = rec.get('Id')
    except Exception as e:
        print(f"  ⚠️  Warning: Could not query existing records: {e}")
        print("  Proceeding with create-only approach...")
    
    print(f"  ✅ Found {len(existing_map)} existing records in target")

    # Now upsert each record
    for i, rec in enumerate(records, 1):
        external_id = rec.pop('ExternalID__c', None)  # Store for reference but don't use for upsert
        applicant = rec.get('Applicant__c')
        seminar = rec.get('Seminar__c', '') or 'NULL'
        key = f"{applicant}|{seminar}"
        
        existing_id = existing_map.get(key)
        
        if existing_id:
            # Update existing record
            url = f"{instance_url}/services/data/v59.0/sobjects/Seminar_Application__c/{existing_id}"
            method = 'PATCH'
        else:
            # Create new record
            url = f"{instance_url}/services/data/v59.0/sobjects/Seminar_Application__c"
            method = 'POST'

        req = urllib.request.Request(url, data=json.dumps(rec).encode('utf-8'), method=method)
        req.add_header('Authorization', f'Bearer {access_token}')
        req.add_header('Content-Type', 'application/json')
        req.add_header('Sforce-Auto-Assign', 'FALSE')

        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status in [200, 201, 204]:
                    success += 1
                    if existing_id:
                        updated += 1
                    else:
                        created += 1
                        # Add to map for future lookups in this batch
                        resp_data = json.loads(resp.read().decode('utf-8'))
                        new_id = resp_data.get('id')
                        if new_id:
                            existing_map[key] = new_id
                else:
                    failed += 1
                    errors.append({'external_id': external_id, 'key': key, 'status': resp.status, 'error': 'Unexpected status'})
        except urllib.error.HTTPError as e:
            failed += 1
            try:
                err_body = e.read().decode('utf-8')
                err_data = json.loads(err_body)
            except:
                err_data = [{'message': str(e)}]
            errors.append({'external_id': external_id, 'key': key, 'status': e.code, 'error': err_data})
        except Exception as e:
            failed += 1
            errors.append({'external_id': external_id, 'key': key, 'error': str(e)})

        if i % 25 == 0:
            print(f"  Progress: {i}/{len(records)} (success={success}, created={created}, updated={updated}, failed={failed})")
        if i % 100 == 0:
            time.sleep(1)  # Rate limiting
        elif i % 10 == 0:
            time.sleep(0.1)

    return {
        'success': success,
        'failed': failed,
        'created': created,
        'updated': updated,
        'errors': errors
    }


def upsert_records_bulk(target_org: str, records: List[Dict], batch_size: int = 200):
    """Upsert records using Salesforce Bulk API."""
    import csv
    import tempfile

    total_success = 0
    total_failed = 0
    all_errors = []

    for i in range(0, len(records), batch_size):
        batch = records[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(records) + batch_size - 1) // batch_size

        print(f"  Batch {batch_num}/{total_batches} ({len(batch)} records)...")

        # Create temporary CSV
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            if not batch:
                continue

            # Get all field names
            fieldnames = set()
            for rec in batch:
                fieldnames.update(rec.keys())
            fieldnames = sorted(fieldnames)

            writer = csv.DictWriter(f, fieldnames=fieldnames, lineterminator='\r\n')
            writer.writeheader()
            for rec in batch:
                writer.writerow(rec)
            temp_csv = f.name

        try:
            # Use sf data upsert bulk
            result = subprocess.run(
                [
                    'sf', 'data', 'upsert', 'bulk',
                    '--sobject', 'Seminar_Application__c',
                    '--file', temp_csv,
                    '--external-id', 'ExternalID__c',
                    '--target-org', target_org,
                    '--json',
                    '--wait', '30',
                ],
                capture_output=True,
                text=True,
                timeout=600,
            )

            # Parse response
            try:
                stdout_lines = result.stdout.strip().split('\n')
                json_start = None
                for j, line in enumerate(stdout_lines):
                    if line.strip().startswith('{'):
                        json_start = j
                        break

                if json_start is None:
                    raise ValueError("No JSON found in output")

                json_str = '\n'.join(stdout_lines[json_start:])
                data = json.loads(json_str)
            except Exception as e:
                print(f"    ❌ Failed to parse response: {e}")
                total_failed += len(batch)
                all_errors.append({'batch': batch_num, 'error': str(e)})
                continue

            # Check for errors
            if result.returncode != 0 or data.get('status') != 0:
                error_msg = data.get('message', 'Unknown error')
                print(f"    ❌ Batch error: {error_msg}")
                total_failed += len(batch)
                all_errors.append({'batch': batch_num, 'error': error_msg})
                continue

            # Parse job result
            job_info = data.get('result', {}).get('jobInfo', {})
            processed = job_info.get('numberRecordsProcessed', 0)
            failed = job_info.get('numberRecordsFailed', 0)
            success_count = processed - failed

            total_success += success_count
            total_failed += failed

            if failed > 0:
                records_result = data.get('result', {}).get('records', {})
                failed_results = records_result.get('failedResults', [])
                for fail in failed_results:
                    all_errors.append({
                        'batch': batch_num,
                        'id': fail.get('id', ''),
                        'error': fail.get('error', '')
                    })

            print(f"    ✅ Processed: {processed}, Success: {success_count}, Failed: {failed}")

        finally:
            Path(temp_csv).unlink(missing_ok=True)

        if batch_num < total_batches:
            time.sleep(2)  # Rate limiting

    return {
        'success': total_success,
        'failed': total_failed,
        'errors': all_errors
    }


def main():
    print("=" * 80)
    print("🔄 UPSERT SEMINAR APPLICATION RECORDS")
    print("=" * 80)
    print()

    if len(sys.argv) < 3:
        print("❌ Missing parameters!")
        print("\nUsage:")
        print("  python3 upsert_seminar_applications.py <source_org> <target_org>")
        sys.exit(1)

    source_org = sys.argv[1]
    target_org = sys.argv[2]

    print("📋 Parameters:")
    print(f"  Source Org: {source_org}")
    print(f"  Target Org: {target_org}")
    print()

    # Load mappings
    contact_map, campaign_map = load_mappings()
    if not contact_map or not campaign_map:
        sys.exit(1)
    print()

    # Query source records
    source_records = query_all_applications(source_org)
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
    print("  Using REST API method (bulk API has field indexing delay)...")
    result = upsert_records_rest(target_org, upsert_records)

    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    json_path = RESULTS_DIR / f'seminar_application_upsert_{timestamp}.json'
    json_path.write_text(
        json.dumps(
            {
                'metadata': {
                    'source_org': source_org,
                    'target_org': target_org,
                    'timestamp': timestamp,
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
    print(f"Success:                {result['success']}")
    print(f"  Created:              {result.get('created', 0)}")
    print(f"  Updated:              {result.get('updated', 0)}")
    print(f"Failed:                 {result['failed']}")
    print("=" * 80)
    print(f"\n📄 Results saved to: {json_path}")

    if unmapped:
        unmapped_path = RESULTS_DIR / f'seminar_application_unmapped_{timestamp}.json'
        unmapped_path.write_text(json.dumps(unmapped, indent=2))
        print(f"📄 Unmapped records saved to: {unmapped_path}")


if __name__ == '__main__':
    main()

