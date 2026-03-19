#!/usr/bin/env python3
"""
Compare files for a single contact between two orgs.

Identifies files in the source org that are missing in the target org for the given contact.
Use when you need to verify or troubleshoot file migration for a specific person.

Usage:
    python compare_single_contact_files.py <source_org> <target_org> <contact_name>
    python compare_single_contact_files.py <source_org> <target_org> --contact-id <id>

Examples:
    python compare_single_contact_files.py "AMSA-Royalty-Becky" "AMSA-Prod" "Fernando Aaron Osuna Gallego"
    python compare_single_contact_files.py "AMSA-Royalty-Becky" "AMSA-Prod" "Osuna Gallego"
    python compare_single_contact_files.py "AMSA-Royalty-Becky" "AMSA-Prod" --contact-id 003Pm00000vLz2KIAS
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Optional

BASE_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = BASE_DIR / 'results'


def run_soql(org_alias: str, query: str) -> list:
    """Run SOQL and return records."""
    cleaned = ' '.join(line.strip() for line in query.strip().split('\n') if line.strip())
    try:
        result = subprocess.run(
            ['sf', 'data', 'query', '--query', cleaned, '--target-org', org_alias, '--json'],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            return []
        data = json.loads(result.stdout)
        return data.get('result', {}).get('records', [])
    except Exception:
        return []


def find_contact(org_alias: str, contact_name: str) -> list:
    """Find contacts by name (case-insensitive partial match). Returns list of {Id, Name, Email}."""
    safe = contact_name.replace("'", "''")
    query = f"SELECT Id, Name, Email FROM Contact WHERE Name LIKE '%{safe}%'"
    records = run_soql(org_alias, query)
    return [{k: v for k, v in r.items() if not k.startswith('attributes')} for r in records]


def get_contact_by_id(org_alias: str, contact_id: str) -> Optional[dict]:
    """Get a contact by Id. Returns {Id, Name, Email} or None if not found."""
    query = f"SELECT Id, Name, Email FROM Contact WHERE Id = '{contact_id}'"
    records = run_soql(org_alias, query)
    if not records:
        return None
    r = records[0]
    return {k: v for k, v in r.items() if not k.startswith('attributes')}


def query_contact_files(org_alias: str, contact_id: str) -> list:
    """Get files linked to a contact. Returns list of {Title, FileType, ContentSize, ContentDocumentId, LatestPublishedVersionId}."""
    query = f"""
        SELECT ContentDocumentId, ContentDocument.Title, ContentDocument.FileType,
               ContentDocument.ContentSize, ContentDocument.LatestPublishedVersionId
        FROM ContentDocumentLink
        WHERE LinkedEntityId = '{contact_id}'
    """
    records = run_soql(org_alias, query)
    out = []
    for r in records:
        doc = r.get('ContentDocument', {}) or {}
        out.append({
            'Title': doc.get('Title', ''),
            'FileType': doc.get('FileType', ''),
            'ContentSize': doc.get('ContentSize', 0),
            'ContentDocumentId': r.get('ContentDocumentId', ''),
            'LatestPublishedVersionId': doc.get('LatestPublishedVersionId', ''),
        })
    return out


def main():
    parser = argparse.ArgumentParser(description='Compare files for a single contact between two orgs')
    parser.add_argument('source_org', help='Source org (e.g., AMSA-Royalty-Becky)')
    parser.add_argument('target_org', help='Target org (e.g., AMSA-Prod)')
    parser.add_argument('contact_name', nargs='?', help='Contact name (partial match)')
    parser.add_argument('--contact-id', help='Target org Contact Id (e.g., 003Pm00000vLz2KIAS)')
    args = parser.parse_args()

    source_org = args.source_org
    target_org = args.target_org
    contact_id = args.contact_id
    contact_name = args.contact_name

    if contact_id and contact_name:
        print("Error: Provide either contact_name or --contact-id, not both.")
        sys.exit(1)
    if not contact_id and not contact_name:
        print("Error: Provide contact_name or --contact-id.")
        sys.exit(1)

    # If contact_id provided, resolve target contact first to get name/email
    if contact_id:
        print("=" * 80)
        print("COMPARE FILES FOR SINGLE CONTACT")
        print("=" * 80)
        print(f"Source org:   {source_org}")
        print(f"Target org:  {target_org}")
        print(f"Target Contact Id: {contact_id}")
        print()

        print("Finding contact in target org by Id...")
        target_contact = get_contact_by_id(target_org, contact_id)
        if not target_contact:
            print(f"  No contact found in {target_org} with Id {contact_id}")
            sys.exit(1)
        target_id = target_contact['Id']
        contact_name = target_contact['Name']
        print(f"  Target Contact: {target_contact['Name']} ({target_id})")

        print("\nFinding contact in source org (by name/email)...")
        source_contacts = find_contact(source_org, contact_name)
        if not source_contacts and target_contact.get('Email'):
            safe_email = target_contact['Email'].replace("'", "''")
            source_contacts = run_soql(
                source_org,
                f"SELECT Id, Name, Email FROM Contact WHERE Email = '{safe_email}'"
            )
            source_contacts = [{k: v for k, v in r.items() if not k.startswith('attributes')} for r in source_contacts]
        if not source_contacts:
            print(f"  No contact found in {source_org} matching '{contact_name}' (or by email)")
            sys.exit(1)
        source_contact = source_contacts[0]
        source_id = source_contact['Id']
        print(f"  Source Contact: {source_contact['Name']} ({source_id})")
    else:
        print("=" * 80)
        print("COMPARE FILES FOR SINGLE CONTACT")
        print("=" * 80)
        print(f"Source org:   {source_org}")
        print(f"Target org:  {target_org}")
        print(f"Contact:     {contact_name}")
        print()

        print("Finding contact in source org...")
        source_contacts = find_contact(source_org, contact_name)
        if not source_contacts:
            print(f"  No contact found in {source_org} matching '{contact_name}'")
            sys.exit(1)
        if len(source_contacts) > 1:
            print(f"  Found {len(source_contacts)} matches; using first. Disambiguate by providing full name.")
        source_contact = source_contacts[0]
        source_id = source_contact['Id']
        source_email = source_contact.get('Email') or ''
        print(f"  Source Contact: {source_contact['Name']} ({source_id})")

        print("\nFinding contact in target org...")
        target_contacts = find_contact(target_org, contact_name)
        if not target_contacts and source_email:
            safe_email = source_email.replace("'", "''")
            target_contacts = run_soql(
                target_org,
                f"SELECT Id, Name, Email FROM Contact WHERE Email = '{safe_email}'"
            )
            target_contacts = [{k: v for k, v in r.items() if not k.startswith('attributes')} for r in target_contacts]
        if not target_contacts:
            print(f"  No contact found in {target_org} matching '{contact_name}' (or by email)")
            sys.exit(1)
        if len(target_contacts) > 1 and source_email:
            target_contacts = [c for c in target_contacts if (c.get('Email') or '').lower() == source_email.lower()]
        if not target_contacts:
            target_contacts = find_contact(target_org, contact_name)
        target_contact = target_contacts[0]
        target_id = target_contact['Id']
        print(f"  Target Contact: {target_contact['Name']} ({target_id})")

    print("\nQuerying files from source org...")
    source_files = query_contact_files(source_org, source_id)
    print(f"  Found {len(source_files)} files")

    print("\nQuerying files from target org...")
    target_files = query_contact_files(target_org, target_id)
    print(f"  Found {len(target_files)} files")

    target_by_title = {(f['Title'].lower(), f['ContentSize']): f for f in target_files}
    missing = []
    for f in source_files:
        key = (f['Title'].lower(), f['ContentSize'])
        if key not in target_by_title:
            by_title = [t for t in target_files if t['Title'].lower() == f['Title'].lower()]
            if not by_title:
                missing.append({**f, 'note': 'Not in target'})
            else:
                missing.append({**f, 'note': f"Size mismatch: target has {by_title[0]['ContentSize']} bytes"})

    print()
    print("=" * 80)
    print("REPORT")
    print("=" * 80)
    print(f"Files in source ({source_org}): {len(source_files)}")
    print(f"Files in target ({target_org}): {len(target_files)}")
    print(f"Missing from target:           {len(missing)}")
    print()

    if source_files:
        print("Source files:")
        for f in source_files:
            size_kb = f['ContentSize'] / 1024
            in_target = (f['Title'].lower(), f['ContentSize']) in target_by_title
            mark = "OK" if in_target else "MISSING"
            print(f"  [{mark}] {f['Title']} ({size_kb:.1f} KB)")

    if missing:
        print()
        print("Missing files (in source but not in target):")
        for f in missing:
            size_kb = f['ContentSize'] / 1024
            print(f"  - {f['Title']} ({size_kb:.1f} KB) [{f.get('note', '')}]")
        print()
        print("Run restore_contact_files.py or migrate_object_files.py to copy these files.")
    else:
        print("\nAll source files exist in target.")

    print("=" * 80)


if __name__ == '__main__':
    main()
