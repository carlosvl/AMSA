#!/usr/bin/env python3
"""
Update Campaign.ExternalID__c in target org using mapping
Reads data-migration-tools/data/campaign_id_mapping.json and
updates Campaign.ExternalID__c = source Campaign Id for each mapping.
"""
import json
import subprocess
from pathlib import Path
from datetime import datetime

MAPPING_PATH = Path('data-migration-tools/data/campaign_id_mapping.json')
RESULTS_DIR = Path('data-migration-tools/results')
TARGET_ORG_ALIAS = 'AMSA Prod'


def update_campaign_external_ids():
    print("=" * 80)
    print("🔄 UPDATE Campaign.ExternalID__c TOOL")
    print("=" * 80)
    print()

    if not MAPPING_PATH.exists():
        print(f"❌ Mapping file not found: {MAPPING_PATH}")
        return

    mapping = json.loads(MAPPING_PATH.read_text())
    print(f"📂 Loaded mapping for {len(mapping)} campaigns")
    print(f"  Target org: {TARGET_ORG_ALIAS}")
    print()

    success = 0
    failed = 0
    details = []

    items = list(mapping.items())

    for i, (source_id, target_id) in enumerate(items, 1):
        print(f"[{i}/{len(items)}] Updating Campaign {target_id} (ExternalID__c = {source_id})")

        cmd = [
            'sf', 'data', 'update', 'record',
            '--sobject', 'Campaign',
            '--record-id', target_id,
            '--values', f"ExternalID__c={source_id}",
            '--target-org', TARGET_ORG_ALIAS,
            '--json',
        ]

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                if data.get('status') == 0:
                    success += 1
                    details.append({
                        'source_id': source_id,
                        'target_id': target_id,
                        'status': 'success'
                    })
                else:
                    failed += 1
                    details.append({
                        'source_id': source_id,
                        'target_id': target_id,
                        'status': 'failed',
                        'error': data
                    })
                    print(f"  ❌ API error: {data}")
            except Exception as e:
                failed += 1
                details.append({
                    'source_id': source_id,
                    'target_id': target_id,
                    'status': 'failed',
                    'error': f'Parse error: {e}',
                    'raw': result.stdout,
                })
                print(f"  ❌ Parse error: {e}")
        else:
            failed += 1
            details.append({
                'source_id': source_id,
                'target_id': target_id,
                'status': 'failed',
                'error': result.stderr,
            })
            print(f"  ❌ CLI error: {result.stderr.strip()[:120]}")

        if i % 50 == 0:
            print(f"  Progress: {i}/{len(items)} (success={success}, failed={failed})\n")

    print("\n" + "=" * 80)
    print("📊 SUMMARY")
    print("=" * 80)
    print(f"Total: {len(items)}")
    print(f"✅ Success: {success}")
    print(f"❌ Failed: {failed}")
    if len(items) > 0:
        print(f"📈 Success rate: {success/len(items)*100:.1f}%")
    print("=" * 80)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_json = RESULTS_DIR / f'campaign_external_id_update_{timestamp}.json'

    out_json.write_text(json.dumps({
        'timestamp': timestamp,
        'target_org': TARGET_ORG_ALIAS,
        'total': len(items),
        'success': success,
        'failed': failed,
        'details': details,
    }, indent=2))

    print(f"📄 Detailed results saved to: {out_json}")


if __name__ == '__main__':
    update_campaign_external_ids()
