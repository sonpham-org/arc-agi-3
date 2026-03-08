"""ARC-AGI-3 Database Layer — SQLite + Turso persistence."""

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

try:
    import libsql_experimental as libsql
except ImportError:
    libsql = None

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
    # Sync tracking table (local only — tracks what's been uploaded to Turso)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS session_sync (
            session_id TEXT PRIMARY KEY,
            last_step_num INTEGER DEFAULT 0,
            last_turn_num INTEGER DEFAULT 0,
            last_llm_call_id INTEGER DEFAULT 0,
            last_synced_at REAL,
            FOREIGN KEY (session_id) REFERENCES sessions(id)
        )
    """)
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
# TURSO — shared remote DB for persistent session replays
# ═══════════════════════════════════════════════════════════════════════════

TURSO_DATABASE_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")


def _get_turso_db():
    """Return a libsql connection to Turso, or None if not configured.
    Does NOT sync — callers that write must call conn.sync() themselves."""
    if not libsql or not TURSO_DATABASE_URL or not TURSO_AUTH_TOKEN:
        return None
    try:
        conn = libsql.connect("db/turso_replica.db",
                              sync_url=TURSO_DATABASE_URL,
                              auth_token=TURSO_AUTH_TOKEN)
        return conn
    except Exception as e:
        log.warning(f"Turso connection failed: {e}")
        return None


def _turso_dict_fetchone(cursor):
    """Convert a single libsql tuple row to dict using cursor.description."""
    row = cursor.fetchone()
    if not row:
        return None
    cols = [d[0].lower() for d in cursor.description]
    return dict(zip(cols, row))


def _turso_dict_fetchall(cursor):
    """Convert all libsql tuple rows to dicts using cursor.description."""
    rows = cursor.fetchall()
    if not rows:
        return []
    cols = [d[0].lower() for d in cursor.description]
    return [dict(zip(cols, r)) for r in rows]


def _init_turso_db():
    """Create tables on Turso (idempotent). Called at import time."""
    conn = _get_turso_db()
    if not conn:
        return
    try:
        conn.sync()  # hydrate local replica once at startup
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                game_id TEXT NOT NULL,
                model TEXT DEFAULT '',
                mode TEXT DEFAULT 'local',
                created_at REAL NOT NULL,
                result TEXT DEFAULT 'NOT_FINISHED',
                steps INTEGER DEFAULT 0,
                levels INTEGER DEFAULT 0,
                parent_session_id TEXT DEFAULT NULL,
                branch_at_step INTEGER DEFAULT NULL,
                total_cost REAL DEFAULT 0,
                prompts_json TEXT DEFAULT NULL,
                timeline_json TEXT DEFAULT NULL
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
        except Exception:
            pass
        # Schema migration: add turn_num to llm_calls
        try:
            conn.execute("ALTER TABLE llm_calls ADD COLUMN turn_num INTEGER")
        except Exception:
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
        except Exception:
            pass
        # Schema migration: add columns (idempotent)
        for col, defn in [("prompts_json", "TEXT DEFAULT NULL"),
                          ("timeline_json", "TEXT DEFAULT NULL"),
                          ("user_id", "TEXT DEFAULT NULL"),
                          ("player_type", "TEXT DEFAULT 'agent'"),
                          ("duration_seconds", "REAL DEFAULT NULL")]:
            try:
                conn.execute(f"ALTER TABLE sessions ADD COLUMN {col} {defn}")
            except Exception:
                pass  # column already exists
        # Auth tables (Turso only)
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT NOT NULL UNIQUE,
                created_at REAL NOT NULL,
                last_login_at REAL,
                display_name TEXT DEFAULT NULL
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
        # Observability events table
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
        except Exception:
            pass
        conn.commit()
        conn.sync()
        conn.close()
        log.info("Turso DB initialized successfully")
    except Exception as e:
        log.warning(f"Turso DB init failed: {e}")


def _turso_import_session(payload):
    """Write a session + steps to Turso. Reuses same compression logic as local DB."""
    conn = _get_turso_db()
    if not conn:
        return False
    try:
        sess = payload.get("session")
        steps = payload.get("steps", [])
        prompts_json = json.dumps(sess.get("prompts")) if sess.get("prompts") else None
        timeline_json = json.dumps(sess.get("timeline")) if sess.get("timeline") else None
        user_id = sess.get("user_id")
        conn.execute(
            """INSERT INTO sessions (id, game_id, model, mode, created_at, result, steps, levels,
                                     parent_session_id, branch_at_step, prompts_json, timeline_json,
                                     user_id, player_type, duration_seconds)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 result = excluded.result, steps = excluded.steps, levels = excluded.levels,
                 model = COALESCE(excluded.model, sessions.model),
                 prompts_json = COALESCE(excluded.prompts_json, sessions.prompts_json),
                 timeline_json = COALESCE(excluded.timeline_json, sessions.timeline_json),
                 user_id = COALESCE(excluded.user_id, sessions.user_id),
                 player_type = COALESCE(excluded.player_type, sessions.player_type),
                 duration_seconds = COALESCE(excluded.duration_seconds, sessions.duration_seconds)""",
            (sess["id"], sess["game_id"], sess.get("model", ""),
             sess.get("mode", "online"), sess.get("created_at", time.time()),
             sess.get("result", "NOT_FINISHED"), sess.get("steps", 0),
             sess.get("levels", 0), sess.get("parent_session_id"),
             sess.get("branch_at_step"), prompts_json, timeline_json, user_id,
             sess.get("player_type", "agent"), sess.get("duration_seconds")),
        )
        for s in steps:
            grid_snapshot = None
            if s.get("grid"):
                grid_snapshot = _compress_grid(s["grid"])
            conn.execute(
                """INSERT OR REPLACE INTO session_steps
                   (session_id, step_num, action, data_json, grid_snapshot,
                    change_map_json, llm_response_json, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (sess["id"], s.get("step_num", 0), s.get("action", 0),
                 json.dumps(s.get("data", {})),
                 grid_snapshot,
                 json.dumps(s.get("change_map")) if s.get("change_map") else None,
                 json.dumps(s.get("llm_response")) if s.get("llm_response") else None,
                 s.get("timestamp", time.time())),
            )
        # Import llm_calls if present
        for call in payload.get("llm_calls", []):
            conn.execute(
                """INSERT OR IGNORE INTO llm_calls
                   (session_id, call_type, step_num, turn_num, parent_call_id, model,
                    prompt_preview, prompt_length, response_preview, response_json,
                    input_tokens, output_tokens, cost, duration_ms,
                    thinking_level, tools_active, cache_active, error, attempt, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (sess["id"], call.get("call_type", ""), call.get("step_num"),
                 call.get("turn_num"), call.get("parent_call_id"), call.get("model", ""),
                 call.get("prompt_preview"), call.get("prompt_length", 0),
                 call.get("response_preview"), call.get("response_json"),
                 call.get("input_tokens", 0), call.get("output_tokens", 0),
                 call.get("cost", 0), call.get("duration_ms", 0),
                 call.get("thinking_level"), call.get("tools_active", 0),
                 call.get("cache_active", 0), call.get("error"),
                 call.get("attempt", 0), call.get("timestamp", time.time())),
            )
        # Import session_turns if present
        for turn in payload.get("session_turns", []):
            conn.execute(
                """INSERT OR IGNORE INTO session_turns
                   (session_id, turn_num, turn_type, goal, plan_json,
                    steps_planned, steps_executed, step_start, step_end,
                    llm_calls, total_input_tokens, total_output_tokens,
                    total_cost, total_duration_ms, replan_reason,
                    world_model_updated, rules_version, timestamp_start, timestamp_end)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (sess["id"], turn.get("turn_num", 0), turn.get("turn_type", ""),
                 turn.get("goal"), turn.get("plan_json"),
                 turn.get("steps_planned", 0), turn.get("steps_executed", 0),
                 turn.get("step_start"), turn.get("step_end"),
                 turn.get("llm_calls", 0), turn.get("total_input_tokens", 0),
                 turn.get("total_output_tokens", 0), turn.get("total_cost", 0),
                 turn.get("total_duration_ms", 0), turn.get("replan_reason"),
                 turn.get("world_model_updated", 0), turn.get("rules_version", 0),
                 turn.get("timestamp_start", time.time()), turn.get("timestamp_end")),
            )
        conn.commit()
        conn.sync()
        conn.close()
        log.info(f"Turso: imported session {sess['id']} ({len(steps)} steps)")
        return True
    except Exception as e:
        log.warning(f"Turso import failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# INCREMENTAL TURSO SYNC
# ═══════════════════════════════════════════════════════════════════════════

def _get_sync_state(session_id: str) -> dict:
    """Get the sync watermarks for a session. Returns dict with last_step_num, last_turn_num, last_llm_call_id."""
    try:
        conn = _get_db()
        row = conn.execute(
            "SELECT * FROM session_sync WHERE session_id = ?", (session_id,)
        ).fetchone()
        conn.close()
        if row:
            return dict(row)
        return {"session_id": session_id, "last_step_num": 0, "last_turn_num": 0, "last_llm_call_id": 0}
    except Exception as e:
        log.warning(f"_get_sync_state failed: {e}")
        return {"session_id": session_id, "last_step_num": 0, "last_turn_num": 0, "last_llm_call_id": 0}


def _update_sync_state(session_id: str, last_step_num: int, last_turn_num: int, last_llm_call_id: int):
    """Update the sync watermarks after a successful upload."""
    try:
        conn = _get_db()
        conn.execute(
            """INSERT INTO session_sync (session_id, last_step_num, last_turn_num, last_llm_call_id, last_synced_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(session_id) DO UPDATE SET
                 last_step_num = excluded.last_step_num,
                 last_turn_num = excluded.last_turn_num,
                 last_llm_call_id = excluded.last_llm_call_id,
                 last_synced_at = excluded.last_synced_at""",
            (session_id, last_step_num, last_turn_num, last_llm_call_id, time.time()),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        log.warning(f"_update_sync_state failed: {e}")


def _turso_sync_session(session_id: str) -> dict:
    """Incrementally sync a session to Turso. Only uploads rows newer than last sync.

    Returns {"ok": bool, "steps": N, "turns": N, "calls": N} with counts of newly uploaded rows.
    """
    sync = _get_sync_state(session_id)
    result = {"ok": False, "steps": 0, "turns": 0, "calls": 0}

    try:
        conn = _get_db()
        # Always upsert session header (lightweight, has latest result/steps/levels)
        sess_row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not sess_row:
            conn.close()
            log.warning(f"_turso_sync_session: session {session_id} not found locally")
            return result
        sess = dict(sess_row)

        # Fetch only new rows since last sync
        new_steps = conn.execute(
            "SELECT * FROM session_steps WHERE session_id = ? AND step_num > ? ORDER BY step_num",
            (session_id, sync["last_step_num"]),
        ).fetchall()

        conn.close()
    except Exception as e:
        log.warning(f"_turso_sync_session local read failed: {e}")
        return result

    if not new_steps:
        # Session header-only update (result/levels changed but no new steps)
        payload = {"session": sess, "steps": [], "llm_calls": [], "session_turns": []}
        _turso_import_session(payload)
        result["ok"] = True
        return result

    # Build lean payload: only grid snapshots + action per step, no LLM/change data
    lean_steps = []
    for s in new_steps:
        sd = dict(s)
        sd["change_map_json"] = None
        # Keep only model + parsed (reasoning/plan) from llm_response — drops raw text (85% savings)
        if sd.get("llm_response_json"):
            try:
                lr = json.loads(sd["llm_response_json"])
                sd["llm_response_json"] = json.dumps({"model": lr.get("model"), "parsed": lr.get("parsed")})
            except (json.JSONDecodeError, TypeError):
                sd["llm_response_json"] = None
        lean_steps.append(sd)

    payload = {
        "session": sess,
        "steps": lean_steps,
        "llm_calls": [],
        "session_turns": [],
    }

    if not _turso_import_session(payload):
        return result

    # Update watermarks
    new_last_step = new_steps[-1]["step_num"] if new_steps else sync["last_step_num"]
    _update_sync_state(session_id, new_last_step, sync["last_turn_num"], sync["last_llm_call_id"])

    result["ok"] = True
    result["steps"] = len(new_steps)
    result["turns"] = len(new_turns)
    result["calls"] = len(new_calls)
    return result


def sync_all_to_turso(min_steps=5):
    """Sync all local sessions with >= min_steps to Turso. Called on shutdown."""
    if not TURSO_DATABASE_URL:
        return
    try:
        conn = _get_db()
        # Only pick sessions that have new steps beyond their last sync watermark
        rows = conn.execute(
            """SELECT s.id, s.steps FROM sessions s
               LEFT JOIN session_sync ss ON s.id = ss.session_id
               WHERE s.steps >= ?
                 AND (ss.session_id IS NULL OR s.steps > ss.last_step_num)""",
            (min_steps,)
        ).fetchall()
        conn.close()
    except Exception as e:
        log.warning(f"sync_all_to_turso: failed to read local sessions: {e}")
        return
    if not rows:
        log.info("sync_all_to_turso: nothing to sync")
        return
    synced = 0
    for row in rows:
        sid = row["id"] if isinstance(row, sqlite3.Row) else row[0]
        res = _turso_sync_session(sid)
        if res["ok"]:
            synced += 1
    log.info(f"sync_all_to_turso: synced {synced}/{len(rows)} sessions to Turso")


# ═══════════════════════════════════════════════════════════════════════════
# AUTH HELPERS (Turso only)
# ═══════════════════════════════════════════════════════════════════════════

AUTH_TOKEN_TTL = 30 * 24 * 3600  # 30 days
MAGIC_LINK_TTL = 15 * 60         # 15 minutes


def _turso_find_or_create_user(email: str) -> dict | None:
    """Find existing user by email or create a new one. Returns user dict."""
    conn = _get_turso_db()
    if not conn:
        return None
    try:
        email = email.lower().strip()
        cur = conn.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = _turso_dict_fetchone(cur)
        if user:
            conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?",
                         (time.time(), user["id"]))
            conn.commit()
            conn.sync()
            conn.close()
            user["last_login_at"] = time.time()
            return user
        user_id = str(uuid.uuid4())
        now = time.time()
        conn.execute(
            "INSERT INTO users (id, email, created_at, last_login_at) VALUES (?, ?, ?, ?)",
            (user_id, email, now, now),
        )
        conn.commit()
        conn.sync()
        conn.close()
        return {"id": user_id, "email": email, "created_at": now,
                "last_login_at": now, "display_name": None}
    except Exception as e:
        log.warning(f"_turso_find_or_create_user failed: {e}")
        return None


def _turso_create_auth_token(user_id: str) -> str | None:
    """Create a 30-day auth token for a user. Returns token string."""
    conn = _get_turso_db()
    if not conn:
        return None
    try:
        token = secrets.token_urlsafe(32)
        now = time.time()
        conn.execute(
            "INSERT INTO auth_tokens (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now, now + AUTH_TOKEN_TTL),
        )
        conn.commit()
        conn.sync()
        conn.close()
        return token
    except Exception as e:
        log.warning(f"_turso_create_auth_token failed: {e}")
        return None


def _turso_verify_auth_token(token: str) -> dict | None:
    """Verify an auth token and return the user dict, or None."""
    conn = _get_turso_db()
    if not conn:
        return None
    try:
        cur = conn.execute(
            "SELECT u.id, u.email, u.display_name FROM auth_tokens t "
            "JOIN users u ON t.user_id = u.id "
            "WHERE t.token = ? AND t.expires_at > ?",
            (token, time.time()),
        )
        user = _turso_dict_fetchone(cur)
        if user:
            conn.execute("UPDATE auth_tokens SET last_used_at = ? WHERE token = ?",
                         (time.time(), token))
            conn.commit()
            conn.sync()
        conn.close()
        return user
    except Exception as e:
        log.warning(f"_turso_verify_auth_token failed: {e}")
        return None


def _turso_create_magic_link(email: str) -> str | None:
    """Create a single-use magic link code (15-min expiry). Returns code."""
    conn = _get_turso_db()
    if not conn:
        return None
    try:
        code = secrets.token_urlsafe(32)
        now = time.time()
        conn.execute(
            "INSERT INTO magic_links (code, email, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (code, email.lower().strip(), now, now + MAGIC_LINK_TTL),
        )
        conn.commit()
        conn.sync()
        conn.close()
        return code
    except Exception as e:
        log.warning(f"_turso_create_magic_link failed: {e}")
        return None


def _turso_verify_magic_link(code: str) -> str | None:
    """Verify and consume a magic link code. Returns email or None."""
    conn = _get_turso_db()
    if not conn:
        return None
    try:
        cur = conn.execute(
            "SELECT email FROM magic_links WHERE code = ? AND expires_at > ? AND used = 0",
            (code, time.time()),
        )
        row = _turso_dict_fetchone(cur)
        if not row:
            conn.close()
            return None
        conn.execute("UPDATE magic_links SET used = 1 WHERE code = ?", (code,))
        conn.commit()
        conn.sync()
        conn.close()
        return row["email"]
    except Exception as e:
        log.warning(f"_turso_verify_magic_link failed: {e}")
        return None


def _turso_delete_auth_token(token: str):
    """Delete an auth token (logout)."""
    conn = _get_turso_db()
    if not conn:
        return
    try:
        conn.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
        conn.commit()
        conn.sync()
        conn.close()
    except Exception as e:
        log.warning(f"_turso_delete_auth_token failed: {e}")


def _turso_claim_sessions(user_id: str, session_ids: list[str]) -> int:
    """Claim unowned sessions for a user. Returns count of claimed sessions."""
    conn = _get_turso_db()
    if not conn or not session_ids:
        return 0
    try:
        placeholders = ",".join("?" for _ in session_ids)
        cur = conn.execute(
            f"UPDATE sessions SET user_id = ? WHERE id IN ({placeholders}) AND user_id IS NULL",
            [user_id] + session_ids,
        )
        count = cur.rowcount if hasattr(cur, 'rowcount') else 0
        conn.commit()
        conn.sync()
        conn.close()
        return count
    except Exception as e:
        log.warning(f"_turso_claim_sessions failed: {e}")
        return 0


def _turso_get_user_sessions(user_id: str) -> list[dict]:
    """Get all sessions owned by a user from Turso."""
    conn = _get_turso_db()
    if not conn:
        return []
    try:
        cur = conn.execute(
            "SELECT id, game_id, model, mode, created_at, result, steps, levels, "
            "parent_session_id, branch_at_step, total_cost, user_id "
            "FROM sessions WHERE user_id = ? ORDER BY created_at DESC LIMIT 200",
            (user_id,),
        )
        rows = _turso_dict_fetchall(cur)
        conn.close()
        return rows
    except Exception as e:
        log.warning(f"_turso_get_user_sessions failed: {e}")
        return []


def _turso_count_recent_magic_links(email: str, window: float = 900) -> int:
    """Count magic links created for an email in the last `window` seconds."""
    conn = _get_turso_db()
    if not conn:
        return 0
    try:
        cur = conn.execute(
            "SELECT COUNT(*) as cnt FROM magic_links WHERE email = ? AND created_at > ?",
            (email.lower().strip(), time.time() - window),
        )
        row = _turso_dict_fetchone(cur)
        conn.close()
        return row["cnt"] if row else 0
    except Exception as e:
        log.warning(f"_turso_count_recent_magic_links failed: {e}")
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


# Initialize both DBs at import time (for gunicorn/Railway)
_init_db()
_init_turso_db()
