#!/usr/bin/env python3
"""
Compare CampaignMember records between two orgs.

- Uses existing mappings:
  - data-migration-tools/data/contact_id_mapping.json  (source ContactId -> target ContactId)
  - data-migration-tools/data/campaign_id_mapping.json (source CampaignId -> target CampaignId)

- Focuses on Contact-based CampaignMembers (ContactId != null).
- Matches memberships by (Campaign, Contact, Status).
- Reports:
  - matched memberships
  - memberships present in source but missing in target
  - memberships present in target but not in source (for mapped Campaign/Contact pairs)
  - source records that could not be compared due to missing mappings

Optional date range filter on CampaignMember.CreatedDate.
"""

import json
import subprocess
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

# Resolve base dir relative to this script file so it works from any CWD
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
    """Load contact and campaign ID mappings."""
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


def build_date_filter(start_date: str | None, end_date: str | None):
    """Build WHERE clause for CreatedDate if dates are provided."""
    clauses = []
    if start_date:
        clauses.append(f"CreatedDate >= {start_date}T00:00:00Z")
    if end_date:
        clauses.append(f"CreatedDate <= {end_date}T23:59:59Z")
    if not clauses:
        return ""
    return " WHERE " + " AND ".join(clauses)


def query_campaign_members(org_alias: str, start_date: str | None, end_date: str | None):
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


def normalize_status(status: str | None) -> str:
    return (status or '').strip().lower()


def build_membership_key(camp_id: str, contact_id: str, status: str | None) -> str:
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

    results = {
        'matched_count': len(matched_keys),
        'missing_in_target_count': len(missing_in_target),
        'extra_in_target_count': len(extra_in_target),
        'unmapped_source_count': len(unmapped_source),
        'missing_in_target': missing_in_target,
        'extra_in_target': extra_in_target,
        'unmapped_source_samples': unmapped_source[:50],
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

    if len(sys.argv) < 3:
        print("❌ Missing parameters!")
        print("\nUsage:")
        print(
            "  python3 compare_campaign_members.py <source_org> <target_org> [start_date] [end_date]"
        )
        print("\nDates (optional): YYYY-MM-DD for CreatedDate filter")
        print("If no dates provided, compares ALL CampaignMember records.")
        sys.exit(1)

    source_org = sys.argv[1]
    target_org = sys.argv[2]
    start_date = sys.argv[3] if len(sys.argv) > 3 else None
    end_date = sys.argv[4] if len(sys.argv) > 4 else None

    print("📋 Parameters:")
    print(f"  Source Org: {source_org}")
    print(f"  Target Org: {target_org}")
    print(f"  Start Date (CreatedDate): {start_date or 'ALL'}")
    print(f"  End Date (CreatedDate):   {end_date or 'ALL'}")
    print()

    # Load mappings
    contact_map, campaign_map = load_mappings()
    if not contact_map or not campaign_map:
        sys.exit(1)
    print()

    # Query memberships
    src_members = query_campaign_members(source_org, start_date, end_date)
    if not src_members:
        print("⚠️  No CampaignMember records found in source for given filter")
        sys.exit(0)

    tgt_members = query_campaign_members(target_org, start_date, end_date)

    # Compare
    results = compare_members(src_members, tgt_members, contact_map, campaign_map)

    # Save results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    json_path = RESULTS_DIR / f'campaign_member_comparison_{timestamp}.json'
    txt_path = RESULTS_DIR / f'campaign_member_comparison_{timestamp}.txt'

    json_path.write_text(
        json.dumps(
            {
                'metadata': {
                    'source_org': source_org,
                    'target_org': target_org,
                    'start_date': start_date,
                    'end_date': end_date,
                    'timestamp': timestamp,
                },
                'results': results,
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


if __name__ == '__main__':
    main()
