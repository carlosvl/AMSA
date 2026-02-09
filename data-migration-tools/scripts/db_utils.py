#!/usr/bin/env python3
"""
Database Utilities for Migration Results

Provides a shared interface for storing and retrieving migration results in SQLite.
All migration scripts should use these functions for consistency.
"""

import sqlite3
import json
import csv
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional, Any
from contextlib import contextmanager

# Database location
BASE_DIR = Path(__file__).resolve().parents[1]
DB_PATH = BASE_DIR / 'migration_results.db'


@contextmanager
def get_connection():
    """
    Get a database connection with proper configuration.
    
    Yields:
        sqlite3.Connection: Database connection
    """
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row  # Enable column access by name
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_database():
    """
    Initialize the database with all required tables and indexes.
    Safe to call multiple times (uses IF NOT EXISTS).
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # comparison_runs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS comparison_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_type TEXT NOT NULL,
                source_org TEXT,
                target_org TEXT,
                start_date TEXT,
                end_date TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                total_source_records INTEGER DEFAULT 0,
                total_target_records INTEGER DEFAULT 0,
                matched_count INTEGER DEFAULT 0,
                unmatched_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'in_progress',
                notes TEXT
            )
        """)
        
        # campaign_matches table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS campaign_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                source_id TEXT,
                target_id TEXT,
                source_name TEXT,
                target_name TEXT,
                match_type TEXT,
                source_type TEXT,
                target_type TEXT,
                source_status TEXT,
                target_status TEXT,
                source_contacts INTEGER,
                target_contacts INTEGER,
                created_date DATETIME,
                FOREIGN KEY (run_id) REFERENCES comparison_runs(id)
            )
        """)
        
        # contact_matches table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contact_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                source_id TEXT,
                target_id TEXT,
                match_type TEXT,
                email TEXT,
                first_name TEXT,
                last_name TEXT,
                FOREIGN KEY (run_id) REFERENCES comparison_runs(id)
            )
        """)
        
        # seminar_application_matches table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS seminar_application_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                record_id TEXT,
                applicant_id TEXT,
                seminar_id TEXT,
                match_status TEXT,
                stage TEXT,
                app_date DATE,
                is_duplicate BOOLEAN DEFAULT 0,
                action_taken TEXT,
                FOREIGN KEY (run_id) REFERENCES comparison_runs(id)
            )
        """)
        
        # campaign_member_matches table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS campaign_member_matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                source_id TEXT,
                target_id TEXT,
                campaign_id TEXT,
                contact_id TEXT,
                match_status TEXT,
                status TEXT,
                FOREIGN KEY (run_id) REFERENCES comparison_runs(id)
            )
        """)
        
        # file_comparisons table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_comparisons (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                source_file_id TEXT,
                target_file_id TEXT,
                parent_record_id TEXT,
                file_name TEXT,
                file_size INTEGER,
                match_status TEXT,
                migration_status TEXT,
                FOREIGN KEY (run_id) REFERENCES comparison_runs(id)
            )
        """)
        
        # id_mappings table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS id_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                object_type TEXT NOT NULL,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                created_date DATETIME DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(object_type, source_id)
            )
        """)
        
        # duplicate_groups table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS duplicate_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                object_type TEXT,
                group_key TEXT,
                record_count INTEGER,
                action TEXT,
                FOREIGN KEY (run_id) REFERENCES comparison_runs(id)
            )
        """)
        
        # duplicate_records table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS duplicate_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL,
                record_id TEXT,
                is_keeper BOOLEAN DEFAULT 0,
                last_modified DATETIME,
                delete_status TEXT,
                FOREIGN KEY (group_id) REFERENCES duplicate_groups(id)
            )
        """)
        
        # merge_operations table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS merge_operations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                group_id INTEGER NOT NULL,
                master_id TEXT NOT NULL,
                merged_ids TEXT,
                status TEXT NOT NULL,
                error TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES comparison_runs(id),
                FOREIGN KEY (group_id) REFERENCES duplicate_groups(id)
            )
        """)
        
        # Create indexes
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_comparison_runs_type_timestamp 
            ON comparison_runs(run_type, timestamp)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_campaign_matches_run_id 
            ON campaign_matches(run_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_campaign_matches_match_type 
            ON campaign_matches(match_type)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_contact_matches_run_id 
            ON contact_matches(run_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_seminar_app_matches_run_id 
            ON seminar_application_matches(run_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_seminar_app_matches_status 
            ON seminar_application_matches(match_status)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_campaign_member_matches_run_id 
            ON campaign_member_matches(run_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_file_comparisons_run_id 
            ON file_comparisons(run_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_id_mappings_object_source 
            ON id_mappings(object_type, source_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_id_mappings_object_target 
            ON id_mappings(object_type, target_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_duplicate_groups_run_id 
            ON duplicate_groups(run_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_duplicate_records_group_id 
            ON duplicate_records(group_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_merge_operations_run_id 
            ON merge_operations(run_id)
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_merge_operations_group_id 
            ON merge_operations(group_id)
        """)


def create_comparison_run(
    run_type: str,
    source_org: Optional[str] = None,
    target_org: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    notes: Optional[str] = None
) -> int:
    """
    Create a new comparison run record.
    
    Args:
        run_type: Type of comparison (e.g., 'campaign_comparison')
        source_org: Source org alias
        target_org: Target org alias
        start_date: Start date filter (if applicable)
        end_date: End date filter (if applicable)
        notes: Additional notes
        
    Returns:
        int: The ID of the created run
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO comparison_runs 
            (run_type, source_org, target_org, start_date, end_date, notes)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (run_type, source_org, target_org, start_date, end_date, notes))
        return cursor.lastrowid


def update_comparison_run(
    run_id: int,
    total_source_records: Optional[int] = None,
    total_target_records: Optional[int] = None,
    matched_count: Optional[int] = None,
    unmatched_count: Optional[int] = None,
    status: Optional[str] = None,
    notes: Optional[str] = None
):
    """
    Update statistics for a comparison run.
    
    Args:
        run_id: ID of the run to update
        total_source_records: Total records in source org
        total_target_records: Total records in target org
        matched_count: Number of matched records
        unmatched_count: Number of unmatched records
        status: Run status ('completed', 'failed', 'in_progress')
        notes: Additional notes to append
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        
        updates = []
        params = []
        
        if total_source_records is not None:
            updates.append("total_source_records = ?")
            params.append(total_source_records)
        
        if total_target_records is not None:
            updates.append("total_target_records = ?")
            params.append(total_target_records)
        
        if matched_count is not None:
            updates.append("matched_count = ?")
            params.append(matched_count)
        
        if unmatched_count is not None:
            updates.append("unmatched_count = ?")
            params.append(unmatched_count)
        
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        
        if notes is not None:
            updates.append("notes = ?")
            params.append(notes)
        
        if updates:
            params.append(run_id)
            query = f"UPDATE comparison_runs SET {', '.join(updates)} WHERE id = ?"
            cursor.execute(query, params)


def save_campaign_matches(run_id: int, matches: List[Dict[str, Any]]):
    """
    Save campaign comparison matches.
    
    Args:
        run_id: ID of the comparison run
        matches: List of match dictionaries
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        
        for match in matches:
            cursor.execute("""
                INSERT INTO campaign_matches 
                (run_id, source_id, target_id, source_name, target_name, match_type,
                 source_type, target_type, source_status, target_status,
                 source_contacts, target_contacts, created_date)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id,
                match.get('source_id'),
                match.get('target_id'),
                match.get('source_name'),
                match.get('target_name'),
                match.get('match_type'),
                match.get('source_type'),
                match.get('target_type'),
                match.get('source_status'),
                match.get('target_status'),
                match.get('source_contacts'),
                match.get('target_contacts'),
                match.get('source_created')
            ))


def save_contact_matches(run_id: int, matches: List[Dict[str, Any]]):
    """
    Save contact comparison matches.
    
    Args:
        run_id: ID of the comparison run
        matches: List of match dictionaries
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        
        for match in matches:
            cursor.execute("""
                INSERT INTO contact_matches 
                (run_id, source_id, target_id, match_type, email, first_name, last_name)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id,
                match.get('source_id'),
                match.get('target_id'),
                match.get('match_type'),
                match.get('email'),
                match.get('first_name'),
                match.get('last_name')
            ))


def save_seminar_app_matches(run_id: int, matches: List[Dict[str, Any]]):
    """
    Save seminar application comparison matches.
    
    Args:
        run_id: ID of the comparison run
        matches: List of match dictionaries
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        
        for match in matches:
            cursor.execute("""
                INSERT INTO seminar_application_matches 
                (run_id, record_id, applicant_id, seminar_id, match_status,
                 stage, app_date, is_duplicate, action_taken)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id,
                match.get('id') or match.get('record_id'),
                match.get('applicant_id'),
                match.get('seminar_id'),
                match.get('match_status'),
                match.get('stage'),
                match.get('app_date'),
                match.get('is_duplicate', 0),
                match.get('action_taken', 'none')
            ))


def save_campaign_member_matches(run_id: int, matches: List[Dict[str, Any]]):
    """
    Save campaign member comparison matches.
    
    Args:
        run_id: ID of the comparison run
        matches: List of match dictionaries
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        
        for match in matches:
            cursor.execute("""
                INSERT INTO campaign_member_matches 
                (run_id, source_id, target_id, campaign_id, contact_id, match_status, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id,
                match.get('source_id'),
                match.get('target_id'),
                match.get('campaign_id'),
                match.get('contact_id'),
                match.get('match_status'),
                match.get('status')
            ))


def save_file_comparisons(run_id: int, comparisons: List[Dict[str, Any]]):
    """
    Save file/attachment comparison results.
    
    Args:
        run_id: ID of the comparison run
        comparisons: List of comparison dictionaries
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        
        for comp in comparisons:
            cursor.execute("""
                INSERT INTO file_comparisons 
                (run_id, source_file_id, target_file_id, parent_record_id,
                 file_name, file_size, match_status, migration_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id,
                comp.get('source_file_id'),
                comp.get('target_file_id'),
                comp.get('parent_record_id'),
                comp.get('file_name'),
                comp.get('file_size'),
                comp.get('match_status'),
                comp.get('migration_status')
            ))


def save_duplicate_group(
    run_id: int,
    object_type: str,
    group_key: str,
    records: List[Dict[str, Any]],
    action: str = 'pending'
) -> int:
    """
    Save a duplicate group and its records.
    
    Args:
        run_id: ID of the comparison run
        object_type: Type of object (e.g., 'Seminar_Application__c')
        group_key: Hash/key identifying the duplicate group
        records: List of duplicate records
        action: Action taken ('deleted', 'kept', 'pending')
        
    Returns:
        int: The ID of the created duplicate group
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Create duplicate group
        cursor.execute("""
            INSERT INTO duplicate_groups 
            (run_id, object_type, group_key, record_count, action)
            VALUES (?, ?, ?, ?, ?)
        """, (run_id, object_type, group_key, len(records), action))
        
        group_id = cursor.lastrowid
        
        # Add individual records
        for record in records:
            cursor.execute("""
                INSERT INTO duplicate_records 
                (group_id, record_id, is_keeper, last_modified, delete_status)
                VALUES (?, ?, ?, ?, ?)
            """, (
                group_id,
                record.get('Id') or record.get('record_id'),
                record.get('is_keeper', 0),
                record.get('LastModifiedDate') or record.get('last_modified'),
                record.get('delete_status')
            ))
        
        return group_id


def update_id_mapping(object_type: str, source_id: str, target_id: str):
    """
    Insert or update an ID mapping between orgs.
    
    Args:
        object_type: Type of object (e.g., 'Contact', 'Campaign')
        source_id: Source org record ID
        target_id: Target org record ID
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO id_mappings (object_type, source_id, target_id)
            VALUES (?, ?, ?)
            ON CONFLICT(object_type, source_id) 
            DO UPDATE SET target_id = excluded.target_id
        """, (object_type, source_id, target_id))


def bulk_update_id_mappings(object_type: str, mappings: Dict[str, str]):
    """
    Bulk insert/update ID mappings.
    
    Args:
        object_type: Type of object
        mappings: Dictionary of {source_id: target_id}
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        for source_id, target_id in mappings.items():
            cursor.execute("""
                INSERT INTO id_mappings (object_type, source_id, target_id)
                VALUES (?, ?, ?)
                ON CONFLICT(object_type, source_id) 
                DO UPDATE SET target_id = excluded.target_id
            """, (object_type, source_id, target_id))


def get_id_mappings(object_type: str) -> Dict[str, str]:
    """
    Get all ID mappings for a given object type.
    
    Args:
        object_type: Type of object
        
    Returns:
        Dictionary of {source_id: target_id}
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT source_id, target_id 
            FROM id_mappings 
            WHERE object_type = ?
        """, (object_type,))
        
        return {row['source_id']: row['target_id'] for row in cursor.fetchall()}


def export_run_to_json(run_id: int, output_path: Path):
    """
    Export a comparison run and its results to JSON format.
    
    Args:
        run_id: ID of the run to export
        output_path: Path where JSON should be written
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Get run metadata
        cursor.execute("SELECT * FROM comparison_runs WHERE id = ?", (run_id,))
        run = dict(cursor.fetchone())
        
        # Get matches based on run type
        run_type = run['run_type']
        results = {}
        
        if 'campaign' in run_type:
            cursor.execute("SELECT * FROM campaign_matches WHERE run_id = ?", (run_id,))
            results['campaign_matches'] = [dict(row) for row in cursor.fetchall()]
        
        if 'contact' in run_type:
            cursor.execute("SELECT * FROM contact_matches WHERE run_id = ?", (run_id,))
            results['contact_matches'] = [dict(row) for row in cursor.fetchall()]
        
        if 'seminar' in run_type:
            cursor.execute("SELECT * FROM seminar_application_matches WHERE run_id = ?", (run_id,))
            results['seminar_application_matches'] = [dict(row) for row in cursor.fetchall()]
        
        # Combine and write
        export_data = {
            'metadata': run,
            'results': results
        }
        
        with open(output_path, 'w') as f:
            json.dump(export_data, f, indent=2, default=str)


def export_run_to_csv(run_id: int, output_dir: Path):
    """
    Export a comparison run results to CSV files.
    
    Args:
        run_id: ID of the run to export
        output_dir: Directory where CSV files should be written
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Get run metadata
        cursor.execute("SELECT run_type FROM comparison_runs WHERE id = ?", (run_id,))
        run_type = cursor.fetchone()['run_type']
        
        # Export campaign matches
        if 'campaign' in run_type:
            cursor.execute("SELECT * FROM campaign_matches WHERE run_id = ?", (run_id,))
            rows = cursor.fetchall()
            if rows:
                csv_path = output_dir / f'campaign_matches_{run_id}.csv'
                with open(csv_path, 'w', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows([dict(row) for row in rows])
        
        # Export contact matches
        if 'contact' in run_type:
            cursor.execute("SELECT * FROM contact_matches WHERE run_id = ?", (run_id,))
            rows = cursor.fetchall()
            if rows:
                csv_path = output_dir / f'contact_matches_{run_id}.csv'
                with open(csv_path, 'w', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows([dict(row) for row in rows])
        
        # Export seminar application matches
        if 'seminar' in run_type:
            cursor.execute("SELECT * FROM seminar_application_matches WHERE run_id = ?", (run_id,))
            rows = cursor.fetchall()
            if rows:
                csv_path = output_dir / f'seminar_application_matches_{run_id}.csv'
                with open(csv_path, 'w', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows([dict(row) for row in rows])


def get_duplicate_groups(run_id=None, object_type='Contact', pending_only=True):
    """
    Retrieve duplicate groups with their records.
    
    Args:
        run_id: Optional run ID to filter by
        object_type: Type of object (default: 'Contact')
        pending_only: If True, only return groups with action='pending'
        
    Returns:
        List of dictionaries, each containing:
        - group_id: ID of the duplicate group
        - run_id: Run ID
        - group_key: Group key
        - record_count: Number of records in group
        - action: Current action status
        - records: List of record dictionaries with Id, is_keeper, last_modified
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        
        query = """
            SELECT dg.id as group_id, dg.run_id, dg.object_type, dg.group_key, 
                   dg.record_count, dg.action,
                   dr.id as record_db_id, dr.record_id, dr.is_keeper, dr.last_modified, dr.delete_status
            FROM duplicate_groups dg
            LEFT JOIN duplicate_records dr ON dg.id = dr.group_id
            WHERE dg.object_type = ?
        """
        params = [object_type]
        
        if pending_only:
            query += " AND dg.action = 'pending'"
        
        if run_id:
            query += " AND dg.run_id = ?"
            params.append(run_id)
        
        query += " ORDER BY dg.record_count DESC, dr.last_modified DESC"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        # Group records by duplicate group
        groups = {}
        for row in rows:
            group_id = row['group_id']
            if group_id not in groups:
                groups[group_id] = {
                    'group_id': group_id,
                    'run_id': row['run_id'],
                    'object_type': row['object_type'],
                    'group_key': row['group_key'],
                    'record_count': row['record_count'],
                    'action': row['action'],
                    'records': []
                }
            
            if row['record_id']:  # Some groups might not have records yet
                groups[group_id]['records'].append({
                    'Id': row['record_id'],
                    'is_keeper': bool(row['is_keeper']),
                    'last_modified': row['last_modified'],
                    'delete_status': row['delete_status']
                })
        
        return list(groups.values())


def update_duplicate_group_action(group_id, action):
    """
    Update action status for a duplicate group.
    
    Args:
        group_id: ID of the duplicate group
        action: New action status ('pending', 'merged', 'skipped', etc.)
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE duplicate_groups 
            SET action = ? 
            WHERE id = ?
        """, (action, group_id))


def save_merge_result(run_id, group_id, master_id, merged_ids, status, error=None):
    """
    Save merge operation result to database.
    
    Args:
        run_id: ID of the comparison run
        group_id: ID of the duplicate group
        master_id: ID of the master record (kept)
        merged_ids: List of IDs that were merged into master
        status: 'success' or 'failed'
        error: Error message if status is 'failed'
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        
        # Check if merge_operations table exists, create if not
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS merge_operations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                group_id INTEGER NOT NULL,
                master_id TEXT NOT NULL,
                merged_ids TEXT,  -- JSON array of merged record IDs
                status TEXT NOT NULL,
                error TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (run_id) REFERENCES comparison_runs(id),
                FOREIGN KEY (group_id) REFERENCES duplicate_groups(id)
            )
        """)
        
        # Insert merge result
        merged_ids_json = json.dumps(merged_ids) if merged_ids else '[]'
        cursor.execute("""
            INSERT INTO merge_operations 
            (run_id, group_id, master_id, merged_ids, status, error)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (run_id, group_id, master_id, merged_ids_json, status, error))
        
        return cursor.lastrowid


# Initialize database on import
init_database()
