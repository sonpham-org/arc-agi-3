# Author: Claude Opus 4.6
# Date: 2026-03-18 23:50
# PURPOSE: One-time migration script: copy arena tables from SQLite to PostgreSQL.
#   Reads from SQLite (DB_PATH), writes to PostgreSQL (DATABASE_URL).
#   Creates PG schema if needed, then bulk-inserts all rows preserving IDs.
#   Verifies row counts match after migration.
# SRP/DRY check: Pass — standalone migration script, not part of runtime code
"""Migrate arena data from SQLite to PostgreSQL.

Usage:
    DATABASE_URL=postgres://... python scripts/migrate_arena_to_pg.py
    DATABASE_URL=postgres://... python scripts/migrate_arena_to_pg.py --dry-run
"""

import json
import os
import sqlite3
import sys
import time

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ARENA_TABLES = [
    'arena_research',
    'arena_agents',
    'arena_games',
    'arena_evolution_cycles',
    'arena_comments',
    'arena_program_versions',
    'arena_votes',
    'arena_human_sessions',
    'arena_evolution_sessions',
    'arena_llm_calls',
    'arena_library_requests',
]


def get_sqlite_conn():
    """Connect to the SQLite database."""
    from db import DB_PATH
    print(f"SQLite: {DB_PATH}")
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def get_pg_conn():
    """Connect to PostgreSQL."""
    import psycopg2
    url = os.environ.get('DATABASE_URL')
    if not url:
        print("ERROR: DATABASE_URL not set")
        sys.exit(1)
    print(f"PostgreSQL: {url[:50]}...")
    conn = psycopg2.connect(url)
    return conn


def get_table_columns(sqlite_conn, table):
    """Get column names for a SQLite table."""
    rows = sqlite_conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [r[1] for r in rows]


def migrate_table(sqlite_conn, pg_conn, table, dry_run=False):
    """Migrate a single table from SQLite to PostgreSQL."""
    columns = get_table_columns(sqlite_conn, table)
    rows = sqlite_conn.execute(f"SELECT * FROM {table}").fetchall()

    if not rows:
        print(f"  {table}: 0 rows (skip)")
        return 0

    # Build INSERT with explicit columns
    col_list = ', '.join(columns)
    placeholders = ', '.join(['%s'] * len(columns))
    insert_sql = f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})"

    if dry_run:
        print(f"  {table}: {len(rows)} rows (dry-run, would insert)")
        return len(rows)

    cur = pg_conn.cursor()

    # Clear existing data in PG table
    cur.execute(f"DELETE FROM {table}")

    # Insert all rows
    batch = []
    for row in rows:
        values = tuple(row[col] for col in columns)
        batch.append(values)

    if batch:
        from psycopg2.extras import execute_batch
        execute_batch(cur, insert_sql, batch, page_size=500)

    # Reset sequence to max ID + 1 (for SERIAL columns)
    if 'id' in columns:
        cur.execute(f"SELECT MAX(id) FROM {table}")
        max_id = cur.fetchone()[0]
        if max_id:
            cur.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), %s)", (max_id,))

    print(f"  {table}: {len(rows)} rows migrated")
    return len(rows)


def verify(sqlite_conn, pg_conn):
    """Verify row counts match between SQLite and PostgreSQL."""
    print("\nVerification:")
    all_match = True
    for table in ARENA_TABLES:
        try:
            sq_count = sqlite_conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except Exception:
            sq_count = 0
        cur = pg_conn.cursor()
        cur.execute(f"SELECT COUNT(*) FROM {table}")
        pg_count = cur.fetchone()[0]
        status = "OK" if sq_count == pg_count else "MISMATCH"
        if sq_count != pg_count:
            all_match = False
        print(f"  {table}: SQLite={sq_count}, PG={pg_count} [{status}]")
    return all_match


def main():
    dry_run = '--dry-run' in sys.argv

    if dry_run:
        print("=== DRY RUN (no data will be written) ===\n")

    sqlite_conn = get_sqlite_conn()
    pg_conn = get_pg_conn()

    # Create PG schema
    print("\nCreating PostgreSQL schema...")
    from db_arena import _init_pg_schema
    _init_pg_schema(pg_conn)
    print("Schema ready.\n")

    # Migrate tables (order matters for FK constraints)
    print("Migrating tables:")
    total = 0
    t0 = time.time()

    # Parents first (no FK dependencies)
    for table in ['arena_research', 'arena_agents', 'arena_evolution_cycles', 'arena_program_versions']:
        total += migrate_table(sqlite_conn, pg_conn, table, dry_run)

    # Children (reference arena_agents, arena_program_versions)
    for table in ['arena_games', 'arena_comments', 'arena_votes',
                  'arena_human_sessions', 'arena_evolution_sessions',
                  'arena_llm_calls', 'arena_library_requests']:
        total += migrate_table(sqlite_conn, pg_conn, table, dry_run)

    elapsed = time.time() - t0

    if not dry_run:
        pg_conn.commit()
        print(f"\nMigration complete: {total} rows in {elapsed:.1f}s")

        # Verify
        if verify(sqlite_conn, pg_conn):
            print("\nAll row counts match. Migration successful.")
        else:
            print("\nWARNING: Row count mismatch detected! Check tables above.")
    else:
        print(f"\nDry run complete: {total} rows would be migrated")

    sqlite_conn.close()
    pg_conn.close()


if __name__ == '__main__':
    main()
