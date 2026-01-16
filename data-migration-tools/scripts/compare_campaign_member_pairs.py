#!/usr/bin/env python3
"""
Compare CampaignMember "pairs" (Campaign + Contact) between two orgs, ignoring dates and status.

Goal: Ensure that for every (Campaign, Contact) pair that exists in the source org
(AMSA-Royalty-Prod), there is at least one corresponding CampaignMember in the
target org (AMSA Prod), regardless of CreatedDate or Status.

Usage:
  python3 compare_campaign_member_pairs.py <source_org> <target_org>

Example:
  python3 compare_campaign_member_pairs.py "AMSA-Royalty-Prod" "AMSA Prod"
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

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


def query_all_members(org_alias: str):
    """Query all CampaignMember records with ContactId != null from an org."""
    print(f"📥 Querying ALL CampaignMember from {org_alias} (ContactId != null)...")

    query = (
        "SELECT Id, CampaignId, ContactId, Status, HasResponded, CreatedDate "
        "FROM CampaignMember WHERE ContactId != null"
    )

    records = run_soql(org_alias, query)
    print(f"  ✅ Retrieved {len(records)} CampaignMember records")
    return records


def build_pair_key(camp_id: str, contact_id: str) -> str:
    return f"{camp_id}|{contact_id}"


def compare_pairs(source_records, target_records, contact_map, campaign_map):
    print("\n🔍 Comparing CampaignMember pairs (Campaign+Contact, ignoring Status/CreatedDate)...")

    # Map source pairs into target IDs
    source_pairs = set()
    unmapped_source = []

    for cm in source_records:
        src_camp = cm.get('CampaignId')
        src_contact = cm.get('ContactId')
        if not src_camp or not src_contact:
            continue

        if src_camp not in campaign_map or src_contact not in contact_map:
            unmapped_source.append(cm)
            continue

        tgt_camp = campaign_map[src_camp]
        tgt_contact = contact_map[src_contact]
        key = build_pair_key(tgt_camp, tgt_contact)
        source_pairs.add(key)

    print(f"  📊 Source mapped pairs: {len(source_pairs)}")
    print(f"  ⚠️  Source unmapped memberships: {len(unmapped_source)}")

    # Build target pairs
    target_pairs = set()
    for cm in target_records:
        camp = cm.get('CampaignId')
        contact = cm.get('ContactId')
        if not camp or not contact:
            continue
        target_pairs.add(build_pair_key(camp, contact))

    print(f"  📊 Target pairs: {len(target_pairs)}")

    matched = source_pairs & target_pairs
    missing = source_pairs - target_pairs
    extra = target_pairs - source_pairs

    print(f"  ✅ Matched pairs: {len(matched)}")
    print(f"  ❌ Missing pairs in target: {len(missing)}")
    print(f"  ⚠️  Extra pairs in target (no source match): {len(extra)}")

    return {
        'source_mapped_pairs': len(source_pairs),
        'unmapped_source_memberships': len(unmapped_source),
        'target_pairs': len(target_pairs),
        'matched_pairs': len(matched),
        'missing_pairs': len(missing),
        'extra_pairs': len(extra),
        'missing_pair_keys': list(missing)[:1000],  # cap
    }


def generate_report(results, source_org, target_org):
    lines = []
    lines.append("=" * 80)
    lines.append("CAMPAIGN MEMBER PAIR COMPARISON REPORT")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"Source Org: {source_org}")
    lines.append(f"Target Org: {target_org}")
    lines.append("Date Filter: NONE (all records; ignoring CreatedDate)")
    lines.append(f"Report Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("=" * 80)
    lines.append("SUMMARY")
    lines.append("=" * 80)
    lines.append(f"Source mapped pairs:           {results['source_mapped_pairs']}")
    lines.append(f"Unmapped source memberships:   {results['unmapped_source_memberships']}")
    lines.append(f"Target pairs:                  {results['target_pairs']}")
    lines.append(f"Matched pairs:                 {results['matched_pairs']}")
    lines.append(f"Missing pairs in target:       {results['missing_pairs']}")
    lines.append(f"Extra pairs in target:         {results['extra_pairs']}")
    lines.append("")

    if results['missing_pairs']:
        lines.append("=" * 80)
        lines.append("MISSING PAIRS IN TARGET (up to 50 samples)")
        lines.append("=" * 80)
        lines.append("")
        for key in results['missing_pair_keys'][:50]:
            camp, contact = key.split('|', 1)
            lines.append(f"❌ Campaign={camp} | Contact={contact}")
        lines.append("")

    return "\n".join(lines)


def main():
    print("=" * 80)
    print("📊 CAMPAIGN MEMBER PAIR COMPARISON TOOL (IGNORE DATE & STATUS)")
    print("=" * 80)
    print()

    if len(sys.argv) < 3:
        print("❌ Missing parameters!")
        print("\nUsage:")
        print(
            "  python3 compare_campaign_member_pairs.py <source_org> <target_org>"
        )
        sys.exit(1)

    source_org = sys.argv[1]
    target_org = sys.argv[2]

    print("📋 Parameters:")
    print(f"  Source Org: {source_org}")
    print(f"  Target Org: {target_org}")
    print()

    contact_map, campaign_map = load_mappings()
    if not contact_map or not campaign_map:
        sys.exit(1)
    print()

    src_members = query_all_members(source_org)
    tgt_members = query_all_members(target_org)

    results = compare_pairs(src_members, tgt_members, contact_map, campaign_map)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    json_path = RESULTS_DIR / f'campaign_member_pairs_comparison_{timestamp}.json'
    txt_path = RESULTS_DIR / f'campaign_member_pairs_comparison_{timestamp}.txt'

    json_path.write_text(
        json.dumps(
            {
                'metadata': {
                    'source_org': source_org,
                    'target_org': target_org,
                    'timestamp': timestamp,
                },
                'results': results,
            },
            indent=2,
        )
    )

    txt_path.write_text(generate_report(results, source_org, target_org))

    print("=" * 80)
    print("📄 Results saved:")
    print(f"  - {json_path}")
    print(f"  - {txt_path}")
    print("=" * 80)


if __name__ == '__main__':
    main()
