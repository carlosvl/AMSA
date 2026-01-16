# Data Migration Tools

A collection of utilities for comparing and migrating data between Salesforce orgs.

## 🔧 Available Tools

### 1. Contact Comparison Tool
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
├── docs/           - Documentation
├── scripts/        - Python scripts
├── data/           - Data files and mappings
└── results/        - Comparison results and reports
```

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

## 🔧 Future Enhancements

- [ ] Account comparison tool
- [ ] Opportunity comparison tool
- [ ] Custom object comparison (configurable)
- [ ] Batch processing for large orgs (>10k records)
- [ ] CSV export option
- [ ] Fuzzy name matching
- [ ] Visual comparison reports (HTML)
- [ ] Email notification on completion

---

## 📚 References

- [Salesforce CLI Command Reference](https://developer.salesforce.com/docs/atlas.en-us.sfdx_cli_reference.meta/sfdx_cli_reference/)
- [SOQL Date Literals](https://developer.salesforce.com/docs/atlas.en-us.soql_sosl.meta/soql_sosl/sforce_api_calls_soql_select_dateformats.htm)

---

## 👥 Credits

**Created:** November 27, 2025  
**Branch:** `attachments`  
**Python:** 3.x with standard library only




