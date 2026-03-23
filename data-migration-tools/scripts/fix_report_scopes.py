#!/usr/bin/env python3
"""
Fix Salesforce report scope filters so all reports show ALL records
instead of only the logged-in user's records.

Changes:
  <scope>my</scope>   -> <scope>organization</scope>
  <scope>user</scope> -> <scope>organization</scope>
  <scope>one</scope>  -> <scope>organization</scope>

Also removes the <params> block for scopeid when scope was 'one' or 'user',
since scopeid is meaningless with organization scope.
"""

import os
import re
import glob

REPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "..",
    "force-app",
    "main",
    "default",
    "reports",
    "Alianza_Reports",
)

RESTRICTED_SCOPES = {"my", "user", "one"}
TARGET_SCOPE = "organization"

SCOPEID_PARAM_RE = re.compile(
    r"\s*<params>\s*<name>scopeid</name>\s*<value>[^<]*</value>\s*</params>",
    re.DOTALL,
)


def fix_report(filepath: str) -> bool:
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    original = content

    scope_match = re.search(r"<scope>(\w+)</scope>", content)
    if not scope_match:
        return False

    current_scope = scope_match.group(1)
    if current_scope not in RESTRICTED_SCOPES:
        return False

    content = re.sub(
        r"<scope>\w+</scope>",
        f"<scope>{TARGET_SCOPE}</scope>",
        content,
    )

    content = SCOPEID_PARAM_RE.sub("", content)

    if content == original:
        return False

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(content)
    return True


def main():
    xml_files = glob.glob(os.path.join(REPORTS_DIR, "*.xml"))
    fixed = []
    skipped = []

    for filepath in sorted(xml_files):
        name = os.path.basename(filepath)
        if fix_report(filepath):
            fixed.append(name)
        else:
            skipped.append(name)

    print(f"\nFixed {len(fixed)} reports (scope -> organization):")
    for name in fixed:
        print(f"  ✓ {name}")

    print(f"\nSkipped {len(skipped)} reports (already correct or no scope tag):")
    for name in skipped:
        print(f"  - {name}")


if __name__ == "__main__":
    main()
