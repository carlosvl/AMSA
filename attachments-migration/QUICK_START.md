# Quick Start Guide - Contact Attachments Migration

## 🚀 Quick Usage

### 1. Download Files from Source Org
```bash
cd attachments-migration/scripts
python3 download_contact_files.py
```

### 2. Test Upload (3 files)
```bash
cd attachments-migration/scripts
python3 test_multipart_upload.py
```

### 3. Full Upload (All files)
```bash
cd attachments-migration/scripts
python3 upload_all_multipart.py
```

---

## 📁 Where Everything Is

- **📄 Documentation:** `docs/README.md` (complete guide)
- **🐍 Scripts:** `scripts/` (all Python scripts)
- **📊 Data:** `data/` (JSON mappings & metadata)
- **📝 Queries:** `queries/` (SOQL queries)
- **✅ Results:** `results/` (upload results & logs)
- **📥 Downloads:** `downloaded_contact_files/` (197 MB, gitignored)

---

## 🎯 What You Need

1. Salesforce CLI (`sf`) installed and authenticated
2. Python 3 (no extra packages needed)
3. Two orgs authenticated:
   - Source: AMSA-Royalty-Prod
   - Target: AMSA Prod

---

## ✅ Successful Results

- **181 files** uploaded and linked
- **100% success rate**
- **99.4% Contact mapping** (154/155)
- **~15 minutes** total processing time

---

## 🤖 For LLMs

**Working Method:** Multipart/form-data upload with `FirstPublishLocationId`

**Key Files:**
- `scripts/upload_all_multipart.py` - Use this!
- `data/contact_id_mapping.json` - Contact mappings
- `results/upload_progress_multipart.json` - Progress tracker

**Critical:** ContentDocument creation is async. Always wait 2-30 seconds with retry logic.

See `docs/README.md` for complete technical details.

