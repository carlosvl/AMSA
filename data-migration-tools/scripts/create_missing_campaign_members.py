#!/usr/bin/env python3
"""
Create missing CampaignMember records in target org based on comparison results.

Usage:
  python3 create_missing_campaign_members.py <comparison_json> <target_org>

Example:
  python3 create_missing_campaign_members.py \\
    ../results/campaign_member_comparison_20251202_204811.json \\
    "AMSA Prod"

This script reads the `missing_in_target` array from the comparison JSON
(created by compare_campaign_members.py) and creates corresponding
CampaignMember records in the target org using the Salesforce REST API
directly (no reliance on sf data create commands).

It only uses mappings that were already resolved in the comparison file:
- target_campaign_id
- target_contact_id
- status
"""

import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime
import urllib.request

BASE_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = BASE_DIR / "results"


def get_org_credentials(org_alias: str):
    """Get access token and instance URL from sf org display."""
    try:
        result = subprocess.run(
            ["sf", "org", "display", "--target-org", org_alias, "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            print(f"❌ Failed to get org info for {org_alias}:")
            print(result.stderr.strip())
            return None, None

        data = json.loads(result.stdout)
        info = data.get("result", {})
        return info.get("accessToken"), info.get("instanceUrl")
    except Exception as e:
        print(f"❌ Error getting org credentials for {org_alias}: {e}")
        return None, None


def create_members(missing_members, access_token: str, instance_url: str):
    total = len(missing_members)
    success = 0
    failed = 0
    details = []

    print(f"🧮 Missing memberships to create: {total}")
    print()

    for i, m in enumerate(missing_members, 1):
        camp_id = m.get("target_campaign_id")
        contact_id = m.get("target_contact_id")
        status = (m.get("status") or "").strip()

        if not camp_id or not contact_id:
            failed += 1
            details.append(
                {
                    "source_campaign_id": m.get("source_campaign_id"),
                    "source_contact_id": m.get("source_contact_id"),
                    "target_campaign_id": camp_id,
                    "target_contact_id": contact_id,
                    "status": status,
                    "result": "skipped_missing_ids",
                }
            )
            print(
                f"[{i}/{total}] ⚠️ Skipped: missing target CampaignId or ContactId"
            )
            continue

        body = {
            "CampaignId": camp_id,
            "ContactId": contact_id,
        }
        if status:
            body["Status"] = status

        url = f"{instance_url}/services/data/v59.0/sobjects/CampaignMember"
        data_bytes = json.dumps(body).encode("utf-8")

        req = urllib.request.Request(url, data=data_bytes, method="POST")
        req.add_header("Authorization", f"Bearer {access_token}")
        req.add_header("Content-Type", "application/json")

        print(
            f"[{i}/{total}] Creating CampaignMember: "
            f"Campaign={camp_id}, Contact={contact_id}, Status='{status}'"
        )

        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
                # REST create returns either {id, success, errors} or error list
                if isinstance(resp_data, dict) and resp_data.get("success"):
                    success += 1
                    details.append(
                        {
                            "source_campaign_id": m.get("source_campaign_id"),
                            "source_contact_id": m.get("source_contact_id"),
                            "target_campaign_id": camp_id,
                            "target_contact_id": contact_id,
                            "status": status,
                            "result": "success",
                            "id": resp_data.get("id"),
                        }
                    )
                else:
                    failed += 1
                    details.append(
                        {
                            "source_campaign_id": m.get("source_campaign_id"),
                            "source_contact_id": m.get("source_contact_id"),
                            "target_campaign_id": camp_id,
                            "target_contact_id": contact_id,
                            "status": status,
                            "result": "api_error",
                            "error": resp_data,
                        }
                    )
                    print(f"  ❌ API error: {resp_data}")
        except urllib.error.HTTPError as e:
            failed += 1
            try:
                err_body = e.read().decode("utf-8")
            except Exception:
                err_body = str(e)
            details.append(
                {
                    "source_campaign_id": m.get("source_campaign_id"),
                    "source_contact_id": m.get("source_contact_id"),
                    "target_campaign_id": camp_id,
                    "target_contact_id": contact_id,
                    "status": status,
                    "result": "http_error",
                    "error": err_body,
                    "status_code": e.code,
                }
            )
            print(f"  ❌ HTTP {e.code} error: {err_body[:160]}")
        except Exception as e:
            failed += 1
            details.append(
                {
                    "source_campaign_id": m.get("source_campaign_id"),
                    "source_contact_id": m.get("source_contact_id"),
                    "target_campaign_id": camp_id,
                    "target_contact_id": contact_id,
                    "status": status,
                    "result": "exception",
                    "error": str(e),
                }
            )
            print(f"  ❌ Exception: {e}")

        if i % 20 == 0:
            print(f"  Progress: {i}/{total} (success={success}, failed={failed})")

    return success, failed, details


def main():
    print("=" * 80)
    print("🧩 CREATE MISSING CAMPAIGN MEMBERS")
    print("=" * 80)
    print()

    if len(sys.argv) < 3:
        print("❌ Missing parameters!")
        print("\nUsage:")
        print(
            "  python3 create_missing_campaign_members.py <comparison_json> <target_org>"
        )
        sys.exit(1)

    comparison_json = Path(sys.argv[1])
    target_org = sys.argv[2]

    if not comparison_json.exists():
        print(f"❌ Comparison JSON not found: {comparison_json}")
        sys.exit(1)

    print("📋 Parameters:")
    print(f"  Comparison JSON: {comparison_json}")
    print(f"  Target Org:      {target_org}")
    print()

    data = json.loads(comparison_json.read_text())
    res = data.get("results", {})
    missing = res.get("missing_in_target", [])

    print(f"📂 Missing memberships from comparison: {len(missing)}")
    if not missing:
        print("✅ Nothing to create; no missing memberships")
        sys.exit(0)

    # Authenticate to target org
    print("🔐 Authenticating to target org...")
    access_token, instance_url = get_org_credentials(target_org)
    if not access_token or not instance_url:
        print("❌ Failed to authenticate to target org")
        sys.exit(1)
    print(f"  ✅ Connected to: {instance_url}")
    print()

    success, failed, details = create_members(missing, access_token, instance_url)

    print("\n" + "=" * 80)
    print("📊 SUMMARY")
    print("=" * 80)
    print(f"Total:   {len(missing)}")
    print(f"Success: {success}")
    print(f"Failed:  {failed}")
    if len(missing) > 0:
        print(f"Success rate: {success/len(missing)*100:.1f}%")
    print("=" * 80)

    # Save detailed results
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = RESULTS_DIR / f"campaign_member_create_missing_{timestamp}.json"
    out_json.write_text(
        json.dumps(
            {
                "comparison_file": str(comparison_json),
                "target_org": target_org,
                "timestamp": timestamp,
                "total": len(missing),
                "success": success,
                "failed": failed,
                "details": details,
            },
            indent=2,
        )
    )

    print(f"📄 Detailed results written to: {out_json}")


if __name__ == "__main__":
    main()
