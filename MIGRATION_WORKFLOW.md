# Data Migration Workflow - AMSA Orgs

Complete workflow for comparing and migrating data between AMSA-Royalty-Prod and AMSA Prod.

---

## 📋 Available Tools

### **1. Contact Comparison & Sync** (`data-migration-tools/`)
Tools for comparing and syncing contact records.

### **2. File Migration** (`attachments-migration/`)
Tools for downloading and uploading file attachments.

---

## 🔄 Complete Workflow

### **Step 1: Compare Contacts**
Identify which contacts exist in both orgs and establish mapping.

```bash
cd data-migration-tools/scripts

# Compare contacts for a date range
python3 compare_contacts.py "AMSA-Royalty-Prod" "AMSA Prod" "2025-01-01" "2025-12-31"

# Output: results/contact_comparison_YYYYMMDD_HHMMSS.json
```

**What it does:**
- Matches contacts by ExternalID__c (primary) and Email (secondary)
- Creates contact ID mapping (source → target)
- Identifies unmatched contacts

---

### **Step 2: Update ExternalID__c**
Sync ExternalID__c field for matched contacts to establish strong primary key.

```bash
cd data-migration-tools/scripts

# Update ExternalID__c using latest comparison results
python3 update_external_ids.py ../results/contact_comparison_YYYYMMDD_HHMMSS.json "AMSA Prod" individual --yes

# Output: results/external_id_update_YYYYMMDD_HHMMSS.json
```

**What it does:**
- Updates ExternalID__c in target org
- Uses source Contact ID as the external identifier
- Enables future migrations to use primary key matching

---

### **Step 3: Compare Files**
Identify which files are missing in target org.

```bash
cd data-migration-tools/scripts

# Compare all files attached to contacts
python3 compare_contact_files.py "AMSA-Royalty-Prod" "AMSA Prod"

# Output: results/files_comparison_YYYYMMDD_HHMMSS.json
```

**What it does:**
- Uses contact mapping from Step 1
- Queries all files linked to contacts in both orgs
- Identifies missing files by comparing titles and sizes
- Generates report with 341 missing files

---

### **Step 4: Download Missing Files**
Download files from source org (can filter by date or use comparison results).

```bash
cd attachments-migration/scripts

# Download files created after specific date
python3 download_contact_files.py

# Note: Currently filters by date (after 8/1/25)
# Files saved to: attachments-migration/downloaded_contact_files/
```

**What it does:**
- Queries ContentVersions created after specified date
- Downloads files to local directory
- Creates metadata files with contact mappings

---

### **Step 5: Upload Files to Target**
Upload downloaded files to target org and link to contacts.

```bash
cd attachments-migration/scripts

# Test with 3 files first
python3 test_multipart_upload.py

# Upload all files
python3 upload_all_multipart.py

# Output: results/upload_results_multipart_final.json
```

**What it does:**
- Uses multipart/form-data method (proven working)
- Auto-links files to contacts using FirstPublishLocationId
- Processes in batches with progress tracking
- 100% success rate achieved in previous runs

---

## 📊 Results Summary

### **Contacts (Completed):**
- ✅ 830 contacts compared across two time periods
- ✅ 786 ExternalID__c values updated (100% success)
- ✅ Match rate: 95-98%

### **Files (Identified):**
- 📊 491 contacts have files in source org
- 📊 2,280 total files in source
- 📎 341 files missing in target
- 📁 169 contacts need file migration

### **Previous Migration (Aug-Nov 2025):**
- ✅ 181 files successfully migrated
- ✅ 100% success rate
- ✅ All files linked to correct contacts

---

## 🔧 Integration Notes

### **Contact Mapping Flow:**
```
compare_contacts.py → contact_id_mapping.json → compare_contact_files.py
                                              → download_contact_files.py
                                              → upload_all_multipart.py
```

### **File Migration Flow:**
```
1. compare_contact_files.py (identify missing)
2. download_contact_files.py (download from source)
3. upload_all_multipart.py (upload to target)
```

### **Key Files:**
- `data-migration-tools/data/contact_id_mapping.json` - Contact mappings
- `data-migration-tools/results/files_comparison_*.json` - Missing files list
- `attachments-migration/data/contact_file_versions_enriched.json` - File metadata

---

## 💡 To Migrate the 341 Missing Files

### **Option 1: Adapt Existing Scripts** (Recommended)
The existing scripts in `attachments-migration/` can be updated to:
1. Read the files_comparison results
2. Download only the missing files
3. Upload them using the proven multipart method

### **Option 2: Manual Process**
1. Review `files_comparison_*.txt` report
2. Prioritize which files to migrate
3. Use existing scripts with date filters
4. Run in batches

---

## 📈 Success Metrics

✅ **Contacts:** 98.6% match rate, 786 synced  
✅ **Files (Previous):** 181 migrated, 100% success  
⏳ **Files (Remaining):** 341 identified, ready to migrate

---

## 🚀 Next Steps

To migrate the 341 missing files, we can:
1. Update `download_contact_files.py` to accept a list of specific files
2. Use the `files_comparison_*.json` as input
3. Reuse the proven `upload_all_multipart.py` method

All tools are committed and documented! 🎉

