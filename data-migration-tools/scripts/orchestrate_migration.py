#!/usr/bin/env python3
"""
Migration Orchestrator - Master Script for Full Data Migration

This script orchestrates the complete migration workflow between Salesforce orgs.
It runs all comparison and migration scripts in the correct dependency order,
tracks progress, and supports resuming from failures.

Migration Order (dependency chain):
1. Account (parent records) 
2. Contact (linked to Account)
3. Campaign (independent)
4. CampaignMember (needs Contact + Campaign)
5. Seminar_Application__c (needs Contact + Campaign)
6. Affiliation__c (needs Contact + Account)
7. Observership__c (needs Contact)
8. Mexico_Seminars__c (needs Contact + Campaign)
9. Replica__c (needs Contact)
10. Files for all objects

Usage:
  python3 orchestrate_migration.py <source_org> <target_org> [--phase N] [--dry-run] [--skip-files]

Examples:
  python3 orchestrate_migration.py "AMSA-Royalty-Prod" "AMSA Prod"
  python3 orchestrate_migration.py "AMSA-Royalty-Prod" "AMSA Prod" --phase 2
  python3 orchestrate_migration.py "AMSA-Royalty-Prod" "AMSA Prod" --dry-run
"""

import json
import subprocess
import sys
import argparse
import time
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple

import db_utils

BASE_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = BASE_DIR / 'scripts'
RESULTS_DIR = BASE_DIR / 'results'


# Migration phases in dependency order
MIGRATION_PHASES = [
    {
        'phase': 1,
        'name': 'Account Migration',
        'description': 'Compare and migrate Account records',
        'compare_script': 'compare_accounts.py',
        'upsert_script': 'upsert_accounts.py',
        'object_type': 'Account',
        'dependencies': [],
    },
    {
        'phase': 2,
        'name': 'Contact Migration',
        'description': 'Compare and sync Contact records with ExternalID__c',
        'compare_script': 'compare_contacts.py',
        'upsert_script': 'update_external_ids.py',  # Existing script
        'object_type': 'Contact',
        'dependencies': ['Account'],
    },
    {
        'phase': 3,
        'name': 'Campaign Migration',
        'description': 'Compare and sync Campaign records',
        'compare_script': 'compare_campaigns.py',
        'upsert_script': 'update_campaign_external_ids.py',  # Existing script
        'object_type': 'Campaign',
        'dependencies': [],
    },
    {
        'phase': 4,
        'name': 'CampaignMember Migration',
        'description': 'Compare and create missing CampaignMember records',
        'compare_script': 'compare_campaign_members.py',
        'upsert_script': 'create_missing_campaign_members.py',
        'object_type': 'CampaignMember',
        'dependencies': ['Contact', 'Campaign'],
    },
    {
        'phase': 5,
        'name': 'Seminar Application Migration',
        'description': 'Compare and upsert Seminar_Application__c records',
        'compare_script': 'compare_seminar_applications.py',
        'upsert_script': 'upsert_seminar_applications.py',
        'object_type': 'Seminar_Application__c',
        'dependencies': ['Contact', 'Campaign'],
    },
    {
        'phase': 6,
        'name': 'Affiliation Migration',
        'description': 'Compare and upsert Affiliation__c records',
        'compare_script': 'compare_affiliations.py',
        'upsert_script': 'upsert_affiliations.py',
        'object_type': 'Affiliation__c',
        'dependencies': ['Contact', 'Account'],
    },
    {
        'phase': 7,
        'name': 'Observership Migration',
        'description': 'Compare and upsert Observership__c records',
        'compare_script': 'compare_observerships.py',
        'upsert_script': 'upsert_observerships.py',
        'object_type': 'Observership__c',
        'dependencies': ['Contact'],
    },
    {
        'phase': 8,
        'name': 'Mexico Seminars Migration',
        'description': 'Compare and upsert Mexico_Seminars__c records',
        'compare_script': 'compare_mexico_seminars.py',
        'upsert_script': 'upsert_mexico_seminars.py',
        'object_type': 'Mexico_Seminars__c',
        'dependencies': ['Contact', 'Campaign'],
    },
    {
        'phase': 9,
        'name': 'Replica Migration',
        'description': 'Compare and upsert Replica__c records',
        'compare_script': 'compare_replicas.py',
        'upsert_script': 'upsert_replicas.py',
        'object_type': 'Replica__c',
        'dependencies': ['Contact'],
    },
    {
        'phase': 10,
        'name': 'File Migration',
        'description': 'Migrate files for all objects',
        'compare_script': None,
        'upsert_script': 'migrate_object_files.py',
        'object_type': 'Files',
        'dependencies': ['Contact', 'Account', 'Campaign'],
        'file_objects': ['Contact', 'Account', 'Campaign'],  # Objects to migrate files for
    },
]


def print_banner(text: str, char: str = '='):
    """Print a banner with text."""
    print(f"\n{char * 80}")
    print(f"  {text}")
    print(f"{char * 80}\n")


def run_script(script_name: str, args: List[str], dry_run: bool = False) -> Tuple[int, str]:
    """Run a Python script with arguments."""
    script_path = SCRIPTS_DIR / script_name
    
    if not script_path.exists():
        return 1, f"Script not found: {script_path}"
    
    cmd = ['python3', str(script_path)] + args
    
    if dry_run:
        print(f"  [DRY RUN] Would execute: {' '.join(cmd)}")
        return 0, "Dry run - skipped"
    
    print(f"  Executing: {' '.join(cmd)}")
    print()
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=False,  # Show output in real-time
            text=True,
            timeout=3600,  # 1 hour timeout
            cwd=str(SCRIPTS_DIR)
        )
        return result.returncode, ""
    except subprocess.TimeoutExpired:
        return 1, "Script timed out after 1 hour"
    except Exception as e:
        return 1, str(e)


def check_dependencies(phase: Dict, source_org: str, target_org: str) -> Tuple[bool, str]:
    """Check if dependencies for a phase are met."""
    for dep_type in phase.get('dependencies', []):
        mappings = db_utils.get_id_mappings(dep_type)
        if not mappings:
            return False, f"Missing {dep_type} mappings. Run phase for {dep_type} first."
    return True, ""


def run_compare_phase(phase: Dict, source_org: str, target_org: str, dry_run: bool) -> bool:
    """Run the comparison script for a phase."""
    if not phase.get('compare_script'):
        return True
    
    print(f"📊 Running comparison: {phase['compare_script']}")
    
    args = [source_org, target_org]
    if phase['object_type'] in ['Contact', 'Campaign', 'Account']:
        args.append('2020-01-01')  # Start date for filtering
    args.append('--export-json')
    
    returncode, error = run_script(phase['compare_script'], args, dry_run)
    
    if returncode != 0:
        print(f"  ❌ Comparison failed: {error}")
        return False
    
    print(f"  ✅ Comparison completed")
    return True


def run_upsert_phase(phase: Dict, source_org: str, target_org: str, dry_run: bool) -> bool:
    """Run the upsert/migration script for a phase."""
    if not phase.get('upsert_script'):
        return True
    
    print(f"🔄 Running upsert: {phase['upsert_script']}")
    
    # Special handling for different script types
    script_name = phase['upsert_script']
    
    if script_name == 'update_external_ids.py':
        # This script needs the comparison results file
        # Find most recent comparison file
        results_files = list(RESULTS_DIR.glob('contact_comparison_*.json'))
        if not results_files:
            print(f"  ⚠️  No comparison results found, skipping upsert")
            return True
        latest_file = max(results_files, key=lambda p: p.stat().st_mtime)
        args = [str(latest_file), target_org, 'individual', '--yes']
    elif script_name == 'create_missing_campaign_members.py':
        # Find most recent comparison file
        results_files = list(RESULTS_DIR.glob('campaign_member_comparison_*.json'))
        if not results_files:
            print(f"  ⚠️  No comparison results found, skipping upsert")
            return True
        latest_file = max(results_files, key=lambda p: p.stat().st_mtime)
        args = [str(latest_file), target_org]
    elif script_name == 'migrate_object_files.py':
        # File migration - run for each object type
        for obj_type in phase.get('file_objects', ['Contact']):
            print(f"\n  📁 Migrating files for {obj_type}...")
            file_args = [source_org, target_org, obj_type, '--batch-size', '25']
            if dry_run:
                file_args.append('--dry-run')
            returncode, error = run_script(script_name, file_args, False)  # Don't skip for dry_run
            if returncode != 0:
                print(f"  ⚠️  File migration for {obj_type} had issues: {error}")
        return True
    else:
        # Standard upsert script
        args = [source_org, target_org]
        if dry_run:
            args.append('--dry-run')
    
    returncode, error = run_script(script_name, args, dry_run if script_name != 'migrate_object_files.py' else False)
    
    if returncode != 0:
        print(f"  ❌ Upsert failed: {error}")
        return False
    
    print(f"  ✅ Upsert completed")
    return True


def run_phase(phase: Dict, source_org: str, target_org: str, dry_run: bool) -> bool:
    """Run a complete migration phase (compare + upsert)."""
    print_banner(f"PHASE {phase['phase']}: {phase['name']}", '=')
    print(f"Description: {phase['description']}")
    print(f"Object Type: {phase['object_type']}")
    print(f"Dependencies: {', '.join(phase.get('dependencies', [])) or 'None'}")
    print()
    
    # Check dependencies
    deps_ok, deps_error = check_dependencies(phase, source_org, target_org)
    if not deps_ok:
        print(f"⚠️  Dependency check failed: {deps_error}")
        return False
    
    # Run comparison
    if not run_compare_phase(phase, source_org, target_org, dry_run):
        return False
    
    # Run upsert
    if not run_upsert_phase(phase, source_org, target_org, dry_run):
        return False
    
    print_banner(f"✅ PHASE {phase['phase']} COMPLETED", '-')
    return True


def save_progress(progress: Dict):
    """Save migration progress to file."""
    progress_file = RESULTS_DIR / 'migration_progress.json'
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    progress_file.write_text(json.dumps(progress, indent=2))


def load_progress() -> Dict:
    """Load migration progress from file."""
    progress_file = RESULTS_DIR / 'migration_progress.json'
    if progress_file.exists():
        return json.loads(progress_file.read_text())
    return {'completed_phases': [], 'last_run': None}


def main():
    print_banner("🚀 SALESFORCE DATA MIGRATION ORCHESTRATOR", '═')
    
    parser = argparse.ArgumentParser(
        description='Orchestrate complete data migration between Salesforce orgs'
    )
    parser.add_argument('source_org', help='Source org alias')
    parser.add_argument('target_org', help='Target org alias')
    parser.add_argument('--phase', type=int, help='Start from specific phase (1-10)')
    parser.add_argument('--dry-run', action='store_true',
                        help='Show what would be done without making changes')
    parser.add_argument('--skip-files', action='store_true',
                        help='Skip file migration phase')
    parser.add_argument('--compare-only', action='store_true',
                        help='Only run comparison scripts, skip upserts')
    
    args = parser.parse_args()

    source_org = args.source_org
    target_org = args.target_org
    start_phase = args.phase or 1
    dry_run = args.dry_run
    skip_files = args.skip_files
    compare_only = args.compare_only

    print("📋 Configuration:")
    print(f"  Source Org: {source_org}")
    print(f"  Target Org: {target_org}")
    print(f"  Start Phase: {start_phase}")
    print(f"  Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"  Skip Files: {skip_files}")
    print(f"  Compare Only: {compare_only}")
    print()
    
    # Load previous progress
    progress = load_progress()
    print(f"📊 Previous Progress:")
    print(f"  Completed Phases: {progress.get('completed_phases', [])}")
    print(f"  Last Run: {progress.get('last_run', 'Never')}")
    print()
    
    # Display migration phases
    print("📋 Migration Phases:")
    for phase in MIGRATION_PHASES:
        status = "✅" if phase['phase'] in progress.get('completed_phases', []) else "⬜"
        skip = " (SKIP)" if phase['phase'] == 10 and skip_files else ""
        print(f"  {status} Phase {phase['phase']}: {phase['name']}{skip}")
    print()
    
    if dry_run:
        print("⚠️  DRY RUN MODE - No changes will be made\n")
    
    # Confirm before proceeding
    if not dry_run:
        print("Press Enter to start migration (or Ctrl+C to cancel)...")
        try:
            input()
        except KeyboardInterrupt:
            print("\n❌ Migration cancelled")
            sys.exit(0)
    
    # Run migration phases
    start_time = time.time()
    successful_phases = []
    failed_phase = None
    
    for phase in MIGRATION_PHASES:
        if phase['phase'] < start_phase:
            print(f"⏭️  Skipping Phase {phase['phase']} (before start phase)")
            continue
        
        if phase['phase'] == 10 and skip_files:
            print(f"⏭️  Skipping Phase {phase['phase']} (--skip-files)")
            continue
        
        # For compare-only mode, only run comparison
        if compare_only:
            print_banner(f"PHASE {phase['phase']}: {phase['name']} (Compare Only)", '=')
            if run_compare_phase(phase, source_org, target_org, dry_run):
                successful_phases.append(phase['phase'])
            else:
                failed_phase = phase
                break
        else:
            if run_phase(phase, source_org, target_org, dry_run):
                successful_phases.append(phase['phase'])
                # Update progress
                if not dry_run:
                    progress['completed_phases'] = list(set(
                        progress.get('completed_phases', []) + successful_phases
                    ))
                    progress['last_run'] = datetime.now().isoformat()
                    save_progress(progress)
            else:
                failed_phase = phase
                break
    
    # Summary
    elapsed_time = time.time() - start_time
    print_banner("📊 MIGRATION SUMMARY", '═')
    print(f"Duration: {elapsed_time/60:.1f} minutes")
    print(f"Successful Phases: {successful_phases}")
    print(f"Failed Phase: {failed_phase['phase'] if failed_phase else 'None'}")
    print()
    
    if failed_phase:
        print(f"❌ Migration stopped at Phase {failed_phase['phase']}: {failed_phase['name']}")
        print(f"   To resume, run: python3 orchestrate_migration.py {source_org} {target_org} --phase {failed_phase['phase']}")
        sys.exit(1)
    else:
        print("🎉 Migration completed successfully!")
        
        if compare_only:
            print("\n💡 Next Steps:")
            print(f"   To run full migration with upserts, remove --compare-only flag")
        else:
            print("\n📄 Results saved to: data-migration-tools/results/")
            print(f"   Migration progress: {RESULTS_DIR / 'migration_progress.json'}")


if __name__ == '__main__':
    main()
