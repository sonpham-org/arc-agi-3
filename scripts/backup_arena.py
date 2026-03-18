# Author: Claude Opus 4.6
# Date: 2026-03-18 23:45
# PURPOSE: Standalone backup script for all 11 arena tables in the ARC-AGI-3 SQLite DB.
#   Exports to both JSON (data/arena_backup_{timestamp}.json) and SQL dump
#   (data/arena_backup_{timestamp}.sql). Prints row counts per table.
#   Optional --verify flag reads back the JSON and confirms row counts match.
#   Uses DB_PATH from db.py so it always targets the correct database file.
# SRP/DRY check: Pass — no existing backup utility covers arena tables
"""Backup all 11 arena tables to JSON and SQL files.

Usage:
    python scripts/backup_arena.py            # export backup
    python scripts/backup_arena.py --verify   # export + verify round-trip
"""

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running from repo root: `python scripts/backup_arena.py`
_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from db import DB_PATH  # noqa: E402

ARENA_TABLES = [
    "arena_research",
    "arena_agents",
    "arena_games",
    "arena_evolution_cycles",
    "arena_comments",
    "arena_program_versions",
    "arena_votes",
    "arena_human_sessions",
    "arena_evolution_sessions",
    "arena_llm_calls",
    "arena_library_requests",
]

OUTPUT_DIR = _REPO_ROOT / "data"


def _connect(db_path: Path) -> sqlite3.Connection:
    """Open a read-only connection to the SQLite database."""
    if not db_path.exists():
        print(f"ERROR: Database not found at {db_path}", file=sys.stderr)
        sys.exit(1)
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _export_json(conn: sqlite3.Connection) -> dict:
    """Export all arena tables to a dict of {table_name: [row_dicts]}."""
    data: dict[str, list[dict]] = {}
    for table in ARENA_TABLES:
        if not _table_exists(conn, table):
            print(f"  WARNING: table '{table}' does not exist — skipping")
            data[table] = []
            continue
        rows = conn.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608
        data[table] = [dict(row) for row in rows]
    return data


def _write_sql_dump(conn: sqlite3.Connection, sql_path: Path) -> dict[str, int]:
    """Write a SQL dump of arena tables (schema + data) and return row counts."""
    counts: dict[str, int] = {}
    with open(sql_path, "w", encoding="utf-8") as fh:
        fh.write("-- Arena tables backup\n")
        fh.write(f"-- Generated: {datetime.now(timezone.utc).isoformat()}\n")
        fh.write(f"-- Source DB: {DB_PATH}\n\n")
        fh.write("BEGIN TRANSACTION;\n\n")

        for table in ARENA_TABLES:
            if not _table_exists(conn, table):
                counts[table] = 0
                continue

            # Schema
            schema_row = conn.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            if schema_row and schema_row["sql"]:
                fh.write(f"{schema_row['sql']};\n\n")

            # Data
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()  # noqa: S608
            counts[table] = len(rows)
            if not rows:
                continue
            columns = rows[0].keys()
            for row in rows:
                values = []
                for col in columns:
                    val = row[col]
                    if val is None:
                        values.append("NULL")
                    elif isinstance(val, (int, float)):
                        values.append(str(val))
                    else:
                        escaped = str(val).replace("'", "''")
                        values.append(f"'{escaped}'")
                cols_str = ", ".join(columns)
                vals_str = ", ".join(values)
                fh.write(f"INSERT INTO {table} ({cols_str}) VALUES ({vals_str});\n")
            fh.write("\n")

        fh.write("COMMIT;\n")
    return counts


def backup(verify: bool = False) -> None:
    """Run the full backup pipeline."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    json_path = OUTPUT_DIR / f"arena_backup_{timestamp}.json"
    sql_path = OUTPUT_DIR / f"arena_backup_{timestamp}.sql"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Database: {DB_PATH}")
    print(f"JSON output: {json_path}")
    print(f"SQL output:  {sql_path}")
    print()

    conn = _connect(DB_PATH)
    try:
        # JSON export
        data = _export_json(conn)
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, default=str)

        # SQL export
        sql_counts = _write_sql_dump(conn, sql_path)
    finally:
        conn.close()

    # Print row counts
    print("Row counts:")
    total = 0
    for table in ARENA_TABLES:
        count = len(data[table])
        total += count
        print(f"  {table:40s} {count:>8,}")
    print(f"  {'TOTAL':40s} {total:>8,}")
    print()
    print(f"JSON written: {json_path} ({json_path.stat().st_size:,} bytes)")
    print(f"SQL written:  {sql_path} ({sql_path.stat().st_size:,} bytes)")

    # Verify
    if verify:
        print()
        print("Verifying JSON round-trip...")
        with open(json_path, "r", encoding="utf-8") as fh:
            loaded = json.load(fh)

        all_ok = True
        for table in ARENA_TABLES:
            expected = len(data[table])
            actual = len(loaded.get(table, []))
            status = "OK" if expected == actual else "MISMATCH"
            if status == "MISMATCH":
                all_ok = False
            print(f"  {table:40s} expected={expected:>8,}  actual={actual:>8,}  {status}")

        # Also verify SQL counts match
        for table in ARENA_TABLES:
            json_count = len(data[table])
            sq_count = sql_counts.get(table, 0)
            if json_count != sq_count:
                print(f"  WARNING: SQL count mismatch for {table}: JSON={json_count}, SQL={sq_count}")
                all_ok = False

        if all_ok:
            print("\nVerification PASSED — all row counts match.")
        else:
            print("\nVerification FAILED — see mismatches above.", file=sys.stderr)
            sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backup all 11 arena tables to JSON and SQL.")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="After export, read back the JSON and confirm row counts match.",
    )
    args = parser.parse_args()
    backup(verify=args.verify)


if __name__ == "__main__":
    main()
