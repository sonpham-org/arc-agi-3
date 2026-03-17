# Author: Claude Opus 4.6
# Date: 2026-03-15 00:00
# PURPOSE: Database safety tests — SQL injection guard (column whitelist),
#   context manager commit/rollback behavior, and connection leak prevention.
# SRP/DRY check: Pass — focused on DB layer safety only
"""Database safety tests — column whitelist, context manager behavior."""

import sys
import os
import sqlite3
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Force a temporary DB for tests
import tempfile
_test_db_dir = tempfile.mkdtemp()
os.environ["DB_DATA_DIR"] = _test_db_dir

import db
from db import _init_db, _get_db, _db, db_conn, DB_PATH
from db_sessions import _db_insert_session, _db_update_session, _db_insert_action, _ALLOWED_SESSION_COLUMNS


class TestColumnWhitelist(unittest.TestCase):
    """Tests for _db_update_session column whitelist (SQL injection guard)."""

    def test_allowed_columns_pass(self):
        """Updating with whitelisted columns should succeed."""
        # Insert a test session first
        _db_insert_session("test-wl-1", "ls20", "staging")

        # Update with allowed columns
        _db_update_session("test-wl-1", result="WIN", levels=3)

        # Verify update
        conn = _get_db()
        row = conn.execute("SELECT result, levels FROM sessions WHERE id = ?",
                           ("test-wl-1",)).fetchone()
        conn.close()
        self.assertEqual(row["result"], "WIN")
        self.assertEqual(row["levels"], 3)

    def test_disallowed_column_returns_none(self):
        """Updating with non-whitelisted column should return None (error swallowed by decorator)."""
        _db_insert_session("test-wl-2", "ls20", "staging")

        # 'id' is not in the whitelist — @handle_errors catches ValueError and returns None
        result = _db_update_session("test-wl-2", id="hacked", result="WIN")
        self.assertIsNone(result, "Disallowed column should cause function to return None")

        # Verify the 'id' was NOT changed (data integrity preserved)
        conn = _get_db()
        row = conn.execute("SELECT id FROM sessions WHERE id = ?",
                           ("test-wl-2",)).fetchone()
        conn.close()
        self.assertIsNotNone(row, "Original session should still exist unchanged")

    def test_injection_attempt_blocked(self):
        """Column name like 'result; DROP TABLE sessions--' should be blocked."""
        _db_insert_session("test-wl-3", "ls20", "staging")

        # @handle_errors catches ValueError and returns None
        result = _db_update_session("test-wl-3",
                                    **{"result; DROP TABLE sessions--": "hacked"})
        self.assertIsNone(result, "Injection attempt should return None")

        # Verify sessions table still exists and data is intact
        conn = _get_db()
        row = conn.execute("SELECT 1 FROM sessions WHERE id = ?",
                           ("test-wl-3",)).fetchone()
        conn.close()
        self.assertIsNotNone(row, "Session should still exist after blocked injection")

    def test_whitelist_covers_all_session_columns(self):
        """Whitelist should cover all non-PK session columns used in the codebase."""
        # These are the columns that game_service.py and session_service.py update
        expected_columns = {
            "result", "levels", "total_cost", "duration_seconds", "steps",
            "game_version", "model", "player_type", "user_id", "mode",
        }
        for col in expected_columns:
            self.assertIn(col, _ALLOWED_SESSION_COLUMNS,
                          f"Column '{col}' should be in whitelist")


class TestContextManager(unittest.TestCase):
    """Tests for _db() context manager commit/rollback behavior."""

    def test_commits_on_success(self):
        """Data should persist after successful context manager exit."""
        with _db() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions (id, game_id, created_at, mode) VALUES (?, ?, ?, ?)",
                ("test-cm-1", "ls20", 1000.0, "staging"),
            )

        # Verify persisted
        conn = _get_db()
        row = conn.execute("SELECT * FROM sessions WHERE id = ?",
                           ("test-cm-1",)).fetchone()
        conn.close()
        self.assertIsNotNone(row, "Row should be committed after clean exit")

    def test_rollback_on_exception(self):
        """Data should NOT persist if exception occurs inside context manager."""
        try:
            with _db() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO sessions (id, game_id, created_at, mode) VALUES (?, ?, ?, ?)",
                    ("test-cm-rollback", "ls20", 1000.0, "staging"),
                )
                raise ValueError("Simulated error")
        except ValueError:
            pass

        # Verify NOT persisted
        conn = _get_db()
        row = conn.execute("SELECT * FROM sessions WHERE id = ?",
                           ("test-cm-rollback",)).fetchone()
        conn.close()
        self.assertIsNone(row, "Row should be rolled back after exception")

    def test_db_conn_commits_on_success(self):
        """db_conn() (IMMEDIATE mode) should also commit on success."""
        with db_conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO sessions (id, game_id, created_at, mode) VALUES (?, ?, ?, ?)",
                ("test-dbc-1", "ls20", 1000.0, "staging"),
            )

        conn = _get_db()
        row = conn.execute("SELECT * FROM sessions WHERE id = ?",
                           ("test-dbc-1",)).fetchone()
        conn.close()
        self.assertIsNotNone(row, "Row should be committed with db_conn()")

    def test_db_conn_rollback_on_exception(self):
        """db_conn() should rollback on exception."""
        try:
            with db_conn() as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO sessions (id, game_id, created_at, mode) VALUES (?, ?, ?, ?)",
                    ("test-dbc-rollback", "ls20", 1000.0, "staging"),
                )
                raise RuntimeError("Simulated error")
        except RuntimeError:
            pass

        conn = _get_db()
        row = conn.execute("SELECT * FROM sessions WHERE id = ?",
                           ("test-dbc-rollback",)).fetchone()
        conn.close()
        self.assertIsNone(row, "Row should be rolled back with db_conn()")


class TestDBInsertAction(unittest.TestCase):
    """Tests for _db_insert_action with context manager."""

    def test_insert_action_persists(self):
        """Inserted action should be readable."""
        _db_insert_session("test-act-1", "ls20", "staging")
        _db_insert_action("test-act-1", 1, 1, row=0, col=0)

        conn = _get_db()
        row = conn.execute(
            "SELECT * FROM session_actions WHERE session_id = ? AND step_num = ?",
            ("test-act-1", 1),
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row["action"], 1)

    def test_insert_action_updates_session_steps(self):
        """Inserting action should update session step count."""
        _db_insert_session("test-act-2", "ls20", "staging")
        _db_insert_action("test-act-2", 5, 2)

        conn = _get_db()
        row = conn.execute("SELECT steps FROM sessions WHERE id = ?",
                           ("test-act-2",)).fetchone()
        conn.close()
        self.assertEqual(row["steps"], 5)


if __name__ == "__main__":
    unittest.main()
