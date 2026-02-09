#!/usr/bin/env python3
"""
Salesforce Full Backup Script

Creates a complete snapshot of all Salesforce data into a separate SQLite database.
Each backup is stored as an independent database file for point-in-time recovery.

Usage:
    python backup_salesforce.py <org_alias> <backup_name>
    
Example:
    python backup_salesforce.py "AMSA-Royalty-Prod" "AMSA Enero-2026"
"""

import subprocess
import json
import sqlite3
import sys
import os
import re
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

# Base directory for backups
BASE_DIR = Path(__file__).resolve().parents[1]
BACKUPS_DIR = BASE_DIR / 'backups'


def sanitize_filename(name: str) -> str:
    """Convert backup name to safe filename."""
    # Replace spaces with underscores, remove special characters
    safe = re.sub(r'[^\w\-]', '_', name)
    return safe


def get_backup_db_path(backup_name: str) -> Path:
    """Get the path for a backup database."""
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = sanitize_filename(backup_name)
    return BACKUPS_DIR / f'{safe_name}.db'


def init_backup_database(db_path: Path) -> sqlite3.Connection:
    """
    Initialize a new backup database with all required tables.
    
    Args:
        db_path: Path to the backup database file
        
    Returns:
        sqlite3.Connection: Connection to the database
    """
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Backup metadata table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS backup_metadata (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            backup_name TEXT NOT NULL,
            org_alias TEXT NOT NULL,
            org_id TEXT,
            org_instance_url TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            completed_at DATETIME,
            status TEXT DEFAULT 'in_progress',
            total_objects INTEGER DEFAULT 0,
            total_records INTEGER DEFAULT 0,
            notes TEXT
        )
    """)
    
    # Account records
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sf_id TEXT UNIQUE NOT NULL,
            name TEXT,
            type TEXT,
            industry TEXT,
            billing_street TEXT,
            billing_city TEXT,
            billing_state TEXT,
            billing_postal_code TEXT,
            billing_country TEXT,
            phone TEXT,
            website TEXT,
            description TEXT,
            owner_id TEXT,
            parent_id TEXT,
            external_id TEXT,
            created_date TEXT,
            last_modified_date TEXT,
            raw_data TEXT
        )
    """)
    
    # Contact records
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS contacts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sf_id TEXT UNIQUE NOT NULL,
            first_name TEXT,
            last_name TEXT,
            email TEXT,
            phone TEXT,
            mobile_phone TEXT,
            mailing_street TEXT,
            mailing_city TEXT,
            mailing_state TEXT,
            mailing_postal_code TEXT,
            mailing_country TEXT,
            account_id TEXT,
            title TEXT,
            department TEXT,
            birthdate TEXT,
            owner_id TEXT,
            external_id TEXT,
            created_date TEXT,
            last_modified_date TEXT,
            raw_data TEXT
        )
    """)
    
    # Campaign records
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS campaigns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sf_id TEXT UNIQUE NOT NULL,
            name TEXT,
            type TEXT,
            status TEXT,
            start_date TEXT,
            end_date TEXT,
            description TEXT,
            is_active INTEGER,
            parent_id TEXT,
            owner_id TEXT,
            external_id TEXT,
            created_date TEXT,
            last_modified_date TEXT,
            raw_data TEXT
        )
    """)
    
    # Campaign Member records
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS campaign_members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sf_id TEXT UNIQUE NOT NULL,
            campaign_id TEXT NOT NULL,
            contact_id TEXT,
            lead_id TEXT,
            status TEXT,
            first_responded_date TEXT,
            created_date TEXT,
            last_modified_date TEXT,
            raw_data TEXT
        )
    """)
    
    # Seminar Application records
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS seminar_applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sf_id TEXT UNIQUE NOT NULL,
            name TEXT,
            applicant_id TEXT,
            seminar_id TEXT,
            stage TEXT,
            application_date TEXT,
            external_id TEXT,
            created_date TEXT,
            last_modified_date TEXT,
            raw_data TEXT
        )
    """)
    
    # Affiliation records
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS affiliations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sf_id TEXT UNIQUE NOT NULL,
            name TEXT,
            contact_id TEXT,
            affiliated_account_id TEXT,
            role TEXT,
            status TEXT,
            start_date TEXT,
            end_date TEXT,
            is_primary INTEGER,
            external_id TEXT,
            created_date TEXT,
            last_modified_date TEXT,
            raw_data TEXT
        )
    """)
    
    # Observership records
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS observerships (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sf_id TEXT UNIQUE NOT NULL,
            name TEXT,
            applicant_id TEXT,
            status TEXT,
            start_date TEXT,
            end_date TEXT,
            institution TEXT,
            specialty TEXT,
            external_id TEXT,
            created_date TEXT,
            last_modified_date TEXT,
            raw_data TEXT
        )
    """)
    
    # Mexico Seminars records
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mexico_seminars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sf_id TEXT UNIQUE NOT NULL,
            name TEXT,
            applicant_id TEXT,
            symposium_id TEXT,
            status TEXT,
            application_date TEXT,
            external_id TEXT,
            created_date TEXT,
            last_modified_date TEXT,
            raw_data TEXT
        )
    """)
    
    # Replica records
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS replicas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sf_id TEXT UNIQUE NOT NULL,
            name TEXT,
            contact_id TEXT,
            status TEXT,
            external_id TEXT,
            created_date TEXT,
            last_modified_date TEXT,
            raw_data TEXT
        )
    """)
    
    # Content Version (file metadata + binary)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS content_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sf_id TEXT UNIQUE NOT NULL,
            content_document_id TEXT,
            title TEXT,
            file_extension TEXT,
            file_type TEXT,
            content_size INTEGER,
            version_number INTEGER,
            is_latest INTEGER,
            first_publish_location_id TEXT,
            created_date TEXT,
            last_modified_date TEXT,
            file_path TEXT,
            file_data BLOB,
            raw_data TEXT
        )
    """)
    
    # Add missing columns if they don't exist (for existing databases)
    try:
        cursor.execute("ALTER TABLE content_versions ADD COLUMN file_path TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    try:
        cursor.execute("ALTER TABLE content_versions ADD COLUMN file_data BLOB")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    # Content Document Link (file-to-record relationships)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS content_document_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sf_id TEXT UNIQUE NOT NULL,
            content_document_id TEXT NOT NULL,
            linked_entity_id TEXT NOT NULL,
            share_type TEXT,
            visibility TEXT,
            raw_data TEXT
        )
    """)
    
    # Backup progress tracking
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS backup_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            object_name TEXT NOT NULL,
            records_queried INTEGER DEFAULT 0,
            records_saved INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            started_at DATETIME,
            completed_at DATETIME,
            error_message TEXT
        )
    """)
    
    # Create indexes for common queries
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_contacts_external_id ON contacts(external_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_accounts_name ON accounts(name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_campaigns_name ON campaigns(name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_campaign_members_campaign ON campaign_members(campaign_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_campaign_members_contact ON campaign_members(contact_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_seminar_apps_applicant ON seminar_applications(applicant_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_affiliations_contact ON affiliations(contact_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_observerships_applicant ON observerships(applicant_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_mexico_seminars_applicant ON mexico_seminars(applicant_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_replicas_contact ON replicas(contact_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_content_doc_links_entity ON content_document_links(linked_entity_id)")
    
    conn.commit()
    return conn


def run_sf_query(org_alias: str, query: str) -> List[Dict]:
    """
    Execute a SOQL query against the specified org.
    
    Args:
        org_alias: Salesforce org alias
        query: SOQL query string
        
    Returns:
        List of record dictionaries
    """
    # Clean up multi-line query - remove extra whitespace and newlines
    cleaned_query = ' '.join(line.strip() for line in query.strip().split('\n') if line.strip())
    
    cmd = [
        'sf', 'data', 'query',
        '--query', cleaned_query,
        '--target-org', org_alias,
        '--json'
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        
        # Check for Salesforce API errors
        if 'status' in data and data['status'] != 0:
            error_msg = data.get('message', 'Unknown error')
            print(f"   ⚠️  Salesforce API error: {error_msg}")
            return []
        
        records = data.get('result', {}).get('records', [])
        
        # Clean records - remove Salesforce metadata
        cleaned = []
        for record in records:
            clean_record = {k: v for k, v in record.items() 
                          if not k.startswith('attributes')}
            cleaned.append(clean_record)
        
        return cleaned
    except subprocess.CalledProcessError as e:
        # Try to parse error from stderr or stdout
        try:
            error_data = json.loads(e.stdout)
            error_msg = error_data.get('message', e.stderr or str(e))
        except:
            error_msg = e.stderr or str(e)
        
        # Check if it's a "not supported" error (object doesn't exist)
        if 'not supported' in error_msg.lower() or 'no such column' in error_msg.lower():
            print(f"   ⚠️  Object/field not available in org (may not be deployed): {error_msg[:150]}")
        else:
            print(f"   ⚠️  Query error: {error_msg[:200]}")
        return []
    except json.JSONDecodeError as e:
        print(f"   ⚠️  JSON parse error: {e}")
        return []


def get_org_info(org_alias: str) -> Dict:
    """Get information about the Salesforce org."""
    cmd = ['sf', 'org', 'display', '--target-org', org_alias, '--json']
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        return data.get('result', {})
    except:
        return {}


def backup_accounts(conn: sqlite3.Connection, org_alias: str) -> int:
    """Backup Account records."""
    print("\n📦 Backing up Accounts...")
    
    # Note: Industry field may not exist in all orgs, so we query it separately if needed
    query = """
        SELECT Id, Name, Type, 
               BillingStreet, BillingCity, BillingState, BillingPostalCode, BillingCountry,
               Phone, Website, Description, OwnerId, ParentId,
               CreatedDate, LastModifiedDate
        FROM Account
    """
    
    records = run_sf_query(org_alias, query)
    cursor = conn.cursor()
    
    for record in records:
        cursor.execute("""
            INSERT OR REPLACE INTO accounts 
            (sf_id, name, type, industry, billing_street, billing_city, billing_state,
             billing_postal_code, billing_country, phone, website, description,
             owner_id, parent_id, external_id, created_date, last_modified_date, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.get('Id'),
            record.get('Name'),
            record.get('Type'),
            record.get('Industry'),  # May be null if field doesn't exist
            record.get('BillingStreet'),
            record.get('BillingCity'),
            record.get('BillingState'),
            record.get('BillingPostalCode'),
            record.get('BillingCountry'),
            record.get('Phone'),
            record.get('Website'),
            record.get('Description'),
            record.get('OwnerId'),
            record.get('ParentId'),
            record.get('ExternalID__c'),  # May be null if field doesn't exist
            record.get('CreatedDate'),
            record.get('LastModifiedDate'),
            json.dumps(record)
        ))
    
    conn.commit()
    print(f"   ✅ Backed up {len(records)} Account records")
    return len(records)


def backup_contacts(conn: sqlite3.Connection, org_alias: str) -> int:
    """Backup Contact records."""
    print("\n📦 Backing up Contacts...")
    
    query = """
        SELECT Id, FirstName, LastName, Email, Phone, MobilePhone,
               MailingStreet, MailingCity, MailingState, MailingPostalCode, MailingCountry,
               AccountId, Title, Department, Birthdate, OwnerId,
               CreatedDate, LastModifiedDate
        FROM Contact
    """
    
    records = run_sf_query(org_alias, query)
    cursor = conn.cursor()
    
    for record in records:
        cursor.execute("""
            INSERT OR REPLACE INTO contacts 
            (sf_id, first_name, last_name, email, phone, mobile_phone,
             mailing_street, mailing_city, mailing_state, mailing_postal_code, mailing_country,
             account_id, title, department, birthdate, owner_id, external_id,
             created_date, last_modified_date, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.get('Id'),
            record.get('FirstName'),
            record.get('LastName'),
            record.get('Email'),
            record.get('Phone'),
            record.get('MobilePhone'),
            record.get('MailingStreet'),
            record.get('MailingCity'),
            record.get('MailingState'),
            record.get('MailingPostalCode'),
            record.get('MailingCountry'),
            record.get('AccountId'),
            record.get('Title'),
            record.get('Department'),
            record.get('Birthdate'),
            record.get('OwnerId'),
            record.get('ExternalID__c'),
            record.get('CreatedDate'),
            record.get('LastModifiedDate'),
            json.dumps(record)
        ))
    
    conn.commit()
    print(f"   ✅ Backed up {len(records)} Contact records")
    return len(records)


def backup_campaigns(conn: sqlite3.Connection, org_alias: str) -> int:
    """Backup Campaign records."""
    print("\n📦 Backing up Campaigns...")
    
    query = """
        SELECT Id, Name, Type, Status, StartDate, EndDate, Description, IsActive,
               ParentId, OwnerId, CreatedDate, LastModifiedDate
        FROM Campaign
    """
    
    records = run_sf_query(org_alias, query)
    cursor = conn.cursor()
    
    for record in records:
        cursor.execute("""
            INSERT OR REPLACE INTO campaigns 
            (sf_id, name, type, status, start_date, end_date, description, is_active,
             parent_id, owner_id, external_id, created_date, last_modified_date, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.get('Id'),
            record.get('Name'),
            record.get('Type'),
            record.get('Status'),
            record.get('StartDate'),
            record.get('EndDate'),
            record.get('Description'),
            1 if record.get('IsActive') else 0,
            record.get('ParentId'),
            record.get('OwnerId'),
            record.get('ExternalID__c'),
            record.get('CreatedDate'),
            record.get('LastModifiedDate'),
            json.dumps(record)
        ))
    
    conn.commit()
    print(f"   ✅ Backed up {len(records)} Campaign records")
    return len(records)


def backup_campaign_members(conn: sqlite3.Connection, org_alias: str) -> int:
    """Backup CampaignMember records."""
    print("\n📦 Backing up Campaign Members...")
    
    query = """
        SELECT Id, CampaignId, ContactId, LeadId, Status, FirstRespondedDate,
               CreatedDate, LastModifiedDate
        FROM CampaignMember
    """
    
    records = run_sf_query(org_alias, query)
    cursor = conn.cursor()
    
    for record in records:
        cursor.execute("""
            INSERT OR REPLACE INTO campaign_members 
            (sf_id, campaign_id, contact_id, lead_id, status, first_responded_date,
             created_date, last_modified_date, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.get('Id'),
            record.get('CampaignId'),
            record.get('ContactId'),
            record.get('LeadId'),
            record.get('Status'),
            record.get('FirstRespondedDate'),
            record.get('CreatedDate'),
            record.get('LastModifiedDate'),
            json.dumps(record)
        ))
    
    conn.commit()
    print(f"   ✅ Backed up {len(records)} CampaignMember records")
    return len(records)


def backup_seminar_applications(conn: sqlite3.Connection, org_alias: str) -> int:
    """Backup Seminar_Application__c records."""
    print("\n📦 Backing up Seminar Applications...")
    
    query = """
        SELECT Id, Name, Applicant__c, Seminar__c, Stage__c, Application_Date__c,
               ExternalID__c, CreatedDate, LastModifiedDate
        FROM Seminar_Application__c
    """
    
    records = run_sf_query(org_alias, query)
    cursor = conn.cursor()
    
    for record in records:
        cursor.execute("""
            INSERT OR REPLACE INTO seminar_applications 
            (sf_id, name, applicant_id, seminar_id, stage, application_date,
             external_id, created_date, last_modified_date, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.get('Id'),
            record.get('Name'),
            record.get('Applicant__c'),
            record.get('Seminar__c'),
            record.get('Stage__c'),
            record.get('Application_Date__c'),
            record.get('ExternalID__c'),
            record.get('CreatedDate'),
            record.get('LastModifiedDate'),
            json.dumps(record)
        ))
    
    conn.commit()
    print(f"   ✅ Backed up {len(records)} Seminar_Application__c records")
    return len(records)


def backup_affiliations(conn: sqlite3.Connection, org_alias: str) -> int:
    """Backup Affiliation__c records."""
    print("\n📦 Backing up Affiliations...")
    
    query = """
        SELECT Id, Name, Contact__c, Affiliated_Account__c, Role__c, Status__c,
               Start_Date__c, End_Date__c, Primary__c, ExternalID__c,
               CreatedDate, LastModifiedDate
        FROM Affiliation__c
    """
    
    records = run_sf_query(org_alias, query)
    cursor = conn.cursor()
    
    for record in records:
        cursor.execute("""
            INSERT OR REPLACE INTO affiliations 
            (sf_id, name, contact_id, affiliated_account_id, role, status,
             start_date, end_date, is_primary, external_id, created_date, last_modified_date, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.get('Id'),
            record.get('Name'),
            record.get('Contact__c'),
            record.get('Affiliated_Account__c'),
            record.get('Role__c'),
            record.get('Status__c'),
            record.get('Start_Date__c'),
            record.get('End_Date__c'),
            1 if record.get('Primary__c') else 0,
            record.get('ExternalID__c'),
            record.get('CreatedDate'),
            record.get('LastModifiedDate'),
            json.dumps(record)
        ))
    
    conn.commit()
    print(f"   ✅ Backed up {len(records)} Affiliation__c records")
    return len(records)


def backup_observerships(conn: sqlite3.Connection, org_alias: str) -> int:
    """Backup Observership__c records."""
    print("\n📦 Backing up Observerships...")
    
    query = """
        SELECT Id, Name, Applicant__c, Status__c, Start_Date__c, End_Date__c,
               Institution__c, Specialty__c, ExternalID__c, CreatedDate, LastModifiedDate
        FROM Observership__c
    """
    
    records = run_sf_query(org_alias, query)
    cursor = conn.cursor()
    
    for record in records:
        cursor.execute("""
            INSERT OR REPLACE INTO observerships 
            (sf_id, name, applicant_id, status, start_date, end_date,
             institution, specialty, external_id, created_date, last_modified_date, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.get('Id'),
            record.get('Name'),
            record.get('Applicant__c'),
            record.get('Status__c'),
            record.get('Start_Date__c'),
            record.get('End_Date__c'),
            record.get('Institution__c'),
            record.get('Specialty__c'),
            record.get('ExternalID__c'),
            record.get('CreatedDate'),
            record.get('LastModifiedDate'),
            json.dumps(record)
        ))
    
    conn.commit()
    print(f"   ✅ Backed up {len(records)} Observership__c records")
    return len(records)


def backup_mexico_seminars(conn: sqlite3.Connection, org_alias: str) -> int:
    """Backup Mexico_Seminars__c records."""
    print("\n📦 Backing up Mexico Seminars...")
    
    query = """
        SELECT Id, Name, Applicant__c, Symposium__c, Status__c, Application_Date__c,
               ExternalID__c, CreatedDate, LastModifiedDate
        FROM Mexico_Seminars__c
    """
    
    records = run_sf_query(org_alias, query)
    cursor = conn.cursor()
    
    for record in records:
        cursor.execute("""
            INSERT OR REPLACE INTO mexico_seminars 
            (sf_id, name, applicant_id, symposium_id, status, application_date,
             external_id, created_date, last_modified_date, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.get('Id'),
            record.get('Name'),
            record.get('Applicant__c'),
            record.get('Symposium__c'),
            record.get('Status__c'),
            record.get('Application_Date__c'),
            record.get('ExternalID__c'),
            record.get('CreatedDate'),
            record.get('LastModifiedDate'),
            json.dumps(record)
        ))
    
    conn.commit()
    print(f"   ✅ Backed up {len(records)} Mexico_Seminars__c records")
    return len(records)


def backup_replicas(conn: sqlite3.Connection, org_alias: str) -> int:
    """Backup Replica__c records."""
    print("\n📦 Backing up Replicas...")
    
    query = """
        SELECT Id, Name, Replica__c, Status__c, ExternalID__c, 
               CreatedDate, LastModifiedDate
        FROM Replica__c
    """
    
    records = run_sf_query(org_alias, query)
    cursor = conn.cursor()
    
    for record in records:
        cursor.execute("""
            INSERT OR REPLACE INTO replicas 
            (sf_id, name, contact_id, status, external_id, created_date, last_modified_date, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.get('Id'),
            record.get('Name'),
            record.get('Replica__c'),
            record.get('Status__c'),
            record.get('ExternalID__c'),
            record.get('CreatedDate'),
            record.get('LastModifiedDate'),
            json.dumps(record)
        ))
    
    conn.commit()
    print(f"   ✅ Backed up {len(records)} Replica__c records")
    return len(records)


def download_file_content(org_alias: str, content_version_id: str) -> Optional[bytes]:
    """
    Download the actual file binary content from Salesforce.
    
    Args:
        org_alias: Salesforce org alias
        content_version_id: ContentVersion ID
        
    Returns:
        File content as bytes, or None if download fails
    """
    # Get org credentials
    cmd = ['sf', 'org', 'display', '--target-org', org_alias, '--json']
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        org_data = json.loads(result.stdout)
        access_token = org_data.get('result', {}).get('accessToken')
        instance_url = org_data.get('result', {}).get('instanceUrl')
        
        if not access_token or not instance_url:
            return None
        
        # Download VersionData using REST API
        url = f"{instance_url}/services/data/v59.0/sobjects/ContentVersion/{content_version_id}/VersionData"
        
        req = urllib.request.Request(url)
        req.add_header('Authorization', f'Bearer {access_token}')
        
        with urllib.request.urlopen(req, timeout=120) as response:
            return response.read()
            
    except Exception as e:
        print(f"      ⚠️  Download failed for {content_version_id}: {str(e)[:100]}")
        return None


def backup_content_versions(conn: sqlite3.Connection, org_alias: str, backup_name: str) -> int:
    """Backup ContentVersion (file metadata + binaries) records."""
    print("\n📦 Backing up Content Versions (File Metadata + Binaries)...")
    
    query = """
        SELECT Id, ContentDocumentId, Title, FileExtension, FileType, ContentSize,
               VersionNumber, IsLatest, FirstPublishLocationId, CreatedDate, LastModifiedDate
        FROM ContentVersion
        WHERE IsLatest = true
    """
    
    records = run_sf_query(org_alias, query)
    cursor = conn.cursor()
    
    # Create files directory for this backup
    backup_files_dir = BACKUPS_DIR / sanitize_filename(backup_name) / 'files'
    backup_files_dir.mkdir(parents=True, exist_ok=True)
    
    downloaded_count = 0
    failed_count = 0
    
    for i, record in enumerate(records, 1):
        content_version_id = record.get('Id')
        title = record.get('Title', 'Unknown')
        file_extension = record.get('FileExtension', '')
        content_size = record.get('ContentSize', 0)
        
        # Determine filename
        if file_extension and not title.lower().endswith(f'.{file_extension.lower()}'):
            filename = f"{title}.{file_extension}"
        else:
            filename = title
        
        # Sanitize filename
        safe_filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        safe_filename = safe_filename.strip('. ')[:200]
        
        file_path = backup_files_dir / safe_filename
        
        # Check if file already exists (resume functionality)
        file_exists = file_path.exists() and file_path.stat().st_size > 0
        file_data = None
        
        if content_size and content_size > 0:
            if file_exists:
                # File already downloaded - skip download but verify size matches
                existing_size = file_path.stat().st_size
                if existing_size == content_size:
                    if i % 50 == 0:
                        print(f"   ⏭️  Skipping existing files... ({i}/{len(records)})")
                    # Read existing file for BLOB storage if small
                    if existing_size < 1024 * 1024:  # < 1MB
                        try:
                            with open(file_path, 'rb') as f:
                                file_data = f.read()
                        except:
                            pass
                    downloaded_count += 1
                else:
                    # Size mismatch - re-download
                    print(f"      ⚠️  Size mismatch for {safe_filename[:50]}... ({existing_size} vs {content_size}), re-downloading")
                    file_exists = False
            
            if not file_exists:
                # Download file content
                if i % 10 == 0:
                    print(f"   📥 Downloading files... ({i}/{len(records)})")
                
                file_data = download_file_content(org_alias, content_version_id)
                
                if file_data:
                    # Save to file system
                    try:
                        with open(file_path, 'wb') as f:
                            f.write(file_data)
                        downloaded_count += 1
                    except Exception as e:
                        print(f"      ⚠️  Failed to save {safe_filename}: {str(e)[:100]}")
                        failed_count += 1
                        file_path = None
                else:
                    failed_count += 1
                    file_path = None
        
        # Store in database (metadata + file path, optionally BLOB for small files)
        # For files > 1MB, store path only; for smaller files, can store BLOB
        store_blob = file_data is not None and len(file_data) < 1024 * 1024  # < 1MB
        
        cursor.execute("""
            INSERT OR REPLACE INTO content_versions 
            (sf_id, content_document_id, title, file_extension, file_type, content_size,
             version_number, is_latest, first_publish_location_id, created_date, last_modified_date,
             file_path, file_data, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.get('Id'),
            record.get('ContentDocumentId'),
            record.get('Title'),
            record.get('FileExtension'),
            record.get('FileType'),
            record.get('ContentSize'),
            record.get('VersionNumber'),
            1 if record.get('IsLatest') else 0,
            record.get('FirstPublishLocationId'),
            record.get('CreatedDate'),
            record.get('LastModifiedDate'),
            str(file_path) if file_path else None,
            file_data if store_blob else None,  # Store BLOB only for small files
            json.dumps(record)
        ))
    
    conn.commit()
    print(f"   ✅ Backed up {len(records)} ContentVersion records")
    print(f"   📥 Downloaded {downloaded_count} files ({failed_count} failed)")
    print(f"   📁 Files stored in: {backup_files_dir}")
    return len(records)


def backup_content_document_links(conn: sqlite3.Connection, org_alias: str) -> int:
    """Backup ContentDocumentLink records."""
    print("\n📦 Backing up Content Document Links...")
    
    # First, get all ContentDocumentIds from ContentVersion
    print("   📋 Getting ContentDocument IDs...")
    cv_query = "SELECT ContentDocumentId FROM ContentVersion WHERE IsLatest = true"
    cv_records = run_sf_query(org_alias, cv_query)
    
    if not cv_records:
        print("   ⚠️  No ContentVersions found, skipping ContentDocumentLinks")
        return 0
    
    # Extract unique ContentDocumentIds
    doc_ids = list(set([r.get('ContentDocumentId') for r in cv_records if r.get('ContentDocumentId')]))
    
    if not doc_ids:
        print("   ⚠️  No ContentDocumentIds found")
        return 0
    
    print(f"   📋 Querying {len(doc_ids)} ContentDocumentLinks...")
    
    # Query in batches (Salesforce limit is typically 2000 for IN clause)
    cursor = conn.cursor()
    total_count = 0
    batch_size = 2000
    
    for i in range(0, len(doc_ids), batch_size):
        batch = doc_ids[i:i+batch_size]
        doc_ids_str = "', '".join(batch)
        
        query = f"""
            SELECT Id, ContentDocumentId, LinkedEntityId, ShareType, Visibility
            FROM ContentDocumentLink
            WHERE ContentDocumentId IN ('{doc_ids_str}')
        """
        
        records = run_sf_query(org_alias, query)
        
        for record in records:
            cursor.execute("""
                INSERT OR REPLACE INTO content_document_links 
                (sf_id, content_document_id, linked_entity_id, share_type, visibility, raw_data)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                record.get('Id'),
                record.get('ContentDocumentId'),
                record.get('LinkedEntityId'),
                record.get('ShareType'),
                record.get('Visibility'),
                json.dumps(record)
            ))
            total_count += 1
        
        conn.commit()
    
    print(f"   ✅ Backed up {total_count} ContentDocumentLink records")
    return total_count
    
    records = run_sf_query(org_alias, query)
    cursor = conn.cursor()
    
    for record in records:
        cursor.execute("""
            INSERT OR REPLACE INTO content_document_links 
            (sf_id, content_document_id, linked_entity_id, share_type, visibility, raw_data)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            record.get('Id'),
            record.get('ContentDocumentId'),
            record.get('LinkedEntityId'),
            record.get('ShareType'),
            record.get('Visibility'),
            json.dumps(record)
        ))
    
    conn.commit()
    print(f"   ✅ Backed up {len(records)} ContentDocumentLink records")
    return len(records)


def run_backup(org_alias: str, backup_name: str, notes: str = None):
    """
    Run a complete backup of the Salesforce org.
    
    Args:
        org_alias: Salesforce org alias
        backup_name: Name/reference for this backup
        notes: Optional notes about this backup
    """
    print(f"\n{'='*60}")
    print(f"🗄️  SALESFORCE FULL BACKUP")
    print(f"{'='*60}")
    print(f"Backup Name: {backup_name}")
    print(f"Org Alias:   {org_alias}")
    print(f"Started:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")
    
    # Get org info
    org_info = get_org_info(org_alias)
    
    # Create backup database
    db_path = get_backup_db_path(backup_name)
    print(f"\n📁 Creating backup database: {db_path}")
    
    if db_path.exists():
        print(f"   ⚠️  Database already exists. It will be updated.")
    
    conn = init_backup_database(db_path)
    cursor = conn.cursor()
    
    # Record backup metadata
    cursor.execute("""
        INSERT INTO backup_metadata (backup_name, org_alias, org_id, org_instance_url, notes)
        VALUES (?, ?, ?, ?, ?)
    """, (
        backup_name, 
        org_alias, 
        org_info.get('id'),
        org_info.get('instanceUrl'),
        notes
    ))
    backup_id = cursor.lastrowid
    conn.commit()
    
    # Run all backup operations
    total_records = 0
    total_objects = 0
    
    try:
        # Core objects
        count = backup_accounts(conn, org_alias)
        total_records += count
        total_objects += 1
        
        count = backup_contacts(conn, org_alias)
        total_records += count
        total_objects += 1
        
        count = backup_campaigns(conn, org_alias)
        total_records += count
        total_objects += 1
        
        count = backup_campaign_members(conn, org_alias)
        total_records += count
        total_objects += 1
        
        count = backup_seminar_applications(conn, org_alias)
        total_records += count
        total_objects += 1
        
        # Custom objects
        count = backup_affiliations(conn, org_alias)
        total_records += count
        total_objects += 1
        
        count = backup_observerships(conn, org_alias)
        total_records += count
        total_objects += 1
        
        count = backup_mexico_seminars(conn, org_alias)
        total_records += count
        total_objects += 1
        
        count = backup_replicas(conn, org_alias)
        total_records += count
        total_objects += 1
        
        # File metadata + binaries
        count = backup_content_versions(conn, org_alias, backup_name)
        total_records += count
        total_objects += 1
        
        count = backup_content_document_links(conn, org_alias)
        total_records += count
        total_objects += 1
        
        # Update backup metadata with completion info
        cursor.execute("""
            UPDATE backup_metadata 
            SET completed_at = CURRENT_TIMESTAMP,
                status = 'completed',
                total_objects = ?,
                total_records = ?
            WHERE id = ?
        """, (total_objects, total_records, backup_id))
        conn.commit()
        
        print(f"\n{'='*60}")
        print(f"✅ BACKUP COMPLETED SUCCESSFULLY")
        print(f"{'='*60}")
        print(f"Total Objects: {total_objects}")
        print(f"Total Records: {total_records:,}")
        print(f"Database:      {db_path}")
        print(f"Size:          {db_path.stat().st_size / 1024 / 1024:.2f} MB")
        print(f"Completed:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"{'='*60}\n")
        
    except Exception as e:
        # Update backup metadata with error
        cursor.execute("""
            UPDATE backup_metadata 
            SET status = 'failed',
                notes = ?
            WHERE id = ?
        """, (str(e), backup_id))
        conn.commit()
        
        print(f"\n❌ BACKUP FAILED: {e}")
        raise
    finally:
        conn.close()


def list_backups():
    """List all available backups."""
    print(f"\n{'='*60}")
    print("📋 AVAILABLE BACKUPS")
    print(f"{'='*60}")
    
    if not BACKUPS_DIR.exists():
        print("No backups found.")
        return
    
    backups = list(BACKUPS_DIR.glob('*.db'))
    
    if not backups:
        print("No backups found.")
        return
    
    for db_path in sorted(backups, key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute("SELECT * FROM backup_metadata ORDER BY created_at DESC LIMIT 1")
            metadata = cursor.fetchone()
            
            if metadata:
                print(f"\n📁 {db_path.name}")
                print(f"   Name:     {metadata['backup_name']}")
                print(f"   Org:      {metadata['org_alias']}")
                print(f"   Status:   {metadata['status']}")
                print(f"   Created:  {metadata['created_at']}")
                print(f"   Records:  {metadata['total_records']:,}")
                print(f"   Size:     {db_path.stat().st_size / 1024 / 1024:.2f} MB")
            
            conn.close()
        except Exception as e:
            print(f"\n📁 {db_path.name} (error reading metadata: {e})")


def show_backup_summary(backup_name: str):
    """Show detailed summary of a backup."""
    db_path = get_backup_db_path(backup_name)
    
    if not db_path.exists():
        print(f"Backup not found: {backup_name}")
        return
    
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Get metadata
    cursor.execute("SELECT * FROM backup_metadata ORDER BY created_at DESC LIMIT 1")
    metadata = cursor.fetchone()
    
    print(f"\n{'='*60}")
    print(f"📊 BACKUP SUMMARY: {backup_name}")
    print(f"{'='*60}")
    print(f"Status:      {metadata['status']}")
    print(f"Org:         {metadata['org_alias']}")
    print(f"Created:     {metadata['created_at']}")
    print(f"Completed:   {metadata['completed_at']}")
    print(f"\nObject Counts:")
    print(f"{'='*60}")
    
    tables = [
        ('accounts', 'Account'),
        ('contacts', 'Contact'),
        ('campaigns', 'Campaign'),
        ('campaign_members', 'CampaignMember'),
        ('seminar_applications', 'Seminar_Application__c'),
        ('affiliations', 'Affiliation__c'),
        ('observerships', 'Observership__c'),
        ('mexico_seminars', 'Mexico_Seminars__c'),
        ('replicas', 'Replica__c'),
        ('content_versions', 'ContentVersion'),
        ('content_document_links', 'ContentDocumentLink')
    ]
    
    total = 0
    for table, label in tables:
        cursor.execute(f"SELECT COUNT(*) as cnt FROM {table}")
        count = cursor.fetchone()['cnt']
        total += count
        print(f"  {label:<30} {count:>10,}")
    
    print(f"{'='*60}")
    print(f"  {'TOTAL':<30} {total:>10,}")
    print(f"{'='*60}")
    
    conn.close()


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python backup_salesforce.py <org_alias> <backup_name> [notes]")
        print("  python backup_salesforce.py --list")
        print("  python backup_salesforce.py --summary <backup_name>")
        print("\nExamples:")
        print('  python backup_salesforce.py "AMSA-Royalty-Prod" "AMSA Enero-2026"')
        print('  python backup_salesforce.py "AMSA-Royalty-Prod" "Pre-Migration" "Before migration to new org"')
        print('  python backup_salesforce.py --list')
        print('  python backup_salesforce.py --summary "AMSA Enero-2026"')
        sys.exit(1)
    
    if sys.argv[1] == '--list':
        list_backups()
    elif sys.argv[1] == '--summary':
        if len(sys.argv) < 3:
            print("Please provide a backup name")
            sys.exit(1)
        show_backup_summary(sys.argv[2])
    else:
        org_alias = sys.argv[1]
        backup_name = sys.argv[2] if len(sys.argv) > 2 else f"Backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        notes = sys.argv[3] if len(sys.argv) > 3 else None
        
        run_backup(org_alias, backup_name, notes)


if __name__ == '__main__':
    main()
