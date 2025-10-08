#!/usr/bin/env python3
"""
DuckDB File Analyzer

A comprehensive tool to analyze DuckDB files and display all available information
including databases, tables, columns, and data in a visual format.

"""

import argparse
import sys
import os
from typing import List, Dict, Any
import duckdb
from tabulate import tabulate
import json


class DuckDBAnalyzer:
    """Analyzes DuckDB files and provides comprehensive information display."""
    
    def __init__(self, db_path: str):
        """Initialize the analyzer with a DuckDB file path."""
        self.db_path = db_path
        self.conn = None
        
    def __enter__(self):
        """Context manager entry."""
        if not os.path.exists(self.db_path):
            raise FileNotFoundError(f"DuckDB file not found: {self.db_path}")
        
        self.conn = duckdb.connect(self.db_path, read_only=True)
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if self.conn:
            self.conn.close()
    
    def get_database_info(self) -> Dict[str, Any]:
        """Get basic database information."""
        info = {}
        
        # Get database file size
        info['file_size'] = os.path.getsize(self.db_path)
        
        # Get DuckDB version
        version_result = self.conn.execute("SELECT version()").fetchone()
        info['duckdb_version'] = version_result[0] if version_result else "Unknown"
        
        # Get database name
        info['database_name'] = os.path.basename(self.db_path)
        
        return info
    
    def get_tables_info(self) -> List[Dict[str, Any]]:
        """Get information about all tables in the database."""
        tables_query = """
        SELECT 
            table_name,
            table_type,
            table_catalog,
            table_schema
        FROM information_schema.tables 
        WHERE table_schema = 'main'
        ORDER BY table_name
        """
        
        tables = self.conn.execute(tables_query).fetchall()
        tables_info = []
        
        for table in tables:
            table_name = table[0]
            table_info = {
                'name': table_name,
                'type': table[1],
                'catalog': table[2],
                'schema': table[3]
            }
            
            # Get row count
            try:
                count_result = self.conn.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()
                table_info['row_count'] = count_result[0] if count_result else 0
            except Exception as e:
                table_info['row_count'] = f"Error: {str(e)}"
            
            # Get column information
            table_info['columns'] = self.get_table_columns(table_name)
            
            tables_info.append(table_info)
        
        return tables_info
    
    def get_table_columns(self, table_name: str) -> List[Dict[str, Any]]:
        """Get detailed column information for a specific table."""
        columns_query = """
        SELECT 
            column_name,
            data_type,
            is_nullable,
            column_default,
            ordinal_position
        FROM information_schema.columns 
        WHERE table_name = ? AND table_schema = 'main'
        ORDER BY ordinal_position
        """
        
        columns = self.conn.execute(columns_query, [table_name]).fetchall()
        columns_info = []
        
        for col in columns:
            col_info = {
                'name': col[0],
                'type': col[1],
                'nullable': col[2] == 'YES',
                'default': col[3],
                'position': col[4]
            }
            columns_info.append(col_info)
        
        return columns_info
    
    def get_sample_data(self, table_name: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get sample data from a table."""
        try:
            query = f"SELECT * FROM {table_name} LIMIT {limit}"
            result = self.conn.execute(query)
            
            # Get column names
            columns = [desc[0] for desc in result.description]
            
            # Get data rows
            rows = result.fetchall()
            
            # Convert to list of dictionaries
            sample_data = []
            for row in rows:
                row_dict = {}
                for i, value in enumerate(row):
                    # Convert complex types to strings for display
                    if isinstance(value, (dict, list)):
                        row_dict[columns[i]] = json.dumps(value, default=str)
                    else:
                        row_dict[columns[i]] = value
                sample_data.append(row_dict)
            
            return sample_data
        except Exception as e:
            return [{'error': f"Could not fetch data: {str(e)}"}]
    
    def get_database_statistics(self) -> Dict[str, Any]:
        """Get database statistics and metadata."""
        stats = {}
        
        # Get total number of tables
        tables_count = self.conn.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'main'").fetchone()
        stats['total_tables'] = tables_count[0] if tables_count else 0
        
        # Get total number of columns across all tables
        columns_count = self.conn.execute("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema = 'main'").fetchone()
        stats['total_columns'] = columns_count[0] if columns_count else 0
        
        # Get database size in MB
        stats['file_size_mb'] = round(self.get_database_info()['file_size'] / (1024 * 1024), 2)
        
        return stats
    
    def display_database_overview(self):
        """Display a comprehensive overview of the database."""
        print("=" * 80)
        print("🔍 DUCKDB FILE ANALYZER")
        print("=" * 80)
        
        # Database info
        db_info = self.get_database_info()
        print(f"\n📁 Database: {db_info['database_name']}")
        print(f"📊 File Size: {db_info['file_size']:,} bytes ({db_info['file_size'] / (1024*1024):.2f} MB)")
        print(f"🔧 DuckDB Version: {db_info['duckdb_version']}")
        
        # Statistics
        stats = self.get_database_statistics()
        print(f"\n📈 Statistics:")
        print(f"   • Total Tables: {stats['total_tables']}")
        print(f"   • Total Columns: {stats['total_columns']}")
        print(f"   • Database Size: {stats['file_size_mb']} MB")
    
    def display_tables_summary(self):
        """Display a summary of all tables."""
        tables = self.get_tables_info()
        
        if not tables:
            print("\n❌ No tables found in the database.")
            return
        
        print(f"\n📋 TABLES SUMMARY ({len(tables)} tables)")
        print("-" * 80)
        
        # Create table summary
        table_data = []
        for table in tables:
            table_data.append([
                table['name'],
                table['type'],
                table['row_count'],
                len(table['columns'])
            ])
        
        headers = ["Table Name", "Type", "Rows", "Columns"]
        print(tabulate(table_data, headers=headers, tablefmt="grid"))
    
    def display_table_details(self, table_name: str, show_data: bool = True, data_limit: int = 5):
        """Display detailed information about a specific table."""
        tables = self.get_tables_info()
        table = next((t for t in tables if t['name'] == table_name), None)
        
        if not table:
            print(f"\n❌ Table '{table_name}' not found.")
            return
        
        print(f"\n🔍 TABLE DETAILS: {table_name}")
        print("=" * 60)
        print(f"Type: {table['type']}")
        print(f"Rows: {table['row_count']:,}")
        print(f"Columns: {len(table['columns'])}")
        
        # Display columns
        print(f"\n📊 COLUMNS:")
        print("-" * 60)
        
        column_data = []
        for col in table['columns']:
            column_data.append([
                col['position'],
                col['name'],
                col['type'],
                "✓" if col['nullable'] else "✗",
                col['default'] or "None"
            ])
        
        headers = ["#", "Column Name", "Type", "Nullable", "Default"]
        print(tabulate(column_data, headers=headers, tablefmt="grid"))
        
        # Display sample data
        if show_data and table['row_count'] > 0:
            print(f"\n📄 SAMPLE DATA (first {data_limit} rows):")
            print("-" * 60)
            
            sample_data = self.get_sample_data(table_name, data_limit)
            
            if sample_data and 'error' not in sample_data[0]:
                # Convert to list of lists for tabulate
                data_rows = []
                if sample_data:
                    headers = list(sample_data[0].keys())
                    for row in sample_data:
                        data_rows.append([str(row.get(col, '')) for col in headers])
                    
                    print(tabulate(data_rows, headers=headers, tablefmt="grid"))
            else:
                print("❌ Could not retrieve sample data")
    
    def display_all_tables_detailed(self, show_data: bool = True, data_limit: int = 3):
        """Display detailed information for all tables."""
        tables = self.get_tables_info()
        
        if not tables:
            print("\n❌ No tables found in the database.")
            return
        
        for table in tables:
            self.display_table_details(table['name'], show_data, data_limit)
            print("\n" + "=" * 80)
    
    def export_to_json(self, output_file: str):
        """Export all database information to a JSON file."""
        db_info = self.get_database_info()
        tables_info = self.get_tables_info()
        stats = self.get_database_statistics()
        
        export_data = {
            'database_info': db_info,
            'statistics': stats,
            'tables': tables_info
        }
        
        with open(output_file, 'w') as f:
            json.dump(export_data, f, indent=2, default=str)
        
        print(f"\n💾 Database information exported to: {output_file}")


def main():
    """Main function to run the DuckDB analyzer."""
    parser = argparse.ArgumentParser(
        description="Analyze DuckDB files and display comprehensive information",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python helper_duckdb_parser.py database.duckdb
  python helper_duckdb_parser.py database.duckdb --no-data
  python helper_duckdb_parser.py database.duckdb --data-limit 10
  python helper_duckdb_parser.py database.duckdb --export results.json
        """
    )
    
    parser.add_argument(
        'db_path',
        help='Path to the DuckDB file to analyze'
    )
    
    parser.add_argument(
        '--no-data',
        action='store_true',
        help='Skip displaying sample data from tables'
    )
    
    parser.add_argument(
        '--data-limit',
        type=int,
        default=5,
        help='Maximum number of sample rows to display per table (default: 5)'
    )
    
    parser.add_argument(
        '--export',
        type=str,
        help='Export all information to a JSON file'
    )
    
    parser.add_argument(
        '--table',
        type=str,
        help='Show detailed information for a specific table only'
    )
    
    args = parser.parse_args()
    
    try:
        with DuckDBAnalyzer(args.db_path) as analyzer:
            # Display overview
            analyzer.display_database_overview()
            
            # Display tables summary
            analyzer.display_tables_summary()
            
            # Display detailed information
            if args.table:
                analyzer.display_table_details(args.table, not args.no_data, args.data_limit)
            else:
                analyzer.display_all_tables_detailed(not args.no_data, args.data_limit)
            
            # Export if requested
            if args.export:
                analyzer.export_to_json(args.export)
            
            print(f"\n✅ Analysis complete!")
            
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
