"""ARC-AGI-3 Database Layer — SQLite persistence."""

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
    """Create the sessions database and tables if they don't exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            game_id TEXT NOT NULL,
            model TEXT DEFAULT '',
            mode TEXT DEFAULT 'local',
            created_at REAL NOT NULL,
            result TEXT DEFAULT 'NOT_FINISHED',
            steps INTEGER DEFAULT 0,
            levels INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS session_steps (
            session_id TEXT NOT NULL,
            step_num INTEGER NOT NULL,
            action INTEGER NOT NULL,
            data_json TEXT DEFAULT '{}',
            grid_snapshot TEXT,
            change_map_json TEXT,
            llm_response_json TEXT,
            timestamp REAL NOT NULL,
            PRIMARY KEY (session_id, step_num),
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        );
    """)
    # Schema migration: add columns (idempotent)
    for col, defn in [("parent_session_id", "TEXT DEFAULT NULL"),
                      ("branch_at_step", "INTEGER DEFAULT NULL"),
                      ("total_cost", "REAL DEFAULT 0"),
                      ("prompts_json", "TEXT DEFAULT NULL"),
                      ("timeline_json", "TEXT DEFAULT NULL"),
                      ("user_id", "TEXT DEFAULT NULL"),
                      ("player_type", "TEXT DEFAULT 'agent'"),
                      ("duration_seconds", "REAL DEFAULT NULL")]:
        try:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {col} {defn}")
        except sqlite3.OperationalError:
            pass  # column already exists
    # Session events table (compaction, branch, resume tracking)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            step_num INTEGER,
            data_json TEXT DEFAULT '{}',
            timestamp REAL NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)
    # LLM call log table
    conn.execute("""
        CREATE TABLE IF NOT EXISTS llm_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            call_type TEXT NOT NULL,
            step_num INTEGER,
            parent_call_id INTEGER,
            model TEXT NOT NULL,
            prompt_preview TEXT,
            prompt_length INTEGER,
            response_preview TEXT,
            response_json TEXT,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cost REAL DEFAULT 0,
            duration_ms INTEGER DEFAULT 0,
            thinking_level TEXT,
            tools_active INTEGER DEFAULT 0,
            cache_active INTEGER DEFAULT 0,
            error TEXT,
            attempt INTEGER DEFAULT 0,
            timestamp REAL NOT NULL,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_llm_calls_session ON llm_calls(session_id)")
    except sqlite3.OperationalError:
        pass
    # Schema migration: add turn_num to llm_calls
    try:
        conn.execute("ALTER TABLE llm_calls ADD COLUMN turn_num INTEGER")
    except sqlite3.OperationalError:
        pass  # column already exists
    # Session turns table (planning cycles)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_turns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            turn_num INTEGER NOT NULL,
            turn_type TEXT NOT NULL,
            goal TEXT,
            plan_json TEXT,
            steps_planned INTEGER DEFAULT 0,
            steps_executed INTEGER DEFAULT 0,
            step_start INTEGER,
            step_end INTEGER,
            llm_calls INTEGER DEFAULT 0,
            total_input_tokens INTEGER DEFAULT 0,
            total_output_tokens INTEGER DEFAULT 0,
            total_cost REAL DEFAULT 0,
            total_duration_ms INTEGER DEFAULT 0,
            replan_reason TEXT,
            world_model_updated INTEGER DEFAULT 0,
            rules_version INTEGER DEFAULT 0,
            timestamp_start REAL NOT NULL,
            timestamp_end REAL,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_session_turns_session ON session_turns(session_id)")
    except sqlite3.OperationalError:
        pass
    # Leaderboard index: covers player_type filter + ORDER BY levels/steps
    try:
        conn.execute("""CREATE INDEX IF NOT EXISTS idx_sessions_leaderboard
                        ON sessions(player_type, steps, levels DESC)""")
    except sqlite3.OperationalError:
        pass
    # Batch tables
    conn.executescript("""
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
    """)
    # Observability events table (client-side obs screen events synced to server)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS obs_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            event_idx INTEGER NOT NULL,
            event_json TEXT NOT NULL,
            timestamp REAL NOT NULL
        )
    """)
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_obs_session ON obs_events(session_id, event_idx)")
    except sqlite3.OperationalError:
        pass
    # Comments table (per-game discussion)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id TEXT NOT NULL,
            author_id TEXT NOT NULL,
            author_name TEXT NOT NULL,
            body TEXT NOT NULL,
            upvotes INTEGER DEFAULT 0,
            downvotes INTEGER DEFAULT 0,
            created_at REAL NOT NULL
        )
    """)
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_comments_game ON comments(game_id, created_at DESC)")
    except sqlite3.OperationalError:
        pass
    # Track who voted on which comment (prevent double-voting)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS comment_votes (
            comment_id INTEGER NOT NULL,
            voter_id TEXT NOT NULL,
            vote INTEGER NOT NULL,
            PRIMARY KEY (comment_id, voter_id),
            FOREIGN KEY (comment_id) REFERENCES comments(id)
        )
    """)
    # Auth tables
    conn.executescript("""
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
    """)
    conn.commit()
    conn.close()


def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _compress_grid(grid: list) -> str:
    """Compress a grid to zlib+base64 for storage."""
    raw = json.dumps(grid).encode()
    return base64.b64encode(zlib.compress(raw)).decode()


def _decompress_grid(data: str) -> list:
    """Decompress a zlib+base64 grid."""
    return json.loads(zlib.decompress(base64.b64decode(data)))


def _db_insert_session(session_id: str, game_id: str, mode: str):
    """Insert a new session record."""
    try:
        conn = _get_db()
        conn.execute(
            "INSERT OR IGNORE INTO sessions (id, game_id, mode, created_at) VALUES (?, ?, ?, ?)",
            (session_id, game_id, mode, time.time()),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning(f"DB insert session failed: {e}")


def _db_insert_step(session_id: str, step_num: int, action: int,
                     data: dict, grid: list, change_map: dict,
                     llm_response: dict | None = None):
    """Insert a step record with compressed grid."""
    try:
        conn = _get_db()
        conn.execute(
            "INSERT OR REPLACE INTO session_steps "
            "(session_id, step_num, action, data_json, grid_snapshot, change_map_json, llm_response_json, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id, step_num, action,
                json.dumps(data),
                _compress_grid(grid) if grid else None,
                json.dumps(change_map) if change_map else None,
                json.dumps(llm_response) if llm_response else None,
                time.time(),
            ),
        )
        conn.execute(
            "UPDATE sessions SET steps = ?, result = (SELECT result FROM sessions WHERE id = ?) WHERE id = ?",
            (step_num, session_id, session_id),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning(f"DB insert step failed: {e}")


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
            "parent_session_id, branch_at_step, total_cost, user_id "
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


def _log_llm_call(session_id: str, call_type: str, model: str, *,
                   step_num: int | None = None,
                   turn_num: int | None = None,
                   parent_call_id: int | None = None,
                   prompt_preview: str | None = None,
                   prompt_length: int = 0,
                   response_preview: str | None = None,
                   response_json: dict | None = None,
                   input_tokens: int = 0,
                   output_tokens: int = 0,
                   cost: float = 0,
                   duration_ms: int = 0,
                   thinking_level: str | None = None,
                   tools_active: bool = False,
                   cache_active: bool = False,
                   error: str | None = None,
                   attempt: int = 0) -> int | None:
    """Insert an LLM call log row. Returns call_id or None on failure."""
    try:
        conn = _get_db()
        cur = conn.execute(
            "INSERT INTO llm_calls "
            "(session_id, call_type, step_num, turn_num, parent_call_id, model, "
            " prompt_preview, prompt_length, response_preview, response_json, "
            " input_tokens, output_tokens, cost, duration_ms, "
            " thinking_level, tools_active, cache_active, error, attempt, timestamp) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id, call_type, step_num, turn_num, parent_call_id, model,
                prompt_preview[:500] if prompt_preview else None,
                prompt_length,
                response_preview[:1000] if response_preview else None,
                json.dumps(response_json) if response_json else None,
                input_tokens, output_tokens, cost, duration_ms,
                thinking_level, int(tools_active), int(cache_active),
                error, attempt, time.time(),
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


def _log_turn(session_id: str, turn_num: int, turn_type: str, *,
               goal: str = "", plan_json: str | None = None,
               steps_planned: int = 0, steps_executed: int = 0,
               step_start: int | None = None, step_end: int | None = None,
               llm_calls: int = 0,
               total_input_tokens: int = 0, total_output_tokens: int = 0,
               total_cost: float = 0, total_duration_ms: int = 0,
               replan_reason: str | None = None,
               world_model_updated: bool = False, rules_version: int = 0,
               timestamp_start: float = 0, timestamp_end: float | None = None) -> int | None:
    """Insert a turn log row. Returns turn_id or None on failure."""
    try:
        conn = _get_db()
        cur = conn.execute(
            "INSERT INTO session_turns "
            "(session_id, turn_num, turn_type, goal, plan_json, "
            " steps_planned, steps_executed, step_start, step_end, "
            " llm_calls, total_input_tokens, total_output_tokens, "
            " total_cost, total_duration_ms, replan_reason, "
            " world_model_updated, rules_version, timestamp_start, timestamp_end) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                session_id, turn_num, turn_type,
                goal[:500] if goal else None, plan_json,
                steps_planned, steps_executed, step_start, step_end,
                llm_calls, total_input_tokens, total_output_tokens,
                total_cost, total_duration_ms, replan_reason,
                int(world_model_updated), rules_version,
                timestamp_start or time.time(),
                timestamp_end,
            ),
        )
        turn_id = cur.lastrowid
        conn.commit()
        conn.close()
        return turn_id
    except Exception as e:
        log.warning(f"_log_turn failed: {e}")
        return None


def _get_session_turns(session_id: str) -> list[dict]:
    """Return all session_turns for a session, ordered by turn_num."""
    try:
        conn = _get_db()
        rows = conn.execute(
            "SELECT * FROM session_turns WHERE session_id = ? ORDER BY turn_num",
            (session_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        log.warning(f"_get_session_turns failed: {e}")
        return []


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

        steps = [dict(r) for r in conn.execute(
            "SELECT * FROM session_steps WHERE session_id = ? ORDER BY step_num", (session_id,),
        ).fetchall()]
        calls = [dict(r) for r in conn.execute(
            "SELECT * FROM llm_calls WHERE session_id = ? ORDER BY id", (session_id,),
        ).fetchall()]
        turns = [dict(r) for r in conn.execute(
            "SELECT * FROM session_turns WHERE session_id = ? ORDER BY turn_num", (session_id,),
        ).fetchall()]
        conn.close()

        # Create directory
        out_dir = SESSIONS_DIR / session_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_db_path = out_dir / "session.db"

        # Create self-contained SQLite
        out_conn = sqlite3.connect(str(out_db_path))
        out_conn.execute("PRAGMA journal_mode=WAL")
        out_conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, game_id TEXT NOT NULL, model TEXT DEFAULT '',
                mode TEXT DEFAULT 'local', created_at REAL NOT NULL,
                result TEXT DEFAULT 'NOT_FINISHED', steps INTEGER DEFAULT 0,
                levels INTEGER DEFAULT 0, parent_session_id TEXT, branch_at_step INTEGER,
                total_cost REAL DEFAULT 0, prompts_json TEXT, timeline_json TEXT, user_id TEXT
            );
            CREATE TABLE IF NOT EXISTS session_steps (
                session_id TEXT NOT NULL, step_num INTEGER NOT NULL, action INTEGER NOT NULL,
                data_json TEXT DEFAULT '{}', grid_snapshot TEXT, change_map_json TEXT,
                llm_response_json TEXT, timestamp REAL NOT NULL,
                PRIMARY KEY (session_id, step_num)
            );
            CREATE TABLE IF NOT EXISTS llm_calls (
                id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, call_type TEXT NOT NULL,
                step_num INTEGER, turn_num INTEGER, parent_call_id INTEGER, model TEXT NOT NULL,
                prompt_preview TEXT, prompt_length INTEGER, response_preview TEXT, response_json TEXT,
                input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,
                cost REAL DEFAULT 0, duration_ms INTEGER DEFAULT 0, thinking_level TEXT,
                tools_active INTEGER DEFAULT 0, cache_active INTEGER DEFAULT 0,
                error TEXT, attempt INTEGER DEFAULT 0, timestamp REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS session_turns (
                id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, turn_num INTEGER NOT NULL,
                turn_type TEXT NOT NULL, goal TEXT, plan_json TEXT,
                steps_planned INTEGER DEFAULT 0, steps_executed INTEGER DEFAULT 0,
                step_start INTEGER, step_end INTEGER, llm_calls INTEGER DEFAULT 0,
                total_input_tokens INTEGER DEFAULT 0, total_output_tokens INTEGER DEFAULT 0,
                total_cost REAL DEFAULT 0, total_duration_ms INTEGER DEFAULT 0,
                replan_reason TEXT, world_model_updated INTEGER DEFAULT 0,
                rules_version INTEGER DEFAULT 0, timestamp_start REAL NOT NULL, timestamp_end REAL
            );
        """)

        # Insert session
        sess_cols = ["id", "game_id", "model", "mode", "created_at", "result", "steps", "levels",
                     "parent_session_id", "branch_at_step", "total_cost", "prompts_json", "timeline_json", "user_id"]
        out_conn.execute(
            f"INSERT OR REPLACE INTO sessions ({','.join(sess_cols)}) VALUES ({','.join('?' for _ in sess_cols)})",
            tuple(sess.get(c) for c in sess_cols),
        )

        # Insert steps
        step_cols = ["session_id", "step_num", "action", "data_json", "grid_snapshot",
                     "change_map_json", "llm_response_json", "timestamp"]
        for s in steps:
            out_conn.execute(
                f"INSERT OR REPLACE INTO session_steps ({','.join(step_cols)}) VALUES ({','.join('?' for _ in step_cols)})",
                tuple(s.get(c) for c in step_cols),
            )

        # Insert calls
        call_cols = ["id", "session_id", "call_type", "step_num", "turn_num", "parent_call_id", "model",
                     "prompt_preview", "prompt_length", "response_preview", "response_json",
                     "input_tokens", "output_tokens", "cost", "duration_ms", "thinking_level",
                     "tools_active", "cache_active", "error", "attempt", "timestamp"]
        for c in calls:
            out_conn.execute(
                f"INSERT OR REPLACE INTO llm_calls ({','.join(call_cols)}) VALUES ({','.join('?' for _ in call_cols)})",
                tuple(c.get(col) for col in call_cols),
            )

        # Insert turns
        turn_cols = ["id", "session_id", "turn_num", "turn_type", "goal", "plan_json",
                     "steps_planned", "steps_executed", "step_start", "step_end", "llm_calls",
                     "total_input_tokens", "total_output_tokens", "total_cost", "total_duration_ms",
                     "replan_reason", "world_model_updated", "rules_version", "timestamp_start", "timestamp_end"]
        for t in turns:
            out_conn.execute(
                f"INSERT OR REPLACE INTO session_turns ({','.join(turn_cols)}) VALUES ({','.join('?' for _ in turn_cols)})",
                tuple(t.get(col) for col in turn_cols),
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
            "turns": len(turns),
        }
        (out_dir / "meta.json").write_text(json.dumps(meta))

        log.info(f"Exported session {session_id} to {out_dir}")
        return out_dir
    except Exception as e:
        log.warning(f"_export_session_to_file failed: {e}")
        return None


def _read_session_from_file(session_id: str) -> dict | None:
    """Read a session from its per-session file directory.

    Returns {"session": {...}, "steps": [...], "calls": [...], "turns": [...]}
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
        steps = [dict(r) for r in conn.execute(
            "SELECT * FROM session_steps WHERE session_id = ? ORDER BY step_num", (session_id,),
        ).fetchall()]
        calls = [dict(r) for r in conn.execute(
            "SELECT * FROM llm_calls WHERE session_id = ? ORDER BY id", (session_id,),
        ).fetchall()]
        turns = [dict(r) for r in conn.execute(
            "SELECT * FROM session_turns WHERE session_id = ? ORDER BY turn_num", (session_id,),
        ).fetchall()]
        conn.close()
        return {"session": dict(sess_row), "steps": steps, "calls": calls, "turns": turns}
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
