# AMSA Repository Summary

> LLM-optimized overview of the codebase. Read this first for project context.

## Overview

**AMSA** is a Salesforce DX project for the Alianza Mexicana para la Salud (AMSA) organization. It combines:
- **Salesforce metadata** (force-app) — reports, objects, custom fields
- **Data migration tools** (Python) — compare, migrate, and validate data between orgs
- **Attachments migration** — backup and restore ContentVersion/ContentDocument files

**Technology stack:** Salesforce DX (API v59.0), Python 3, SQLite, simple-salesforce, zeep (SOAP), Salesforce CLI.

---

## Directory Structure

```
AMSA/
├── force-app/main/default/     # Salesforce metadata (source of truth)
│   ├── objects/               # Custom objects & fields
│   ├── reports/               # Alianza_Reports folder
│   └── ...                    # Other metadata (flows, layouts, etc.)
├── data-migration-tools/      # Python migration & cleanup utilities
│   ├── docs/README.md         # Main documentation
│   ├── scripts/               # Python scripts (cleanup_menu.py is the main entry)
│   ├── results/               # Export outputs (JSON, TXT)
│   │   ├── reports/           # Shareable Markdown reports (.md) with Mermaid
│   │   └── backups/           # Pre-deletion/merge record backups
│   └── migration_results.db   # SQLite (gitignored)
├── attachments-migration/     # File backup/restore
├── scripts/                   # Misc scripts (SOQL, Apex)
├── sfdx-project.json          # SFDX config (API 59.0)
├── requirements.txt           # Python deps
└── package.json               # LWC/Jest/ESLint/Prettier
```

---

## Data Model (Key Objects)

| Object | Purpose |
|--------|---------|
| **Contact** | People/contacts; `ExternalID__c` for cross-org mapping |
| **Campaign** | Campaigns; `ExternalID__c` for mapping |
| **CampaignMember** | Campaign membership |
| **Seminar_Application__c** | Seminar applications (Applicant__c → Contact, Seminar__c → Campaign) |
| **Mexico_Seminars__c** | Mexico seminars |
| **Observership__c** | Observerships |
| **Replica__c** | Replicas |
| **Affiliation__c** | Affiliations |

**Matching strategy:** Primary = `ExternalID__c` (source ID stored in target); Secondary = Email or other identifiers.

---

## Data Migration Tools

All tools live in `data-migration-tools/scripts/`. Results go to SQLite `migration_results.db` (and optionally JSON/CSV).

### Comparison Tools
- `compare_contacts.py` — Contacts (ExternalID__c, Email)
- `compare_campaigns.py` — Campaigns (Name, ExternalID__c)
- `compare_campaign_members.py` — Campaign members
- `compare_seminar_applications.py` — Seminar applications
- `compare_mexico_seminars.py` — Mexico seminars
- `compare_observerships.py` — Observerships
- `compare_replicas.py` — Replicas
- `compare_single_contact_files.py` — Files for one contact
- `compare_accounts.py` — Accounts

### Duplicate & Ghost Cleanup
- `cleanup_menu.py` — **Interactive launcher** for all detection + cleanup operations (recommended entry point)
  - Detects duplicates: Observership\_\_c, Mexico\_Seminars\_\_c, Contact
  - Detects ghost records: Observership\_\_c, Mexico\_Seminars\_\_c
  - Generates shareable Markdown reports with Mermaid diagrams
  - Executes cleanup: bulk delete (custom objects) or SOAP merge (Contacts)
  - Re-parents child records and re-links files (ContentDocumentLink) to keepers before deletion
  - Contact merge auto-reparents all children and files via Salesforce
- `detect_contact_duplicates.py` — Find Contact duplicates (name + email)
- `detect_observership_duplicates.py` — Find Observership\_\_c duplicates
- `detect_mexico_seminar_duplicates.py` — Find Mexico\_Seminars\_\_c duplicates
- `delete_ghost_observerships.py` — Detect/delete ghost Observership\_\_c records
- `delete_ghost_mexico_seminars.py` — Detect/delete ghost Mexico\_Seminars\_\_c records
- `merge_contact_duplicates.py` — Standalone Contact merge (SOAP API)
- `remove_duplicate_seminar_applications.py` — Remove duplicate seminar apps

### File Migration
- `migrate_object_files.py` — Migrate ContentVersion for any object
- `restore_contact_files.py` — Restore files from local backup
- `verify_restore.py` — Verify restore completeness

### Utilities
- `db_utils.py` — SQLite helpers
- `query_results.py` — Query migration_results.db
- `validate_migration.py` — Validation
- `update_external_ids.py` — Update ExternalID__c
- `upsert_*.py` — Upsert scripts per object

### Prerequisites
- Salesforce CLI authenticated (`sf org list`)
- Python 3
- `requirements.txt`: simple-salesforce, requests, zeep

---

## Force-App Metadata

- **Objects:** Contact, Campaign, Seminar_Application__c, Mexico_Seminars__c, Observership__c, Replica__c, Affiliation__c, etc.
- **Reports:** `force-app/main/default/reports/Alianza_Reports/` — many report-meta.xml files
- **Record types:** Master_Contact_Record_Type, Alianza_Contact_Record_Type
- **Custom fields:** ExternalID__c on Contact and Campaign; many Contact fields (Specialty, Institution, etc.)

---

## Development Workflow

1. **Deploy:** `sf project deploy start` (or VS Code Salesforce extensions)
2. **Lint:** `npm run lint` (ESLint for aura/lwc)
3. **Format:** `npm run prettier` / `prettier:verify`
4. **Tests:** `npm run test:unit` (sfdx-lwc-jest)
5. **Migration:** Run scripts from `data-migration-tools/scripts/` with org aliases

---

## SQLite Database (migration_results.db)

**Tables:** `comparison_runs`, `campaign_matches`, `contact_matches`, `seminar_application_matches`, `campaign_member_matches`, `file_comparisons`, `id_mappings`, `duplicate_groups`, `duplicate_records`, `merge_operations`.

**Query:** `python3 query_results.py <command> [options]` — runs, run-details, campaigns, contacts, seminar-apps, mappings, duplicates, export, stats.

---

## Integration Points

- **Salesforce CLI** — SOQL, REST, SOAP (merge)
- **simple-salesforce** — Python REST client
- **zeep** — SOAP for merge operations
- **SQLite** — Centralized migration state

---

## Key Conventions

- Org aliases: e.g. `AMSA Prod`, `AMSA-Royalty-Prod`, `AMSA_Enero-2026`
- Date format: `YYYY-MM-DD` for script args
- Results: `results/<tool>_YYYYMMDD_HHMMSS.{json,txt}`
- Always run prerequisite comparisons before file migration (Contact, Campaign, etc.)

---

## Quick Reference

| Task | Command / Location |
|------|--------------------|
| **Cleanup menu** | `cleanup_menu.py [org] [--action N] [--report] [--execute]` |
| Compare contacts | `compare_contacts.py <source> <target> <start_date> [end_date]` |
| Detect duplicates | `detect_contact_duplicates.py <org>` |
| Migrate Contact files | `compare_contacts_sqlite.py` → `migrate_object_files.py ... Contact` |
| Restore files | `restore_contact_files.py <target> <backup_org> [--since DATE]` |
| Verify restore | `verify_restore.py <target> <backup_org>` |
| Query DB | `query_results.py runs` / `campaigns` / `contacts` / etc. |
