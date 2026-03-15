# Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
# Date: 2026-03-11 13:47
# PURPOSE: SQLite database layer for ARC-AGI-3. Manages schema migrations, session
#   persistence (sessions, session_actions, llm_calls), observatory data, share links,
#   auth (magic links, Google OAuth), leaderboard, and tool execution logging.
#   Single DB file on Railway Volume. Schema docs in .claude/database_structure.md.
#   Modified in Phase 2 to support imports from session_manager.py.
#   Phase 17: Refactored into domain-specific modules (db_sessions, db_auth, db_exports, etc.)
#            with db.py as thin facade + connection manager.
# SRP/DRY check: Pass — all DB operations consolidated here; session state in session_manager.py
"""ARC-AGI-3 Database Layer — SQLite persistence.

Schema docs: .claude/database_structure.md

Phase 17: Modularized facade.
- Core infrastructure: _get_db(), _init_db(), _migrate_schema(), db_conn(), _db()
- Domain modules: db_sessions, db_llm, db_tools, db_auth, db_exports, db_deprecated
- All existing imports from db.py continue to work (re-exported below)
"""

import base64
import json
import logging
import os
import sqlite3
import time
import zlib
from contextlib import contextmanager
from pathlib import Path

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# CORE INFRASTRUCTURE
# ═══════════════════════════════════════════════════════════════════════════

_DATA_DIR = Path(os.environ.get("DB_DATA_DIR", Path(__file__).parent / "data"))
DB_PATH = _DATA_DIR / "sessions.db"


def _init_db():
    """Create the sessions database and tables if they don't exist.

    Also performs schema migrations from the old schema (session_steps, old column names)
    to the new schema (session_actions, renamed columns).
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")

    # ── Migrate old tables before creating new ones ─────────────────────────
    _migrate_schema(conn)

    conn.executescript("""
        -- Session metadata
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            game_id TEXT NOT NULL,
            created_at REAL NOT NULL,
            user_id TEXT,
            player_type TEXT DEFAULT 'agent',
            scaffolding_json TEXT,
            model TEXT DEFAULT '',
            result TEXT DEFAULT 'NOT_FINISHED',
            steps INTEGER DEFAULT 0,
            levels INTEGER DEFAULT 0,
            steps_per_level_json TEXT,
            total_cost REAL DEFAULT 0,
            duration_seconds REAL,
            parent_session_id TEXT,
            branch_at_step INTEGER,
            mode TEXT DEFAULT 'local',
            live_mode INTEGER DEFAULT 0,
            live_fps INTEGER,
            game_version TEXT
        );

        -- Game actions (replaces session_steps)
        CREATE TABLE IF NOT EXISTS session_actions (
            session_id TEXT NOT NULL,
            step_num INTEGER NOT NULL,
            action INTEGER NOT NULL,
            row INTEGER,
            col INTEGER,
            author_id TEXT,
            author_type TEXT,
            call_id INTEGER,
            states_json TEXT,
            timestamp REAL NOT NULL,
            PRIMARY KEY (session_id, step_num),
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );

        -- LLM calls
        CREATE TABLE IF NOT EXISTS llm_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            agent_type TEXT NOT NULL,
            agent_id TEXT,
            step_num INTEGER,
            turn_num INTEGER,
            parent_call_id INTEGER,
            model TEXT NOT NULL,
            input_json TEXT,
            input_tokens INTEGER DEFAULT 0,
            output_json TEXT,
            output_tokens INTEGER DEFAULT 0,
            thinking_tokens INTEGER DEFAULT 0,
            thinking_json TEXT,
            cost REAL DEFAULT 0,
            duration_ms INTEGER DEFAULT 0,
            error TEXT,
            timestamp REAL NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );
        CREATE INDEX IF NOT EXISTS idx_llm_calls_session ON llm_calls(session_id);

        -- Tool executions (REPL code, memory ops)
        CREATE TABLE IF NOT EXISTS tool_executions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            call_id INTEGER,
            agent_id TEXT,
            tool_name TEXT NOT NULL,
            code TEXT,
            output TEXT,
            error TEXT,
            variables_snapshot_json TEXT,
            is_checkpoint INTEGER DEFAULT 0,
            timestamp REAL NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id),
            FOREIGN KEY (call_id) REFERENCES llm_calls(id)
        );
        CREATE INDEX IF NOT EXISTS idx_tool_exec_session ON tool_executions(session_id);

        -- Agent memory snapshots (per-step memory state for inspection)
        CREATE TABLE IF NOT EXISTS agent_memory_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            step_num INTEGER NOT NULL,
            agent_type TEXT DEFAULT 'orchestrator',
            agent_id TEXT,
            memory_json TEXT NOT NULL,
            timestamp REAL NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );
        CREATE INDEX IF NOT EXISTS idx_memory_snap_session ON agent_memory_snapshots(session_id);

        -- Comments
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            author_name TEXT NOT NULL,
            body TEXT NOT NULL,
            upvotes INTEGER DEFAULT 0,
            downvotes INTEGER DEFAULT 0,
            location TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_comments_location ON comments(location, created_at DESC);

        -- Comment votes
        CREATE TABLE IF NOT EXISTS comment_votes (
            comment_id INTEGER NOT NULL,
            voter_id TEXT NOT NULL,
            vote INTEGER NOT NULL,
            PRIMARY KEY (comment_id, voter_id),
            FOREIGN KEY (comment_id) REFERENCES comments(id)
        );

        -- Auth
        CREATE TABLE IF NOT EXISTS users (
            id TEXT PRIMARY KEY,
            email TEXT NOT NULL UNIQUE,
            created_at REAL NOT NULL,
            last_login_at REAL,
            display_name TEXT DEFAULT NULL,
            google_id TEXT DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS auth_tokens (
            token TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            last_used_at REAL,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS magic_links (
            code TEXT PRIMARY KEY,
            email TEXT NOT NULL,
            created_at REAL NOT NULL,
            expires_at REAL NOT NULL,
            used INTEGER DEFAULT 0
        );

        -- Batch tables (CLI batch runner)
        CREATE TABLE IF NOT EXISTS batch_runs (
            id TEXT PRIMARY KEY,
            created_at REAL NOT NULL,
            config_json TEXT,
            status TEXT DEFAULT 'running',
            total_games INTEGER DEFAULT 0,
            completed_games INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            failures INTEGER DEFAULT 0,
            finished_at REAL
        );
        CREATE TABLE IF NOT EXISTS batch_games (
            batch_id TEXT NOT NULL,
            game_id TEXT NOT NULL,
            session_id TEXT,
            status TEXT DEFAULT 'pending',
            result TEXT,
            steps INTEGER DEFAULT 0,
            levels INTEGER DEFAULT 0,
            started_at REAL,
            finished_at REAL,
            error TEXT,
            PRIMARY KEY (batch_id, game_id)
        );

        -- Leaderboard index
        CREATE INDEX IF NOT EXISTS idx_sessions_leaderboard
            ON sessions(player_type, steps, levels DESC);

        -- ═══════════════════════════════════════════════════════════════════
        -- Arena Auto Research tables
        -- ═══════════════════════════════════════════════════════════════════

        -- Per-game auto research context
        CREATE TABLE IF NOT EXISTS arena_research (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            program_md TEXT DEFAULT '',
            program_version INTEGER DEFAULT 0,
            generation INTEGER DEFAULT 0,
            status TEXT DEFAULT 'stopped',
            created_at REAL DEFAULT (unixepoch('now')),
            updated_at REAL DEFAULT (unixepoch('now'))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_ar_game ON arena_research(game_id);

        -- Agents (shared genome pool per game)
        CREATE TABLE IF NOT EXISTS arena_agents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            name TEXT NOT NULL,
            code TEXT NOT NULL,
            generation INTEGER DEFAULT 0,
            elo REAL DEFAULT 1000.0,
            peak_elo REAL DEFAULT 1000.0,
            games_played INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            draws INTEGER DEFAULT 0,
            contributor TEXT,
            is_human INTEGER DEFAULT 0,
            is_anchor INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            created_at REAL DEFAULT (unixepoch('now')),
            UNIQUE(game_id, name)
        );
        CREATE INDEX IF NOT EXISTS idx_aa_game_elo ON arena_agents(game_id, elo DESC);
        CREATE INDEX IF NOT EXISTS idx_aa_game_active ON arena_agents(game_id, active);

        -- Games (matches between agents)
        CREATE TABLE IF NOT EXISTS arena_games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            agent1_id INTEGER REFERENCES arena_agents(id),
            agent2_id INTEGER REFERENCES arena_agents(id),
            winner_id INTEGER REFERENCES arena_agents(id),
            agent1_score INTEGER DEFAULT 0,
            agent2_score INTEGER DEFAULT 0,
            turns INTEGER DEFAULT 0,
            history TEXT DEFAULT '[]',
            is_upset INTEGER DEFAULT 0,
            created_at REAL DEFAULT (unixepoch('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_ag_game ON arena_games(game_id);
        CREATE INDEX IF NOT EXISTS idx_ag_agents ON arena_games(agent1_id, agent2_id);
        CREATE INDEX IF NOT EXISTS idx_ag_created ON arena_games(created_at);

        -- Evolution cycles (LLM conversations that produced agents)
        CREATE TABLE IF NOT EXISTS arena_evolution_cycles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            generation INTEGER,
            worker_label TEXT,
            agents_created INTEGER DEFAULT 0,
            agents_passed INTEGER DEFAULT 0,
            conversation TEXT DEFAULT '[]',
            started_at REAL,
            finished_at REAL
        );
        CREATE INDEX IF NOT EXISTS idx_aec_game ON arena_evolution_cycles(game_id);

        -- Community discussion (strategy comments + votes)
        CREATE TABLE IF NOT EXISTS arena_comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            user_id TEXT,
            username TEXT DEFAULT 'Anon',
            content TEXT NOT NULL,
            comment_type TEXT DEFAULT 'strategy',
            parent_id INTEGER REFERENCES arena_comments(id),
            upvotes INTEGER DEFAULT 0,
            downvotes INTEGER DEFAULT 0,
            created_at REAL DEFAULT (unixepoch('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_ac_game ON arena_comments(game_id, created_at DESC);

        -- Program.md version history (for voting)
        CREATE TABLE IF NOT EXISTS arena_program_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            content TEXT NOT NULL,
            author TEXT,
            change_summary TEXT,
            votes_for INTEGER DEFAULT 0,
            votes_against INTEGER DEFAULT 0,
            vote_deadline REAL,
            applied INTEGER DEFAULT 0,
            created_at REAL DEFAULT (unixepoch('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_apv_game ON arena_program_versions(game_id, version DESC);

        -- Vote tracking (prevent double-voting)
        CREATE TABLE IF NOT EXISTS arena_votes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            version_id INTEGER REFERENCES arena_program_versions(id),
            user_id TEXT NOT NULL,
            vote INTEGER NOT NULL,
            created_at REAL DEFAULT (unixepoch('now')),
            UNIQUE(version_id, user_id)
        );

        -- Human play sessions
        CREATE TABLE IF NOT EXISTS arena_human_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            human_agent_id INTEGER REFERENCES arena_agents(id),
            opponent_id INTEGER REFERENCES arena_agents(id),
            delay_ms INTEGER NOT NULL,
            winner TEXT,
            turns INTEGER DEFAULT 0,
            created_at REAL DEFAULT (unixepoch('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_ahs_game ON arena_human_sessions(game_id);
    """)

    conn.commit()
    conn.close()


def _get_table_columns(conn, table_name: str) -> set[str]:
    """Return a set of column names for a table (empty set if table doesn't exist)."""
    try:
        rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {r[1] for r in rows}
    except Exception:
        return set()


def _table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
    ).fetchone()
    return row is not None


def _migrate_schema(conn):
    """Migrate old DB schema to the new one. Idempotent — safe to run multiple times."""

    # ── 1. sessions: rename prompts_json → scaffolding_json, drop timeline_json ──
    sess_cols = _get_table_columns(conn, "sessions")
    if "prompts_json" in sess_cols and "scaffolding_json" not in sess_cols:
        conn.execute("ALTER TABLE sessions RENAME COLUMN prompts_json TO scaffolding_json")
        log.info("Migrated sessions: prompts_json → scaffolding_json")
    if "timeline_json" in sess_cols:
        # SQLite can't DROP columns before 3.35. We leave it in place but stop using it.
        # On newer SQLite we could drop it, but it's harmless to keep.
        pass
    if "steps_per_level_json" not in sess_cols and sess_cols:
        try:
            conn.execute("ALTER TABLE sessions ADD COLUMN steps_per_level_json TEXT")
            log.info("Migrated sessions: added steps_per_level_json")
        except Exception:
            pass
    if "scaffolding_json" not in sess_cols and "prompts_json" not in sess_cols and sess_cols:
        try:
            conn.execute("ALTER TABLE sessions ADD COLUMN scaffolding_json TEXT")
            log.info("Migrated sessions: added scaffolding_json")
        except Exception:
            pass

    if "player_type" not in sess_cols and sess_cols:
        try:
            conn.execute("ALTER TABLE sessions ADD COLUMN player_type TEXT DEFAULT 'agent'")
            log.info("Migrated sessions: added player_type")
        except Exception:
            pass
    if "live_mode" not in sess_cols and sess_cols:
        try:
            conn.execute("ALTER TABLE sessions ADD COLUMN live_mode INTEGER DEFAULT 0")
            log.info("Migrated sessions: added live_mode")
        except Exception:
            pass
    if "live_fps" not in sess_cols and sess_cols:
        try:
            conn.execute("ALTER TABLE sessions ADD COLUMN live_fps INTEGER")
            log.info("Migrated sessions: added live_fps")
        except Exception:
            pass
    if "game_version" not in sess_cols and sess_cols:
        try:
            conn.execute("ALTER TABLE sessions ADD COLUMN game_version TEXT")
            log.info("Migrated sessions: added game_version")
        except Exception:
            pass

    # ── 2. session_steps → session_actions (migrate data) ──────────────────────
    if _table_exists(conn, "session_steps") and not _table_exists(conn, "session_actions"):
        log.info("Migrating session_steps → session_actions ...")
        conn.execute("""
            CREATE TABLE session_actions (
                session_id TEXT NOT NULL,
                step_num INTEGER NOT NULL,
                action INTEGER NOT NULL,
                row INTEGER,
                col INTEGER,
                author_id TEXT,
                author_type TEXT,
                call_id INTEGER,
                states_json TEXT,
                timestamp REAL NOT NULL,
                PRIMARY KEY (session_id, step_num),
                FOREIGN KEY (session_id) REFERENCES sessions(id)
            )
        """)
        # Copy data, converting data_json→row/col and grid_snapshot→states_json
        old_rows = conn.execute("SELECT * FROM session_steps").fetchall()
        old_cols = _get_table_columns(conn, "session_steps")
        for r in old_rows:
            rd = {col: r[i] for i, col in enumerate(
                [desc[0] for desc in conn.execute("SELECT * FROM session_steps LIMIT 0").description]
            )} if not isinstance(r, dict) else r
            # Parse data_json for row/col
            act_row, act_col = None, None
            if rd.get("data_json"):
                try:
                    d = json.loads(rd["data_json"]) if isinstance(rd["data_json"], str) else rd["data_json"]
                    if isinstance(d, dict):
                        act_col = d.get("x")
                        act_row = d.get("y")
                except Exception:
                    pass
            # Convert grid_snapshot to states_json
            states_json = None
            if rd.get("grid_snapshot"):
                states_json = json.dumps([{"grid": rd["grid_snapshot"]}])
            conn.execute(
                "INSERT OR IGNORE INTO session_actions "
                "(session_id, step_num, action, row, col, states_json, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (rd.get("session_id"), rd.get("step_num"), rd.get("action", 0),
                 act_row, act_col, states_json, rd.get("timestamp", 0)),
            )
        conn.execute("DROP TABLE session_steps")
        log.info(f"Migrated {len(old_rows)} rows from session_steps → session_actions")

    # ── 3. llm_calls: rename call_type → agent_type, response_json → output_json, etc. ──
    llm_cols = _get_table_columns(conn, "llm_calls")
    if "call_type" in llm_cols and "agent_type" not in llm_cols:
        conn.execute("ALTER TABLE llm_calls RENAME COLUMN call_type TO agent_type")
        log.info("Migrated llm_calls: call_type → agent_type")
    if "response_json" in llm_cols and "output_json" not in llm_cols:
        conn.execute("ALTER TABLE llm_calls RENAME COLUMN response_json TO output_json")
        log.info("Migrated llm_calls: response_json → output_json")
    if "response_preview" in llm_cols and "output_json" not in llm_cols and "response_json" not in llm_cols:
        # Old schema had response_preview but not response_json — add output_json
        try:
            conn.execute("ALTER TABLE llm_calls ADD COLUMN output_json TEXT")
            # Copy data from response_preview to output_json
            conn.execute("UPDATE llm_calls SET output_json = response_preview WHERE output_json IS NULL AND response_preview IS NOT NULL")
            log.info("Migrated llm_calls: added output_json from response_preview")
        except Exception:
            pass
    if "agent_id" not in llm_cols and llm_cols:
        try:
            conn.execute("ALTER TABLE llm_calls ADD COLUMN agent_id TEXT")
            log.info("Migrated llm_calls: added agent_id")
        except Exception:
            pass
    if "input_json" not in llm_cols and llm_cols:
        try:
            conn.execute("ALTER TABLE llm_calls ADD COLUMN input_json TEXT")
            # Copy from prompt_preview if available
            if "prompt_preview" in llm_cols:
                conn.execute("UPDATE llm_calls SET input_json = prompt_preview WHERE input_json IS NULL AND prompt_preview IS NOT NULL")
            log.info("Migrated llm_calls: added input_json")
        except Exception:
            pass
    if "output_json" not in llm_cols and "response_json" not in llm_cols and "response_preview" not in llm_cols and llm_cols:
        try:
            conn.execute("ALTER TABLE llm_calls ADD COLUMN output_json TEXT")
            log.info("Migrated llm_calls: added output_json")
        except Exception:
            pass
    if "parent_call_id" not in llm_cols and llm_cols:
        try:
            conn.execute("ALTER TABLE llm_calls ADD COLUMN parent_call_id INTEGER")
            log.info("Migrated llm_calls: added parent_call_id")
        except Exception:
            pass
    if "thinking_tokens" not in llm_cols and llm_cols:
        try:
            conn.execute("ALTER TABLE llm_calls ADD COLUMN thinking_tokens INTEGER DEFAULT 0")
            log.info("Migrated llm_calls: added thinking_tokens")
        except Exception:
            pass
    if "thinking_json" not in llm_cols and llm_cols:
        try:
            conn.execute("ALTER TABLE llm_calls ADD COLUMN thinking_json TEXT")
            log.info("Migrated llm_calls: added thinking_json")
        except Exception:
            pass

    # ── 4. comments: rename game_id → location, author_id → user_id ───────────
    comment_cols = _get_table_columns(conn, "comments")
    if "game_id" in comment_cols and "location" not in comment_cols:
        conn.execute("ALTER TABLE comments RENAME COLUMN game_id TO location")
        # Drop old index, new one will be created by main script
        try:
            conn.execute("DROP INDEX IF EXISTS idx_comments_game")
        except Exception:
            pass
        log.info("Migrated comments: game_id → location")
    if "author_id" in comment_cols and "user_id" not in comment_cols:
        conn.execute("ALTER TABLE comments RENAME COLUMN author_id TO user_id")
        log.info("Migrated comments: author_id → user_id")

    # ── 5. Drop removed tables (session_events, obs_events, session_turns, session_steps) ──
    for old_table in ("session_events", "obs_events", "session_turns"):
        if _table_exists(conn, old_table):
            conn.execute(f"DROP TABLE {old_table}")
            log.info(f"Dropped removed table: {old_table}")
    # Drop session_steps if session_actions already exists (migration done)
    if _table_exists(conn, "session_steps") and _table_exists(conn, "session_actions"):
        conn.execute("DROP TABLE session_steps")
        log.info("Dropped old session_steps table (session_actions exists)")

    conn.commit()


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


@contextmanager
def db_conn():
    """Context manager for SQLite connections with atomic transaction.
    
    Uses BEGIN IMMEDIATE for stricter isolation in high-frequency paths.
    On successful exit, commits the transaction. On exception, rolls back.
    """
    conn = _get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        log.exception("db_conn transaction rolled back: %s", str(e), extra={"operation": "db_conn", "error_type": type(e).__name__})
        raise
    finally:
        conn.close()


@contextmanager
def _db():
    """Context manager for SQLite connections.

    Usage:
        with _db() as conn:
            conn.execute(...)
            # commit happens automatically on clean exit
            # connection closes on exit (clean or exception)
    """
    conn = _get_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# COMPRESSION HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _compress_grid(grid: list) -> str:
    """Compress a grid to zlib+base64 for storage."""
    raw = json.dumps(grid).encode()
    return base64.b64encode(zlib.compress(raw)).decode()


def _decompress_grid(data: str) -> list:
    """Decompress a zlib+base64 grid."""
    return json.loads(zlib.decompress(base64.b64decode(data)))


# ═══════════════════════════════════════════════════════════════════════════
# RE-EXPORTS FROM DOMAIN MODULES (Phase 17 Modularization)
# ═══════════════════════════════════════════════════════════════════════════

# Sessions
from db_sessions import (
    _db_insert_session,
    _db_insert_action,
    _db_update_session,
)

# LLM Calls
from db_llm import (
    _log_llm_call,
    _get_session_calls,
)

# Tool Executions
from db_tools import (
    _log_tool_execution,
    _get_session_tool_executions,
)

# Auth
from db_auth import (
    find_or_create_user,
    create_auth_token,
    verify_auth_token,
    create_magic_link,
    verify_magic_link,
    delete_auth_token,
    claim_sessions,
    get_user_sessions,
    count_recent_magic_links,
    AUTH_TOKEN_TTL,
    MAGIC_LINK_TTL,
)

# Exports
from db_exports import (
    _export_session_to_file,
    _read_session_from_file,
    _list_file_sessions,
    SESSIONS_DIR,
)

# Memory Snapshots
from db_memory import (
    save_memory_snapshot,
    get_session_memory_snapshots,
    get_memory_at_step,
    bulk_save_memory_snapshots,
)

# Deprecated (backward compat)
from db_deprecated import (
    _log_turn,
    _get_session_turns,
)

# Arena Auto Research
from db_arena import (
    arena_get_or_create_research,
    arena_get_leaderboard,
    arena_submit_agent,
    arena_get_agent,
    arena_record_game,
    arena_update_elo,
    arena_get_recent_games,
    arena_get_game,
    arena_count_pair_games,
    arena_prune_weak_agents,
    arena_get_comments,
    arena_post_comment,
    arena_vote_comment,
    arena_get_program,
    arena_propose_program,
    arena_vote_program,
    arena_apply_program_vote,
    arena_submit_human_result,
    arena_get_or_create_human_agent,
    arena_get_research_stats,
    arena_strip_old_history,
    arena_delete_old_games,
)

# Facade exports
__all__ = [
    # Core infrastructure
    '_init_db', '_migrate_schema', '_get_db', 'db_conn', '_db',
    '_compress_grid', '_decompress_grid',
    # Sessions
    '_db_insert_session', '_db_insert_action', '_db_update_session',
    # LLM Calls
    '_log_llm_call', '_get_session_calls',
    # Tool Executions
    '_log_tool_execution', '_get_session_tool_executions',
    # Auth
    'find_or_create_user', 'create_auth_token', 'verify_auth_token',
    'create_magic_link', 'verify_magic_link', 'delete_auth_token',
    'claim_sessions', 'get_user_sessions', 'count_recent_magic_links',
    'AUTH_TOKEN_TTL', 'MAGIC_LINK_TTL',
    # Exports
    '_export_session_to_file', '_read_session_from_file', '_list_file_sessions',
    'SESSIONS_DIR',
    # Memory Snapshots
    'save_memory_snapshot', 'get_session_memory_snapshots',
    'get_memory_at_step', 'bulk_save_memory_snapshots',
    # Deprecated
    '_log_turn', '_get_session_turns',
    # Globals
    '_DATA_DIR', 'DB_PATH',
]

# Initialize DB at import time (for gunicorn/Railway)
_init_db()
