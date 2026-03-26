"""Unit tests for db.py — database layer, migrations, compression."""

import unittest
from unittest.mock import patch, MagicMock, call
import sys
import os
import sqlite3
import json
import base64
import zlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import db


class TestDatabasePath(unittest.TestCase):
    """Test database path configuration."""

    def test_db_path_exists(self):
        """DB_PATH is defined."""
        self.assertTrue(hasattr(db, 'DB_PATH'))

    def test_data_dir_from_env_or_default(self):
        """_DATA_DIR is set from env or uses default."""
        self.assertTrue(hasattr(db, '_DATA_DIR'))
        # Should be a Path object
        from pathlib import Path
        self.assertIsInstance(db._DATA_DIR, Path)


class TestCompressionHelpers(unittest.TestCase):
    """Test grid compression/decompression."""

    def test_compress_grid_returns_string(self):
        """Compress grid to base64 string."""
        grid = [[1, 2], [3, 4]]
        result = db._compress_grid(grid)
        self.assertIsInstance(result, str)
        # Should be valid base64
        try:
            base64.b64decode(result)
        except Exception:
            self.fail("Compressed grid is not valid base64")

    def test_decompress_grid_recovers_original(self):
        """Decompress grid recovers original data."""
        grid = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
        compressed = db._compress_grid(grid)
        decompressed = db._decompress_grid(compressed)
        self.assertEqual(decompressed, grid)

    def test_compress_empty_grid(self):
        """Compress empty grid."""
        grid = []
        compressed = db._compress_grid(grid)
        self.assertIsInstance(compressed, str)
        decompressed = db._decompress_grid(compressed)
        self.assertEqual(decompressed, grid)

    def test_compress_large_grid(self):
        """Compress large grid (performance check)."""
        grid = [[i % 16 for i in range(64)] for _ in range(64)]
        compressed = db._compress_grid(grid)
        self.assertIsInstance(compressed, str)
        decompressed = db._decompress_grid(compressed)
        self.assertEqual(decompressed, grid)


class TestGetTableColumns(unittest.TestCase):
    """Test _get_table_columns helper."""

    def test_get_columns_from_existing_table(self):
        """Retrieve column names from existing table."""
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE test_table (id INTEGER, name TEXT, value REAL)")
        
        cols = db._get_table_columns(conn, "test_table")
        self.assertEqual(cols, {"id", "name", "value"})
        conn.close()

    def test_get_columns_from_nonexistent_table(self):
        """Return empty set for nonexistent table."""
        conn = sqlite3.connect(":memory:")
        cols = db._get_table_columns(conn, "nonexistent")
        self.assertEqual(cols, set())
        conn.close()

    def test_get_columns_handles_exception(self):
        """Handle exceptions gracefully."""
        conn = MagicMock()
        conn.execute.side_effect = Exception("Test error")
        cols = db._get_table_columns(conn, "table")
        self.assertEqual(cols, set())


class TestTableExists(unittest.TestCase):
    """Test _table_exists helper."""

    def test_table_exists_returns_true(self):
        """Return True for existing table."""
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE test_table (id INTEGER)")
        
        exists = db._table_exists(conn, "test_table")
        self.assertTrue(exists)
        conn.close()

    def test_table_exists_returns_false(self):
        """Return False for nonexistent table."""
        conn = sqlite3.connect(":memory:")
        exists = db._table_exists(conn, "nonexistent")
        self.assertFalse(exists)
        conn.close()


class TestMigrateSchema(unittest.TestCase):
    """Test schema migration logic."""

    def test_migrate_schema_idempotent(self):
        """Schema migration can run multiple times safely."""
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY)")
        
        # Run migration twice
        db._migrate_schema(conn)
        db._migrate_schema(conn)
        
        # Should not raise
        self.assertTrue(True)
        conn.close()

    def test_migrate_sessions_columns_rename(self):
        """Migrate old sessions column names to new ones."""
        conn = sqlite3.connect(":memory:")
        # Create old schema
        conn.execute("""
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                prompts_json TEXT,
                timeline_json TEXT
            )
        """)
        conn.commit()
        
        db._migrate_schema(conn)
        
        # Check that new column exists
        cols = db._get_table_columns(conn, "sessions")
        self.assertIn("scaffolding_json", cols)
        conn.close()

    def test_migrate_llm_calls_column_rename(self):
        """Migrate old llm_calls column names."""
        conn = sqlite3.connect(":memory:")
        conn.execute("""
            CREATE TABLE llm_calls (
                id INTEGER PRIMARY KEY,
                call_type TEXT,
                response_json TEXT
            )
        """)
        conn.commit()
        
        db._migrate_schema(conn)
        
        cols = db._get_table_columns(conn, "llm_calls")
        # New schema should have agent_type and output_json
        self.assertIn("agent_type", cols)
        conn.close()


class TestGetDb(unittest.TestCase):
    """Test _get_db connection function."""

    @patch('db.sqlite3.connect')
    def test_get_db_returns_connection(self, mock_connect):
        """_get_db returns a database connection."""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        
        conn = db._get_db()
        self.assertEqual(conn, mock_conn)
        # Should set row_factory to sqlite3.Row
        self.assertEqual(mock_conn.row_factory, sqlite3.Row)


class TestDbConnContextManager(unittest.TestCase):
    """Test db_conn context manager."""

    @patch('db._get_db')
    def test_db_conn_commits_on_success(self, mock_get_db):
        """db_conn commits on successful exit."""
        mock_conn = MagicMock()
        mock_get_db.return_value = mock_conn
        
        with db.db_conn():
            pass
        
        mock_conn.execute.assert_called_with("BEGIN IMMEDIATE")
        mock_conn.commit.assert_called_once()

    @patch('db._get_db')
    def test_db_conn_rollback_on_exception(self, mock_get_db):
        """db_conn rolls back on exception."""
        mock_conn = MagicMock()
        mock_get_db.return_value = mock_conn
        
        with self.assertRaises(ValueError):
            with db.db_conn():
                raise ValueError("Test error")
        
        mock_conn.rollback.assert_called_once()

    @patch('db._get_db')
    def test_db_conn_closes_connection(self, mock_get_db):
        """db_conn closes connection on exit."""
        mock_conn = MagicMock()
        mock_get_db.return_value = mock_conn
        
        with db.db_conn():
            pass
        
        mock_conn.close.assert_called_once()


class TestDbContextManager(unittest.TestCase):
    """Test _db context manager (simple version)."""

    @patch('db._get_db')
    def test_db_commits_on_success(self, mock_get_db):
        """_db commits on successful exit."""
        mock_conn = MagicMock()
        mock_get_db.return_value = mock_conn
        
        with db._db():
            pass
        
        mock_conn.commit.assert_called_once()

    @patch('db._get_db')
    def test_db_rollback_on_exception(self, mock_get_db):
        """_db rolls back on exception."""
        mock_conn = MagicMock()
        mock_get_db.return_value = mock_conn
        
        with self.assertRaises(RuntimeError):
            with db._db():
                raise RuntimeError("Test error")
        
        mock_conn.rollback.assert_called_once()

    @patch('db._get_db')
    def test_db_closes_connection(self, mock_get_db):
        """_db closes connection on exit."""
        mock_conn = MagicMock()
        mock_get_db.return_value = mock_conn
        
        with db._db():
            pass
        
        mock_conn.close.assert_called_once()


class TestInitDb(unittest.TestCase):
    """Test _init_db initialization."""

    @patch('db._vacuum_if_bloated')
    @patch('db._backup_db')
    @patch('db._check_and_recover_db')
    @patch('db._migrate_schema')
    @patch('db.sqlite3.connect')
    @patch('db.DB_PATH')
    def test_init_db_creates_tables(self, mock_path, mock_connect, mock_migrate,
                                    mock_check, mock_backup, mock_vacuum):
        """_init_db creates schema if not exists."""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_path.parent.mkdir = MagicMock()
        
        db._init_db()
        
        # Should set journal mode
        mock_conn.execute.assert_called()
        # Should call executescript with CREATE TABLE statements
        mock_conn.executescript.assert_called()

    @patch('db._vacuum_if_bloated')
    @patch('db._backup_db')
    @patch('db._check_and_recover_db')
    @patch('db._migrate_schema')
    @patch('db.sqlite3.connect')
    @patch('db.DB_PATH')
    def test_init_db_calls_migrate_schema(self, mock_path, mock_connect, mock_migrate,
                                          mock_check, mock_backup, mock_vacuum):
        """_init_db runs schema migration."""
        mock_conn = MagicMock()
        mock_connect.return_value = mock_conn
        mock_path.parent.mkdir = MagicMock()
        
        db._init_db()
        
        mock_migrate.assert_called_once()


class TestDomainModuleImports(unittest.TestCase):
    """Test that domain modules are properly imported."""

    def test_sessions_module_functions_exported(self):
        """Session functions are exported from db.py."""
        self.assertTrue(hasattr(db, '_db_insert_session'))
        self.assertTrue(hasattr(db, '_db_insert_action'))
        self.assertTrue(hasattr(db, '_db_update_session'))

    def test_llm_module_functions_exported(self):
        """LLM logging functions exported."""
        self.assertTrue(hasattr(db, '_log_llm_call'))
        self.assertTrue(hasattr(db, '_get_session_calls'))

    def test_tools_module_functions_exported(self):
        """Tool execution functions exported."""
        self.assertTrue(hasattr(db, '_log_tool_execution'))
        self.assertTrue(hasattr(db, '_get_session_tool_executions'))

    def test_auth_module_functions_exported(self):
        """Auth functions exported."""
        self.assertTrue(hasattr(db, 'find_or_create_user'))
        self.assertTrue(hasattr(db, 'create_auth_token'))
        self.assertTrue(hasattr(db, 'verify_auth_token'))

    def test_exports_module_functions_exported(self):
        """Export functions exported."""
        self.assertTrue(hasattr(db, '_export_session_to_file'))
        self.assertTrue(hasattr(db, '_read_session_from_file'))


class TestModuleConstants(unittest.TestCase):
    """Test module-level constants."""

    def test_all_constant_globals_exported(self):
        """All important constants in __all__ are defined."""
        all_list = db.__all__
        self.assertIn('_init_db', all_list)
        self.assertIn('_db_insert_session', all_list)
        self.assertIn('_log_llm_call', all_list)


if __name__ == '__main__':
    unittest.main()
