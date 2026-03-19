#!/usr/bin/env python3
"""
Data Cleanup Menu – Interactive Launcher

Provides a single entry point for all duplicate detection and ghost record
cleanup operations.  Sets the target org once and dispatches to worker scripts.
After each detection run a sub-menu lets you generate a shareable Markdown
report (.md) and / or execute the cleanup.

Usage:
  python3 cleanup_menu.py                                    # fully interactive
  python3 cleanup_menu.py "AMSA Prod"                        # interactive, org pre-selected
  python3 cleanup_menu.py "AMSA Prod" --action 2             # detect, then sub-menu
  python3 cleanup_menu.py "AMSA Prod" --action 2 --report    # detect + generate .md
  python3 cleanup_menu.py "AMSA Prod" --action 2 --execute   # detect + execute cleanup
  python3 cleanup_menu.py "AMSA Prod" --action 6             # run all detection (dry-run)

Actions:
  1  Detect duplicate Observership__c records
  2  Detect duplicate Mexico_Seminars__c records
  3  Detect ghost Observership__c records
  4  Detect ghost Mexico_Seminars__c records
  5  Detect duplicate Contact records (SOAP merge)
  6  Run ALL detection (duplicates + ghosts, dry-run)
"""
import argparse
import csv
import json
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS_DIR))
import db_utils

BASE_DIR = SCRIPTS_DIR.parent
RESULTS_DIR = BASE_DIR / 'results'
RESULTS_DIR.mkdir(exist_ok=True)
REPORTS_DIR = RESULTS_DIR / 'reports'
REPORTS_DIR.mkdir(exist_ok=True)
BACKUP_DIR = RESULTS_DIR / 'backups'
BACKUP_DIR.mkdir(exist_ok=True)

# ─── Field definitions (mirrors worker scripts) ─────────────────────────────

OBS_ALL_FIELDS = [
    'Id', 'Name', 'Applicant__c', 'Application_Stage__c', 'Application_Number__c',
    'Application_Notes__c', 'OMI_App_Date_I__c', 'Alianza_App_Date_II__c',
    'Budgeted_Cost__c', 'Actual_Cost__c', 'Actual_Cost_MXP__c',
    'EI__c', 'SI__c', 'Flight__c', 'Flight_Cost__c',
    'Rejection_Reason__c', 'Item_ID__c', 'Purchase_Date__c',
    'CreatedDate', 'LastModifiedDate',
]
OBS_DATA_FIELDS = [
    'Application_Stage__c', 'Application_Number__c', 'Application_Notes__c',
    'OMI_App_Date_I__c', 'Alianza_App_Date_II__c',
    'Budgeted_Cost__c', 'Actual_Cost__c', 'Actual_Cost_MXP__c',
    'EI__c', 'SI__c', 'Flight__c', 'Flight_Cost__c',
    'Rejection_Reason__c', 'Item_ID__c', 'Purchase_Date__c',
]

MEX_ALL_FIELDS = [
    'Id', 'Name', 'Applicant__c', 'Symposium__c', 'Application_Stage__c',
    'Application_Number__c', 'Application_Notes__c', 'App_Date__c',
    'OMI_App_Date_I__c', 'Budgeted_Cost__c', 'Actual_Cost__c', 'Actual_Cost_MXP__c',
    'EI__c', 'SI__c', 'Flight__c', 'Flight_Cost__c',
    'Rejection_Reason__c', 'Participation_Result__c', 'Item_ID__c', 'Purchase_Date__c',
    'CreatedDate', 'LastModifiedDate',
]
MEX_DATA_FIELDS = [
    'Symposium__c', 'Application_Stage__c', 'Application_Number__c',
    'Application_Notes__c', 'App_Date__c', 'OMI_App_Date_I__c',
    'Budgeted_Cost__c', 'Actual_Cost__c', 'Actual_Cost_MXP__c',
    'EI__c', 'SI__c', 'Flight__c', 'Flight_Cost__c',
    'Rejection_Reason__c', 'Participation_Result__c', 'Item_ID__c', 'Purchase_Date__c',
]

CONTACT_ALL_FIELDS = [
    'Id', 'FirstName', 'LastName', 'Email', 'Phone', 'AccountId',
    'CreatedDate', 'LastModifiedDate', 'OwnerId',
]

# ─── Action configuration ───────────────────────────────────────────────────

ACTIONS = {
    '1': {
        'label': 'Detect duplicate Observership__c records',
        'short': 'Observership__c duplicates',
        'object_type': 'Observership__c',
        'kind': 'duplicate',
        'script': 'detect_observership_duplicates.py',
        'key_desc': 'Applicant__c + Application_Number__c (fallback OMI_App_Date_I__c)',
        'all_fields': OBS_ALL_FIELDS,
        'data_fields': OBS_DATA_FIELDS,
        'build_args': lambda org, execute: [org, '--no-prompt'],
    },
    '2': {
        'label': 'Detect duplicate Mexico_Seminars__c records',
        'short': 'Mexico_Seminars__c duplicates',
        'object_type': 'Mexico_Seminars__c',
        'kind': 'duplicate',
        'script': 'detect_mexico_seminar_duplicates.py',
        'key_desc': 'Applicant__c + Symposium__c',
        'all_fields': MEX_ALL_FIELDS,
        'data_fields': MEX_DATA_FIELDS,
        'build_args': lambda org, execute: [org, '--no-prompt'],
    },
    '3': {
        'label': 'Detect ghost Observership__c records',
        'short': 'Ghost Observership__c',
        'object_type': 'Observership__c',
        'kind': 'ghost',
        'script': 'delete_ghost_observerships.py',
        'ghost_labels': {
            'A': 'Missing key lookups (NULL Application_Number AND OMI_App_Date)',
            'B': 'Fully empty ghosts (all data fields NULL)',
        },
        'all_fields': OBS_ALL_FIELDS,
        'data_fields': OBS_DATA_FIELDS,
        'backup_glob': 'backup_observerships_*.json',
        'build_args': lambda org, execute: [org] + (['--execute'] if execute else []),
    },
    '4': {
        'label': 'Detect ghost Mexico_Seminars__c records',
        'short': 'Ghost Mexico_Seminars__c',
        'object_type': 'Mexico_Seminars__c',
        'kind': 'ghost',
        'script': 'delete_ghost_mexico_seminars.py',
        'ghost_labels': {
            'A': 'Missing key lookup (NULL Symposium)',
            'B': 'Fully empty ghosts (all data fields NULL)',
        },
        'all_fields': MEX_ALL_FIELDS,
        'data_fields': MEX_DATA_FIELDS,
        'backup_glob': 'backup_mexico_seminars_*.json',
        'build_args': lambda org, execute: [org] + (['--execute'] if execute else []),
    },
    '5': {
        'label': 'Detect duplicate Contact records',
        'short': 'Contact duplicates',
        'object_type': 'Contact',
        'kind': 'duplicate',
        'merge_mode': 'soap_merge',
        'script': 'detect_contact_duplicates.py',
        'key_desc': 'Full Name (FirstName + LastName) + Email',
        'all_fields': CONTACT_ALL_FIELDS,
        'data_fields': [],
        'build_args': lambda org, execute: [org, '--no-prompt'],
    },
}


# ─── Salesforce helpers ─────────────────────────────────────────────────────

def run_soql(org_alias, query):
    """Run a SOQL query and return a list of record dicts."""
    result = subprocess.run(
        ['sf', 'data', 'query', '--query', query,
         '--target-org', org_alias, '--json'],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        return []
    try:
        return json.loads(result.stdout).get('result', {}).get('records', [])
    except Exception:
        return []


def query_record_count(org_alias, object_type):
    """Return current record count for an object type, or None on error."""
    result = subprocess.run(
        ['sf', 'data', 'query',
         '--query', f'SELECT COUNT() FROM {object_type}',
         '--target-org', org_alias, '--json'],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout).get('result', {}).get('totalSize', 0)
    except Exception:
        return None


def query_records_by_ids(org_alias, object_type, record_ids, fields):
    """Fetch full record data for a list of IDs (batched for SOQL limits)."""
    all_records = []
    for i in range(0, len(record_ids), 400):
        chunk = record_ids[i:i + 400]
        id_list = "', '".join(chunk)
        query = f"SELECT {', '.join(fields)} FROM {object_type} WHERE Id IN ('{id_list}')"
        all_records.extend(run_soql(org_alias, query))
    return all_records


# ─── Org management ─────────────────────────────────────────────────────────

def list_orgs():
    """Fetch authenticated Salesforce orgs via CLI."""
    try:
        result = subprocess.run(
            ['sf', 'org', 'list', '--json'],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        return data.get('result', {}).get('nonScratchOrgs', [])
    except Exception as e:
        print(f"❌ Failed to list orgs: {e}")
        return []


def display_orgs(orgs):
    """Display numbered list of orgs for selection."""
    print("\n" + "=" * 70)
    print("  AUTHENTICATED SALESFORCE ORGS")
    print("=" * 70)
    if not orgs:
        print("  No authenticated orgs found. Run: sf org login web")
        return
    for idx, org in enumerate(orgs, 1):
        alias = org.get('alias', 'No alias')
        username = org.get('username', '')
        status = org.get('connectedStatus', 'Unknown')
        org_type = '[Sandbox]' if org.get('isSandbox') else '[Production]'
        default_tag = ' (DEFAULT)' if org.get('isDefaultUsername') else ''
        print(f"  {idx}. {alias}{default_tag}  {org_type}")
        print(f"     {username}  [{status}]")
    print("=" * 70)


def select_org_interactive(orgs):
    """Prompt user to pick an org by number or alias."""
    while True:
        choice = input("\nEnter org number or alias (q to quit): ").strip()
        if choice.lower() == 'q':
            sys.exit(0)
        try:
            idx = int(choice)
            if 1 <= idx <= len(orgs):
                org = orgs[idx - 1]
                alias = org.get('alias') or org.get('username')
                if org.get('connectedStatus') != 'Connected':
                    print(f"  ⚠️  Org '{alias}' is not connected. Run: sf org login web --alias {alias}")
                    continue
                return alias
        except ValueError:
            pass
        for org in orgs:
            if org.get('alias') == choice or org.get('username') == choice:
                if org.get('connectedStatus') != 'Connected':
                    print(f"  ⚠️  Org '{choice}' is not connected.")
                    continue
                return choice
        print(f"  ❌ '{choice}' not found. Try again.")


def validate_org(org_alias):
    """Quick validation that the org is reachable."""
    try:
        result = subprocess.run(
            ['sf', 'org', 'display', '--target-org', org_alias, '--json'],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return False
        data = json.loads(result.stdout)
        username = data.get('result', {}).get('username', '')
        instance = data.get('result', {}).get('instanceUrl', '')
        print(f"  ✅ Connected: {username} ({instance})")
        return True
    except Exception:
        return False


# ─── Backup & bulk delete (for duplicate cleanup) ───────────────────────────

def save_duplicate_backup(records, object_type, all_fields, timestamp):
    """Save a full backup of duplicate records before deletion (JSON + CSV)."""
    slug = object_type.lower().replace('__c', '')
    json_path = BACKUP_DIR / f'backup_{slug}_duplicates_{timestamp}.json'
    json_path.write_text(json.dumps({
        'backup_type': 'pre_deletion_backup',
        'object': object_type,
        'timestamp': timestamp,
        'record_count': len(records),
        'records': records,
    }, indent=2, default=str))

    csv_path = BACKUP_DIR / f'backup_{slug}_duplicates_{timestamp}.csv'
    with open(csv_path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=all_fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(records)

    print(f"  💾 JSON backup: {json_path}")
    print(f"  💾 CSV backup:  {csv_path}")
    return json_path


def delete_records_bulk(org_alias, object_type, record_ids, batch_size=200):
    """Delete records using Salesforce Bulk API (LF line endings)."""
    total_success = 0
    total_failed = 0
    all_errors = []

    for i in range(0, len(record_ids), batch_size):
        batch = record_ids[i:i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(record_ids) + batch_size - 1) // batch_size
        print(f"    Batch {batch_num}/{total_batches} ({len(batch)} records)...")

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            writer = csv.writer(f, lineterminator='\n')
            writer.writerow(['Id'])
            for rid in batch:
                writer.writerow([rid])
            temp_csv = f.name

        try:
            result = subprocess.run(
                ['sf', 'data', 'delete', 'bulk',
                 '--sobject', object_type,
                 '--file', temp_csv,
                 '--target-org', org_alias,
                 '--json', '--wait', '30'],
                capture_output=True, text=True, timeout=600,
            )
            try:
                stdout_lines = result.stdout.strip().split('\n')
                json_start = next(
                    (j for j, l in enumerate(stdout_lines) if l.strip().startswith('{')), None,
                )
                if json_start is None:
                    raise ValueError("No JSON in output")
                data = json.loads('\n'.join(stdout_lines[json_start:]))
            except Exception as e:
                total_failed += len(batch)
                all_errors.append(f"Batch {batch_num}: parse error: {e}")
                continue

            if result.returncode != 0 and 'result' not in data:
                error_msg = data.get('message', 'Unknown bulk API error')
                total_failed += len(batch)
                all_errors.append(f"Batch {batch_num}: {error_msg}")
                continue

            job_info = data.get('result', {}).get('jobInfo', {})
            processed = job_info.get('numberRecordsProcessed', 0)
            failed = job_info.get('numberRecordsFailed', 0)
            total_success += processed - failed
            total_failed += failed

            if failed:
                for fail in data.get('result', {}).get('records', {}).get('failedResults', []):
                    all_errors.append({'id': fail.get('id', ''), 'error': fail.get('error', '')})
        finally:
            Path(temp_csv).unlink(missing_ok=True)

        if batch_num < total_batches:
            time.sleep(2)

    return {'success': total_success, 'failed': total_failed, 'errors': all_errors}


# ─── Child relationship discovery & re-parenting ────────────────────────────

SKIP_CHILD_SUFFIXES = ('Feed', 'History', 'Share', 'ChangeEvent', 'Tag')
SKIP_CHILD_OBJECTS = frozenset({
    'AttachedContentDocument', 'AttachedContentNote', 'CombinedAttachment',
    'ContentDocumentLink', 'DuplicateRecordItem', 'EntitySubscription',
    'FeedComment', 'FeedItem', 'FlowRecordRelation',
    'NetworkActivityAudit', 'ProcessInstance', 'ProcessInstanceHistory',
    'ProcessInstanceStep', 'ProcessInstanceWorkitem',
    'RecordAction', 'RecordActionHistory', 'TopicAssignment',
    'CollaborationGroupRecord', 'SurveySubject',
})


def discover_child_relationships(org_alias, object_type):
    """Use Salesforce Describe API to find meaningful child relationships.

    Returns a list of dicts with keys:
      child_object, field, relationship_name, cascade_delete
    Filters out system objects (Feed, History, Share, etc.).
    """
    result = subprocess.run(
        ['sf', 'sobject', 'describe', '--sobject', object_type,
         '--target-org', org_alias, '--json'],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        print(f"  ⚠️  Could not describe {object_type}: {result.stderr.strip()[:120]}")
        return []

    try:
        data = json.loads(result.stdout)
    except Exception:
        return []

    child_rels = data.get('result', {}).get('childRelationships', [])
    meaningful = []
    for rel in child_rels:
        child_obj = rel.get('childSObject', '')
        field = rel.get('field', '')
        if not child_obj or not field:
            continue
        if child_obj in SKIP_CHILD_OBJECTS:
            continue
        if any(child_obj.endswith(s) for s in SKIP_CHILD_SUFFIXES):
            continue
        meaningful.append({
            'child_object': child_obj,
            'field': field,
            'relationship_name': rel.get('relationshipName', ''),
            'cascade_delete': rel.get('cascadeDelete', False),
        })
    return meaningful


def _count_children(org_alias, child_obj, field, parent_ids):
    """Count child records pointing to any of the given parent IDs."""
    total = 0
    for i in range(0, len(parent_ids), 400):
        chunk = parent_ids[i:i + 400]
        id_list = "', '".join(chunk)
        query = f"SELECT COUNT() FROM {child_obj} WHERE {field} IN ('{id_list}')"
        result = subprocess.run(
            ['sf', 'data', 'query', '--query', query,
             '--target-org', org_alias, '--json'],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            try:
                total += json.loads(result.stdout).get('result', {}).get('totalSize', 0)
            except Exception:
                pass
    return total


def _query_children(org_alias, child_obj, field, parent_ids):
    """Query child records pointing to any of the given parent IDs."""
    all_children = []
    for i in range(0, len(parent_ids), 400):
        chunk = parent_ids[i:i + 400]
        id_list = "', '".join(chunk)
        query = f"SELECT Id, {field} FROM {child_obj} WHERE {field} IN ('{id_list}')"
        all_children.extend(run_soql(org_alias, query))
    return all_children


def _upsert_records_bulk(org_alias, object_type, fieldname, updates, batch_size=200):
    """Bulk-update records via upsert (Id as external-id).

    updates: list of {'Id': record_id, fieldname: new_value}
    Returns (success_count, failed_count).
    """
    total_success = 0
    total_failed = 0

    for i in range(0, len(updates), batch_size):
        batch = updates[i:i + batch_size]
        batch_num = (i // batch_size) + 1

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['Id', fieldname], lineterminator='\n')
            writer.writeheader()
            writer.writerows(batch)
            temp_csv = f.name

        try:
            result = subprocess.run(
                ['sf', 'data', 'upsert', 'bulk',
                 '--sobject', object_type,
                 '--file', temp_csv,
                 '--external-id', 'Id',
                 '--target-org', org_alias,
                 '--json', '--wait', '30'],
                capture_output=True, text=True, timeout=600,
            )
            try:
                stdout_lines = result.stdout.strip().split('\n')
                json_start = next(
                    (j for j, l in enumerate(stdout_lines) if l.strip().startswith('{')), None,
                )
                if json_start is None:
                    raise ValueError("No JSON in output")
                data = json.loads('\n'.join(stdout_lines[json_start:]))
            except Exception:
                total_failed += len(batch)
                continue

            if result.returncode != 0 and 'result' not in data:
                total_failed += len(batch)
                continue

            job_info = data.get('result', {}).get('jobInfo', {})
            processed = job_info.get('numberRecordsProcessed', 0)
            failed = job_info.get('numberRecordsFailed', 0)
            total_success += processed - failed
            total_failed += failed
        finally:
            Path(temp_csv).unlink(missing_ok=True)

        total_batches = (len(updates) + batch_size - 1) // batch_size
        if batch_num < total_batches:
            time.sleep(2)

    return total_success, total_failed


def reparent_all_children(org_alias, object_type, groups):
    """Discover child relationships and re-parent children from non-keepers to keepers.

    For Lookup relationships: children are updated to point to the keeper.
    For Master-Detail relationships: warns that children will cascade-delete.

    Returns a dict:
      total_reparented, total_failed, warnings, details
    """
    empty = {'total_reparented': 0, 'total_failed': 0, 'warnings': [], 'details': []}

    print(f"\n  🔗 Discovering child relationships for {object_type}...")
    child_rels = discover_child_relationships(org_alias, object_type)

    if not child_rels:
        print(f"  ✅ No child relationships found — safe to delete directly")
        return empty

    reparent_map = {}
    for g in groups:
        keeper_id = next((r['Id'] for r in g['records'] if r['is_keeper']), None)
        if not keeper_id:
            continue
        for r in g['records']:
            if not r['is_keeper']:
                reparent_map[r['Id']] = keeper_id

    if not reparent_map:
        return empty

    non_keeper_ids = list(reparent_map.keys())
    print(f"  📊 Found {len(child_rels)} child relationship(s) — checking for records to re-parent...\n")

    total_reparented = 0
    total_failed = 0
    warnings = []
    details = []

    for rel in child_rels:
        child_obj = rel['child_object']
        field = rel['field']

        child_count = _count_children(org_alias, child_obj, field, non_keeper_ids)
        if child_count == 0:
            continue

        if rel['cascade_delete']:
            msg = (
                f"{child_obj}.{field} is Master-Detail: {child_count} child record(s) "
                f"will be CASCADE-DELETED with their parent"
            )
            warnings.append(msg)
            print(f"    ⚠️  {msg}")
            details.append({
                'child_object': child_obj, 'field': field,
                'count': child_count, 'action': 'cascade_delete',
            })
        else:
            print(f"    🔄 {child_obj}.{field}: {child_count} child record(s) — re-parenting...")
            children = _query_children(org_alias, child_obj, field, non_keeper_ids)
            updates = []
            for child in children:
                old_parent = child.get(field)
                new_parent = reparent_map.get(old_parent)
                if new_parent:
                    updates.append({'Id': child['Id'], field: new_parent})

            if updates:
                success, failed = _upsert_records_bulk(org_alias, child_obj, field, updates)
                total_reparented += success
                total_failed += failed
                details.append({
                    'child_object': child_obj, 'field': field,
                    'count': len(updates), 'action': 'reparented',
                    'success': success, 'failed': failed,
                })
                if success:
                    print(f"       ✅ {success} re-parented")
                if failed:
                    print(f"       ❌ {failed} failed")

    return {
        'total_reparented': total_reparented,
        'total_failed': total_failed,
        'warnings': warnings,
        'details': details,
    }


# ─── Contact SOAP merge helpers ──────────────────────────────────────────────

def _get_org_access_token(org_alias):
    """Return (access_token, instance_url) or (None, None) on failure."""
    try:
        result = subprocess.run(
            ['sf', 'org', 'display', '--target-org', org_alias, '--json'],
            capture_output=True, text=True, timeout=30,
        )
        data = json.loads(result.stdout)
        info = data.get('result', {})
        return info.get('accessToken'), info.get('instanceUrl')
    except Exception:
        return None, None


def _merge_contacts_soap(master_id, duplicate_ids, access_token, instance_url):
    """Merge Contact records via Salesforce SOAP Partner API.

    Salesforce natively re-parents ALL child records to the master.
    Max 2 duplicates per merge call (1 master + 2 victims).
    Returns (success: bool, error_msg: str | None).
    """
    ids_xml = ''.join(
        f'<urn:recordToMergeIds>{did}</urn:recordToMergeIds>' for did in duplicate_ids
    )
    soap_body = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" '
        'xmlns:urn="urn:partner.soap.sforce.com" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        '<soapenv:Header>'
        '<urn:SessionHeader>'
        f'<urn:sessionId>{access_token}</urn:sessionId>'
        '</urn:SessionHeader>'
        '</soapenv:Header>'
        '<soapenv:Body>'
        '<urn:merge>'
        '<urn:request>'
        '<urn:masterRecord xsi:type="urn:Contact">'
        f'<urn:Id>{master_id}</urn:Id>'
        '</urn:masterRecord>'
        f'{ids_xml}'
        '</urn:request>'
        '</urn:merge>'
        '</soapenv:Body>'
        '</soapenv:Envelope>'
    )
    try:
        soap_url = f"{instance_url}/services/Soap/u/59.0"
        req = urllib.request.Request(soap_url, data=soap_body.encode('utf-8'))
        req.add_header('Content-Type', 'text/xml; charset=UTF-8')
        req.add_header('SOAPAction', 'merge')

        with urllib.request.urlopen(req, timeout=60) as response:
            body = response.read().decode('utf-8')
            if 'faultcode' in body.lower() or 'faultstring' in body.lower():
                import xml.etree.ElementTree as ET
                try:
                    root = ET.fromstring(body)
                    fault = root.find('.//{http://schemas.xmlsoap.org/soap/envelope/}faultstring')
                    if fault is None:
                        fault = root.find('.//faultstring')
                    return False, (fault.text if fault is not None else 'SOAP fault')
                except Exception:
                    return False, 'SOAP fault (unparseable response)'
            return True, None
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return False, str(e)


# ─── Markdown report generation ─────────────────────────────────────────────

def _fmt(n):
    """Format an integer with commas, or return 'N/A'."""
    return f'{n:,}' if isinstance(n, int) else 'N/A'


def _is_field_empty(value):
    if value is None:
        return True
    if isinstance(value, str) and value.strip() == '':
        return True
    return False


def _find_latest_ghost_backup(object_type):
    """Find the most recently modified backup JSON produced by a ghost detection run."""
    prefix = 'backup_observerships' if object_type == 'Observership__c' else 'backup_mexico_seminars'
    files = sorted(
        [f for f in BACKUP_DIR.glob(f'{prefix}_*.json') if 'duplicate' not in f.name],
        key=lambda f: f.stat().st_mtime, reverse=True,
    )
    return files[0] if files else None


def _get_latest_ghost_run(object_type):
    """Read the latest ghost detection run entry from the database."""
    run_type = (
        'ghost_observership_detection' if object_type == 'Observership__c'
        else 'ghost_mexico_seminar_detection'
    )
    db_utils.init_database()
    with db_utils.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM comparison_runs WHERE run_type = ? ORDER BY timestamp DESC LIMIT 1",
            (run_type,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def generate_duplicate_report(org_alias, action_key, cleanup_result=None):
    """Build a Markdown report for a duplicate-detection action.  Returns the saved path."""
    config = ACTIONS[action_key]
    object_type = config['object_type']

    db_utils.init_database()
    runs = db_utils.get_duplicate_detection_runs(object_type)
    if not runs:
        print("  ❌ No detection runs found in database")
        return None

    latest = runs[0]
    groups = db_utils.get_duplicate_groups(
        run_id=latest['id'], object_type=object_type, pending_only=False,
    )

    total_records = latest.get('total_source_records', 0)
    total_groups = len(groups)
    total_dup_records = sum(g['record_count'] for g in groups)
    keepers = total_groups
    to_remove = total_dup_records - keepers
    is_merge = config.get('merge_mode') == 'soap_merge'

    lines = [
        f'# Data Cleanup Report: {object_type} Duplicates\n',
        f'| | |',
        f'|---|---|',
        f'| **Org** | {org_alias} |',
        f'| **Date** | {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} |',
        f'| **Duplicate Key** | {config["key_desc"]} |',
        f'| **Run ID** | {latest["id"]} |',
        '',
        '## Before Cleanup\n',
        '| Metric | Count |',
        '|--------|------:|',
        f'| Total Records Scanned | {_fmt(total_records)} |',
        f'| Duplicate Groups Found | {_fmt(total_groups)} |',
        f'| Records in Duplicate Groups | {_fmt(total_dup_records)} |',
        f'| Records to Keep (most recent per group) | {_fmt(keepers)} |',
        f'| Records Flagged for Removal | {_fmt(to_remove)} |',
        '',
    ]

    unique_count = total_records - total_dup_records if isinstance(total_records, int) else 0
    pie_slices = []
    if unique_count > 0:
        pie_slices.append(f'    "Unique (no duplicates)" : {unique_count}')
    if keepers > 0:
        pie_slices.append(f'    "Keepers (1 per group)" : {keepers}')
    if to_remove > 0:
        pie_slices.append(f'    "Flagged for Removal" : {to_remove}')
    if pie_slices:
        lines += ['```mermaid', 'pie title Record Distribution'] + pie_slices + ['```', '']

    if groups:
        lines += [
            '## Duplicate Groups\n',
            '| # | Group Key | Copies | Keeper ID | IDs to Remove |',
            '|--:|-----------|-------:|-----------|---------------|',
        ]
        for idx, g in enumerate(groups[:100], 1):
            keeper_id = next((r['Id'] for r in g['records'] if r['is_keeper']), 'N/A')
            remove_ids = [r['Id'] for r in g['records'] if not r['is_keeper']]
            remove_str = ', '.join(f'`{x}`' for x in remove_ids) or '—'
            key_display = g['group_key'][:60]
            lines.append(
                f'| {idx} | `{key_display}` | {g["record_count"]} | `{keeper_id}` | {remove_str} |'
            )
        if len(groups) > 100:
            lines.append(f'| ... | *{len(groups) - 100} more groups* | | | |')
        lines.append('')

    action_verb = 'Merged' if is_merge else 'Deleted'
    action_label = 'SOAP Merge' if is_merge else 'Bulk Delete'

    if cleanup_result:
        remaining = cleanup_result.get('remaining')
        success = cleanup_result.get('success', 0) or 0
        failed = cleanup_result.get('failed', 0) or 0

        reparent = cleanup_result.get('reparent') or {}
        reparent_details = reparent.get('details', [])
        reparent_total = reparent.get('total_reparented', 0)
        reparent_warnings = reparent.get('warnings', [])

        if is_merge:
            lines += [
                '## Child Record Re-parenting\n',
                '> Salesforce SOAP merge **automatically re-parents all child records** '
                '(Observerships, Mexico Seminars, Campaign Members, Affiliations, etc.) '
                'to the keeper Contact. No manual re-parenting is required.\n',
                '',
            ]
        elif reparent_details:
            lines += [
                '## Child Record Re-parenting\n',
                'Before deletion, child records on non-keeper parents were '
                'moved to the corresponding keeper record.\n',
                '| Child Object | Field | Records | Action |',
                '|-------------|-------|-------:|--------|',
            ]
            for d in reparent_details:
                d_label = (
                    f"Re-parented ({d.get('success', 0)} ok, {d.get('failed', 0)} failed)"
                    if d['action'] == 'reparented'
                    else 'Cascade-deleted with parent'
                )
                lines.append(
                    f'| {d["child_object"]} | `{d["field"]}` | {_fmt(d["count"])} | {d_label} |'
                )
            lines.append('')
            if reparent_warnings:
                for w in reparent_warnings:
                    lines.append(f'> **Warning:** {w}\n')

        lines += [
            '## After Cleanup\n',
            '| Metric | Count |',
            '|--------|------:|',
            f'| Records Successfully {action_verb} | {_fmt(success)} |',
            f'| Records Failed to {action_verb[:-1]} | {_fmt(failed)} |',
        ]
        if not is_merge and reparent_total > 0:
            lines.append(f'| Child Records Re-parented | {_fmt(reparent_total)} |')
        lines += [
            f'| Remaining {object_type} Records | {_fmt(remaining)} |',
            '',
            '```mermaid',
            'flowchart LR',
            f'    A["{_fmt(total_records)} total"] -->|Detection| B["{_fmt(to_remove)} flagged"]',
        ]
        if not is_merge and reparent_total > 0:
            lines.append(f'    B -->|Re-parent| RP["{_fmt(reparent_total)} children moved"]')
            lines.append(f'    RP -->|{action_label}| C["' + _fmt(success) + f' {action_verb.lower()}"]')
            lines.append('    style RP fill:#8e44ad,color:#fff')
        else:
            lines.append(f'    B -->|{action_label}| C["{_fmt(success)} {action_verb.lower()}"]')
        lines += [
            f'    B -->|Failed| D["{_fmt(failed)} failed"]',
            f'    C --> E["{_fmt(remaining)} remaining"]',
            '    style A fill:#3498db,color:#fff',
            '    style B fill:#e67e22,color:#fff',
            '    style C fill:#27ae60,color:#fff',
            '    style D fill:#e74c3c,color:#fff',
            '    style E fill:#2ecc71,color:#fff',
            '```',
            '',
        ]
    else:
        lines += [
            '## Cleanup Status\n',
            '> Cleanup has not been executed yet.\n',
        ]
        if to_remove > 0:
            expected = (total_records - to_remove) if isinstance(total_records, int) else None
            lines += [
                '```mermaid',
                'flowchart LR',
                f'    A["{_fmt(to_remove)} flagged for removal"] -.->|Pending| B["{action_label}"]',
            ]
            if expected is not None:
                lines.append(f'    B -.-> C["~{_fmt(expected)} expected remaining"]')
                lines.append('    style C fill:#95a5a6,color:#fff')
            lines += [
                '    style A fill:#e67e22,color:#fff',
                '    style B fill:#95a5a6,color:#fff',
                '```',
                '',
            ]

    lines += [
        '---',
        f'*Generated by AMSA Data Cleanup Tools — {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*',
    ]

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    slug = object_type.lower().replace('__c', '')
    report_path = REPORTS_DIR / f'{slug}_duplicates_{timestamp}.md'
    report_path.write_text('\n'.join(lines))
    return report_path


def generate_ghost_report(org_alias, action_key, cleanup_result=None):
    """Build a Markdown report for a ghost-detection action.  Returns the saved path."""
    config = ACTIONS[action_key]
    object_type = config['object_type']
    ghost_labels = config['ghost_labels']
    data_fields = config['data_fields']

    backup_path = _find_latest_ghost_backup(object_type)
    if not backup_path:
        print("  ❌ No ghost backup file found in results/backups/")
        return None

    with open(backup_path) as f:
        backup_data = json.load(f)
    records = backup_data.get('records', [])
    total_ghosts = len(records)

    cat_a, cat_b = [], []
    for rec in records:
        if object_type == 'Observership__c':
            a_flag = (_is_field_empty(rec.get('Application_Number__c'))
                      and _is_field_empty(rec.get('OMI_App_Date_I__c')))
        else:
            a_flag = _is_field_empty(rec.get('Symposium__c'))
        b_flag = all(_is_field_empty(rec.get(fld)) for fld in data_fields)
        if a_flag:
            cat_a.append(rec)
        if b_flag:
            cat_b.append(rec)

    run_entry = _get_latest_ghost_run(object_type)
    total_scanned = run_entry.get('total_source_records', '—') if run_entry else '—'

    lines = [
        f'# Data Cleanup Report: {object_type} Ghost Records\n',
        f'| | |',
        f'|---|---|',
        f'| **Org** | {org_alias} |',
        f'| **Date** | {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} |',
        f'| **Backup file** | `{backup_path.name}` |',
        '',
        '## Before Cleanup\n',
        '| Category | Description | Count |',
        '|:--------:|-------------|------:|',
        f'| A | {ghost_labels["A"]} | {_fmt(len(cat_a))} |',
        f'| B | {ghost_labels["B"]} | {_fmt(len(cat_b))} |',
        f'| **Total unique ghosts** | | **{_fmt(total_ghosts)}** |',
        f'| Total records scanned | | {_fmt(total_scanned)} |',
        '',
    ]

    if isinstance(total_scanned, int) and total_scanned > 0:
        clean_count = total_scanned - total_ghosts
        pie_slices = []
        if clean_count > 0:
            pie_slices.append(f'    "Clean Records" : {clean_count}')
        if total_ghosts > 0:
            pie_slices.append(f'    "Ghost Records" : {total_ghosts}')
        if pie_slices:
            lines += ['```mermaid', 'pie title Record Classification'] + pie_slices + ['```', '']

    for cat_label, cat_records in [('A', cat_a), ('B', cat_b)]:
        if not cat_records:
            continue
        lines += [
            f'### Category {cat_label}: {ghost_labels[cat_label]} ({_fmt(len(cat_records))} records)\n',
            '| # | Record ID | Name | Applicant | Created |',
            '|--:|-----------|------|-----------|---------|',
        ]
        for idx, rec in enumerate(cat_records[:50], 1):
            lines.append(
                f'| {idx} | `{rec.get("Id", "")}` | {rec.get("Name", "—")} '
                f'| `{rec.get("Applicant__c", "—")}` | {str(rec.get("CreatedDate", "—"))[:10]} |'
            )
        if len(cat_records) > 50:
            lines.append(f'| ... | *{len(cat_records) - 50} more records* | | | |')
        lines.append('')

    if cleanup_result:
        remaining = cleanup_result.get('remaining')
        lines += [
            '## After Cleanup\n',
            '| Metric | Value |',
            '|--------|------:|',
            f'| Ghost records detected | {_fmt(total_ghosts)} |',
            f'| Remaining {object_type} records | {_fmt(remaining)} |',
            '',
            '```mermaid',
            'flowchart LR',
            f'    A["{_fmt(total_scanned)} records"] -->|Detection| B["{_fmt(total_ghosts)} ghosts"]',
            f'    B -->|Cleanup| C["{_fmt(remaining)} remaining"]',
            '    style A fill:#3498db,color:#fff',
            '    style B fill:#e67e22,color:#fff',
            '    style C fill:#27ae60,color:#fff',
            '```',
            '',
        ]
    else:
        lines += [
            '## Cleanup Status\n',
            '> Cleanup has not been executed yet.\n',
        ]
        if total_ghosts > 0:
            lines += [
                '```mermaid',
                'flowchart LR',
                f'    A["{_fmt(total_ghosts)} ghosts detected"] -.->|Pending| B["Bulk Delete"]',
            ]
            if isinstance(total_scanned, int):
                expected = total_scanned - total_ghosts
                lines.append(f'    B -.-> C["~{_fmt(expected)} expected remaining"]')
                lines.append('    style C fill:#95a5a6,color:#fff')
            lines += [
                '    style A fill:#e67e22,color:#fff',
                '    style B fill:#95a5a6,color:#fff',
                '```',
                '',
            ]

    lines += [
        '---',
        f'*Generated by AMSA Data Cleanup Tools — {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*',
    ]

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    slug = object_type.lower().replace('__c', '')
    report_path = REPORTS_DIR / f'ghost_{slug}_{timestamp}.md'
    report_path.write_text('\n'.join(lines))
    return report_path


def generate_report(org_alias, action_key, cleanup_result=None):
    """Dispatch to the appropriate report generator."""
    config = ACTIONS[action_key]
    if config['kind'] == 'duplicate':
        return generate_duplicate_report(org_alias, action_key, cleanup_result)
    return generate_ghost_report(org_alias, action_key, cleanup_result)


# ─── Cleanup execution ──────────────────────────────────────────────────────

def execute_duplicate_cleanup(org_alias, action_key):
    """Delete non-keeper duplicate records with child re-parenting and backup.

    Flow:
      1. Read groups/non-keepers from DB
      2. Discover child relationships (Salesforce Describe API)
      3. Re-parent Lookup children to the keeper; warn about Master-Detail cascades
      4. Backup non-keeper records
      5. Bulk-delete non-keepers
    Returns result dict (or None if cancelled).
    """
    config = ACTIONS[action_key]
    object_type = config['object_type']

    db_utils.init_database()
    groups = db_utils.get_duplicate_groups(object_type=object_type, pending_only=True)

    non_keeper_ids = []
    for g in groups:
        for rec in g['records']:
            if not rec['is_keeper']:
                non_keeper_ids.append(rec['Id'])

    if not non_keeper_ids:
        print("  ⚠️  No non-keeper records found in the database (already cleaned?).")
        return None

    print(f"\n  📊 Found {len(non_keeper_ids)} non-keeper records to delete across {len(groups)} groups")

    # ── Step 1: Discover and re-parent child records ─────────────────────────
    reparent_result = reparent_all_children(org_alias, object_type, groups)

    if reparent_result['warnings']:
        print(f"\n  {'─' * 60}")
        print(f"  ⚠️  WARNINGS (Master-Detail cascade):")
        for w in reparent_result['warnings']:
            print(f"    • {w}")
        print(f"  {'─' * 60}")
        resp = input("  Continue with deletion (cascade children will be lost)? (yes/no): ").strip().lower()
        if resp not in ('yes', 'y'):
            print("  ❌ Cancelled")
            return None

    if reparent_result['total_failed'] > 0:
        print(f"\n  ⚠️  {reparent_result['total_failed']} child re-parent operations failed.")
        resp = input("  Continue with deletion anyway? (yes/no): ").strip().lower()
        if resp not in ('yes', 'y'):
            print("  ❌ Cancelled")
            return None

    if reparent_result['total_reparented'] > 0:
        print(f"\n  ✅ Re-parented {reparent_result['total_reparented']} child record(s) to keeper(s)")

    # ── Step 2: Confirmation ─────────────────────────────────────────────────
    response = input(f"\n  ⚠️  Delete {len(non_keeper_ids)} {object_type} records? (yes/no): ").strip().lower()
    if response not in ('yes', 'y'):
        print("  ❌ Cancelled")
        return None

    # ── Step 3: Backup ───────────────────────────────────────────────────────
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    print(f"\n  💾 Creating backup of {len(non_keeper_ids)} records...")
    backup_records = query_records_by_ids(
        org_alias, object_type, non_keeper_ids, config['all_fields'],
    )
    if backup_records:
        save_duplicate_backup(backup_records, object_type, config['all_fields'], timestamp)
    else:
        print("  ⚠️  Could not fetch records for backup (proceeding with ID-only backup)")
        id_backup_path = BACKUP_DIR / f'backup_{object_type.lower().replace("__c","")}_dup_ids_{timestamp}.json'
        id_backup_path.write_text(json.dumps(non_keeper_ids, indent=2))
        print(f"  💾 ID backup: {id_backup_path}")

    # ── Step 4: Delete non-keepers ───────────────────────────────────────────
    print(f"\n  🗑️  Deleting {len(non_keeper_ids)} records...")
    result = delete_records_bulk(org_alias, object_type, non_keeper_ids)

    for g in groups:
        db_utils.update_duplicate_group_action(g['group_id'], 'deleted')

    remaining = query_record_count(org_alias, object_type)
    result['remaining'] = remaining
    result['reparent'] = reparent_result

    print(f"\n  {'=' * 60}")
    print(f"  CLEANUP SUMMARY")
    print(f"  {'=' * 60}")
    if reparent_result['total_reparented'] > 0:
        print(f"  Re-parented: {reparent_result['total_reparented']} child records")
    print(f"  Deleted:     {result['success']}")
    print(f"  Failed:      {result['failed']}")
    print(f"  Remaining:   {_fmt(remaining)}")
    print(f"  {'=' * 60}")

    if result['errors']:
        error_path = RESULTS_DIR / f'dup_delete_errors_{object_type.lower().replace("__c","")}_{timestamp}.json'
        error_path.write_text(json.dumps(result['errors'], indent=2))
        print(f"\n  ⚠️  Errors saved to: {error_path}")

    return result


def execute_ghost_cleanup(org_alias, action_key):
    """Re-run the ghost script with --execute and return a result summary."""
    config = ACTIONS[action_key]
    args_list = config['build_args'](org_alias, True)
    rc = run_script(config['script'], args_list)

    remaining = query_record_count(org_alias, config['object_type'])
    return {
        'type': 'ghost',
        'executed': rc == 0,
        'success': None,
        'failed': None,
        'remaining': remaining,
    }


def execute_contact_merge(org_alias, action_key):
    """Merge duplicate Contact records using Salesforce SOAP API.

    Salesforce native merge automatically re-parents ALL child records
    (Observerships, Mexico Seminars, Campaign Members, etc.) to the keeper.
    SOAP merge supports up to 2 duplicates per call; groups with more are
    merged iteratively.

    Returns result dict compatible with the report generator, or None if
    cancelled.
    """
    config = ACTIONS[action_key]
    object_type = config['object_type']

    db_utils.init_database()
    groups = db_utils.get_duplicate_groups(object_type=object_type, pending_only=True)

    if not groups:
        print("  ⚠️  No pending duplicate groups found in the database.")
        return None

    total_non_keepers = sum(
        sum(1 for r in g['records'] if not r['is_keeper']) for g in groups
    )
    if total_non_keepers == 0:
        print("  ⚠️  No non-keeper records to merge (already cleaned?).")
        return None

    print(f"\n  📊 Found {total_non_keepers} non-keeper records across {len(groups)} groups")
    print(f"  ℹ️  Contact merge uses Salesforce SOAP API — all child records")
    print(f"     (Observerships, Mexico Seminars, Campaign Members, etc.) are")
    print(f"     automatically re-parented to the keeper by Salesforce.\n")

    response = input(
        f"  ⚠️  Merge {total_non_keepers} duplicate Contacts into their keepers? (yes/no): "
    ).strip().lower()
    if response not in ('yes', 'y'):
        print("  ❌ Cancelled")
        return None

    access_token, instance_url = _get_org_access_token(org_alias)
    if not access_token:
        print("  ❌ Could not obtain access token for org")
        return None

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    print(f"\n  💾 Creating backup of non-keeper Contact records...")
    non_keeper_ids = [
        r['Id'] for g in groups for r in g['records'] if not r['is_keeper']
    ]
    backup_records = query_records_by_ids(
        org_alias, object_type, non_keeper_ids, config['all_fields'],
    )
    if backup_records:
        save_duplicate_backup(backup_records, object_type, config['all_fields'], timestamp)
    else:
        print("  ⚠️  Could not fetch records for backup (proceeding with ID-only backup)")
        id_path = BACKUP_DIR / f'backup_contact_dup_ids_{timestamp}.json'
        id_path.write_text(json.dumps(non_keeper_ids, indent=2))
        print(f"  💾 ID backup: {id_path}")

    merged_count = 0
    failed_count = 0
    errors = []

    print(f"\n  🔄 Merging {len(groups)} duplicate groups via SOAP API...")
    for idx, group in enumerate(groups, 1):
        keeper_id = next(
            (r['Id'] for r in group['records'] if r['is_keeper']), None,
        )
        if not keeper_id:
            failed_count += 1
            errors.append(f"Group {group['group_id']}: no keeper found")
            continue

        non_keepers = [r['Id'] for r in group['records'] if not r['is_keeper']]

        group_ok = True
        for chunk_start in range(0, len(non_keepers), 2):
            chunk = non_keepers[chunk_start:chunk_start + 2]
            success, error = _merge_contacts_soap(
                keeper_id, chunk, access_token, instance_url,
            )
            if success:
                merged_count += len(chunk)
            else:
                group_ok = False
                failed_count += len(chunk)
                errors.append(
                    f"Group {group['group_id']} (keeper {keeper_id}): {error}"
                )
                break

        if group_ok:
            db_utils.update_duplicate_group_action(group['group_id'], 'merged')

        if idx % 25 == 0 or idx == len(groups):
            print(f"    [{idx}/{len(groups)}] merged: {merged_count}, failed: {failed_count}")

        if idx < len(groups):
            time.sleep(0.5)

    remaining = query_record_count(org_alias, object_type)

    print(f"\n  {'=' * 60}")
    print(f"  CONTACT MERGE SUMMARY")
    print(f"  {'=' * 60}")
    print(f"  Merged:    {merged_count} duplicate records")
    print(f"  Failed:    {failed_count}")
    print(f"  Remaining: {_fmt(remaining)} contacts")
    print(f"  {'=' * 60}")

    if errors:
        error_path = RESULTS_DIR / f'contact_merge_errors_{timestamp}.json'
        error_path.write_text(json.dumps(errors, indent=2))
        print(f"\n  ⚠️  Errors saved to: {error_path}")

    return {
        'success': merged_count,
        'failed': failed_count,
        'remaining': remaining,
        'merge_mode': 'soap_merge',
        'errors': errors,
    }


# ─── Script runner ───────────────────────────────────────────────────────────

def run_script(script_name, args_list):
    """Run a worker script as a subprocess, streaming output."""
    script_path = SCRIPTS_DIR / script_name
    cmd = [sys.executable, str(script_path)] + args_list
    print(f"\n{'─' * 70}")
    print(f"  Running: {script_name} {' '.join(args_list)}")
    print(f"{'─' * 70}\n")
    result = subprocess.run(cmd, cwd=str(SCRIPTS_DIR))
    print(f"\n{'─' * 70}")
    status = "✅ Completed" if result.returncode == 0 else f"❌ Exited with code {result.returncode}"
    print(f"  {status}: {script_name}")
    print(f"{'─' * 70}")
    return result.returncode


def run_action(action_key, org_alias, execute=False):
    """Run a single detection action."""
    action = ACTIONS[action_key]
    args_list = action['build_args'](org_alias, execute)
    return run_script(action['script'], args_list)


# ─── Menus ───────────────────────────────────────────────────────────────────

def display_menu(org_alias):
    """Display the main action menu."""
    print(f"\n{'=' * 70}")
    print(f"  DATA CLEANUP MENU  |  Target Org: {org_alias}")
    print(f"{'=' * 70}")
    print()
    print("  DUPLICATE DETECTION & CLEANUP")
    print("  ─────────────────────────────────────────────")
    print("  1  Observership__c duplicates")
    print("  2  Mexico_Seminars__c duplicates")
    print("  5  Contact duplicates  (SOAP merge)")
    print()
    print("  GHOST RECORD DETECTION & CLEANUP")
    print("  ─────────────────────────────────────────────")
    print("  3  Ghost Observership__c records")
    print("  4  Ghost Mexico_Seminars__c records")
    print()
    print("  BATCH OPERATIONS")
    print("  ─────────────────────────────────────────────")
    print("  6  Run ALL detection (duplicates + ghosts, dry-run)")
    print()
    print("  ─────────────────────────────────────────────")
    print("  7  Change target org")
    print("  0  Exit")
    print(f"{'=' * 70}")


def post_action_menu(org_alias, action_key):
    """Sub-menu shown after a detection run completes."""
    config = ACTIONS[action_key]
    cleanup_result = None

    while True:
        print(f"\n{'═' * 70}")
        print(f"  WHAT NEXT?  ({config['short']})")
        print(f"{'═' * 70}")
        print()
        print("  a  Generate shareable report (.md)")
        if cleanup_result:
            print("  b  (cleanup already executed)")
        else:
            if config.get('merge_mode') == 'soap_merge':
                label = "Execute cleanup (SOAP merge — auto re-parents children)"
            elif config['kind'] == 'duplicate':
                label = "Execute cleanup (delete non-keeper records)"
            else:
                label = "Execute cleanup (delete ghost records)"
            print(f"  b  {label}")
        print("  c  Return to main menu")
        print(f"{'═' * 70}")

        choice = input("\nSelect (a/b/c): ").strip().lower()

        if choice == 'a':
            print("\n  📝 Generating Markdown report...")
            report_path = generate_report(org_alias, action_key, cleanup_result)
            if report_path:
                print(f"\n  ✅ Report saved: {report_path}")
            else:
                print("\n  ❌ Could not generate report (no detection data found)")

        elif choice == 'b':
            if cleanup_result:
                print("  ⚠️  Cleanup was already executed for this run.")
                continue
            if config.get('merge_mode') == 'soap_merge':
                cleanup_result = execute_contact_merge(org_alias, action_key)
            elif config['kind'] == 'duplicate':
                cleanup_result = execute_duplicate_cleanup(org_alias, action_key)
            else:
                cleanup_result = execute_ghost_cleanup(org_alias, action_key)

        elif choice == 'c':
            return

        else:
            print(f"  ❌ Invalid choice: {choice}")


def run_all_detection(org_alias):
    """Run all detection scripts in sequence (dry-run mode)."""
    all_keys = ('1', '2', '3', '4', '5')
    total = len(all_keys)
    print(f"\n🚀 Running ALL detection scripts (dry-run)...\n")
    results = {}
    for idx, key in enumerate(all_keys, 1):
        action = ACTIONS[key]
        print(f"\n{'━' * 70}")
        print(f"  [{idx}/{total}] {action['label']}")
        print(f"{'━' * 70}")
        rc = run_action(key, org_alias, execute=False)
        results[key] = rc

    print(f"\n{'=' * 70}")
    print("  ALL DETECTION SUMMARY")
    print(f"{'=' * 70}")
    for key, rc in results.items():
        icon = "✅" if rc == 0 else "❌"
        print(f"  {icon} {ACTIONS[key]['label']}")
    print(f"{'=' * 70}")


def interactive_loop(org_alias):
    """Main interactive menu loop."""
    while True:
        display_menu(org_alias)
        choice = input("\nSelect action: ").strip()

        if choice == '0':
            print("\n👋 Exiting.")
            break
        elif choice == '7':
            orgs = list_orgs()
            display_orgs(orgs)
            new_alias = select_org_interactive(orgs)
            if validate_org(new_alias):
                org_alias = new_alias
            else:
                print(f"  ❌ Could not connect to {new_alias}")
        elif choice == '6':
            run_all_detection(org_alias)
            input("\nPress Enter to return to menu...")
        elif choice in ACTIONS:
            rc = run_action(choice, org_alias, execute=False)
            if rc == 0:
                post_action_menu(org_alias, choice)
            else:
                print(f"\n  ❌ Detection failed (exit code {rc}).  Fix the issue and retry.")
                input("\nPress Enter to return to menu...")
        else:
            print(f"  ❌ Invalid choice: {choice}")
            input("\nPress Enter to return to menu...")


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='Data Cleanup Menu – interactive launcher for duplicate and ghost record tools',
    )
    parser.add_argument('org_alias', nargs='?', default=None,
                        help='Target org alias (optional; prompted if omitted)')
    parser.add_argument('--action', choices=['1', '2', '3', '4', '5', '6'],
                        help='Run a specific action non-interactively')
    parser.add_argument('--execute', action='store_true',
                        help='Execute cleanup after detection (non-interactive)')
    parser.add_argument('--report', action='store_true',
                        help='Generate Markdown report after detection (non-interactive)')
    args = parser.parse_args()

    print("=" * 70)
    print("  🧹  DATA CLEANUP MENU")
    print("=" * 70)

    org_alias = args.org_alias
    if not org_alias:
        orgs = list_orgs()
        display_orgs(orgs)
        if not orgs:
            sys.exit(1)
        org_alias = select_org_interactive(orgs)

    print(f"\n🔐 Validating org: {org_alias}...")
    if not validate_org(org_alias):
        print(f"❌ Could not connect to org '{org_alias}'")
        sys.exit(1)

    # Non-interactive mode
    if args.action:
        if args.action == '6':
            run_all_detection(org_alias)
            return

        rc = run_action(args.action, org_alias, execute=False)
        if rc != 0:
            sys.exit(rc)

        cleanup_result = None
        if args.execute:
            config = ACTIONS[args.action]
            if config.get('merge_mode') == 'soap_merge':
                cleanup_result = execute_contact_merge(org_alias, args.action)
            elif config['kind'] == 'duplicate':
                cleanup_result = execute_duplicate_cleanup(org_alias, args.action)
            else:
                cleanup_result = execute_ghost_cleanup(org_alias, args.action)

        if args.report:
            report_path = generate_report(org_alias, args.action, cleanup_result)
            if report_path:
                print(f"\n  ✅ Report saved: {report_path}")

        if not args.execute and not args.report:
            post_action_menu(org_alias, args.action)
        return

    # Interactive mode
    interactive_loop(org_alias)


if __name__ == '__main__':
    main()
