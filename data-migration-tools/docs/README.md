# Data Migration Tools

A collection of utilities for comparing and migrating data between Salesforce orgs.

## Database Storage

All comparison and migration results are now stored in a centralized SQLite database for better querying, historical tracking, and analysis. Legacy JSON/CSV exports are still available via command-line flags.

## 🔧 Available Tools

### 1. Campaign Comparison Tool
Compares campaigns between two Salesforce orgs using campaign names and ExternalID__c.

**Location:** `scripts/compare_campaigns.py`

**Features:**
- Primary matching: Campaign Name (case-insensitive)
- Secondary matching: ExternalID__c
- Date range filtering on source org
- Results stored in SQLite database
- Optional JSON/CSV export

**Usage:**
```bash
cd data-migration-tools/scripts
python3 compare_campaigns.py <source_org> <target_org> <start_date> [end_date] [--export-json] [--export-csv]
```

**Example:**
```bash
python3 compare_campaigns.py 'AMSA-Royalty-Prod' 'AMSA Prod' '2025-01-01'
python3 compare_campaigns.py 'AMSA-Royalty-Prod' 'AMSA Prod' '2025-01-01' '2025-12-31' --export-json
```

**Output:**
- SQLite database: `migration_results.db` (automatic)
- JSON/CSV files (optional, with flags)

---

### 2. Seminar Application Comparison Tool
Compares Seminar_Application__c records between orgs.

**Location:** `scripts/compare_seminar_applications.py`

**Features:**
- Matches by Applicant__c (Contact) + Seminar__c (Campaign)
- Identifies extra records in target org
- Uses ID mappings from database
- Results stored in SQLite

**Usage:**
```bash
python3 compare_seminar_applications.py <source_org> <target_org> [--export-json] [--export-csv]
```

---

### 3. Contact Duplicate Detection Tool
Detects duplicate Contact records within a single Salesforce org using full name and email as matching fields.

**Location:** `scripts/detect_contact_duplicates.py`

**Features:**
- Matches duplicates by Full Name (FirstName + LastName) + Email
- Normalizes names and emails for accurate matching
- Stores results in SQLite database
- Identifies potential keeper records (most recently modified)
- Optional JSON/CSV export

**Usage:**
```bash
cd data-migration-tools/scripts
python3 detect_contact_duplicates.py <org_alias> [--export-json] [--export-csv]
```

**Example:**
```bash
python3 detect_contact_duplicates.py "AMSA Prod"
python3 detect_contact_duplicates.py "AMSA Prod" --export-json --export-csv
```

**Output:**
- SQLite database: `migration_results.db` (automatic)
- Text report: `results/contact_duplicates_YYYYMMDD_HHMMSS.txt`
- JSON/CSV files (optional, with flags)

**Query Results:**
```bash
# Query duplicate groups from database
python3 query_results.py duplicates --run-id <id>
python3 query_results.py duplicates --pending-only
```

---

### 4. Contact Duplicate Merge Tool
Merges duplicate Contact records detected by the duplicate detection tool. Uses Salesforce SOAP API to perform merges, with master record selected based on most recent LastModifiedDate.

**Location:** `scripts/merge_contact_duplicates.py`

**Features:**
- Interactive one-by-one merge review
- Batch processing mode for all pending merges
- Master record auto-selection (most recent LastModifiedDate)
- SOAP API merge implementation
- Merge tracking and reporting
- Dry-run mode for testing

**Prerequisites:**
- No additional Python packages required (uses standard library + raw SOAP API)
- Salesforce CLI must be authenticated with target org

**Usage:**
```bash
cd data-migration-tools/scripts

# Interactive mode (one-by-one)
python3 merge_contact_duplicates.py "AMSA Prod"

# Batch mode (process all)
python3 merge_contact_duplicates.py "AMSA Prod" --batch

# Specific run ID
python3 merge_contact_duplicates.py "AMSA Prod" --run-id 5

# Dry run (test without merging)
python3 merge_contact_duplicates.py "AMSA Prod" --dry-run
```

**Interactive Mode:**
- Displays each duplicate group with master and duplicate records
- Options: Merge, Skip, or Exit
- Shows detailed contact information before merge
- Confirms each merge operation

**Batch Mode:**
- Processes all pending duplicate groups automatically
- Shows progress for each group
- Continues on errors (logs failures)

**Output:**
- SQLite database: `merge_operations` table (automatic)
- Text report: `results/contact_merge_YYYYMMDD_HHMMSS.txt`
- Updates `duplicate_groups.action` to 'merged' after successful merge

**Master Record Selection:**
- Record with most recent `LastModifiedDate` is selected as master
- All other records in the group are merged into master
- Master record values take precedence (no field-level conflict resolution)

---

### 5. Contact Comparison Tool
Compares contacts between two Salesforce orgs using ExternalID__c and Email matching.

**Location:** `scripts/compare_contacts.py`

**Features:**
- Primary matching: Source Contact ID → Target ExternalID__c
- Secondary matching: Email address
- Date range filtering on source org
- Detailed comparison reports (JSON + TXT)
- Match statistics and unmapped contact identification

**Usage:**
```bash
cd data-migration-tools/scripts
python3 compare_contacts.py <source_org> <target_org> <start_date> [end_date]
```

**Example:**
```bash
python3 compare_contacts.py 'AMSA-Royalty-Prod' 'AMSA Prod' '2025-08-01'
python3 compare_contacts.py 'AMSA-Royalty-Prod' 'AMSA Prod' '2025-08-01' '2025-11-27'
```

**Parameters:**
- `source_org`: Org alias for source (e.g., "AMSA-Royalty-Prod")
- `target_org`: Org alias for target (e.g., "AMSA Prod")
- `start_date`: Start date in YYYY-MM-DD format
- `end_date`: (Optional) End date in YYYY-MM-DD format

**Output:**
- JSON file: `results/contact_comparison_YYYYMMDD_HHMMSS.json`
- Text report: `results/contact_comparison_YYYYMMDD_HHMMSS.txt`

---

## 📁 Folder Structure

```
data-migration-tools/
├── docs/                   - Documentation
├── scripts/                - Python scripts
│   ├── db_utils.py        - Database utility module
│   ├── query_results.py   - CLI query tool
│   ├── schema.sql         - Database schema reference
│   └── compare_*.py       - Comparison scripts
├── data/                   - Data files (legacy)
├── results/                - Export results (optional)
└── migration_results.db    - SQLite database (gitignored)
```

---

## 💾 SQLite Database

All comparison and migration results are stored in a centralized SQLite database located at:
```
data-migration-tools/migration_results.db
```

### Database Schema

**Core Tables:**
- `comparison_runs` - Tracks all comparison/migration operations
- `campaign_matches` - Campaign comparison results
- `contact_matches` - Contact comparison results
- `seminar_application_matches` - Seminar application results
- `campaign_member_matches` - Campaign member results
- `file_comparisons` - File/attachment comparisons
- `id_mappings` - Cross-org ID mappings
- `duplicate_groups` - Duplicate record tracking
- `duplicate_records` - Individual duplicate records

See `scripts/schema.sql` for complete schema definition.

### Query Tool

Use the `query_results.py` CLI tool to query and analyze results:

```bash
# List all comparison runs
python3 query_results.py runs

# Filter by type
python3 query_results.py runs --type campaign_comparison --limit 10

# Show run details
python3 query_results.py run-details <run_id>

# Query campaign matches
python3 query_results.py campaigns --run-id <id>
python3 query_results.py campaigns --status not_matched

# Query contact matches
python3 query_results.py contacts --run-id <id>

# Query seminar applications
python3 query_results.py seminar-apps --run-id <id> --status extra

# Query ID mappings
python3 query_results.py mappings --type Contact
python3 query_results.py mappings --type Campaign --source-id 701...

# Export run to JSON/CSV
python3 query_results.py export <run_id> --format json
python3 query_results.py export <run_id> --format csv

# Show database statistics
python3 query_results.py stats

# Query duplicate groups
python3 query_results.py duplicates --pending-only
```

### Direct SQL Queries

You can also query the database directly using sqlite3:

```bash
# Open database
sqlite3 data-migration-tools/migration_results.db

# Example queries
SELECT * FROM comparison_runs ORDER BY timestamp DESC LIMIT 10;

SELECT COUNT(*) FROM campaign_matches WHERE match_type = 'not_matched';

SELECT object_type, COUNT(*) FROM id_mappings GROUP BY object_type;

SELECT * FROM campaign_matches WHERE run_id = 1 AND match_type = 'Name';
```

### Benefits of SQLite Storage

1. **Historical Tracking** - All runs stored with timestamps
2. **Better Querying** - SQL queries instead of parsing JSON
3. **Cross-Reference** - Link campaigns, contacts, and applications
4. **Performance** - Indexed queries for fast lookups
5. **Atomic Operations** - Transaction support for data integrity
6. **Reduced Files** - No more scattered JSON/CSV files

---

## 🔑 Prerequisites

1. **Salesforce CLI** installed and authenticated
   ```bash
   sf --version
   sf org list
   ```

2. **Python 3** with standard library
   ```bash
   python3 --version
   ```

3. **Authenticated Orgs** - Both source and target orgs must be authenticated in SF CLI

---

## 📊 Understanding Results

### Match Types

1. **Matched by ExternalID__c** (Primary)
   - Source Contact ID found in Target's ExternalID__c field
   - Most reliable matching method
   - Indicates contacts were previously migrated or synced

2. **Matched by Email** (Secondary)
   - Email address matches between orgs
   - Used when ExternalID__c is not set or doesn't match
   - May need manual verification

3. **Not Matched**
   - No ExternalID__c match
   - No Email match or Email is missing
   - Requires manual investigation or data creation

### Report Sections

**Summary:**
- Total contacts analyzed
- Match counts and percentages
- Overall match rate

**Matched by ExternalID__c:**
- Contacts successfully matched using primary method
- Shows Source ID → Target ID mapping
- Highest confidence matches

**Matched by Email:**
- Contacts matched via email address
- May indicate ExternalID__c needs updating
- Consider syncing ExternalID__c for these records

**Not Matched:**
- Contacts with no corresponding record in target
- May need to be created or manually mapped
- Review for data quality issues

---

## 🤖 For LLMs

### Tool Purpose
Compare contacts between Salesforce orgs to identify matches and gaps before data migration.

### Matching Strategy
1. **Primary:** Match Source Contact.Id against Target Contact.ExternalID__c
2. **Secondary:** Match by Email if primary fails
3. **Report:** Classify results into matched, partially matched, and unmatched

### Key Design Decisions
- Uses SOQL queries via Salesforce CLI
- No external Python packages required
- Results saved in both JSON (programmatic) and TXT (human-readable)
- Date filtering on source to focus on recent changes
- Progress indicators for long-running queries

### Common Use Cases
1. **Pre-migration validation** - Check if contacts already exist
2. **Post-migration verification** - Verify migration success
3. **Data quality assessment** - Find missing ExternalID__c values
4. **Duplicate detection** - Identify multiple email matches
5. **Gap analysis** - Find contacts needing creation

---

## 🔧 Migration from Legacy JSON Files

If you have existing JSON mapping files in `data/`, they can be imported into the database:

```python
import json
import db_utils

# Load legacy mapping
with open('../data/contact_id_mapping.json') as f:
    mappings = json.load(f)

# Import to database
db_utils.bulk_update_id_mappings('Contact', mappings)
print(f"Imported {len(mappings)} Contact mappings")
```

---

## 🔧 Complete Object Coverage

All Salesforce objects in the data model now have compare and upsert scripts:

| Object | Compare Script | Upsert Script |
|--------|---------------|---------------|
| Account | `compare_accounts.py` | `upsert_accounts.py` |
| Contact | `compare_contacts.py` | `update_external_ids.py` |
| Campaign | `compare_campaigns.py` | `update_campaign_external_ids.py` |
| CampaignMember | `compare_campaign_members.py` | `create_missing_campaign_members.py` |
| Seminar_Application__c | `compare_seminar_applications.py` | `upsert_seminar_applications.py` |
| Affiliation__c | `compare_affiliations.py` | `upsert_affiliations.py` |
| Observership__c | `compare_observerships.py` | `upsert_observerships.py` |
| Mexico_Seminars__c | `compare_mexico_seminars.py` | `upsert_mexico_seminars.py` |
| Replica__c | `compare_replicas.py` | `upsert_replicas.py` |

### Utility Scripts

| Script | Purpose |
|--------|---------|
| `migrate_object_files.py` | Generic file migration for any object type |
| `orchestrate_migration.py` | Master script to run full migration workflow |
| `validate_migration.py` | Post-migration validation and integrity checks |

---

## 🚀 Full Migration Workflow

Use the orchestrator to run a complete migration:

```bash
cd data-migration-tools/scripts

# Run full migration (all phases)
python3 orchestrate_migration.py "AMSA-Royalty-Prod" "AMSA Prod"

# Run from specific phase
python3 orchestrate_migration.py "AMSA-Royalty-Prod" "AMSA Prod" --phase 5

# Dry run (compare only)
python3 orchestrate_migration.py "AMSA-Royalty-Prod" "AMSA Prod" --dry-run

# Skip file migration
python3 orchestrate_migration.py "AMSA-Royalty-Prod" "AMSA Prod" --skip-files
```

### Migration Phases (Dependency Order)

1. **Account** - Parent records
2. **Contact** - Linked to Account
3. **Campaign** - Independent
4. **CampaignMember** - Needs Contact + Campaign
5. **Seminar_Application__c** - Needs Contact + Campaign
6. **Affiliation__c** - Needs Contact + Account
7. **Observership__c** - Needs Contact
8. **Mexico_Seminars__c** - Needs Contact + Campaign
9. **Replica__c** - Needs Contact
10. **Files** - For all objects

---

## ✅ Migration Validation

After migration, validate the results:

```bash
# Basic validation
python3 validate_migration.py "AMSA-Royalty-Prod" "AMSA Prod"

# Verbose with report export
python3 validate_migration.py "AMSA-Royalty-Prod" "AMSA Prod" --verbose --export-report
```

Validates:
- Record counts match between orgs
- ID mappings exist in database
- Files migrated for all objects
- Relationship integrity

---

## 🔧 Future Enhancements

- [x] Account comparison tool
- [x] Custom object comparison (Affiliation, Observership, Mexico_Seminars, Replica)
- [x] Generic file migration for all objects
- [x] Migration orchestrator
- [x] Post-migration validation
- [x] SQLite database storage
- [x] CLI query tool
- [x] Contact duplicate detection
- [x] Contact duplicate merge tool
- [ ] Opportunity comparison tool
- [ ] Batch processing for large orgs (>10k records)
- [ ] Fuzzy name matching
- [ ] Visual comparison reports (HTML)
- [ ] Email notification on completion
- [ ] Database backup/restore utilities
- [ ] Field-level conflict resolution for merges

---

## 📚 References

- [Salesforce CLI Command Reference](https://developer.salesforce.com/docs/atlas.en-us.sfdx_cli_reference.meta/sfdx_cli_reference/)
- [SOQL Date Literals](https://developer.salesforce.com/docs/atlas.en-us.soql_sosl.meta/soql_sosl/sforce_api_calls_soql_select_dateformats.htm)

---

## 👥 Credits

**Created:** November 27, 2025  
**SQLite Migration:** January 15, 2026  
**Branch:** `attachments`  
**Python:** 3.x with standard library only
**Database:** SQLite 3.x (built into Python)




