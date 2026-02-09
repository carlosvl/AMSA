#!/usr/bin/env python3
"""
Query Results CLI Tool

Command-line interface for querying and analyzing migration results from SQLite database.

Usage:
  python3 query_results.py runs [--type TYPE] [--limit N]
  python3 query_results.py run-details <run_id>
  python3 query_results.py campaigns [--run-id ID] [--status STATUS]
  python3 query_results.py contacts [--run-id ID]
  python3 query_results.py seminar-apps [--run-id ID] [--status STATUS]
  python3 query_results.py mappings --type TYPE [--source-id ID]
  python3 query_results.py export <run_id> --format [json|csv]
  python3 query_results.py stats [--date-from DATE]
  python3 query_results.py duplicates [--pending-only]
"""

import sys
import argparse
import sqlite3
from datetime import datetime
from pathlib import Path
import json

import db_utils

def format_table(headers, rows, max_width=120):
    """Format data as a simple table"""
    if not rows:
        return "No data found."
    
    # Calculate column widths
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(val)))
    
    # Limit column widths
    max_col_width = max_width // len(headers)
    col_widths = [min(w, max_col_width) for w in col_widths]
    
    # Create separator
    separator = '+' + '+'.join('-' * (w + 2) for w in col_widths) + '+'
    
    # Format header
    lines = [separator]
    header_row = '|'
    for header, width in zip(headers, col_widths):
        header_row += f' {header:<{width}} |'
    lines.append(header_row)
    lines.append(separator)
    
    # Format rows
    for row in rows:
        row_str = '|'
        for val, width in zip(row, col_widths):
            val_str = str(val)[:width]
            row_str += f' {val_str:<{width}} |'
        lines.append(row_str)
    
    lines.append(separator)
    return '\n'.join(lines)


def cmd_runs(args):
    """List all comparison runs"""
    with db_utils.get_connection() as conn:
        cursor = conn.cursor()
        
        query = "SELECT id, run_type, source_org, target_org, timestamp, status FROM comparison_runs"
        params = []
        
        if args.type:
            query += " WHERE run_type = ?"
            params.append(args.type)
        
        query += " ORDER BY timestamp DESC"
        
        if args.limit:
            query += f" LIMIT {args.limit}"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        if not rows:
            print("No runs found.")
            return
        
        headers = ['ID', 'Type', 'Source Org', 'Target Org', 'Timestamp', 'Status']
        data = []
        for row in rows:
            data.append([
                row['id'],
                row['run_type'],
                row['source_org'] or 'N/A',
                row['target_org'] or 'N/A',
                row['timestamp'],
                row['status']
            ])
        
        print(format_table(headers, data))
        print(f"\nTotal: {len(rows)} run(s)")


def cmd_run_details(args):
    """Show details for a specific run"""
    with db_utils.get_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("SELECT * FROM comparison_runs WHERE id = ?", (args.run_id,))
        run = cursor.fetchone()
        
        if not run:
            print(f"Run {args.run_id} not found.")
            return
        
        print("=" * 80)
        print(f"RUN DETAILS - ID: {run['id']}")
        print("=" * 80)
        print(f"Type:              {run['run_type']}")
        print(f"Source Org:        {run['source_org'] or 'N/A'}")
        print(f"Target Org:        {run['target_org'] or 'N/A'}")
        print(f"Start Date:        {run['start_date'] or 'N/A'}")
        print(f"End Date:          {run['end_date'] or 'N/A'}")
        print(f"Timestamp:         {run['timestamp']}")
        print(f"Status:            {run['status']}")
        print(f"Source Records:    {run['total_source_records']}")
        print(f"Target Records:    {run['total_target_records']}")
        print(f"Matched:           {run['matched_count']}")
        print(f"Unmatched:         {run['unmatched_count']}")
        
        if run['matched_count'] and run['total_source_records']:
            match_pct = (run['matched_count'] / run['total_source_records']) * 100
            print(f"Match Rate:        {match_pct:.1f}%")
        
        if run['notes']:
            print(f"Notes:             {run['notes']}")
        
        print("=" * 80)
        
        # Show summary of matches
        run_type = run['run_type']
        if 'campaign' in run_type:
            cursor.execute("""
                SELECT match_type, COUNT(*) as count 
                FROM campaign_matches 
                WHERE run_id = ? 
                GROUP BY match_type
            """, (args.run_id,))
            matches = cursor.fetchall()
            if matches:
                print("\nCampaign Matches by Type:")
                for match in matches:
                    print(f"  {match['match_type']}: {match['count']}")
        
        elif 'contact' in run_type:
            cursor.execute("""
                SELECT match_type, COUNT(*) as count 
                FROM contact_matches 
                WHERE run_id = ? 
                GROUP BY match_type
            """, (args.run_id,))
            matches = cursor.fetchall()
            if matches:
                print("\nContact Matches by Type:")
                for match in matches:
                    print(f"  {match['match_type']}: {match['count']}")
        
        elif 'seminar' in run_type:
            cursor.execute("""
                SELECT match_status, COUNT(*) as count 
                FROM seminar_application_matches 
                WHERE run_id = ? 
                GROUP BY match_status
            """, (args.run_id,))
            matches = cursor.fetchall()
            if matches:
                print("\nSeminar Application Matches by Status:")
                for match in matches:
                    print(f"  {match['match_status']}: {match['count']}")


def cmd_campaigns(args):
    """Query campaign matches"""
    with db_utils.get_connection() as conn:
        cursor = conn.cursor()
        
        query = """
            SELECT source_id, target_id, source_name, target_name, match_type, 
                   source_type, target_type, source_status
            FROM campaign_matches
        """
        params = []
        where_clauses = []
        
        if args.run_id:
            where_clauses.append("run_id = ?")
            params.append(args.run_id)
        
        if args.status:
            where_clauses.append("match_type = ?")
            params.append(args.status)
        
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        
        query += " ORDER BY source_name"
        
        if args.limit:
            query += f" LIMIT {args.limit}"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        if not rows:
            print("No campaign matches found.")
            return
        
        headers = ['Source ID', 'Target ID', 'Name', 'Match Type', 'Type', 'Status']
        data = []
        for row in rows:
            data.append([
                row['source_id'][:15] if row['source_id'] else 'N/A',
                row['target_id'][:15] if row['target_id'] else 'N/A',
                (row['source_name'] or 'N/A')[:30],
                row['match_type'] or 'N/A',
                row['source_type'] or 'N/A',
                row['source_status'] or 'N/A'
            ])
        
        print(format_table(headers, data))
        print(f"\nTotal: {len(rows)} campaign(s)")


def cmd_contacts(args):
    """Query contact matches"""
    with db_utils.get_connection() as conn:
        cursor = conn.cursor()
        
        query = """
            SELECT source_id, target_id, email, first_name, last_name, match_type
            FROM contact_matches
        """
        params = []
        
        if args.run_id:
            query += " WHERE run_id = ?"
            params.append(args.run_id)
        
        query += " ORDER BY last_name, first_name"
        
        if args.limit:
            query += f" LIMIT {args.limit}"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        if not rows:
            print("No contact matches found.")
            return
        
        headers = ['Source ID', 'Target ID', 'Email', 'First Name', 'Last Name', 'Match Type']
        data = []
        for row in rows:
            data.append([
                row['source_id'][:15] if row['source_id'] else 'N/A',
                row['target_id'][:15] if row['target_id'] else 'N/A',
                (row['email'] or 'N/A')[:30],
                row['first_name'] or 'N/A',
                row['last_name'] or 'N/A',
                row['match_type'] or 'N/A'
            ])
        
        print(format_table(headers, data))
        print(f"\nTotal: {len(rows)} contact(s)")


def cmd_seminar_apps(args):
    """Query seminar application matches"""
    with db_utils.get_connection() as conn:
        cursor = conn.cursor()
        
        query = """
            SELECT record_id, applicant_id, seminar_id, match_status, stage, app_date
            FROM seminar_application_matches
        """
        params = []
        where_clauses = []
        
        if args.run_id:
            where_clauses.append("run_id = ?")
            params.append(args.run_id)
        
        if args.status:
            where_clauses.append("match_status = ?")
            params.append(args.status)
        
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        
        query += " ORDER BY app_date DESC"
        
        if args.limit:
            query += f" LIMIT {args.limit}"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        if not rows:
            print("No seminar application matches found.")
            return
        
        headers = ['Record ID', 'Applicant', 'Seminar', 'Status', 'Stage', 'App Date']
        data = []
        for row in rows:
            data.append([
                row['record_id'][:15] if row['record_id'] else 'N/A',
                row['applicant_id'][:15] if row['applicant_id'] else 'N/A',
                row['seminar_id'][:15] if row['seminar_id'] else 'N/A',
                row['match_status'] or 'N/A',
                row['stage'] or 'N/A',
                row['app_date'] or 'N/A'
            ])
        
        print(format_table(headers, data))
        print(f"\nTotal: {len(rows)} application(s)")


def cmd_mappings(args):
    """Query ID mappings"""
    with db_utils.get_connection() as conn:
        cursor = conn.cursor()
        
        query = "SELECT object_type, source_id, target_id, created_date FROM id_mappings"
        params = []
        where_clauses = []
        
        if args.type:
            where_clauses.append("object_type = ?")
            params.append(args.type)
        
        if args.source_id:
            where_clauses.append("source_id = ?")
            params.append(args.source_id)
        
        if where_clauses:
            query += " WHERE " + " AND ".join(where_clauses)
        
        query += " ORDER BY object_type, created_date DESC"
        
        if args.limit:
            query += f" LIMIT {args.limit}"
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        
        if not rows:
            print("No ID mappings found.")
            return
        
        headers = ['Object Type', 'Source ID', 'Target ID', 'Created']
        data = []
        for row in rows:
            data.append([
                row['object_type'],
                row['source_id'][:18],
                row['target_id'][:18],
                row['created_date'][:19]
            ])
        
        print(format_table(headers, data))
        print(f"\nTotal: {len(rows)} mapping(s)")


def cmd_export(args):
    """Export a run to JSON or CSV"""
    results_dir = Path(__file__).resolve().parents[1] / 'results'
    results_dir.mkdir(exist_ok=True)
    
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    
    if args.format == 'json':
        output_path = results_dir / f'export_run_{args.run_id}_{timestamp}.json'
        db_utils.export_run_to_json(args.run_id, output_path)
        print(f"✅ Exported to: {output_path}")
    
    elif args.format == 'csv':
        db_utils.export_run_to_csv(args.run_id, results_dir)
        print(f"✅ Exported to: {results_dir}")


def cmd_stats(args):
    """Show summary statistics"""
    with db_utils.get_connection() as conn:
        cursor = conn.cursor()
        
        # Overall stats
        cursor.execute("SELECT COUNT(*) as count FROM comparison_runs")
        total_runs = cursor.fetchone()['count']
        
        cursor.execute("""
            SELECT run_type, COUNT(*) as count 
            FROM comparison_runs 
            GROUP BY run_type
        """)
        runs_by_type = cursor.fetchall()
        
        cursor.execute("""
            SELECT status, COUNT(*) as count 
            FROM comparison_runs 
            GROUP BY status
        """)
        runs_by_status = cursor.fetchall()
        
        # ID mappings
        cursor.execute("""
            SELECT object_type, COUNT(*) as count 
            FROM id_mappings 
            GROUP BY object_type
        """)
        mappings = cursor.fetchall()
        
        print("=" * 80)
        print("DATABASE STATISTICS")
        print("=" * 80)
        print(f"\nTotal Runs: {total_runs}")
        
        print("\nRuns by Type:")
        for row in runs_by_type:
            print(f"  {row['run_type']}: {row['count']}")
        
        print("\nRuns by Status:")
        for row in runs_by_status:
            print(f"  {row['status']}: {row['count']}")
        
        print("\nID Mappings:")
        for row in mappings:
            print(f"  {row['object_type']}: {row['count']}")
        
        print("=" * 80)


def cmd_duplicates(args):
    """Query duplicate groups"""
    with db_utils.get_connection() as conn:
        cursor = conn.cursor()
        
        query = """
            SELECT id, run_id, object_type, group_key, record_count, action
            FROM duplicate_groups
        """
        
        if args.pending_only:
            query += " WHERE action = 'pending'"
        
        query += " ORDER BY record_count DESC"
        
        cursor.execute(query)
        rows = cursor.fetchall()
        
        if not rows:
            print("No duplicate groups found.")
            return
        
        headers = ['ID', 'Run ID', 'Object Type', 'Group Key', 'Records', 'Action']
        data = []
        for row in rows:
            data.append([
                row['id'],
                row['run_id'],
                row['object_type'],
                row['group_key'][:30],
                row['record_count'],
                row['action']
            ])
        
        print(format_table(headers, data))
        print(f"\nTotal: {len(rows)} duplicate group(s)")


def main():
    parser = argparse.ArgumentParser(
        description='Query and analyze migration results',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Commands')
    
    # runs command
    runs_parser = subparsers.add_parser('runs', help='List all comparison runs')
    runs_parser.add_argument('--type', help='Filter by run type')
    runs_parser.add_argument('--limit', type=int, default=20, help='Limit results')
    
    # run-details command
    details_parser = subparsers.add_parser('run-details', help='Show details for a run')
    details_parser.add_argument('run_id', type=int, help='Run ID')
    
    # campaigns command
    campaigns_parser = subparsers.add_parser('campaigns', help='Query campaign matches')
    campaigns_parser.add_argument('--run-id', type=int, help='Filter by run ID')
    campaigns_parser.add_argument('--status', help='Filter by match type')
    campaigns_parser.add_argument('--limit', type=int, default=50, help='Limit results')
    
    # contacts command
    contacts_parser = subparsers.add_parser('contacts', help='Query contact matches')
    contacts_parser.add_argument('--run-id', type=int, help='Filter by run ID')
    contacts_parser.add_argument('--limit', type=int, default=50, help='Limit results')
    
    # seminar-apps command
    seminar_parser = subparsers.add_parser('seminar-apps', help='Query seminar application matches')
    seminar_parser.add_argument('--run-id', type=int, help='Filter by run ID')
    seminar_parser.add_argument('--status', help='Filter by match status')
    seminar_parser.add_argument('--limit', type=int, default=50, help='Limit results')
    
    # mappings command
    mappings_parser = subparsers.add_parser('mappings', help='Query ID mappings')
    mappings_parser.add_argument('--type', required=True, help='Object type (Contact, Campaign, etc.)')
    mappings_parser.add_argument('--source-id', help='Filter by source ID')
    mappings_parser.add_argument('--limit', type=int, default=50, help='Limit results')
    
    # export command
    export_parser = subparsers.add_parser('export', help='Export a run to file')
    export_parser.add_argument('run_id', type=int, help='Run ID')
    export_parser.add_argument('--format', required=True, choices=['json', 'csv'], help='Export format')
    
    # stats command
    stats_parser = subparsers.add_parser('stats', help='Show database statistics')
    stats_parser.add_argument('--date-from', help='Filter from date (YYYY-MM-DD)')
    
    # duplicates command
    duplicates_parser = subparsers.add_parser('duplicates', help='Query duplicate groups')
    duplicates_parser.add_argument('--pending-only', action='store_true', help='Show only pending duplicates')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        return
    
    # Route to appropriate command handler
    commands = {
        'runs': cmd_runs,
        'run-details': cmd_run_details,
        'campaigns': cmd_campaigns,
        'contacts': cmd_contacts,
        'seminar-apps': cmd_seminar_apps,
        'mappings': cmd_mappings,
        'export': cmd_export,
        'stats': cmd_stats,
        'duplicates': cmd_duplicates
    }
    
    handler = commands.get(args.command)
    if handler:
        handler(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
