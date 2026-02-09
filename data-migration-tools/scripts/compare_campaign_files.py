#!/usr/bin/env python3
"""
Compare Campaign Files by Year

Compares files (ContentDocuments) attached to Campaigns between two orgs
for a given year, and produces a "missing files" report that is compatible
with migrate_missing_files.py (reuses its JSON shape).

- Matching parent records: by Campaign Id mapping (source -> target)
- Matching files: by Title (case-insensitive) and approximate size
"""

import json
import subprocess
import sys
from datetime import datetime
from collections import defaultdict
from pathlib import Path

MAPPING_PATH = Path('../data/campaign_id_mapping.json')
RESULTS_DIR = Path('../results')


def run_soql(org_alias: str, query: str):
    """Run a SOQL query via sf data query and return records list."""
    result = subprocess.run(
        [
            'sf', 'data', 'query',
            '--query', query,
            '--target-org', org_alias,
            '--json',
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )

    if result.returncode != 0:
        print(f"  ❌ SOQL error for org {org_alias}:")
        print(result.stderr.strip())
        return []

    try:
        data = json.loads(result.stdout)
        return data.get('result', {}).get('records', [])
    except Exception as e:
        print(f"  ❌ Failed to parse SOQL JSON: {e}")
        return []


def load_campaign_ids_for_year(source_org: str, year: int):
    """Return list of source Campaign IDs for campaigns created in the given year.

    Uses CreatedDate, not StartDate, to avoid missing campaigns without StartDate.
    """
    print(f"📥 Querying source campaigns for year {year} (by CreatedDate)...")
    start = f"{year}-01-01T00:00:00Z"
    end = f"{year + 1}-01-01T00:00:00Z"  # exclusive upper bound

    query = (
        "SELECT Id, Name, CreatedDate FROM Campaign "
        f"WHERE CreatedDate >= {start} AND CreatedDate < {end}"
    )

    records = run_soql(source_org, query)
    print(f"  ✅ Found {len(records)} campaigns in source for {year}")

    ids = [r['Id'] for r in records]
    return ids, records


def load_campaign_mapping():
    """Load stable campaign_id_mapping.json (sourceId -> targetId)."""
    if not MAPPING_PATH.exists():
        print(f"❌ Campaign mapping file not found: {MAPPING_PATH}")
        return None

    mapping = json.loads(MAPPING_PATH.read_text())
    print(f"📂 Loaded campaign mapping: {len(mapping)} entries")
    return mapping


def query_files_for_parents(org_alias: str, label: str, parent_ids):
    """Query ContentDocumentLinks and ContentDocuments for a list of parent IDs.

    Works for any parent record type (e.g., Campaign, Contact).
    Returns dict[parentId] -> list of file dicts.
    """
    print(f"📥 Querying files from {label} ({org_alias})...")

    if not parent_ids:
        print("  ⚠️  No parent IDs provided")
        return {}

    batch_size = 200
    all_links = []

    for i in range(0, len(parent_ids), batch_size):
        batch = parent_ids[i:i + batch_size]
        ids_str = "','".join(batch)
        query = f"SELECT ContentDocumentId, LinkedEntityId FROM ContentDocumentLink WHERE LinkedEntityId IN ('{ids_str}')"

        if i == 0:
            print(f"  📊 Querying ContentDocumentLink in batches of {batch_size}...")

        result = subprocess.run(
            [
                'sf', 'data', 'query',
                '--query', query,
                '--target-org', org_alias,
                '--json',
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )

        if result.returncode != 0:
            print(f"  ⚠️  Batch {i // batch_size + 1} failed: {result.stderr.strip()[:160]}")
            continue

        try:
            data = json.loads(result.stdout)
            batch_links = data.get('result', {}).get('records', [])
            all_links.extend(batch_links)
        except Exception as e:
            print(f"  ⚠️  Failed to parse batch {i // batch_size + 1}: {e}")
            continue

    print(f"  ✅ Found {len(all_links)} ContentDocumentLink records in {label}")

    # Unique ContentDocument IDs
    doc_ids = list({l['ContentDocumentId'] for l in all_links if l.get('ContentDocumentId')})
    print(f"  📊 Querying details for {len(doc_ids)} unique ContentDocuments in {label}...")

    all_docs = {}
    for i in range(0, len(doc_ids), batch_size):
        batch = doc_ids[i:i + batch_size]
        ids_str = "','".join(batch)
        doc_query = (
            "SELECT Id, Title, FileType, ContentSize, CreatedDate, LatestPublishedVersionId "
            f"FROM ContentDocument WHERE Id IN ('{ids_str}')"
        )

        result = subprocess.run(
            [
                'sf', 'data', 'query',
                '--query', doc_query,
                '--target-org', org_alias,
                '--json',
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )

        if result.returncode != 0:
            print(f"  ⚠️  Doc batch {i // batch_size + 1} failed: {result.stderr.strip()[:160]}")
            continue

        try:
            data = json.loads(result.stdout)
            docs = data.get('result', {}).get('records', [])
            for d in docs:
                all_docs[d['Id']] = d
        except Exception as e:
            print(f"  ⚠️  Failed to parse doc batch {i // batch_size + 1}: {e}")
            continue

    # Organize by parent
    files_by_parent = defaultdict(list)
    for link in all_links:
        parent_id = link.get('LinkedEntityId')
        doc_id = link.get('ContentDocumentId')
        if not doc_id or doc_id not in all_docs:
            continue
        doc = all_docs[doc_id]
        files_by_parent[parent_id].append(
            {
                'ContentDocumentId': doc['Id'],
                'Title': doc.get('Title', 'Unknown'),
                'FileType': doc.get('FileType', ''),
                'ContentSize': doc.get('ContentSize', 0),
                'CreatedDate': doc.get('CreatedDate', ''),
                'LatestPublishedVersionId': doc.get('LatestPublishedVersionId', ''),
            }
        )

    print(f"  ✅ Parents with files in {label}: {len(files_by_parent)}")
    return files_by_parent


def compare_files(source_files, target_files, mapping):
    """Compare files between source and target for mapped parents.

    mapping: dict[source_campaign_id] -> target_campaign_id

    Returns results dict with shape compatible with migrate_missing_files.py:
    - results['missing_files'] is a list of dicts with keys
      'source_contact_id', 'target_contact_id', 'missing_count', 'files'
    (even though these are Campaigns, not Contacts; the migration script
    treats them generically as parent records).
    """
    print("\n🔍 Comparing files for mapped Campaigns...")

    results = {
        'contacts_with_files_in_source': 0,   # naming kept for compatibility
        'contacts_with_files_in_target': 0,
        'contacts_missing_files': 0,
        'total_files_in_source': 0,
        'total_files_in_target': 0,
        'missing_files': [],
        'contacts_not_in_target': [],
    }

    for source_id, target_id in mapping.items():
        src_list = source_files.get(source_id, [])
        tgt_list = target_files.get(target_id, [])

        if src_list:
            results['contacts_with_files_in_source'] += 1
            results['total_files_in_source'] += len(src_list)

        if tgt_list:
            results['contacts_with_files_in_target'] += 1
            results['total_files_in_target'] += len(tgt_list)

        if not src_list:
            continue  # nothing to migrate

        # Build lookup for target by title (case-insensitive)
        target_by_title = {f['Title'].lower(): f for f in tgt_list}

        missing = []
        for sf in src_list:
            title_key = sf['Title'].lower()
            tf = target_by_title.get(title_key)
            if not tf:
                missing.append(sf)
                continue

            # Compare size; if difference > 1KB consider it mismatched
            size_diff = abs(sf.get('ContentSize', 0) - tf.get('ContentSize', 0))
            if size_diff > 1024:
                sf = dict(sf)  # copy
                sf['note'] = (
                    f"Size mismatch: source={sf.get('ContentSize')} bytes, "
                    f"target={tf.get('ContentSize')} bytes"
                )
                missing.append(sf)

        if missing:
            results['contacts_missing_files'] += 1
            results['missing_files'].append(
                {
                    'source_contact_id': source_id,   # actually Campaign Id
                    'target_contact_id': target_id,   # actually Campaign Id
                    'missing_count': len(missing),
                    'files': missing,
                }
            )

    return results


def generate_report(results, source_org, target_org, year):
    """Generate a human-readable summary report."""
    total_missing = sum(m['missing_count'] for m in results['missing_files'])

    lines = []
    lines.append("=" * 80)
    lines.append("CAMPAIGN FILES COMPARISON REPORT")
    lines.append("=" * 80)
    lines.append("")
    lines.append(f"Source Org: {source_org}")
    lines.append(f"Target Org: {target_org}")
    lines.append(f"Year (Campaign StartDate): {year}")
    lines.append(f"Report Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    lines.append("=" * 80)
    lines.append("SUMMARY")
    lines.append("=" * 80)
    lines.append(f"Source Campaigns with Files: {results['contacts_with_files_in_source']}")
    lines.append(f"Total Files in Source: {results['total_files_in_source']}")
    lines.append(f"Target Campaigns with Files: {results['contacts_with_files_in_target']}")
    lines.append(f"Total Files in Target: {results['total_files_in_target']}")
    lines.append("")
    lines.append(f"📊 Campaigns Missing Files: {results['contacts_missing_files']}")
    lines.append(f"📊 Total Missing Files: {total_missing}")
    lines.append("")

    if results['missing_files']:
        lines.append("=" * 80)
        lines.append(
            f"CAMPAIGNS WITH MISSING FILES ({len(results['missing_files'])} campaigns)"
        )
        lines.append("=" * 80)
        lines.append("")

        for item in results['missing_files'][:50]:
            lines.append(f"📁 Source Campaign: {item['source_contact_id']}")
            lines.append(f"   Target Campaign: {item['target_contact_id']}")
            lines.append(f"   Missing Files: {item['missing_count']}")
            lines.append("")
            for f in item['files'][:10]:
                size_mb = f.get('ContentSize', 0) / (1024 * 1024)
                lines.append(f"   ❌ {f['Title']}")
                lines.append(
                    f"      Type: {f.get('FileType', '')} | Size: {size_mb:.2f} MB"
                )
                lines.append(f"      Created: {f.get('CreatedDate', '')}")
                if 'note' in f:
                    lines.append(f"      Note: {f['note']}")
                lines.append("")
            if item['missing_count'] > 10:
                lines.append(
                    f"   ... and {item['missing_count'] - 10} more files for this campaign"
                )
                lines.append("")

        if len(results['missing_files']) > 50:
            lines.append(
                f"... and {len(results['missing_files']) - 50} more campaigns with missing files"
            )
            lines.append("")

    return "\n".join(lines)


def main():
    print("=" * 80)
    print("📎 CAMPAIGN FILES COMPARISON (BY YEAR)")
    print("=" * 80)
    print()

    if len(sys.argv) < 4:
        print("❌ Missing parameters!")
        print("\nUsage:")
        print(
            "  python3 compare_campaign_files.py <source_org> <target_org> <year>"
        )
        print("\nExample:")
        print(
            "  python3 compare_campaign_files.py 'AMSA-Royalty-Prod' 'AMSA Prod' 2025"
        )
        sys.exit(1)

    source_org = sys.argv[1]
    target_org = sys.argv[2]
    year = int(sys.argv[3])

    print("📋 Parameters:")
    print(f"  Source Org: {source_org}")
    print(f"  Target Org: {target_org}")
    print(f"  Year: {year}")
    print()

    # Load mapping
    mapping = load_campaign_mapping()
    if not mapping:
        sys.exit(1)
    print()

    # Get campaigns for this year
    year_ids, year_records = load_campaign_ids_for_year(source_org, year)
    if not year_ids:
        print("⚠️  No campaigns found for this year in source org")
        sys.exit(0)

    # Filter mapping to campaigns in this year
    year_mapping = {sid: mapping[sid] for sid in year_ids if sid in mapping}
    print(
        f"📊 Mapped campaigns in {year}: {len(year_mapping)} (out of {len(year_ids)})"
    )
    if not year_mapping:
        print("⚠️  No mapped campaigns for this year; nothing to compare")
        sys.exit(0)
    print()

    # Query files for these campaigns
    source_ids = list(year_mapping.keys())
    target_ids = list(year_mapping.values())

    source_files = query_files_for_parents(source_org, 'Source', source_ids)
    print()
    target_files = query_files_for_parents(target_org, 'Target', target_ids)
    print()

    if not source_files:
        print("⚠️  No files found in source org for these campaigns")
        sys.exit(0)

    # Compare
    results = compare_files(source_files, target_files, year_mapping)

    # Generate report
    REPORTS_DIR = RESULTS_DIR
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    json_path = REPORTS_DIR / f'campaign_files_comparison_{year}_{timestamp}.json'
    txt_path = REPORTS_DIR / f'campaign_files_comparison_{year}_{timestamp}.txt'

    # Save JSON
    json_path.write_text(
        json.dumps(
            {
                'metadata': {
                    'source_org': source_org,
                    'target_org': target_org,
                    'year': year,
                    'timestamp': timestamp,
                },
                'results': results,
            },
            indent=2,
        )
    )

    # Save text report
    txt_path.write_text(generate_report(results, source_org, target_org, year))

    print("=" * 80)
    print("📄 Results saved:")
    print(f"  - {json_path}")
    print(f"  - {txt_path}")
    print("=" * 80)


if __name__ == '__main__':
    main()
