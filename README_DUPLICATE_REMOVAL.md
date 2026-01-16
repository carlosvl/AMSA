# Salesforce Duplicate Seminar Application Remover

This Python script identifies and removes duplicate `Seminar_Application__c` records from your Salesforce org based on specific criteria, keeping only the most recently modified record in each duplicate group.

## Duplicate Detection Criteria

Records are considered duplicates when **ALL** of the following fields match:
- **Applicant__c** (Master-Detail relationship to Contact)
- **Application_Stage__c** (Picklist value)
- **App_Date__c** (Date field)

When duplicates are found, the script keeps the record with the most recent **LastModifiedDate** and deletes all others in that group.

## Prerequisites

1. **Python 3.7 or higher** installed on your system
2. **Salesforce credentials** with appropriate permissions:
   - API Enabled
   - Read and Delete permissions on `Seminar_Application__c` object
3. **Salesforce Security Token** (see setup instructions below)

## Installation

### 1. Install Python Dependencies

```bash
pip install -r requirements.txt
```

Or install manually:

```bash
pip install simple-salesforce
```

### 2. Configure Salesforce Credentials

You have two options for providing credentials:

#### Option A: Configuration File (Recommended)

1. Copy the example configuration file:
   ```bash
   cp config.example.json config.json
   ```

2. Edit `config.json` with your credentials:
   ```json
   {
     "username": "your-email@example.com",
     "password": "your-password",
     "security_token": "your-security-token",
     "domain": "login"
   }
   ```

   - `username`: Your Salesforce username
   - `password`: Your Salesforce password
   - `security_token`: Your Salesforce security token (see below)
   - `domain`: Use `"login"` for production, `"test"` for sandbox

#### Option B: Environment Variables

Set the following environment variables:

```bash
export SF_USERNAME="your-email@example.com"
export SF_PASSWORD="your-password"
export SF_SECURITY_TOKEN="your-security-token"
export SF_DOMAIN="login"  # Optional: defaults to "login"
```

### 3. Get Your Salesforce Security Token

1. Log in to Salesforce
2. Go to **Setup** (gear icon in top-right)
3. In Quick Find, search for "Reset My Security Token"
4. Click **Reset Security Token**
5. Check your email for the new security token
6. Use this token in your configuration

**Note:** If you reset your password, your security token will also be reset.

## Usage

### Step 1: Dry Run (Recommended First)

Always run in dry-run mode first to see what would be deleted without actually deleting anything:

```bash
python remove_duplicate_seminar_applications.py
```

This will:
- Connect to Salesforce
- Fetch all `Seminar_Application__c` records
- Identify duplicates
- Generate a CSV report (`duplicate_report_YYYYMMDD_HHMMSS.csv`)
- Show a summary of what would be deleted
- **NOT delete anything**

### Step 2: Review the Report

Open the generated CSV report to review:
- All duplicate groups
- Which records will be kept (most recent)
- Which records will be deleted

The CSV contains:
- `Group_Number`: Groups duplicates together
- `Record_ID`: Salesforce record ID
- `Record_Name`: Record name (App #)
- `Applicant_ID`: The Contact ID
- `Application_Stage`: Current stage
- `App_Date`: Application date
- `Last_Modified_Date`: When the record was last modified
- `Action`: Either "KEEP (Most Recent)" or "DELETE"

### Step 3: Execute Deletion (When Ready)

Once you've reviewed the report and confirmed the deletions are correct:

```bash
python remove_duplicate_seminar_applications.py --execute
```

You will be prompted to type `DELETE` to confirm. This action **cannot be undone**.

## Command Line Options

- **No flags** (default): Dry-run mode, no deletions
- `--execute`: Enable deletion mode (requires confirmation)
- `--config <file>`: Use a custom config file (default: `config.json`)

### Examples

```bash
# Dry run with default config
python remove_duplicate_seminar_applications.py

# Dry run with custom config
python remove_duplicate_seminar_applications.py --config prod_config.json

# Execute with default config
python remove_duplicate_seminar_applications.py --execute

# Execute with custom config
python remove_duplicate_seminar_applications.py --execute --config sandbox_config.json
```

## Output Files

The script generates two types of files:

1. **CSV Report**: `duplicate_report_YYYYMMDD_HHMMSS.csv`
   - Lists all duplicates found
   - Shows which records will be kept/deleted

2. **Log File**: `duplicate_removal_YYYYMMDD_HHMMSS.log`
   - Detailed execution log
   - Error messages and warnings
   - Deletion results (if executed)

## Safety Features

- **Dry-run by default**: Must explicitly use `--execute` flag
- **Confirmation required**: Must type "DELETE" to proceed
- **Detailed reporting**: CSV report before any deletion
- **Comprehensive logging**: All actions logged to file
- **Error handling**: Failed deletions are logged and reported

## Troubleshooting

### "simple-salesforce library not found"
```bash
pip install simple-salesforce
```

### "Missing Salesforce credentials"
- Ensure your `config.json` file exists and has all required fields
- Or set environment variables: `SF_USERNAME`, `SF_PASSWORD`, `SF_SECURITY_TOKEN`

### "Login failed" or "Authentication error"
- Verify your username and password are correct
- Ensure your security token is current (reset if needed)
- Check if you're using the correct domain (`login` vs `test`)
- Verify your IP is not restricted (or add to trusted IPs in Salesforce)

### "Insufficient privileges"
- Ensure your user has API Enabled permission
- Verify you have Delete permission on `Seminar_Application__c` object
- Check object-level and record-level sharing rules

### No duplicates found but you know they exist
- Verify the duplicate criteria: Applicant__c, Application_Stage__c, and App_Date__c must ALL match
- Check if any of these fields contain null values (nulls are treated as "NULL" in grouping)
- Review the log file for any query errors

## Best Practices

1. **Always test in Sandbox first** before running in production
2. **Run dry-run mode first** to review what will be deleted
3. **Review the CSV report** carefully before executing
4. **Keep the CSV report** as a record of what was deleted
5. **Check the log file** for any errors or warnings
6. **Backup your data** if possible (Data Export in Salesforce)
7. **Run during off-hours** to minimize user impact

## What Gets Kept?

For each group of duplicates, the script keeps **ONE** record:
- The record with the **most recent LastModifiedDate**
- This ensures you keep the record with the latest information

All other records in the duplicate group are deleted.

## Rollback / Recovery

**Important:** Deleted records cannot be recovered by this script.

If you need to recover deleted records:
1. Use Salesforce's **Recycle Bin** (records are kept for 15 days)
2. Go to Setup > Recycle Bin
3. Search for and restore deleted `Seminar_Application__c` records
4. Use the CSV report to identify which records were deleted

For system administrators:
- Consider enabling **Field History Tracking** on key fields
- Set up regular **Data Export** backups
- Consider using a sandbox for testing first

## Support

For issues or questions:
1. Check the log file for detailed error messages
2. Review the Salesforce API documentation
3. Verify your Salesforce user permissions
4. Contact your Salesforce administrator if permissions are needed

## Technical Details

- **API Used**: Salesforce REST API via simple-salesforce library
- **Query Method**: `query_all()` to handle large datasets (>2000 records)
- **Deletion Method**: Individual record deletion with error handling
- **Rate Limiting**: Respects Salesforce API limits (handled by library)
- **Duplicate Detection**: In-memory grouping after fetching all records

## License

This script is provided as-is for use within the AMSA organization.



