#!/usr/bin/env python3
"""
Contact Comparison Tool with SQLite Support
Wrapper around compare_contacts.py that adds database storage
"""
import sys
import argparse
import subprocess
import json
from pathlib import Path
import db_utils

def main():
    parser = argparse.ArgumentParser(description='Compare contacts between orgs')
    parser.add_argument('source_org', help='Source org alias')
    parser.add_argument('target_org', help='Target org alias')
    parser.add_argument('start_date', help='Start date (YYYY-MM-DD)')
    parser.add_argument('end_date', nargs='?', help='End date (optional)')
    parser.add_argument('--export-json', action='store_true')
    parser.add_argument('--export-csv', action='store_true')
    
    args = parser.parse_args()
    
    print("💾 Initializing database...")
    run_id = db_utils.create_comparison_run(
        run_type='contact_comparison',
        source_org=args.source_org,
        target_org=args.target_org,
        start_date=args.start_date,
        end_date=args.end_date
    )
    print(f"  ✅ Run ID: {run_id}\n")
    
    try:
        # Run original script and capture output
        cmd = ['python3', 'compare_contacts.py', args.source_org, args.target_org, args.start_date]
        if args.end_date:
            cmd.append(args.end_date)
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        print(result.stdout)
        
        if result.returncode != 0:
            db_utils.update_comparison_run(run_id, status='failed',
                                          notes=f'Script error: {result.stderr}')
            sys.exit(result.returncode)
        
        # Parse results from generated JSON file
        results_dir = Path(__file__).resolve().parents[1] / 'results'
        # Find most recent JSON file
        json_files = sorted(results_dir.glob('contact_comparison_*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
        
        if json_files:
            with open(json_files[0]) as f:
                data = json.load(f)
                results = data.get('results', {})
                
                # Save to database
                print("\n💾 Saving to database...")
                matches = []
                for match_type, match_list in results.items():
                    if isinstance(match_list, list):
                        for match in match_list:
                            match['match_type'] = match_type
                            matches.append(match)
                
                if matches:
                    db_utils.save_contact_matches(run_id, matches)
                    print(f"  ✅ Saved {len(matches)} contact matches")
                
                # Update mappings
                contact_mapping = {}
                for match in matches:
                    if match.get('target_id'):
                        contact_mapping[match['source_id']] = match['target_id']
                
                if contact_mapping:
                    db_utils.bulk_update_id_mappings('Contact', contact_mapping)
                    print(f"  ✅ Updated {len(contact_mapping)} ID mappings")
                
                db_utils.update_comparison_run(run_id, status='completed',
                                              matched_count=len(contact_mapping))
        
        print(f"\nRun ID: {run_id}")
        print(f"Database: {db_utils.DB_PATH}")
        
    except Exception as e:
        db_utils.update_comparison_run(run_id, status='failed', notes=str(e))
        raise

if __name__ == '__main__':
    main()
