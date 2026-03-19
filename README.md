# AMSA — Alianza Mexicana para la Salud

Salesforce DX project for the Alianza Mexicana para la Salud (AMSA) organization. Combines Salesforce metadata management with Python-based data migration and cleanup tools.

## Prerequisites

| Requirement | Details |
|-------------|---------|
| **Salesforce CLI** | `sf` v2+ — [Install guide](https://developer.salesforce.com/docs/atlas.en-us.sfdx_setup.meta/sfdx_setup/sfdx_setup_intro.htm) |
| **Python** | 3.9+ |
| **Authenticated orgs** | At least one org authenticated via `sf org login web` |
| **Python packages** | `pip install -r requirements.txt` (simple-salesforce, requests, zeep) |

Verify your setup:

```bash
sf org list                        # confirm authenticated orgs
python3 --version                  # confirm Python 3.9+
```

## Project Structure

```
AMSA/
├── force-app/main/default/        # Salesforce metadata (source of truth)
│   ├── objects/                    # Custom objects & fields
│   ├── reports/                    # Alianza_Reports
│   └── ...                        # Flows, layouts, etc.
├── data-migration-tools/
│   ├── scripts/                   # Python tools (see below)
│   ├── results/                   # Outputs (JSON, TXT, CSV)
│   │   ├── reports/               # Shareable Markdown reports (.md)
│   │   └── backups/               # Pre-deletion record backups
│   ├── docs/README.md             # Detailed tool documentation
│   └── migration_results.db       # SQLite state (gitignored)
├── attachments-migration/         # File backup/restore utilities
├── sfdx-project.json              # SFDX config (API v59.0)
├── requirements.txt               # Python dependencies
└── REPOSITORY_SUMMARY.md          # Full LLM-optimized codebase overview
```

## Data Cleanup Menu

The **cleanup menu** (`cleanup_menu.py`) is the main entry point for detecting and removing duplicate and ghost records from a Salesforce org. It sets the target org once and provides an interactive menu for all cleanup operations.

### Quick Start

```bash
cd data-migration-tools/scripts
python3 cleanup_menu.py
```

This launches the fully interactive mode: you pick an org, then choose from the menu.

### Menu Options

```
  DUPLICATE DETECTION & CLEANUP
  ─────────────────────────────────────────────
  1  Observership__c duplicates
  2  Mexico_Seminars__c duplicates
  5  Contact duplicates  (SOAP merge)

  GHOST RECORD DETECTION & CLEANUP
  ─────────────────────────────────────────────
  3  Ghost Observership__c records
  4  Ghost Mexico_Seminars__c records

  BATCH OPERATIONS
  ─────────────────────────────────────────────
  6  Run ALL detection (duplicates + ghosts, dry-run)
```

After running any detection option (1–5), a **post-action sub-menu** appears:

| Option | What it does |
|--------|--------------|
| **a** | Generate a shareable Markdown report (`.md`) with before/after tables and Mermaid diagrams |
| **b** | Execute the cleanup (bulk delete for custom objects, SOAP merge for Contacts) |
| **c** | Return to main menu |

You can generate the report first (to review or share for approval), then come back and run the cleanup. Regenerating the report after cleanup will include the "After" section with results.

> **Contact merges** use Salesforce's native SOAP merge API, which automatically re-parents **all** child records (Observerships, Mexico Seminars, Campaign Members, Affiliations, etc.) to the keeper Contact. No manual re-parenting step is needed.

### Usage Examples

```bash
# Fully interactive — prompted for org and action
python3 cleanup_menu.py

# Pre-select the org, then interactive menu
python3 cleanup_menu.py "AMSA Prod"

# Run a specific action, then get the sub-menu
python3 cleanup_menu.py "AMSA Prod" --action 2

# Non-interactive: detect + generate Markdown report
python3 cleanup_menu.py "AMSA Prod" --action 2 --report

# Non-interactive: detect + execute cleanup
python3 cleanup_menu.py "AMSA Prod" --action 2 --execute

# Non-interactive: detect + cleanup + report (includes after data)
python3 cleanup_menu.py "AMSA Prod" --action 2 --report --execute

# Contact duplicates — detect + SOAP merge + report
python3 cleanup_menu.py "AMSA Prod" --action 5 --execute --report

# Run all detection in dry-run mode
python3 cleanup_menu.py "AMSA Prod" --action 6
```

### What Gets Detected

| Type | Object | Detection Logic | Cleanup Method |
|------|--------|----------------|----------------|
| **Duplicates** | `Observership__c` | Same `Applicant__c` + `Application_Number__c` (fallback `OMI_App_Date_I__c`) | Bulk delete (re-parents children first) |
| **Duplicates** | `Mexico_Seminars__c` | Same `Applicant__c` + `Symposium__c` | Bulk delete (re-parents children first) |
| **Duplicates** | `Contact` | Same Full Name + Email | SOAP merge (auto re-parents all children) |
| **Ghosts (Cat A)** | `Observership__c` | Connected to Contact but missing `Application_Number__c` AND `OMI_App_Date_I__c` | Bulk delete |
| **Ghosts (Cat A)** | `Mexico_Seminars__c` | Connected to Contact but missing `Symposium__c` | Bulk delete |
| **Ghosts (Cat B)** | Both custom objects | Connected to Contact but ALL data fields are NULL/empty | Bulk delete |

### Safety Features

- **Dry-run by default** — detection never deletes anything unless you explicitly choose cleanup
- **Backups before every deletion/merge** — JSON + CSV saved to `results/backups/` before any records are removed
- **Child re-parenting** — for custom objects, child records are re-parented to the keeper before deletion; for Contacts, Salesforce SOAP merge handles this automatically
- **Confirmation prompts** — interactive confirmation before bulk deletes or merges
- **Database tracking** — every detection run and its results are logged in SQLite for audit

### Generated Reports

Markdown reports are saved to `results/reports/` and include:

- Metadata table (org, date, run ID)
- **Before Cleanup** summary with a Mermaid pie chart showing record distribution
- Detailed tables (duplicate groups or ghost record samples)
- **Child Re-parenting** summary (for custom object duplicates) or auto-reparent note (for Contacts)
- **After Cleanup** results with a Mermaid flowchart showing the deletion/merge pipeline
- If cleanup hasn't run yet, a pending-state diagram shows the expected outcome

Reports render with full diagram support on GitHub, VS Code, and most Markdown viewers.

## Other Data Migration Tools

All tools live in `data-migration-tools/scripts/`. See `data-migration-tools/docs/README.md` for full documentation.

| Category | Scripts |
|----------|---------|
| **Comparison** | `compare_contacts.py`, `compare_campaigns.py`, `compare_campaign_members.py`, `compare_seminar_applications.py`, `compare_mexico_seminars.py`, `compare_observerships.py`, `compare_replicas.py` |
| **Duplicate detection** | `detect_contact_duplicates.py`, `detect_observership_duplicates.py`, `detect_mexico_seminar_duplicates.py` |
| **Merge / removal** | `merge_contact_duplicates.py` (standalone), `remove_duplicate_seminar_applications.py` |
| **Cleanup menu** | `cleanup_menu.py` — interactive launcher for all detection + cleanup (recommended entry point) |
| **Ghost cleanup** | `delete_ghost_observerships.py`, `delete_ghost_mexico_seminars.py` |
| **File migration** | `migrate_object_files.py`, `restore_contact_files.py`, `verify_restore.py` |
| **Utilities** | `db_utils.py`, `query_results.py`, `validate_migration.py`, `update_external_ids.py` |

## Salesforce Metadata

Deploy and retrieve metadata using standard Salesforce DX commands:

```bash
sf project deploy start --target-org "AMSA Prod"    # deploy metadata
sf project retrieve start --target-org "AMSA Prod"   # retrieve metadata
```

Key custom objects: `Seminar_Application__c`, `Mexico_Seminars__c`, `Observership__c`, `Replica__c`, `Affiliation__c`.

## Development

```bash
npm run lint              # ESLint for Aura/LWC
npm run prettier          # Format code
npm run prettier:verify   # Check formatting
npm run test:unit         # Jest tests for LWC
```
