#!/usr/bin/env python3
"""
Compare CampaignMember records between two orgs.

- Uses ID mappings from database (Contact, Campaign). Run compare_contacts_sqlite and
  compare_campaigns first to populate mappings.

- Focuses on Contact-based CampaignMembers (ContactId != null).
- Matches memberships by (Campaign, Contact, Status).
- Reports:
  - matched memberships
  - memberships present in source but missing in target
  - memberships present in target but not in source (for mapped Campaign/Contact pairs)
  - source records that could not be compared due to missing mappings

Optional date range filter on CampaignMember.CreatedDate.
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import db_utils

# Resolve base dir relative to this script file so it works from any CWD
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


def load_mappings():
    """Load contact and campaign ID mappings from database."""
    print("📂 Loading ID mappings from database...")
    contact_map = db_utils.get_id_mappings('Contact')
    campaign_map = db_utils.get_id_mappings('Campaign')
    print(f"  ✅ Contact mappings:  {len(contact_map)} entries")
    print(f"  ✅ Campaign mappings: {len(campaign_map)} entries")
    if not contact_map:
        print("  ⚠️  Warning: No Contact mappings. Run compare_contacts_sqlite.py first.")
    if not campaign_map:
        print("  ⚠️  Warning: No Campaign mappings. Run compare_campaigns.py first.")
    return contact_map, campaign_map


def build_date_filter(start_date: Optional[str], end_date: Optional[str]):
    """Build WHERE clause for CreatedDate if dates are provided."""
    clauses = []
    if start_date:
        clauses.append(f"CreatedDate >= {start_date}T00:00:00Z")
    if end_date:
        clauses.append(f"CreatedDate <= {end_date}T23:59:59Z")
    if not clauses:
        return ""
    return " WHERE " + " AND ".join(clauses)


def query_campaign_members(org_alias: str, start_date: Optional[str], end_date: Optional[str]):
    """Query CampaignMember records (Contact-based) from an org."""
    print(f"📥 Querying CampaignMember from {org_alias}...")

    where_clause = build_date_filter(start_date, end_date)
    if where_clause:
        where_clause += " AND ContactId != null"
    else:
        where_clause = " WHERE ContactId != null"

    query = (
        "SELECT Id, CampaignId, ContactId, Status, HasResponded, CreatedDate "
        f"FROM CampaignMember{where_clause}"
    )

    records = run_soql(org_alias, query)
    print(f"  ✅ Retrieved {len(records)} CampaignMember records")
    return records


def normalize_status(status: Optional[str]) -> str:
    return (status or '').strip().lower()


def build_membership_key(camp_id: str, contact_id: str, status: Optional[str]) -> str:
    return f"{camp_id}|{contact_id}|{normalize_status(status)}"


def compare_members(source_records, target_records, contact_map, campaign_map):
    """Compare CampaignMembers between source and target.

    Returns a results dict with:
    - matched_count
    - missing_in_target: list of membership dicts
    - extra_in_target: list of membership dicts
    - unmapped_source: list of source records without mapping
    """
    print("\n🔍 Comparing CampaignMember records...")

    # Build mapped keys for source
    source_keys = set()
    source_by_key = {}
    unmapped_source = []

    for cm in source_records:
        src_camp = cm.get('CampaignId')
        src_contact = cm.get('ContactId')
        status = cm.get('Status')

        if not src_camp or not src_contact:
            continue

        if src_camp not in campaign_map or src_contact not in contact_map:
            unmapped_source.append(cm)
            continue

        tgt_camp = campaign_map[src_camp]
        tgt_contact = contact_map[src_contact]
        key = build_membership_key(tgt_camp, tgt_contact, status)

        source_keys.add(key)
        source_by_key[key] = {
            'source_id': cm.get('Id'),
            'source_campaign_id': src_camp,
            'source_contact_id': src_contact,
            'target_campaign_id': tgt_camp,
            'target_contact_id': tgt_contact,
            'status': status,
            'hasResponded': cm.get('HasResponded'),
            'createdDate': cm.get('CreatedDate'),
        }

    print(f"  📊 Source mapped memberships: {len(source_keys)}")
    print(f"  ⚠️  Source unmapped memberships (no mapping): {len(unmapped_source)}")

    # Build keys for target
    target_keys = set()
    target_by_key = {}

    for cm in target_records:
        tgt_camp = cm.get('CampaignId')
        tgt_contact = cm.get('ContactId')
        status = cm.get('Status')

        if not tgt_camp or not tgt_contact:
            continue

        # Only consider memberships where campaign/contact are in mapping values
        if tgt_camp not in campaign_map.values() or tgt_contact not in contact_map.values():
            continue

        key = build_membership_key(tgt_camp, tgt_contact, status)
        target_keys.add(key)
        target_by_key[key] = {
            'target_id': cm.get('Id'),
            'target_campaign_id': tgt_camp,
            'target_contact_id': tgt_contact,
            'status': status,
            'hasResponded': cm.get('HasResponded'),
            'createdDate': cm.get('CreatedDate'),
        }

    print(f"  📊 Target mapped memberships: {len(target_keys)}")

    matched_keys = source_keys & target_keys
    missing_keys = source_keys - target_keys
    extra_keys = target_keys - source_keys

    print(f"  ✅ Matched: {len(matched_keys)}")
    print(f"  ❌ Missing in target: {len(missing_keys)}")
    print(f"  ⚠️  Extra in target (not in source): {len(extra_keys)}")

    missing_in_target = [source_by_key[k] for k in missing_keys]
    extra_in_target = [target_by_key[k] for k in extra_keys]

    # Build id_mapping for matched records (enables migrate_object_files)
    id_mapping = {}
    for k in matched_keys:
        src_id = source_by_key.get(k, {}).get('source_id')
        tgt_id = target_by_key.get(k, {}).get('target_id')
        if src_id and tgt_id:
            id_mapping[src_id] = tgt_id

    results = {
        'matched_count': len(matched_keys),
        'missing_in_target_count': len(missing_in_target),
        'extra_in_target_count': len(extra_in_target),
        'unmapped_source_count': len(unmapped_source),
        'missing_in_target': missing_in_target,
        'extra_in_target': extra_in_target,
        'unmapped_source_samples': unmapped_source[:50],
        'id_mapping': id_mapping,
        'matched_keys': matched_keys,
        'source_by_key': source_by_key,
        'target_by_key': target_by_key,
    }

    return results


def generate_report(results, source_org, target_org, start_date, end_date):
    lines = []
    lines.append("=" * 80)
    lines.append("CAMPAIGN MEMBER COMPARISON REPORT")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"Source Org: {source_org}")
    lines.append(f"Target Org: {target_org}")
    if start_date or end_date:
        lines.append(
            f"Date Range (CreatedDate): {start_date or 'ALL'} to {end_date or 'ALL'}"
        )
    else:
        lines.append("Date Range (CreatedDate): ALL")
    lines.append(f"Report Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("=" * 80)
    lines.append("SUMMARY")
    lines.append("=" * 80)
    lines.append(f"Matched memberships: {results['matched_count']}")
    lines.append(f"Missing in target: {results['missing_in_target_count']}")
    lines.append(f"Extra in target: {results['extra_in_target_count']}")
    lines.append(f"Unmapped source memberships: {results['unmapped_source_count']}")
    lines.append("")

    if results['missing_in_target']:
        lines.append("=" * 80)
        lines.append("MISSING IN TARGET (sample up to 50)")
        lines.append("=" * 80)
        lines.append("")
        for m in results['missing_in_target'][:50]:
            lines.append(
                f"❌ Campaign {m['source_campaign_id']} -> {m['target_campaign_id']} | "
                f"Contact {m['source_contact_id']} -> {m['target_contact_id']} | "
                f"Status: {m['status']}"
            )
            lines.append(f"   Created: {m['createdDate']} | Responded: {m['hasResponded']}")
            lines.append("")

    if results['extra_in_target']:
        lines.append("=" * 80)
        lines.append("EXTRA IN TARGET (not in source, sample up to 50)")
        lines.append("=" * 80)
        lines.append("")
        for m in results['extra_in_target'][:50]:
            lines.append(
                f"⚠️  Campaign {m['target_campaign_id']} | "
                f"Contact {m['target_contact_id']} | Status: {m['status']}"
            )
            lines.append(f"   Created: {m['createdDate']} | Responded: {m['hasResponded']}")
            lines.append("")

    if results['unmapped_source_samples']:
        lines.append("=" * 80)
        lines.append(
            "UNMAPPED SOURCE MEMBERSHIPS (no mapping for Campaign or Contact; "
            "sample up to 50)"
        )
        lines.append("=" * 80)
        lines.append("")
        for cm in results['unmapped_source_samples']:
            lines.append(
                f"⚠️  Source CM Id: {cm.get('Id')} | "
                f"CampaignId: {cm.get('CampaignId')} | "
                f"ContactId: {cm.get('ContactId')} | Status: {cm.get('Status')}"
            )
            lines.append(f"   Created: {cm.get('CreatedDate')} | Responded: {cm.get('HasResponded')}")
            lines.append("")

    return "\n".join(lines)


def main():
    print("=" * 80)
    print("📊 CAMPAIGN MEMBER COMPARISON TOOL")
    print("=" * 80)
    print()

    parser = argparse.ArgumentParser(
        description='Compare CampaignMember records between orgs using Contact/Campaign ID mappings'
    )
    parser.add_argument('source_org', help='Source org alias')
    parser.add_argument('target_org', help='Target org alias')
    parser.add_argument('start_date', nargs='?', help='Start date YYYY-MM-DD (optional)')
    parser.add_argument('end_date', nargs='?', help='End date YYYY-MM-DD (optional)')
    parser.add_argument('--export-json', action='store_true')
    parser.add_argument('--export-csv', action='store_true')
    args = parser.parse_args()

    source_org = args.source_org
    target_org = args.target_org
    start_date = args.start_date
    end_date = args.end_date

    print("📋 Parameters:")
    print(f"  Source Org: {source_org}")
    print(f"  Target Org: {target_org}")
    print(f"  Start Date (CreatedDate): {start_date or 'ALL'}")
    print(f"  End Date (CreatedDate):   {end_date or 'ALL'}")
    print()

    # Create database run
    print("💾 Initializing database...")
    run_id = db_utils.create_comparison_run(
        run_type='campaign_member_comparison',
        source_org=source_org,
        target_org=target_org,
        start_date=start_date,
        end_date=end_date
    )
    print(f"  ✅ Run ID: {run_id}")
    print()

    # Load mappings
    contact_map, campaign_map = load_mappings()
    if not contact_map or not campaign_map:
        db_utils.update_comparison_run(run_id, status='failed', notes='No Contact or Campaign mappings')
        sys.exit(1)
    print()

    # Query memberships
    src_members = query_campaign_members(source_org, start_date, end_date)
    if not src_members:
        db_utils.update_comparison_run(run_id, status='completed', total_source_records=0,
                                       notes='No CampaignMember records in source')
        print("⚠️  No CampaignMember records found in source for given filter")
        sys.exit(0)

    tgt_members = query_campaign_members(target_org, start_date, end_date)

    # Compare
    results = compare_members(src_members, tgt_members, contact_map, campaign_map)

    # Build matches for save_campaign_member_matches
    matches = []
    for m in results.get('missing_in_target', []):
        matches.append({
            'source_id': m.get('source_id'),
            'target_id': None,
            'campaign_id': m.get('target_campaign_id'),
            'contact_id': m.get('target_contact_id'),
            'match_status': 'missing',
            'status': m.get('status'),
        })
    for m in results.get('extra_in_target', []):
        matches.append({
            'source_id': None,
            'target_id': m.get('target_id'),
            'campaign_id': m.get('target_campaign_id'),
            'contact_id': m.get('target_contact_id'),
            'match_status': 'extra',
            'status': m.get('status'),
        })
    for k in results.get('matched_keys', []):
        src = results.get('source_by_key', {}).get(k, {})
        tgt = results.get('target_by_key', {}).get(k, {})
        matches.append({
            'source_id': src.get('source_id'),
            'target_id': tgt.get('target_id'),
            'campaign_id': tgt.get('target_campaign_id'),
            'contact_id': tgt.get('target_contact_id'),
            'match_status': 'matched',
            'status': src.get('status'),
        })
    for cm in results.get('unmapped_source_samples', []):
        matches.append({
            'source_id': cm.get('Id'),
            'target_id': None,
            'campaign_id': cm.get('CampaignId'),
            'contact_id': cm.get('ContactId'),
            'match_status': 'unmapped',
            'status': cm.get('Status'),
        })

    if matches:
        db_utils.save_campaign_member_matches(run_id, matches)
        print(f"  ✅ Saved {len(matches)} campaign member records to database")

    # Update id_mappings for migrate_object_files
    id_mapping = results.get('id_mapping', {})
    if id_mapping:
        db_utils.bulk_update_id_mappings('CampaignMember', id_mapping)
        print(f"  ✅ Updated {len(id_mapping)} CampaignMember ID mappings")

    # Update run statistics
    db_utils.update_comparison_run(
        run_id,
        total_source_records=len(src_members),
        total_target_records=len(tgt_members),
        matched_count=results['matched_count'],
        unmatched_count=results['missing_in_target_count'],
        status='completed'
    )

    # Save results to files
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    json_path = RESULTS_DIR / f'campaign_member_comparison_{timestamp}.json'
    txt_path = RESULTS_DIR / f'campaign_member_comparison_{timestamp}.txt'

    # Exclude non-serializable data from JSON
    results_export = {k: v for k, v in results.items()
                     if k not in ('source_by_key', 'target_by_key', 'matched_keys')}
    results_export['id_mapping'] = results.get('id_mapping', {})

    json_path.write_text(
        json.dumps(
            {
                'metadata': {
                    'source_org': source_org,
                    'target_org': target_org,
                    'start_date': start_date,
                    'end_date': end_date,
                    'timestamp': timestamp,
                    'run_id': run_id,
                },
                'results': results_export,
            },
            indent=2,
        )
    )

    txt_path.write_text(
        generate_report(results, source_org, target_org, start_date, end_date)
    )

    print("=" * 80)
    print("📄 Results saved:")
    print(f"  - {json_path}")
    print(f"  - {txt_path}")
    print("=" * 80)
    print(f"\nRun ID: {run_id}")
    print(f"Database: {db_utils.DB_PATH}")


if __name__ == '__main__':
    main()
