-- SQLite Schema for Migration Results Database
-- This file documents the schema; actual creation is done via db_utils.py

-- Track all comparison/migration operations
CREATE TABLE IF NOT EXISTS comparison_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_type TEXT NOT NULL,  -- 'campaign_comparison', 'seminar_app_comparison', etc.
    source_org TEXT,
    target_org TEXT,
    start_date TEXT,  -- For date-filtered queries
    end_date TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    total_source_records INTEGER DEFAULT 0,
    total_target_records INTEGER DEFAULT 0,
    matched_count INTEGER DEFAULT 0,
    unmatched_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'in_progress',  -- 'completed', 'failed', 'in_progress'
    notes TEXT
);

-- Campaign comparison results
CREATE TABLE IF NOT EXISTS campaign_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    source_id TEXT,
    target_id TEXT,
    source_name TEXT,
    target_name TEXT,
    match_type TEXT,  -- 'name', 'external_id', 'not_matched', 'name_mismatch'
    source_type TEXT,
    target_type TEXT,
    source_status TEXT,
    target_status TEXT,
    source_contacts INTEGER,
    target_contacts INTEGER,
    created_date DATETIME,
    FOREIGN KEY (run_id) REFERENCES comparison_runs(id)
);

-- Contact comparison results
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
);

-- Seminar application comparison results
CREATE TABLE IF NOT EXISTS seminar_application_matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    record_id TEXT,
    applicant_id TEXT,
    seminar_id TEXT,
    match_status TEXT,  -- 'matched', 'missing', 'extra'
    stage TEXT,
    app_date DATE,
    is_duplicate BOOLEAN DEFAULT 0,
    action_taken TEXT,  -- 'keep', 'delete', 'none'
    FOREIGN KEY (run_id) REFERENCES comparison_runs(id)
);

-- Campaign member comparison results
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
);

-- File/attachment comparison results
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
);

-- Cross-org ID mappings
CREATE TABLE IF NOT EXISTS id_mappings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    object_type TEXT NOT NULL,  -- 'Contact', 'Campaign', etc.
    source_id TEXT NOT NULL,
    target_id TEXT NOT NULL,
    created_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(object_type, source_id)
);

-- Duplicate record tracking
CREATE TABLE IF NOT EXISTS duplicate_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    object_type TEXT,
    group_key TEXT,  -- Hash of duplicate criteria
    record_count INTEGER,
    action TEXT,  -- 'deleted', 'kept', 'pending'
    FOREIGN KEY (run_id) REFERENCES comparison_runs(id)
);

-- Individual duplicate records
CREATE TABLE IF NOT EXISTS duplicate_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id INTEGER NOT NULL,
    record_id TEXT,
    is_keeper BOOLEAN DEFAULT 0,
    last_modified DATETIME,
    delete_status TEXT,
    FOREIGN KEY (group_id) REFERENCES duplicate_groups(id)
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_comparison_runs_type_timestamp 
    ON comparison_runs(run_type, timestamp);

CREATE INDEX IF NOT EXISTS idx_campaign_matches_run_id 
    ON campaign_matches(run_id);

CREATE INDEX IF NOT EXISTS idx_campaign_matches_match_type 
    ON campaign_matches(match_type);

CREATE INDEX IF NOT EXISTS idx_contact_matches_run_id 
    ON contact_matches(run_id);

CREATE INDEX IF NOT EXISTS idx_seminar_app_matches_run_id 
    ON seminar_application_matches(run_id);

CREATE INDEX IF NOT EXISTS idx_seminar_app_matches_status 
    ON seminar_application_matches(match_status);

CREATE INDEX IF NOT EXISTS idx_campaign_member_matches_run_id 
    ON campaign_member_matches(run_id);

CREATE INDEX IF NOT EXISTS idx_file_comparisons_run_id 
    ON file_comparisons(run_id);

CREATE INDEX IF NOT EXISTS idx_id_mappings_object_source 
    ON id_mappings(object_type, source_id);

CREATE INDEX IF NOT EXISTS idx_id_mappings_object_target 
    ON id_mappings(object_type, target_id);

CREATE INDEX IF NOT EXISTS idx_duplicate_groups_run_id 
    ON duplicate_groups(run_id);

CREATE INDEX IF NOT EXISTS idx_duplicate_records_group_id 
    ON duplicate_records(group_id);

-- Merge operations tracking
CREATE TABLE IF NOT EXISTS merge_operations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER NOT NULL,
    group_id INTEGER NOT NULL,
    master_id TEXT NOT NULL,
    merged_ids TEXT,  -- JSON array of merged record IDs
    status TEXT NOT NULL,  -- 'success', 'failed'
    error TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (run_id) REFERENCES comparison_runs(id),
    FOREIGN KEY (group_id) REFERENCES duplicate_groups(id)
);

CREATE INDEX IF NOT EXISTS idx_merge_operations_run_id 
    ON merge_operations(run_id);

CREATE INDEX IF NOT EXISTS idx_merge_operations_group_id 
    ON merge_operations(group_id);
