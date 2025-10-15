#!/usr/bin/env python3
"""
DuckDB File Comparator

A comprehensive tool to compare two DuckDB files and identify differences
in both metadata (schemas, tables, columns) and data content.

Usage:
    python helper_duckdb_comparer.py file1.db file2.db [--compare-data]
"""

import argparse
import sys
import os
from typing import List, Dict, Any, Tuple, Set
import duckdb
from tabulate import tabulate
import json
from datetime import datetime


class DuckDBComparator:
    """Compares two DuckDB files and reports differences."""
    
    def __init__(self, db1_path: str, db2_path: str):
        """Initialize the comparator with two DuckDB file paths."""
        self.db1_path = db1_path
        self.db2_path = db2_path
        self.conn1 = None
        self.conn2 = None
        
    def __enter__(self):
        """Context manager entry."""
        if not os.path.exists(self.db1_path):
            raise FileNotFoundError(f"DuckDB file not found: {self.db1_path}")
        if not os.path.exists(self.db2_path):
            raise FileNotFoundError(f"DuckDB file not found: {self.db2_path}")
        
        self.conn1 = duckdb.connect(self.db1_path, read_only=True)
        self.conn2 = duckdb.connect(self.db2_path, read_only=True)
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        if self.conn1:
            self.conn1.close()
        if self.conn2:
            self.conn2.close()
    
    def get_database_metadata(self, conn: duckdb.DuckDBPyConnection) -> Dict[str, Any]:
        """Get comprehensive metadata from a DuckDB connection."""
        metadata = {
            'tables': {},
            'schemas': set(),
            'views': {},
            'indexes': {},
            'file_size': 0
        }
        
        # Get all schemas
        try:
            schemas_result = conn.execute("SELECT schema_name FROM information_schema.schemata").fetchall()
            metadata['schemas'] = {row[0] for row in schemas_result}
        except Exception as e:
            print(f"Warning: Could not get schemas: {e}")
        
        # Get all tables with their information
        try:
            tables_result = conn.execute("""
                SELECT table_schema, table_name, table_type 
                FROM information_schema.tables 
                WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
            """).fetchall()
            
            for schema, table_name, table_type in tables_result:
                table_key = f"{schema}.{table_name}" if schema != 'main' else table_name
                
                # Get column information
                columns_result = conn.execute(f"""
                    SELECT column_name, data_type, is_nullable, column_default
                    FROM information_schema.columns 
                    WHERE table_schema = ? AND table_name = ?
                    ORDER BY ordinal_position
                """, [schema, table_name]).fetchall()
                
                columns = []
                for col_name, data_type, is_nullable, default_val in columns_result:
                    columns.append({
                        'name': col_name,
                        'type': data_type,
                        'nullable': is_nullable == 'YES',
                        'default': default_val
                    })
                
                # Get row count
                try:
                    count_result = conn.execute(f"SELECT COUNT(*) FROM {table_key}").fetchone()
                    row_count = count_result[0] if count_result else 0
                except Exception:
                    row_count = 0
                
                metadata['tables'][table_key] = {
                    'schema': schema,
                    'name': table_name,
                    'type': table_type,
                    'columns': columns,
                    'row_count': row_count
                }
        except Exception as e:
            print(f"Warning: Could not get table information: {e}")
        
        # Get views
        try:
            views_result = conn.execute("""
                SELECT table_schema, table_name 
                FROM information_schema.views 
                WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
            """).fetchall()
            
            for schema, view_name in views_result:
                view_key = f"{schema}.{view_name}" if schema != 'main' else view_name
                metadata['views'][view_key] = {
                    'schema': schema,
                    'name': view_name
                }
        except Exception as e:
            print(f"Warning: Could not get view information: {e}")
        
        return metadata
    
    def compare_metadata(self) -> Dict[str, Any]:
        """Compare metadata between the two databases."""
        print("🔍 Analyzing metadata...")
        
        metadata1 = self.get_database_metadata(self.conn1)
        metadata2 = self.get_database_metadata(self.conn2)
        
        differences = {
            'identical': True,
            'schema_differences': [],
            'table_differences': [],
            'column_differences': [],
            'view_differences': [],
            'summary': {}
        }
        
        # Compare schemas
        schemas1 = metadata1['schemas']
        schemas2 = metadata2['schemas']
        
        if schemas1 != schemas2:
            differences['identical'] = False
            only_in_1 = schemas1 - schemas2
            only_in_2 = schemas2 - schemas1
            
            if only_in_1:
                differences['schema_differences'].append({
                    'type': 'missing_in_db2',
                    'schemas': list(only_in_1)
                })
            if only_in_2:
                differences['schema_differences'].append({
                    'type': 'missing_in_db1',
                    'schemas': list(only_in_2)
                })
        
        # Compare tables
        tables1 = set(metadata1['tables'].keys())
        tables2 = set(metadata2['tables'].keys())
        
        if tables1 != tables2:
            differences['identical'] = False
            only_in_1 = tables1 - tables2
            only_in_2 = tables2 - tables1
            
            if only_in_1:
                differences['table_differences'].append({
                    'type': 'missing_in_db2',
                    'tables': list(only_in_1)
                })
            if only_in_2:
                differences['table_differences'].append({
                    'type': 'missing_in_db1',
                    'tables': list(only_in_2)
                })
        
        # Compare common tables
        common_tables = tables1 & tables2
        for table in common_tables:
            table1 = metadata1['tables'][table]
            table2 = metadata2['tables'][table]
            
            # Compare row counts
            if table1['row_count'] != table2['row_count']:
                differences['identical'] = False
                differences['table_differences'].append({
                    'type': 'row_count_difference',
                    'table': table,
                    'db1_count': table1['row_count'],
                    'db2_count': table2['row_count']
                })
            
            # Compare columns
            cols1 = {col['name']: col for col in table1['columns']}
            cols2 = {col['name']: col for col in table2['columns']}
            
            if cols1 != cols2:
                differences['identical'] = False
                
                # Find column differences
                col_names1 = set(cols1.keys())
                col_names2 = set(cols2.keys())
                
                only_in_1 = col_names1 - col_names2
                only_in_2 = col_names2 - col_names1
                common_cols = col_names1 & col_names2
                
                if only_in_1:
                    differences['column_differences'].append({
                        'type': 'missing_in_db2',
                        'table': table,
                        'columns': list(only_in_1)
                    })
                
                if only_in_2:
                    differences['column_differences'].append({
                        'type': 'missing_in_db1',
                        'table': table,
                        'columns': list(only_in_2)
                    })
                
                # Compare common columns
                for col_name in common_cols:
                    col1 = cols1[col_name]
                    col2 = cols2[col_name]
                    
                    if col1 != col2:
                        differences['column_differences'].append({
                            'type': 'column_definition_difference',
                            'table': table,
                            'column': col_name,
                            'db1_definition': col1,
                            'db2_definition': col2
                        })
        
        # Compare views
        views1 = set(metadata1['views'].keys())
        views2 = set(metadata2['views'].keys())
        
        if views1 != views2:
            differences['identical'] = False
            only_in_1 = views1 - views2
            only_in_2 = views2 - views1
            
            if only_in_1:
                differences['view_differences'].append({
                    'type': 'missing_in_db2',
                    'views': list(only_in_1)
                })
            if only_in_2:
                differences['view_differences'].append({
                    'type': 'missing_in_db1',
                    'views': list(only_in_2)
                })
        
        # Summary
        differences['summary'] = {
            'db1_tables': len(metadata1['tables']),
            'db2_tables': len(metadata2['tables']),
            'db1_views': len(metadata1['views']),
            'db2_views': len(metadata2['views']),
            'db1_schemas': len(metadata1['schemas']),
            'db2_schemas': len(metadata2['schemas'])
        }
        
        return differences
    
    def compare_data(self) -> Dict[str, Any]:
        """Compare actual data content between the two databases."""
        print("🔍 Analyzing data content...")
        
        metadata1 = self.get_database_metadata(self.conn1)
        metadata2 = self.get_database_metadata(self.conn2)
        
        data_differences = {
            'identical': True,
            'table_data_differences': [],
            'summary': {}
        }
        
        # Get common tables
        tables1 = set(metadata1['tables'].keys())
        tables2 = set(metadata2['tables'].keys())
        common_tables = tables1 & tables2
        
        for table in common_tables:
            try:
                # Get all data from both tables
                data1_result = self.conn1.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                data2_result = self.conn2.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
                
                # Convert to sets of tuples for comparison
                set1 = set(data1_result)
                set2 = set(data2_result)
                
                if set1 != set2:
                    data_differences['identical'] = False
                    
                    only_in_1 = set1 - set2
                    only_in_2 = set2 - set1
                    
                    data_differences['table_data_differences'].append({
                        'table': table,
                        'db1_only_rows': len(only_in_1),
                        'db2_only_rows': len(only_in_2),
                        'db1_total_rows': len(data1_result),
                        'db2_total_rows': len(data2_result),
                        'sample_db1_only': list(only_in_1)[:5] if only_in_1 else [],
                        'sample_db2_only': list(only_in_2)[:5] if only_in_2 else []
                    })
                
            except Exception as e:
                print(f"Warning: Could not compare data for table {table}: {e}")
        
        return data_differences
    
    def print_metadata_differences(self, differences: Dict[str, Any]):
        """Print metadata differences in a human-readable format."""
        print("\n" + "="*80)
        print("📊 METADATA COMPARISON RESULTS")
        print("="*80)
        
        if differences['identical']:
            print("✅ The databases have identical metadata!")
            return
        
        print("❌ The databases have different metadata:")
        
        # Schema differences
        if differences['schema_differences']:
            print("\n📁 SCHEMA DIFFERENCES:")
            for diff in differences['schema_differences']:
                if diff['type'] == 'missing_in_db2':
                    print(f"  • Schemas only in DB1: {', '.join(diff['schemas'])}")
                elif diff['type'] == 'missing_in_db1':
                    print(f"  • Schemas only in DB2: {', '.join(diff['schemas'])}")
        
        # Table differences
        if differences['table_differences']:
            print("\n📋 TABLE DIFFERENCES:")
            for diff in differences['table_differences']:
                if diff['type'] == 'missing_in_db2':
                    print(f"  • Tables only in DB1: {', '.join(diff['tables'])}")
                elif diff['type'] == 'missing_in_db1':
                    print(f"  • Tables only in DB2: {', '.join(diff['tables'])}")
                elif diff['type'] == 'row_count_difference':
                    print(f"  • Row count difference in '{diff['table']}': {diff['db1_count']} vs {diff['db2_count']}")
        
        # Column differences
        if differences['column_differences']:
            print("\n🔧 COLUMN DIFFERENCES:")
            for diff in differences['column_differences']:
                if diff['type'] == 'missing_in_db2':
                    print(f"  • Columns only in DB1 table '{diff['table']}': {', '.join(diff['columns'])}")
                elif diff['type'] == 'missing_in_db1':
                    print(f"  • Columns only in DB2 table '{diff['table']}': {', '.join(diff['columns'])}")
                elif diff['type'] == 'column_definition_difference':
                    print(f"  • Column '{diff['column']}' in table '{diff['table']}' has different definitions:")
                    print(f"    DB1: {diff['db1_definition']}")
                    print(f"    DB2: {diff['db2_definition']}")
        
        # View differences
        if differences['view_differences']:
            print("\n👁️ VIEW DIFFERENCES:")
            for diff in differences['view_differences']:
                if diff['type'] == 'missing_in_db2':
                    print(f"  • Views only in DB1: {', '.join(diff['views'])}")
                elif diff['type'] == 'missing_in_db1':
                    print(f"  • Views only in DB2: {', '.join(diff['views'])}")
        
        # Summary
        summary = differences['summary']
        print(f"\n📈 SUMMARY:")
        print(f"  DB1: {summary['db1_tables']} tables, {summary['db1_views']} views, {summary['db1_schemas']} schemas")
        print(f"  DB2: {summary['db2_tables']} tables, {summary['db2_views']} views, {summary['db2_schemas']} schemas")
    
    def print_data_differences(self, differences: Dict[str, Any]):
        """Print data differences in a human-readable format."""
        print("\n" + "="*80)
        print("📊 DATA COMPARISON RESULTS")
        print("="*80)
        
        if differences['identical']:
            print("✅ The databases have identical data!")
            return
        
        print("❌ The databases have different data:")
        
        # Data differences
        if differences['table_data_differences']:
            print("\n📋 DATA DIFFERENCES:")
            for diff in differences['table_data_differences']:
                print(f"\n  Table: {diff['table']}")
                print(f"    DB1 total rows: {diff['db1_total_rows']}")
                print(f"    DB2 total rows: {diff['db2_total_rows']}")
                print(f"    Rows only in DB1: {diff['db1_only_rows']}")
                print(f"    Rows only in DB2: {diff['db2_only_rows']}")
                
                if diff['sample_db1_only']:
                    print(f"    Sample rows only in DB1:")
                    for i, row in enumerate(diff['sample_db1_only'], 1):
                        print(f"      {i}. {row}")
                
                if diff['sample_db2_only']:
                    print(f"    Sample rows only in DB2:")
                    for i, row in enumerate(diff['sample_db2_only'], 1):
                        print(f"      {i}. {row}")


def main():
    """Main function to run the DuckDB comparator."""
    parser = argparse.ArgumentParser(
        description="Compare two DuckDB files and report differences",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python helper_duckdb_comparer.py file1.db file2.db
  python helper_duckdb_comparer.py file1.db file2.db --compare-data
  python helper_duckdb_comparer.py file1.db file2.db --metadata-only
        """
    )
    
    parser.add_argument('db1', help='Path to first DuckDB file')
    parser.add_argument('db2', help='Path to second DuckDB file')
    parser.add_argument('--compare-data', action='store_true', 
                       help='Compare actual data content (slower for large databases)')
    parser.add_argument('--metadata-only', action='store_true',
                       help='Only compare metadata (schemas, tables, columns)')
    parser.add_argument('--output-json', help='Save detailed results to JSON file')
    
    args = parser.parse_args()
    
    # Validate arguments
    if args.compare_data and args.metadata_only:
        print("Error: Cannot specify both --compare-data and --metadata-only")
        sys.exit(1)
    
    try:
        with DuckDBComparator(args.db1, args.db2) as comparator:
            print(f"🔍 Comparing DuckDB files:")
            print(f"  DB1: {args.db1}")
            print(f"  DB2: {args.db2}")
            print(f"  Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            
            results = {}
            
            # Always compare metadata
            metadata_diff = comparator.compare_metadata()
            results['metadata'] = metadata_diff
            comparator.print_metadata_differences(metadata_diff)
            
            # Compare data if requested
            if args.compare_data:
                data_diff = comparator.compare_data()
                results['data'] = data_diff
                comparator.print_data_differences(data_diff)
            
            # Save to JSON if requested
            if args.output_json:
                with open(args.output_json, 'w') as f:
                    json.dump(results, f, indent=2, default=str)
                print(f"\n💾 Detailed results saved to: {args.output_json}")
            
            # Exit with appropriate code
            if args.metadata_only:
                sys.exit(0 if metadata_diff['identical'] else 1)
            elif args.compare_data:
                sys.exit(0 if (metadata_diff['identical'] and data_diff['identical']) else 1)
            else:
                sys.exit(0 if metadata_diff['identical'] else 1)
                
    except FileNotFoundError as e:
        print(f"❌ Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
