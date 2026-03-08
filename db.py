"""ARC-AGI-3 Database Layer — SQLite persistence.

Schema docs: .claude/database_structure.md
"""

import base64
import json
import logging
import os
import secrets
import sqlite3
import time
import uuid
import zlib
from pathlib import Path

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# LOCAL SQLite
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
            mode TEXT DEFAULT 'local'
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
# SESSION CRUD
# ═══════════════════════════════════════════════════════════════════════════

def _db_insert_session(session_id: str, game_id: str, mode: str, user_id: str | None = None):
    """Insert a new session record."""
    try:
        conn = _get_db()
        conn.execute(
            "INSERT OR IGNORE INTO sessions (id, game_id, mode, created_at, user_id) VALUES (?, ?, ?, ?, ?)",
            (session_id, game_id, mode, time.time(), user_id),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning(f"DB insert session failed: {e}")


def _db_insert_action(session_id: str, step_num: int, action: int,
                      states: list | None = None, *,
                      row: int | None = None, col: int | None = None,
                      author_id: str | None = None,
                      author_type: str | None = None,
                      call_id: int | None = None):
    """Insert a game action record."""
    try:
        conn = _get_db()
        conn.execute(
            "INSERT OR REPLACE INTO session_actions "
            "(session_id, step_num, action, row, col, author_id, author_type, call_id, states_json, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id, step_num, action,
                row, col, author_id, author_type, call_id,
                json.dumps(states) if states else None,
                time.time(),
            ),
        )
        conn.execute(
            "UPDATE sessions SET steps = ? WHERE id = ?",
            (step_num, session_id),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning(f"DB insert action failed: {e}")


def _db_update_session(session_id: str, **kwargs):
    """Update session fields."""
    try:
        conn = _get_db()
        sets = ", ".join(f"{k} = ?" for k in kwargs)
        conn.execute(f"UPDATE sessions SET {sets} WHERE id = ?",
                     (*kwargs.values(), session_id))
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning(f"DB update session failed: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# LLM CALLS
# ═══════════════════════════════════════════════════════════════════════════

def _log_llm_call(session_id: str, agent_type: str, model: str, *,
                   agent_id: str | None = None,
                   step_num: int | None = None,
                   turn_num: int | None = None,
                   parent_call_id: int | None = None,
                   input_json: str | None = None,
                   input_tokens: int = 0,
                   output_json: str | None = None,
                   output_tokens: int = 0,
                   thinking_tokens: int = 0,
                   thinking_json: str | None = None,
                   cost: float = 0,
                   duration_ms: int = 0,
                   error: str | None = None) -> int | None:
    """Insert an LLM call log row. Returns call_id or None on failure."""
    try:
        conn = _get_db()
        cur = conn.execute(
            "INSERT INTO llm_calls "
            "(session_id, agent_type, agent_id, step_num, turn_num, parent_call_id, model, "
            " input_json, input_tokens, output_json, output_tokens, "
            " thinking_tokens, thinking_json, "
            " cost, duration_ms, error, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id, agent_type, agent_id,
                step_num, turn_num, parent_call_id, model,
                input_json, input_tokens, output_json, output_tokens,
                thinking_tokens, thinking_json,
                cost, duration_ms, error, time.time(),
            ),
        )
        call_id = cur.lastrowid
        conn.commit()
        conn.close()
        return call_id
    except Exception as e:
        log.warning(f"_log_llm_call failed: {e}")
        return None


def _get_session_calls(session_id: str) -> list[dict]:
    """Return all llm_calls for a session, ordered by timestamp."""
    try:
        conn = _get_db()
        rows = conn.execute(
            "SELECT * FROM llm_calls WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        log.warning(f"_get_session_calls failed: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════
# TOOL EXECUTIONS
# ═══════════════════════════════════════════════════════════════════════════

def _log_tool_execution(session_id: str, tool_name: str, *,
                         call_id: int | None = None,
                         agent_id: str | None = None,
                         code: str | None = None,
                         output: str | None = None,
                         error: str | None = None,
                         variables_snapshot: dict | None = None,
                         is_checkpoint: bool = False) -> int | None:
    """Insert a tool execution record. Returns id or None on failure."""
    try:
        conn = _get_db()
        cur = conn.execute(
            "INSERT INTO tool_executions "
            "(session_id, call_id, agent_id, tool_name, code, output, error, "
            " variables_snapshot_json, is_checkpoint, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id, call_id, agent_id, tool_name,
                code, output, error,
                json.dumps(variables_snapshot) if variables_snapshot else None,
                int(is_checkpoint), time.time(),
            ),
        )
        exec_id = cur.lastrowid
        conn.commit()
        conn.close()
        return exec_id
    except Exception as e:
        log.warning(f"_log_tool_execution failed: {e}")
        return None


def _get_session_tool_executions(session_id: str) -> list[dict]:
    """Return all tool_executions for a session, ordered by id."""
    try:
        conn = _get_db()
        rows = conn.execute(
            "SELECT * FROM tool_executions WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        log.warning(f"_get_session_tool_executions failed: {e}")
        return []


# ═══════════════════════════════════════════════════════════════════════════
# DEPRECATED — backward compat stubs for removed tables
# ═══════════════════════════════════════════════════════════════════════════

def _log_turn(session_id: str, turn_num: int, scaffolding_type: str, **kwargs):
    """Deprecated: session_turns table removed. No-op for backward compat."""
    pass


def _get_session_turns(session_id: str) -> list[dict]:
    """Deprecated: session_turns table removed. Returns empty list."""
    return []


# ═══════════════════════════════════════════════════════════════════════════
# AUTH HELPERS
# ═══════════════════════════════════════════════════════════════════════════

AUTH_TOKEN_TTL = 30 * 24 * 3600  # 30 days
MAGIC_LINK_TTL = 15 * 60         # 15 minutes


def find_or_create_user(email: str, display_name: str = "", google_id: str = "") -> dict | None:
    """Find existing user by email or create a new one. Returns user dict."""
    try:
        conn = _get_db()
        email = email.lower().strip()
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if row:
            user = dict(row)
            updates = ["last_login_at = ?"]
            params = [time.time()]
            if display_name and not user.get("display_name"):
                updates.append("display_name = ?")
                params.append(display_name)
            if google_id and not user.get("google_id"):
                updates.append("google_id = ?")
                params.append(google_id)
            params.append(user["id"])
            conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
            conn.commit()
            conn.close()
            user["last_login_at"] = time.time()
            if display_name and not user.get("display_name"):
                user["display_name"] = display_name
            return user
        user_id = str(uuid.uuid4())
        now = time.time()
        conn.execute(
            "INSERT INTO users (id, email, created_at, last_login_at, display_name, google_id) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, email, now, now, display_name or None, google_id or None),
        )
        conn.commit()
        conn.close()
        return {"id": user_id, "email": email, "created_at": now,
                "last_login_at": now, "display_name": display_name or None}
    except Exception as e:
        log.warning(f"find_or_create_user failed: {e}")
        return None


def create_auth_token(user_id: str) -> str | None:
    """Create a 30-day auth token for a user. Returns token string."""
    try:
        conn = _get_db()
        token = secrets.token_urlsafe(32)
        now = time.time()
        conn.execute(
            "INSERT INTO auth_tokens (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now, now + AUTH_TOKEN_TTL),
        )
        conn.commit()
        conn.close()
        return token
    except Exception as e:
        log.warning(f"create_auth_token failed: {e}")
        return None


def verify_auth_token(token: str) -> dict | None:
    """Verify an auth token and return the user dict, or None."""
    try:
        conn = _get_db()
        row = conn.execute(
            "SELECT u.id, u.email, u.display_name FROM auth_tokens t "
            "JOIN users u ON t.user_id = u.id "
            "WHERE t.token = ? AND t.expires_at > ?",
            (token, time.time()),
        ).fetchone()
        if row:
            conn.execute("UPDATE auth_tokens SET last_used_at = ? WHERE token = ?",
                         (time.time(), token))
            conn.commit()
        conn.close()
        return dict(row) if row else None
    except Exception as e:
        log.warning(f"verify_auth_token failed: {e}")
        return None


def create_magic_link(email: str) -> str | None:
    """Create a single-use magic link code (15-min expiry). Returns code."""
    try:
        conn = _get_db()
        code = secrets.token_urlsafe(32)
        now = time.time()
        conn.execute(
            "INSERT INTO magic_links (code, email, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (code, email.lower().strip(), now, now + MAGIC_LINK_TTL),
        )
        conn.commit()
        conn.close()
        return code
    except Exception as e:
        log.warning(f"create_magic_link failed: {e}")
        return None


def verify_magic_link(code: str) -> str | None:
    """Verify and consume a magic link code. Returns email or None."""
    try:
        conn = _get_db()
        row = conn.execute(
            "SELECT email FROM magic_links WHERE code = ? AND expires_at > ? AND used = 0",
            (code, time.time()),
        ).fetchone()
        if not row:
            conn.close()
            return None
        conn.execute("UPDATE magic_links SET used = 1 WHERE code = ?", (code,))
        conn.commit()
        conn.close()
        return row["email"]
    except Exception as e:
        log.warning(f"verify_magic_link failed: {e}")
        return None


def delete_auth_token(token: str):
    """Delete an auth token (logout)."""
    try:
        conn = _get_db()
        conn.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning(f"delete_auth_token failed: {e}")


def claim_sessions(user_id: str, session_ids: list[str]) -> int:
    """Claim unowned sessions for a user. Returns count of claimed sessions."""
    if not session_ids:
        return 0
    try:
        conn = _get_db()
        placeholders = ",".join("?" for _ in session_ids)
        cur = conn.execute(
            f"UPDATE sessions SET user_id = ? WHERE id IN ({placeholders}) AND user_id IS NULL",
            [user_id] + session_ids,
        )
        count = cur.rowcount if hasattr(cur, 'rowcount') else 0
        conn.commit()
        conn.close()
        return count
    except Exception as e:
        log.warning(f"claim_sessions failed: {e}")
        return 0


def get_user_sessions(user_id: str) -> list[dict]:
    """Get all sessions owned by a user."""
    try:
        conn = _get_db()
        rows = conn.execute(
            "SELECT id, game_id, model, mode, created_at, result, steps, levels, "
            "parent_session_id, branch_at_step, total_cost, user_id, player_type, "
            "steps_per_level_json, duration_seconds "
            "FROM sessions WHERE user_id = ? ORDER BY created_at DESC LIMIT 200",
            (user_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        log.warning(f"get_user_sessions failed: {e}")
        return []


def count_recent_magic_links(email: str, window: float = 900) -> int:
    """Count magic links created for an email in the last `window` seconds."""
    try:
        conn = _get_db()
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM magic_links WHERE email = ? AND created_at > ?",
            (email.lower().strip(), time.time() - window),
        ).fetchone()
        conn.close()
        return row["cnt"] if row else 0
    except Exception as e:
        log.warning(f"count_recent_magic_links failed: {e}")
        return 0


# ═══════════════════════════════════════════════════════════════════════════
# PER-SESSION FILE EXPORT
# ═══════════════════════════════════════════════════════════════════════════

SESSIONS_DIR = _DATA_DIR / "sessions"


def _export_session_to_file(session_id: str) -> Path | None:
    """Export a session from the central DB into a self-contained per-session directory.

    Creates data/sessions/{session_id}/session.db (full SQLite copy) and
    data/sessions/{session_id}/meta.json (lightweight index).
    Idempotent — re-export overwrites existing files.
    Returns the directory path, or None on failure.
    """
    try:
        conn = _get_db()
        sess_row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not sess_row:
            conn.close()
            log.warning(f"_export_session_to_file: session {session_id} not found")
            return None
        sess = dict(sess_row)

        actions = [dict(r) for r in conn.execute(
            "SELECT * FROM session_actions WHERE session_id = ? ORDER BY step_num", (session_id,),
        ).fetchall()]
        calls = [dict(r) for r in conn.execute(
            "SELECT * FROM llm_calls WHERE session_id = ? ORDER BY id", (session_id,),
        ).fetchall()]
        tool_execs = [dict(r) for r in conn.execute(
            "SELECT * FROM tool_executions WHERE session_id = ? ORDER BY id", (session_id,),
        ).fetchall()]
        conn.close()

        # Create directory
        out_dir = SESSIONS_DIR / session_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_db_path = out_dir / "session.db"

        # Create self-contained SQLite with new schema
        out_conn = sqlite3.connect(str(out_db_path))
        out_conn.execute("PRAGMA journal_mode=WAL")
        out_conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, game_id TEXT NOT NULL, created_at REAL NOT NULL,
                user_id TEXT, player_type TEXT DEFAULT 'agent', scaffolding_json TEXT,
                model TEXT DEFAULT '', result TEXT DEFAULT 'NOT_FINISHED',
                steps INTEGER DEFAULT 0, levels INTEGER DEFAULT 0,
                steps_per_level_json TEXT, total_cost REAL DEFAULT 0,
                duration_seconds REAL, parent_session_id TEXT, branch_at_step INTEGER,
                mode TEXT DEFAULT 'local'
            );
            CREATE TABLE IF NOT EXISTS session_actions (
                session_id TEXT NOT NULL, step_num INTEGER NOT NULL, action INTEGER NOT NULL,
                row INTEGER, col INTEGER, author_id TEXT, author_type TEXT,
                call_id INTEGER, states_json TEXT, timestamp REAL NOT NULL,
                PRIMARY KEY (session_id, step_num)
            );
            CREATE TABLE IF NOT EXISTS llm_calls (
                id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, agent_type TEXT NOT NULL,
                agent_id TEXT, step_num INTEGER, turn_num INTEGER, parent_call_id INTEGER,
                model TEXT NOT NULL, input_json TEXT, input_tokens INTEGER DEFAULT 0,
                output_json TEXT, output_tokens INTEGER DEFAULT 0,
                cost REAL DEFAULT 0, duration_ms INTEGER DEFAULT 0,
                error TEXT, timestamp REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tool_executions (
                id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, call_id INTEGER,
                agent_id TEXT, tool_name TEXT NOT NULL, code TEXT, output TEXT, error TEXT,
                variables_snapshot_json TEXT, is_checkpoint INTEGER DEFAULT 0,
                timestamp REAL NOT NULL
            );
        """)

        # Insert session
        sess_cols = ["id", "game_id", "created_at", "user_id", "player_type", "scaffolding_json",
                     "model", "result", "steps", "levels", "steps_per_level_json",
                     "total_cost", "duration_seconds", "parent_session_id", "branch_at_step", "mode"]
        out_conn.execute(
            f"INSERT OR REPLACE INTO sessions ({','.join(sess_cols)}) VALUES ({','.join('?' for _ in sess_cols)})",
            tuple(sess.get(c) for c in sess_cols),
        )

        # Insert actions
        action_cols = ["session_id", "step_num", "action", "row", "col",
                       "author_id", "author_type", "call_id", "states_json", "timestamp"]
        for a in actions:
            out_conn.execute(
                f"INSERT OR REPLACE INTO session_actions ({','.join(action_cols)}) VALUES ({','.join('?' for _ in action_cols)})",
                tuple(a.get(c) for c in action_cols),
            )

        # Insert calls
        call_cols = ["id", "session_id", "agent_type", "agent_id", "step_num", "turn_num",
                     "parent_call_id", "model", "input_json", "input_tokens",
                     "output_json", "output_tokens", "cost", "duration_ms", "error", "timestamp"]
        for c in calls:
            out_conn.execute(
                f"INSERT OR REPLACE INTO llm_calls ({','.join(call_cols)}) VALUES ({','.join('?' for _ in call_cols)})",
                tuple(c.get(col) for col in call_cols),
            )

        # Insert tool executions
        te_cols = ["id", "session_id", "call_id", "agent_id", "tool_name", "code",
                   "output", "error", "variables_snapshot_json", "is_checkpoint", "timestamp"]
        for t in tool_execs:
            out_conn.execute(
                f"INSERT OR REPLACE INTO tool_executions ({','.join(te_cols)}) VALUES ({','.join('?' for _ in te_cols)})",
                tuple(t.get(col) for col in te_cols),
            )

        out_conn.commit()
        out_conn.close()

        # Write meta.json
        total_cost = sess.get("total_cost", 0) or 0
        meta = {
            "id": session_id,
            "game_id": sess.get("game_id", ""),
            "model": sess.get("model", ""),
            "result": sess.get("result", "NOT_FINISHED"),
            "steps": sess.get("steps", 0),
            "levels": sess.get("levels", 0),
            "total_cost": round(total_cost, 4),
            "created_at": sess.get("created_at", 0),
            "calls": len(calls),
        }
        (out_dir / "meta.json").write_text(json.dumps(meta))

        log.info(f"Exported session {session_id} to {out_dir}")
        return out_dir
    except Exception as e:
        log.warning(f"_export_session_to_file failed: {e}")
        return None


def _read_session_from_file(session_id: str) -> dict | None:
    """Read a session from its per-session file directory.

    Returns {"session": {...}, "actions": [...], "calls": [...], "tool_executions": [...]}
    or None if the directory doesn't exist.
    """
    session_dir = SESSIONS_DIR / session_id
    db_path = session_dir / "session.db"
    if not db_path.exists():
        return None
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        sess_row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not sess_row:
            conn.close()
            return None
        actions = [dict(r) for r in conn.execute(
            "SELECT * FROM session_actions WHERE session_id = ? ORDER BY step_num", (session_id,),
        ).fetchall()]
        calls = [dict(r) for r in conn.execute(
            "SELECT * FROM llm_calls WHERE session_id = ? ORDER BY id", (session_id,),
        ).fetchall()]
        tool_execs = [dict(r) for r in conn.execute(
            "SELECT * FROM tool_executions WHERE session_id = ? ORDER BY id", (session_id,),
        ).fetchall()]
        conn.close()
        return {"session": dict(sess_row), "actions": actions, "calls": calls, "tool_executions": tool_execs}
    except Exception as e:
        log.warning(f"_read_session_from_file failed for {session_id}: {e}")
        return None


def _list_file_sessions() -> list[dict]:
    """Scan data/sessions/*/meta.json and return list of metadata dicts, sorted by created_at desc."""
    results = []
    if not SESSIONS_DIR.exists():
        return results
    for meta_path in SESSIONS_DIR.glob("*/meta.json"):
        try:
            meta = json.loads(meta_path.read_text())
            results.append(meta)
        except Exception:
            pass
    results.sort(key=lambda m: m.get("created_at", 0), reverse=True)
    return results


# Initialize DB at import time (for gunicorn/Railway)
_init_db()
