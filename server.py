"""ARC-AGI-3 Web Player + LLM Reasoning Server."""

import argparse
import base64
import copy
import hashlib
import json
import logging
import os
import re
import secrets
import sqlite3
try:
    import libsql_experimental as libsql
except ImportError:
    libsql = None
import sys
import io
import threading
import time
import traceback
import zlib
from collections import deque
from functools import wraps
from pathlib import Path
from typing import Any, Optional

import httpx as _httpx
from dotenv import load_dotenv
from flask import Flask, abort, jsonify, make_response, render_template, request

import arc_agi
from arcengine import GameAction, GameState

load_dotenv(Path(__file__).parent / ".env")

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.logger.setLevel(logging.INFO)

# ═══════════════════════════════════════════════════════════════════════════
# FEATURE FLAGS — dual-mode gating (local vs online)
# ═══════════════════════════════════════════════════════════════════════════

FEATURES = {
    "copilot":       {"local": True,  "online": False},
    "server_llm":    {"local": True,  "online": False},
    "puter_js":      {"local": True,  "online": True},
    "byok":          {"local": True,  "online": True},
    "session_db":    {"local": True,  "online": True},
    "memory_md":     {"local": True,  "online": False},
}

# Will be set by CLI args; default to local
_server_mode = "local"
_server_port_local = 5000
_server_port_online = 5001


def get_mode() -> str:
    """Determine mode from SERVER_MODE env var or port the request arrived on."""
    env_mode = os.environ.get("SERVER_MODE", "")
    if env_mode in ("local", "online"):
        return env_mode
    try:
        port = int(request.environ.get("SERVER_PORT", _server_port_local))
        if port == _server_port_online:
            return "online"
    except (ValueError, RuntimeError):
        pass
    return "local"


def feature_enabled(name: str) -> bool:
    mode = get_mode()
    return FEATURES.get(name, {}).get(mode, False)


def get_enabled_features() -> dict[str, bool]:
    mode = get_mode()
    return {name: feat.get(mode, False) for name, feat in FEATURES.items()}


# ═══════════════════════════════════════════════════════════════════════════
# BOT PROTECTION — Turnstile + Rate Limiting + UA Filtering
# ═══════════════════════════════════════════════════════════════════════════

TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY", "")
TURNSTILE_SECRET_KEY = os.environ.get("TURNSTILE_SECRET_KEY", "")

# Analytics — Umami (set both env vars to enable)
UMAMI_URL = os.environ.get("UMAMI_URL", "")          # e.g. https://umami.example.com
UMAMI_WEBSITE_ID = os.environ.get("UMAMI_WEBSITE_ID", "")

BOT_UA_PATTERNS = [
    "bot", "crawler", "spider", "scraper", "wget", "curl", "python-requests",
    "httpx", "aiohttp", "go-http-client", "java/", "libwww", "headlesschrome",
    "phantomjs", "selenium", "puppeteer", "playwright", "mechanize", "scrapy",
    "chatgpt", "gptbot", "claude-web", "anthropic-ai", "bingbot", "googlebot",
    "baiduspider", "yandexbot", "duckduckbot", "facebookexternalhit",
    "twitterbot", "applebot", "semrushbot", "ahrefsbot", "mj12bot",
    "dotbot", "petalbot", "bytespider", "ccbot",
]

_rate_buckets: dict[str, dict] = {}
_rate_lock = threading.Lock()
RATE_LIMIT = 60       # max requests per window
RATE_WINDOW = 60      # window in seconds

_verified_tokens: dict[str, float] = {}
_token_lock = threading.Lock()
TURNSTILE_TOKEN_TTL = 3600  # verified session lasts 1 hour


def _get_client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _is_bot_ua(ua: str) -> bool:
    ua_lower = ua.lower()
    return any(pat in ua_lower for pat in BOT_UA_PATTERNS)


def _check_rate_limit(ip: str) -> bool:
    now = time.time()
    with _rate_lock:
        bucket = _rate_buckets.get(ip)
        if bucket is None or now - bucket["window_start"] > RATE_WINDOW:
            _rate_buckets[ip] = {"count": 1, "window_start": now}
            return True
        bucket["count"] += 1
        return bucket["count"] <= RATE_LIMIT


def _verify_turnstile_token(token: str, ip: str) -> bool:
    if not TURNSTILE_SECRET_KEY:
        return True
    try:
        resp = _httpx.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": TURNSTILE_SECRET_KEY, "response": token, "remoteip": ip},
            timeout=10.0,
        )
        return resp.json().get("success", False)
    except Exception as e:
        app.logger.warning(f"Turnstile verification failed: {e}")
        return False


def _is_turnstile_verified() -> bool:
    if get_mode() == "local":
        return True  # skip Turnstile in local mode
    if not TURNSTILE_SITE_KEY or not TURNSTILE_SECRET_KEY:
        return True  # skip if not configured
    token_hash = request.cookies.get("ts_verified", "")
    if not token_hash:
        return False
    now = time.time()
    with _token_lock:
        expiry = _verified_tokens.get(token_hash)
        if expiry and now < expiry:
            return True
        _verified_tokens.pop(token_hash, None)
    return False


def bot_protection(f):
    """UA filtering + rate limiting on API routes (online mode only)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if get_mode() == "local":
            return f(*args, **kwargs)
        ip = _get_client_ip()
        ua = request.headers.get("User-Agent", "")
        if _is_bot_ua(ua):
            app.logger.info(f"Blocked bot UA from {ip}: {ua[:80]}")
            abort(403)
        if not _check_rate_limit(ip):
            app.logger.info(f"Rate limited {ip}")
            return jsonify({"error": "Rate limit exceeded. Try again later."}), 429
        return f(*args, **kwargs)
    return decorated


def turnstile_required(f):
    """Require Turnstile verification for protected routes."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _is_turnstile_verified():
            return jsonify({"error": "Human verification required", "need_turnstile": True}), 403
        return f(*args, **kwargs)
    return decorated

# ── Global state ───────────────────────────────────────────────────────────

arcade_instance: Optional[arc_agi.Arcade] = None
game_sessions: dict[str, Any] = {}
session_grids: dict[str, list[list[int]]] = {}
session_snapshots: dict[str, list[dict]] = {}  # session_id → list of snapshots for undo
session_api_mode: dict[str, str] = {}  # session-scoped api mode: "local" or "official"
session_api_keys: dict[str, str] = {}  # session-scoped ARC API keys
session_lock = threading.Lock()
session_step_counts: dict[str, int] = {}  # session_id → server-side step counter
session_last_llm: dict[str, dict] = {}  # session_id → last LLM response (for DB storage)

# ── Tool execution sessions (Python sandbox per game session) ─────────
_tool_sessions: dict[str, dict] = {}  # session_id → {namespace: dict, created_at: float}
_tool_session_lock = threading.Lock()

# ── Gemini context caching ────────────────────────────────────────────
# Maps (model, content_hash) → {cache_name: str, expires_at: float}
_gemini_cache_registry: dict[tuple, dict] = {}
_gemini_cache_lock = threading.Lock()

# ── Copilot auth state ────────────────────────────────────────────────────
_COPILOT_TOKEN_FILE = Path(__file__).parent / "data" / ".copilot_token"

def _load_copilot_token() -> Optional[str]:
    """Load persisted Copilot OAuth token from disk."""
    try:
        if _COPILOT_TOKEN_FILE.exists():
            return _COPILOT_TOKEN_FILE.read_text().strip() or None
    except Exception:
        pass
    return None

def _save_copilot_token(token: Optional[str]):
    """Persist Copilot OAuth token to disk."""
    try:
        _COPILOT_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        if token:
            _COPILOT_TOKEN_FILE.write_text(token)
        elif _COPILOT_TOKEN_FILE.exists():
            _COPILOT_TOKEN_FILE.unlink()
    except Exception:
        pass

copilot_oauth_token: Optional[str] = _load_copilot_token()
copilot_api_token: Optional[str] = None  # Copilot short-lived API token
copilot_token_expiry: float = 0.0  # Unix timestamp when copilot_api_token expires
copilot_device_code: Optional[str] = None  # Pending device code during auth flow
copilot_auth_lock = threading.Lock()

# ── Custom memory overrides ──────────────────────────────────────────────
_custom_system_prompt: Optional[str] = None  # overrides ARC_AGI3_DESCRIPTION when set
_custom_hard_memory: Optional[str] = None    # extra agent memory injected into prompt

# ── Per-provider throttle ────────────────────────────────────────────────
# Min seconds between calls per provider (tuned for free tiers)
PROVIDER_MIN_DELAY: dict[str, float] = {
    "gemini":      4.0,   # 15 req/min free
    "anthropic":   1.0,   # paid, generous limits
    "groq":        2.5,   # 30 req/min free (varies by model)
    "mistral":     2.0,   # ~1-2 req/sec free
    "huggingface": 6.0,   # ~10 req/min free
    "cloudflare":  0.5,   # neuron-based, no per-minute limit
    "copilot":     4.0,   # unknown exact limit, pace it out
    "ollama":      0.0,   # local, no limit
}
_provider_last_call: dict[str, float] = {}  # provider → last call unix time
_throttle_lock = threading.Lock()

# ═══════════════════════════════════════════════════════════════════════════
# SQLite SESSION PERSISTENCE
# ═══════════════════════════════════════════════════════════════════════════

DB_PATH = Path(__file__).parent / "data" / "sessions.db"


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
                      ("total_cost", "REAL DEFAULT 0")]:
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
        app.logger.warning(f"DB insert session failed: {e}")


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
        app.logger.warning(f"DB insert step failed: {e}")


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
        app.logger.warning(f"DB update session failed: {e}")

def _reconstruct_session(game_id: str, actions: list[dict], capture_per_step: bool = False):
    """Replay a list of {action, data} dicts on a fresh env. Returns (env, state_dict).
    If capture_per_step=True, also returns list of per-step state dicts."""
    bare_id = game_id.split("-")[0]
    arc = get_arcade()
    env = arc.make(bare_id)
    state = env_state_dict(env)
    per_step_states = [] if capture_per_step else None
    for act in actions:
        action = GameAction.from_id(int(act["action"]))
        data = act.get("data") or None
        if isinstance(data, str):
            data = json.loads(data)
        frame_data = env.step(action, data=data if data else None)
        if frame_data is not None:
            state = env_state_dict(env, frame_data)
        if capture_per_step:
            per_step_states.append({
                "state": state.get("state", "NOT_FINISHED"),
                "levels_completed": state.get("levels_completed", 0),
            })
    if capture_per_step:
        return env, state, per_step_states
    return env, state


def _try_recover_session(session_id: str):
    """Try to recover a session from DB by replaying its steps. Returns (env, state) or (None, None)."""
    try:
        conn = _get_db()
        sess = conn.execute("SELECT game_id FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not sess:
            conn.close()
            return None, None
        rows = conn.execute(
            "SELECT action, data_json FROM session_steps WHERE session_id = ? ORDER BY step_num",
            (session_id,),
        ).fetchall()
        conn.close()
        if not rows:
            # Session exists but no steps — just recreate env at initial state
            bare_id = sess["game_id"].split("-")[0]
            arc = get_arcade()
            env = arc.make(bare_id)
            state = env_state_dict(env)
            with session_lock:
                game_sessions[session_id] = env
                session_grids[session_id] = state.get("grid", [])
                session_snapshots[session_id] = []
                session_step_counts[session_id] = 0
            app.logger.info(f"Recovered session {session_id} (0 steps)")
            return env, state

        actions = [{"action": r["action"], "data": r["data_json"]} for r in rows]
        env, state = _reconstruct_session(sess["game_id"], actions)
        with session_lock:
            game_sessions[session_id] = env
            session_grids[session_id] = state.get("grid", [])
            session_snapshots[session_id] = []
            session_step_counts[session_id] = len(actions)
        app.logger.info(f"Recovered session {session_id} ({len(actions)} steps replayed)")
        return env, state
    except Exception as e:
        app.logger.warning(f"Session recovery failed for {session_id}: {e}")
        return None, None


# Initialize DB at import time (for gunicorn/Railway)
_init_db()


# ═══════════════════════════════════════════════════════════════════════════
# TURSO — shared remote DB for persistent session replays
# ═══════════════════════════════════════════════════════════════════════════

TURSO_DATABASE_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_AUTH_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")


def _get_turso_db():
    """Return a libsql connection to Turso, or None if not configured."""
    if not libsql or not TURSO_DATABASE_URL or not TURSO_AUTH_TOKEN:
        return None
    try:
        conn = libsql.connect("turso_replica.db",
                              sync_url=TURSO_DATABASE_URL,
                              auth_token=TURSO_AUTH_TOKEN)
        conn.sync()
        return conn
    except Exception as e:
        logging.warning(f"Turso connection failed: {e}")
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
                total_cost REAL DEFAULT 0
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
        conn.commit()
        conn.sync()
        conn.close()
        logging.info("Turso DB initialized successfully")
    except Exception as e:
        logging.warning(f"Turso DB init failed: {e}")


def _turso_import_session(payload):
    """Write a session + steps to Turso. Reuses same compression logic as local DB."""
    conn = _get_turso_db()
    if not conn:
        return False
    try:
        sess = payload.get("session")
        steps = payload.get("steps", [])
        conn.execute(
            """INSERT INTO sessions (id, game_id, model, mode, created_at, result, steps, levels,
                                     parent_session_id, branch_at_step)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 result = excluded.result, steps = excluded.steps, levels = excluded.levels,
                 model = COALESCE(excluded.model, sessions.model)""",
            (sess["id"], sess["game_id"], sess.get("model", ""),
             sess.get("mode", "online"), sess.get("created_at", time.time()),
             sess.get("result", "NOT_FINISHED"), sess.get("steps", 0),
             sess.get("levels", 0), sess.get("parent_session_id"),
             sess.get("branch_at_step")),
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
        conn.commit()
        conn.sync()
        conn.close()
        logging.info(f"Turso: imported session {sess['id']} ({len(steps)} steps)")
        return True
    except Exception as e:
        logging.warning(f"Turso import failed: {e}")
        return False


# Initialize Turso DB at import time
_init_turso_db()


COLOR_MAP = {
    0: "#FFFFFF", 1: "#CCCCCC", 2: "#999999", 3: "#666666",
    4: "#333333", 5: "#000000", 6: "#E53AA3", 7: "#FF7BCC",
    8: "#F93C31", 9: "#1E93FF", 10: "#88D8F1", 11: "#FFDC00",
    12: "#FF851B", 13: "#921231", 14: "#4FCC30", 15: "#A356D6",
}

COLOR_NAMES = {
    0: "White", 1: "LightGray", 2: "Gray", 3: "DarkGray",
    4: "VeryDarkGray", 5: "Black", 6: "Magenta", 7: "LightMagenta",
    8: "Red", 9: "Blue", 10: "LightBlue", 11: "Yellow",
    12: "Orange", 13: "Maroon", 14: "Green", 15: "Purple",
}

ACTION_NAMES = {
    0: "RESET", 1: "ACTION1", 2: "ACTION2", 3: "ACTION3",
    4: "ACTION4", 5: "ACTION5", 6: "ACTION6", 7: "ACTION7",
}

ARC_AGI3_DESCRIPTION = """\
ARC-AGI-3 is an interactive reasoning benchmark. Each game is a 64x64 pixel
grid with 16 colors (0-15).  There are NO instructions — you must discover the
rules and goals by experimenting.

Action mappings:
- ACTION1 = UP, ACTION2 = DOWN, ACTION3 = LEFT, ACTION4 = RIGHT (directional movement)
- ACTION5 = context-dependent (cycle, toggle, interact — varies by game)
- ACTION6 = CLICK at (x, y) — for selecting, placing, or interacting with specific cells
- ACTION7 = context-dependent (secondary interact, rotate, swap — varies by game)
- ACTION0 = RESET — restarts the current level. Use only as a last resort.

Key facts:
- States: NOT_FINISHED (playing), WIN (all levels done), GAME_OVER (failed).
- Large uniform regions = background/walls. Small shapes = player/items.
- Edge bars = health/energy/progress meters."""

SYSTEM_MSG = (
    "You are an expert puzzle-solving AI agent. Analyse game grids and output "
    "ONLY valid JSON — no markdown, no explanation outside JSON."
)

# ═══════════════════════════════════════════════════════════════════════════
# MODEL REGISTRY — capabilities include image/reasoning/tools support
# ═══════════════════════════════════════════════════════════════════════════

MODEL_REGISTRY: dict[str, dict] = {
    # ── Gemini ────────────────────────────────────────────────────────────
    "gemini-3.1-pro": {
        "provider": "gemini", "api_model": "gemini-3.1-pro-preview",
        "env_key": "GEMINI_API_KEY",
        "price": "$2/$12 per 1M tok",
        "context_window": 1000000,
        "capabilities": {"image": True, "reasoning": True, "tools": True},
    },
    "gemini-3-pro": {
        "provider": "gemini", "api_model": "gemini-3-pro-preview",
        "env_key": "GEMINI_API_KEY",
        "price": "$2/$12 per 1M tok",
        "context_window": 1000000,
        "capabilities": {"image": True, "reasoning": True, "tools": True},
    },
    "gemini-3-flash": {
        "provider": "gemini", "api_model": "gemini-3-flash-preview",
        "env_key": "GEMINI_API_KEY",
        "price": "$0.50/$3 per 1M tok",
        "context_window": 1000000,
        "capabilities": {"image": True, "reasoning": True, "tools": True},
    },
    "gemini-2.5-pro": {
        "provider": "gemini", "api_model": "gemini-2.5-pro",
        "env_key": "GEMINI_API_KEY",
        "price": "$1.25/$10 per 1M tok",
        "context_window": 1000000,
        "capabilities": {"image": True, "reasoning": True, "tools": True},
    },
    "gemini-2.5-flash": {
        "provider": "gemini", "api_model": "gemini-2.5-flash",
        "env_key": "GEMINI_API_KEY",
        "price": "$0.30/$2.50 per 1M tok",
        "context_window": 1000000,
        "capabilities": {"image": True, "reasoning": True, "tools": True},
    },
    "gemini-2.5-flash-lite": {
        "provider": "gemini", "api_model": "gemini-2.5-flash-lite",
        "env_key": "GEMINI_API_KEY",
        "price": "$0.10/$0.40 per 1M tok",
        "context_window": 1000000,
        "capabilities": {"image": True, "reasoning": False, "tools": False},
    },
    "gemini-2.0-flash": {
        "provider": "gemini", "api_model": "gemini-2.0-flash",
        "env_key": "GEMINI_API_KEY",
        "price": "$0.10/$0.40 per 1M tok",
        "context_window": 1000000,
        "capabilities": {"image": True, "reasoning": False, "tools": True},
    },
    "gemini-2.0-flash-lite": {
        "provider": "gemini", "api_model": "gemini-2.0-flash-lite",
        "env_key": "GEMINI_API_KEY",
        "price": "$0.075/$0.30 per 1M tok",
        "context_window": 1000000,
        "capabilities": {"image": True, "reasoning": False, "tools": False},
    },
    # ── Anthropic ─────────────────────────────────────────────────────────
    "claude-sonnet-4-6": {
        "provider": "anthropic", "api_model": "claude-sonnet-4-6",
        "env_key": "ANTHROPIC_API_KEY",
        "price": "$3/$15 per 1M tok",
        "context_window": 200000,
        "capabilities": {"image": True, "reasoning": True, "tools": True},
    },
    "claude-sonnet-4-5": {
        "provider": "anthropic", "api_model": "claude-sonnet-4-5-20241022",
        "env_key": "ANTHROPIC_API_KEY",
        "price": "$3/$15 per 1M tok",
        "context_window": 200000,
        "capabilities": {"image": True, "reasoning": True, "tools": True},
    },
    "claude-haiku-4-5": {
        "provider": "anthropic", "api_model": "claude-haiku-4-5-20251001",
        "env_key": "ANTHROPIC_API_KEY",
        "price": "$0.80/$4 per 1M tok",
        "context_window": 200000,
        "capabilities": {"image": True, "reasoning": False, "tools": True},
    },
    # ── Groq ──────────────────────────────────────────────────
    "groq/llama-3.3-70b-versatile": {
        "provider": "groq", "api_model": "llama-3.3-70b-versatile",
        "env_key": "GROQ_API_KEY",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "price": "Free tier",
        "context_window": 128000,
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    "groq/gemma2-9b-it": {
        "provider": "groq", "api_model": "gemma2-9b-it",
        "env_key": "GROQ_API_KEY",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "price": "Free tier",
        "context_window": 8192,
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    "groq/mixtral-8x7b-32768": {
        "provider": "groq", "api_model": "mixtral-8x7b-32768",
        "env_key": "GROQ_API_KEY",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "price": "Free tier",
        "context_window": 32768,
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    # ── Mistral ───────────────────────────────────────────────
    "mistral/mistral-small-latest": {
        "provider": "mistral", "api_model": "mistral-small-latest",
        "env_key": "MISTRAL_API_KEY",
        "url": "https://api.mistral.ai/v1/chat/completions",
        "price": "Free tier",
        "context_window": 128000,
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    "mistral/open-mistral-nemo": {
        "provider": "mistral", "api_model": "open-mistral-nemo",
        "env_key": "MISTRAL_API_KEY",
        "url": "https://api.mistral.ai/v1/chat/completions",
        "price": "Free tier",
        "context_window": 128000,
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    # ── HuggingFace ───────────────────────────────────────────────────────
    "hf/qwen2.5-72b-instruct": {
        "provider": "huggingface", "api_model": "Qwen/Qwen2.5-72B-Instruct",
        "env_key": "HUGGINGFACE_API_KEY",
        "url": "https://router.huggingface.co/v1/chat/completions",
        "price": "Free tier",
        "context_window": 128000,
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    "hf/llama-3.1-70b-instruct": {
        "provider": "huggingface", "api_model": "meta-llama/Llama-3.1-70B-Instruct",
        "env_key": "HUGGINGFACE_API_KEY",
        "url": "https://router.huggingface.co/v1/chat/completions",
        "price": "Free tier",
        "context_window": 128000,
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    # ── Cloudflare Workers AI ────────────────────────────────────────────
    "cf/llama-3.3-70b-instruct": {
        "provider": "cloudflare", "api_model": "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        "env_key": "CLOUDFLARE_API_KEY",
        "price": "Free (10k neurons/day)",
        "context_window": 128000,
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    "cf/llama-3.1-8b-instruct": {
        "provider": "cloudflare", "api_model": "@cf/meta/llama-3.1-8b-instruct-fast",
        "env_key": "CLOUDFLARE_API_KEY",
        "price": "Free (10k neurons/day)",
        "context_window": 128000,
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    "cf/llama-4-scout-17b": {
        "provider": "cloudflare", "api_model": "@cf/meta/llama-4-scout-17b-16e-instruct",
        "env_key": "CLOUDFLARE_API_KEY",
        "price": "Free (10k neurons/day)",
        "context_window": 128000,
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    "cf/qwen3-30b": {
        "provider": "cloudflare", "api_model": "@cf/qwen/qwen3-30b-a3b-fp8",
        "env_key": "CLOUDFLARE_API_KEY",
        "price": "Free (10k neurons/day)",
        "context_window": 32768,
        "capabilities": {"image": False, "reasoning": True, "tools": False},
    },
    "cf/qwq-32b": {
        "provider": "cloudflare", "api_model": "@cf/qwen/qwq-32b",
        "env_key": "CLOUDFLARE_API_KEY",
        "price": "Free (10k neurons/day)",
        "context_window": 32768,
        "capabilities": {"image": False, "reasoning": True, "tools": False},
    },
    "cf/deepseek-r1-distill-32b": {
        "provider": "cloudflare", "api_model": "@cf/deepseek-ai/deepseek-r1-distill-qwen-32b",
        "env_key": "CLOUDFLARE_API_KEY",
        "price": "Free (10k neurons/day)",
        "context_window": 32768,
        "capabilities": {"image": False, "reasoning": True, "tools": False},
    },
    "cf/mistral-small-3.1-24b": {
        "provider": "cloudflare", "api_model": "@cf/mistralai/mistral-small-3.1-24b-instruct",
        "env_key": "CLOUDFLARE_API_KEY",
        "price": "Free (10k neurons/day)",
        "context_window": 128000,
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    "cf/llama-3.2-11b-vision": {
        "provider": "cloudflare", "api_model": "@cf/meta/llama-3.2-11b-vision-instruct",
        "env_key": "CLOUDFLARE_API_KEY",
        "price": "Free (10k neurons/day)",
        "context_window": 128000,
        "capabilities": {"image": True, "reasoning": False, "tools": False},
    },
    # ── GitHub Copilot (local only, requires OAuth) ──────────────────────
    "copilot/gpt-4.1": {
        "provider": "copilot", "api_model": "gpt-4.1",
        "env_key": "",  # no env key — auth via OAuth
        "price": "Free (unlimited)",
        "context_window": 1000000,
        "capabilities": {"image": True, "reasoning": False, "tools": True},
    },
    "copilot/gpt-4o": {
        "provider": "copilot", "api_model": "gpt-4o",
        "env_key": "",
        "price": "Free (unlimited)",
        "context_window": 128000,
        "capabilities": {"image": True, "reasoning": False, "tools": True},
    },
    "copilot/gpt-5-mini": {
        "provider": "copilot", "api_model": "gpt-5-mini",
        "env_key": "",
        "price": "Free (unlimited)",
        "context_window": 1000000,
        "capabilities": {"image": True, "reasoning": True, "tools": True},
    },
    "copilot/claude-sonnet-4": {
        "provider": "copilot", "api_model": "claude-sonnet-4",
        "env_key": "",
        "price": "Premium (300/mo)",
        "context_window": 200000,
        "capabilities": {"image": True, "reasoning": True, "tools": True},
    },
    "copilot/gemini-2.5-pro": {
        "provider": "copilot", "api_model": "gemini-2.5-pro",
        "env_key": "",
        "price": "Premium (300/mo)",
        "context_window": 1000000,
        "capabilities": {"image": True, "reasoning": True, "tools": True},
    },
}

# Ollama models discovered at runtime; all support text only by default.
OLLAMA_VRAM = {
    "qwen2.5:32b": "~19GB", "qwen2.5:14b": "~9GB", "qwen3-8b:latest": "~5GB",
    "deepseek-r1:latest": "~5GB", "mistral:7b": "~4.4GB",
    "llama3.1:latest": "~4.9GB", "llama3:latest": "~4.7GB",
    "llava:latest": "~5GB",
}

# Models that support vision via Ollama (llava family)
OLLAMA_VISION_MODELS = {"llava", "llava:latest", "llava:13b", "bakllava"}


# ═══════════════════════════════════════════════════════════════════════════
# GRID HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def get_arcade():
    global arcade_instance
    if arcade_instance is None:
        arcade_instance = arc_agi.Arcade()
    return arcade_instance


def frame_to_grid(frame) -> list[list[int]]:
    return frame.tolist()


def compress_row(row: list[int]) -> str:
    if not row:
        return ""
    parts = []
    cur, count = row[0], 1
    for v in row[1:]:
        if v == cur:
            count += 1
        else:
            parts.append(f"{cur}x{count}" if count > 1 else str(cur))
            cur, count = v, 1
    parts.append(f"{cur}x{count}" if count > 1 else str(cur))
    return " ".join(parts)


def compute_change_map(prev_grid, curr_grid):
    if not prev_grid or not curr_grid:
        return {"changes": [], "change_count": 0, "change_map_text": ""}
    h = min(len(prev_grid), len(curr_grid))
    w = min(len(prev_grid[0]), len(curr_grid[0])) if h > 0 else 0
    changes, rows = [], []
    for y in range(h):
        row_chars = []
        for x in range(w):
            if prev_grid[y][x] != curr_grid[y][x]:
                changes.append({"x": x, "y": y, "from": prev_grid[y][x], "to": curr_grid[y][x]})
                row_chars.append("X")
            else:
                row_chars.append(".")
        row_str = "".join(row_chars)
        if "X" in row_str:
            rows.append(f"Row {y}: {_compress_change_row(row_str)}")
    return {
        "changes": changes,
        "change_count": len(changes),
        "change_map_text": "\n".join(rows) if rows else "(no changes)",
    }


def _compress_change_row(row: str) -> str:
    if not row:
        return ""
    parts = []
    cur, count = row[0], 1
    for ch in row[1:]:
        if ch == cur:
            count += 1
        else:
            parts.append(f"{cur}x{count}" if count > 3 else cur * count)
            cur, count = ch, 1
    parts.append(f"{cur}x{count}" if count > 3 else cur * count)
    return "".join(parts)


def compute_color_histogram(grid: list) -> str:
    if not grid:
        return ""
    counts: dict[int, int] = {}
    for row in grid:
        for v in row:
            counts[v] = counts.get(v, 0) + 1
    return "\n".join(
        f"  {v} ({COLOR_NAMES.get(v, '?')}): {cnt} cells"
        for v, cnt in sorted(counts.items())
    )


def compute_region_map(grid: list) -> str:
    if not grid:
        return ""
    h, w = len(grid), len(grid[0])
    visited = [[False] * w for _ in range(h)]
    regions: dict[int, list] = {}
    for sy in range(h):
        for sx in range(w):
            if visited[sy][sx]:
                continue
            color = grid[sy][sx]
            queue = deque([(sy, sx)])
            visited[sy][sx] = True
            cells = []
            while queue:
                y, x = queue.popleft()
                cells.append((y, x))
                for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and not visited[ny][nx] and grid[ny][nx] == color:
                        visited[ny][nx] = True
                        queue.append((ny, nx))
            ys = [c[0] for c in cells]
            xs = [c[1] for c in cells]
            regions.setdefault(color, []).append({
                "size": len(cells),
                "bbox": f"rows {min(ys)}-{max(ys)}, cols {min(xs)}-{max(xs)}",
            })
    lines = []
    for color in sorted(regions):
        name = COLOR_NAMES.get(color, str(color))
        top = sorted(regions[color], key=lambda r: -r["size"])[:5]
        for r in top:
            lines.append(f"  {color}={name}: {r['size']} cells at {r['bbox']}")
        if len(regions[color]) > 5:
            lines.append(f"  {color}={name}: ... ({len(regions[color]) - 5} more)")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# TOOL EXECUTION — Python sandbox for Gemini function calling
# ═══════════════════════════════════════════════════════════════════════════

def _get_tool_declarations():
    """Return Gemini Tool with a run_python FunctionDeclaration."""
    from google import genai
    return genai.types.Tool(function_declarations=[
        genai.types.FunctionDeclaration(
            name="run_python",
            description=(
                "Execute Python code to analyse the game grid. "
                "Pre-imported: numpy (as np), collections, itertools. "
                "Available variables: `grid` (numpy 2D int array of current grid), "
                "`prev_grid` (numpy 2D int array of previous grid, or None). "
                "Variables you define persist across calls within the same turn. "
                "Use print() to return results. "
                "IMPORTANT: Keep code short and simple — use numpy vectorized ops, "
                "avoid nested loops over large arrays. Combine analyses into one call "
                "when possible. You have max 3 tool calls per turn, so be efficient."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "code": {
                        "type": "STRING",
                        "description": "Python code to execute. Use print() for output.",
                    }
                },
                "required": ["code"],
            },
        ),
    ])


_BLOCKED_MODULES = frozenset({
    'os', 'sys', 'subprocess', 'shutil', 'pathlib', 'socket', 'http',
    'urllib', 'requests', 'httpx', 'aiohttp', 'ftplib', 'smtplib',
    'ctypes', 'multiprocessing', 'signal', 'importlib', 'code', 'codeop',
    'compileall', 'py_compile', 'zipimport', 'pkgutil', 'pkg_resources',
})


def _safe_import(name, *args, **kwargs):
    """Restricted __import__ that blocks dangerous modules."""
    top_level = name.split('.')[0]
    if top_level in _BLOCKED_MODULES:
        raise ImportError(f"Module '{name}' is not allowed in the sandbox")
    return __builtins__['__import__'](name, *args, **kwargs) \
        if isinstance(__builtins__, dict) \
        else __import__(name, *args, **kwargs)


def _get_or_create_tool_session(session_id: str, grid, prev_grid) -> dict:
    """Get or create a sandboxed namespace for Python execution."""
    import numpy as np
    import collections
    import itertools

    with _tool_session_lock:
        sess = _tool_sessions.get(session_id)
        if sess is None:
            # Start from real builtins, override dangerous ones
            if isinstance(__builtins__, dict):
                safe_builtins = dict(__builtins__)
            else:
                safe_builtins = {k: getattr(__builtins__, k) for k in dir(__builtins__)
                                 if not k.startswith('_')}
                safe_builtins['__import__'] = __builtins__.__import__

            # Replace/remove dangerous builtins
            safe_builtins['open'] = None
            safe_builtins['eval'] = None
            safe_builtins['exec'] = None
            safe_builtins['compile'] = None
            safe_builtins['breakpoint'] = None
            safe_builtins['exit'] = None
            safe_builtins['quit'] = None
            safe_builtins['__import__'] = _safe_import

            ns = {
                '__builtins__': safe_builtins,
                'np': np,
                'numpy': np,
                'collections': collections,
                'itertools': itertools,
                'Counter': collections.Counter,
                'defaultdict': collections.defaultdict,
            }
            sess = {'namespace': ns, 'created_at': time.time()}
            _tool_sessions[session_id] = sess

    # Always update grid/prev_grid to current values
    ns = sess['namespace']
    ns['grid'] = np.array(grid) if grid else np.array([[]])
    ns['prev_grid'] = np.array(prev_grid) if prev_grid else None
    return sess


def _execute_python(session_id: str, code: str, grid, prev_grid, timeout: float = 5.0) -> str:
    """Execute Python code in a sandboxed namespace, capturing print output."""
    sess = _get_or_create_tool_session(session_id, grid, prev_grid)
    ns = sess['namespace']

    output_buf = io.StringIO()
    result = [None]  # mutable container for thread result
    error = [None]

    def _run():
        import builtins
        old_print = ns['__builtins__'].get('print', builtins.print) if isinstance(ns['__builtins__'], dict) else builtins.print
        # Override print to capture to buffer
        def captured_print(*args, **kwargs):
            kwargs['file'] = output_buf
            builtins.print(*args, **kwargs)
        if isinstance(ns['__builtins__'], dict):
            ns['__builtins__']['print'] = captured_print
        try:
            exec(code, ns)
        except Exception as e:
            error[0] = f"{type(e).__name__}: {e}"

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        return "[TIMEOUT] Code execution exceeded 5 seconds."

    output = output_buf.getvalue()
    if error[0]:
        output = (output + "\n" + error[0]).strip()

    # Truncate long output
    if len(output) > 4000:
        output = output[:4000] + "\n... [truncated]"

    return output or "(no output)"


def _cleanup_tool_session(session_id: str):
    """Remove a tool session when the game session is reset/ended."""
    with _tool_session_lock:
        _tool_sessions.pop(session_id, None)


# ═══════════════════════════════════════════════════════════════════════════
# GEMINI CONTEXT CACHING
# ═══════════════════════════════════════════════════════════════════════════

# Minimum tokens for Gemini caching (API requirement: 32,768 tokens ≈ ~130K chars)
_GEMINI_CACHE_MIN_CHARS = 130_000
_GEMINI_CACHE_TTL_MINUTES = 30


def _get_or_create_gemini_cache(model: str, static_content: str) -> str | None:
    """Create/reuse a Gemini cached content object for the static prompt parts.

    Returns the cache name string, or None if content is too small for caching.
    """
    if len(static_content) < _GEMINI_CACHE_MIN_CHARS:
        return None

    content_hash = hashlib.sha256(static_content.encode()).hexdigest()[:16]
    cache_key = (model, content_hash)

    with _gemini_cache_lock:
        cached = _gemini_cache_registry.get(cache_key)
        if cached and time.time() < cached["expires_at"]:
            return cached["cache_name"]

    # Create a new cache
    try:
        from google import genai
        api_key = os.environ.get("GEMINI_API_KEY", "")
        client = genai.Client(api_key=api_key)

        cache = client.caches.create(
            model=model,
            config=genai.types.CreateCachedContentConfig(
                contents=[genai.types.Content(
                    role="user",
                    parts=[genai.types.Part.from_text(text=static_content)],
                )],
                ttl=f"{_GEMINI_CACHE_TTL_MINUTES * 60}s",
                display_name=f"arc-agi-{content_hash[:8]}",
            ),
        )

        with _gemini_cache_lock:
            _gemini_cache_registry[cache_key] = {
                "cache_name": cache.name,
                "expires_at": time.time() + (_GEMINI_CACHE_TTL_MINUTES * 60) - 60,
            }
        app.logger.info(f"Created Gemini cache: {cache.name} for model {model}")
        return cache.name
    except Exception as e:
        app.logger.warning(f"Gemini cache creation failed: {e}")
        return None


def _build_prompt_parts(payload: dict, input_settings: dict, tools_mode: str,
                        planning_mode: str = "off") -> tuple[str, str]:
    """Split prompt into static (cacheable) and dynamic parts.

    Returns (static_str, dynamic_str).
    """
    grid = payload.get("grid", [])
    history = payload.get("history", [])
    change_map = payload.get("change_map", {})

    # ── Static parts (system description, palette, memory) ────────────
    static_parts = []
    sys_prompt = _custom_system_prompt if _custom_system_prompt else ARC_AGI3_DESCRIPTION
    static_parts.append(f"""{sys_prompt}

COLOR PALETTE: 0=White 1=LightGray 2=Gray 3=DarkGray 4=VeryDarkGray 5=Black
               6=Magenta 7=LightMagenta 8=Red 9=Blue 10=LightBlue 11=Yellow
               12=Orange 13=Maroon 14=Green 15=Purple""")

    if _custom_hard_memory:
        static_parts.append(f"## AGENT MEMORY\n{_custom_hard_memory}")

    static_str = "\n\n".join(static_parts)

    # ── Dynamic parts (everything else) are built by _build_prompt ────
    # We return just the static portion; the caller uses the full prompt too
    return static_str, ""  # dynamic not needed separately


def env_state_dict(env, frame_data=None) -> dict:
    if frame_data is None:
        frame_data = env.observation_space
    if frame_data is None:
        return {"error": "No frame data available"}
    frames = frame_data.frame
    grid = frame_to_grid(frames[-1]) if frames else []
    available = frame_data.available_actions
    action_labels = {aid: ACTION_NAMES.get(aid, f"ACTION{aid}") for aid in available}
    return {
        "grid": grid,
        "state": frame_data.state.value if hasattr(frame_data.state, "value") else str(frame_data.state),
        "levels_completed": frame_data.levels_completed,
        "win_levels": frame_data.win_levels,
        "available_actions": available,
        "action_labels": action_labels,
        "game_id": frame_data.game_id,
    }


# ═══════════════════════════════════════════════════════════════════════════
# PROMPT BUILDING  (config-driven: input sources, tools mode)
# ═══════════════════════════════════════════════════════════════════════════

def _build_prompt(payload: dict, input_settings: dict, tools_mode: str, planning_mode: str = "off", interrupt_plan: bool = False) -> str:
    """Build an LLM prompt controlled by the input settings from the UI."""
    grid = payload.get("grid", [])
    state = payload.get("state", "")
    available = payload.get("available_actions", [])
    levels_completed = payload.get("levels_completed", 0)
    win_levels = payload.get("win_levels", 0)
    history = payload.get("history", [])
    game_id = payload.get("game_id", "unknown")
    change_map = payload.get("change_map", {})

    parts: list[str] = []

    sys_prompt = _custom_system_prompt if _custom_system_prompt else ARC_AGI3_DESCRIPTION
    parts.append(f"""{sys_prompt}

COLOR PALETTE: 0=White 1=LightGray 2=Gray 3=DarkGray 4=VeryDarkGray 5=Black
               6=Magenta 7=LightMagenta 8=Red 9=Blue 10=LightBlue 11=Yellow
               12=Orange 13=Maroon 14=Green 15=Purple""")

    # ── Hard memory (agent priors) ───────────────────────────────────────
    if _custom_hard_memory:
        parts.append(f"## AGENT MEMORY\n{_custom_hard_memory}")

    # ── State header ──────────────────────────────────────────────────────
    action_desc = ", ".join(f"{a}={ACTION_NAMES.get(a, f'ACTION{a}')}" for a in available)
    parts.append(
        f"## STATE\nGame: {game_id} | State: {state} | "
        f"Levels: {levels_completed}/{win_levels}\n"
        f"Available actions: {action_desc}"
    )

    # ── Compact context (replaces verbose history when provided) ────────
    compact_context = payload.get("compact_context", "")
    if compact_context:
        parts.append(compact_context)

    # ── History (always included) ─────────────────────────────────────────
    if history:
        lines = []
        for h in history:
            aname = ACTION_NAMES.get(h.get("action", 0), "?")
            line = f"  Step {h.get('step', '?')}: {aname} -> {h.get('result_state', '?')}"
            cm = h.get("change_map")
            if cm and cm.get("change_count", 0) > 0:
                line += f" ({cm['change_count']} cells changed)"
                if cm.get("change_map_text"):
                    line += f"\n    Changes: {cm['change_map_text']}"
            elif cm and cm.get("change_count") == 0:
                line += " (no change)"
            grid_snap = h.get("grid")
            if grid_snap:
                rle = "\n".join(f"    Row {i}: {compress_row(r)}" for i, r in enumerate(grid_snap))
                line += f"\n{rle}"
            lines.append(line)
        parts.append(f"## HISTORY ({len(history)} steps)\n" + "\n".join(lines))

    # ── Diff / change map ─────────────────────────────────────────────────
    if input_settings.get("diff") and change_map and change_map.get("change_count", 0) > 0:
        parts.append(
            f"## CHANGES ({change_map['change_count']} cells changed)\n"
            f"{change_map.get('change_map_text', '')}"
        )

    # ── Full grid ─────────────────────────────────────────────────────────
    if input_settings.get("full_grid", True):
        grid_text = "\n".join(f"Row {i}: {compress_row(r)}" for i, r in enumerate(grid))
        parts.append(f"## GRID (RLE, colors 0-15)\n{grid_text}")

    # ── Color histogram ───────────────────────────────────────────────────
    if input_settings.get("color_histogram") or tools_mode == "on":
        histo = compute_color_histogram(grid)
        if histo:
            parts.append(f"## COLOR HISTOGRAM\n{histo}")

    # ── Region map (only with tools=on, or if explicitly requested) ───────
    if tools_mode == "on":
        rmap = compute_region_map(grid)
        if rmap:
            parts.append(f"## REGION MAP\n{rmap}")

    # ── Image note ────────────────────────────────────────────────────────
    if input_settings.get("image"):
        parts.append(
            "## IMAGE\nA screenshot of the current grid is attached. "
            "Use it together with the numeric data above."
        )

    # ── Task block ────────────────────────────────────────────────────────
    tool_extra = ""
    if tools_mode == "on":
        tool_extra = (
            "\n- You have access to a run_python tool. Call it to analyse the grid programmatically "
            "(e.g. find objects, count colors, detect patterns, measure distances). "
            "The grid is available as a numpy array variable `grid`. Use print() to see results."
            '\n- Include "analysis" in your JSON with a summary of what the tool found.'
        )

    analysis_field = ', "analysis": "<detailed spatial analysis>"' if tools_mode == "on" else ''
    is_planning = planning_mode and planning_mode != "off"

    if is_planning:
        plan_n = int(planning_mode)
        expected_field = ', "expected": "<what you expect to see after this plan>"' if interrupt_plan else ''
        expected_rule = '\n- "expected": briefly describe what you expect after the plan completes (e.g. "character at the door", "score increased").' if interrupt_plan else ''
        parts.append(f"""## YOUR TASK
1. Identify key objects (character, walls, targets, items).
2. Determine what must happen next to progress.
3. Plan a sequence of actions (up to {plan_n} steps).

Respond with EXACTLY this JSON (nothing else):
{{"observation": "<what you see>", "reasoning": "<your plan>", "plan": [{{"action": <n>, "data": {{}}}}, ...]{analysis_field}{expected_field}}}

Rules:
- Return a "plan" array of up to {plan_n} steps. Each step has "action" (0-7) and "data" ({{}} or {{"x": <0-63>, "y": <0-63>}}).
- ACTION6: set "data" to {{"x": <0-63>, "y": <0-63>}}.
- Other actions: set "data" to {{}}.{expected_rule}{tool_extra}""")
    else:
        parts.append(f"""## YOUR TASK
1. Identify key objects (character, walls, targets, items).
2. Determine what must happen next to progress.
3. Choose the best action.

Respond with EXACTLY this JSON (nothing else):
{{"observation": "<what you see>", "reasoning": "<your plan>", "action": <number>, "data": {{}}{analysis_field}}}

Rules:
- "action" must be a plain integer (0-7).
- ACTION6: set "data" to {{"x": <0-63>, "y": <0-63>}}.
- Other actions: set "data" to {{}}.{tool_extra}""")

    return "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# LLM CALLS (with multimodal image support)
# ═══════════════════════════════════════════════════════════════════════════

def _parse_llm_response(content: str, model_name: str) -> dict:
    if not isinstance(content, str):
        content = json.dumps(content) if content else ""
    thinking = ""
    think_match = re.search(r"<think>(.*?)</think>", content, re.DOTALL)
    if think_match:
        thinking = think_match.group(1).strip()
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

    # Try to extract JSON from the main content
    parsed = _extract_json(content)
    if parsed:
        return {"raw": content, "thinking": thinking[:500] if thinking else None,
                "parsed": parsed, "model": model_name}

    # If main content had no JSON, try inside the thinking block
    if thinking:
        parsed = _extract_json(thinking)
        if parsed:
            return {"raw": content or thinking, "thinking": thinking[:500],
                    "parsed": parsed, "model": model_name}

    return {"raw": content or thinking, "thinking": thinking[:500] if thinking else None,
            "parsed": None, "model": model_name}


def _extract_json(text: str) -> dict | None:
    """Extract first valid JSON object with 'action' or 'plan' using balanced-brace matching."""
    import re
    cleaned = re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)
    i = 0
    while i < len(cleaned):
        if cleaned[i] != "{":
            i += 1
            continue
        depth = 0
        in_str = False
        esc = False
        for j in range(i, len(cleaned)):
            ch = cleaned[j]
            if esc:
                esc = False
                continue
            if ch == "\\" and in_str:
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(cleaned[i : j + 1])
                        if "action" in obj or "plan" in obj:
                            return obj
                    except json.JSONDecodeError:
                        pass
                    break
        i += 1
    return None


THINKING_BUDGETS = {
    "off": 0,
    "low": 1024,
    "med": 4096,
    "high": 8192,
    "max": 24576,
}


def _call_gemini(model_name: str, prompt: str, image_b64: str | None = None,
                  tools_enabled: bool = False, session_id: str | None = None,
                  grid=None, prev_grid=None,
                  cached_content_name: str | None = None,
                  thinking_level: str = "low",
                  max_tokens: int = 16384) -> dict | str:
    """Call Gemini API. When tools_enabled, runs a multi-turn function-calling loop.

    Returns dict {"text": str, "tool_calls": list, "usage": dict, "cache_active": bool}
    when tools_enabled, or plain str when tools are off (backward compat).
    """
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY", "")
    client = genai.Client(api_key=api_key)

    # Build initial contents
    parts = []
    if image_b64:
        image_bytes = base64.b64decode(image_b64)
        parts.append(genai.types.Part.from_bytes(data=image_bytes, mime_type="image/png"))
    parts.append(genai.types.Part.from_text(text=f"{SYSTEM_MSG}\n\n{prompt}"))
    contents = [genai.types.Content(role="user", parts=parts)]

    is_thinking_model = any(x in model_name for x in ("2.5", "3-pro", "3-flash", "3.1"))
    budget = THINKING_BUDGETS.get(thinking_level, 1024)
    use_thinking = is_thinking_model and budget > 0
    config = genai.types.GenerateContentConfig(
        temperature=0.3,
        max_output_tokens=max_tokens,
    )
    if is_thinking_model:
        config.thinking_config = genai.types.ThinkingConfig(
            thinking_budget=budget,
        )
    if tools_enabled:
        config.tools = [_get_tool_declarations()]
    if cached_content_name:
        config.cached_content = cached_content_name

    tool_calls_log = []
    max_rounds = 3

    for round_i in range(max_rounds):
        # On the last round, remove tools to force a text answer
        if round_i == max_rounds - 1 and config.tools:
            config.tools = None

        response = client.models.generate_content(
            model=model_name, contents=contents, config=config,
        )

        # Check for function calls in the response
        has_function_call = False
        if response.candidates and response.candidates[0].content:
            model_parts = response.candidates[0].content.parts or []
            fn_call_parts = [p for p in model_parts if p.function_call]

            if fn_call_parts and tools_enabled and session_id:
                has_function_call = True
                # Append the model's response to contents
                contents.append(response.candidates[0].content)

                # Execute each function call
                fn_response_parts = []
                for part in fn_call_parts:
                    fc = part.function_call
                    code = fc.args.get("code", "") if fc.args else ""
                    app.logger.info(f"Tool call: {fc.name}, code length: {len(code)}")

                    output = _execute_python(session_id, code, grid, prev_grid)

                    tool_calls_log.append({
                        "name": fc.name,
                        "arguments": {"code": code},
                        "output": output,
                    })

                    fn_response_parts.append(
                        genai.types.Part.from_function_response(
                            name=fc.name,
                            response={"result": output},
                        )
                    )

                # Append function responses and continue the loop
                contents.append(genai.types.Content(
                    role="user",
                    parts=fn_response_parts,
                ))
                continue  # next round

        # No function call — extract final text and return
        final_text = response.text if response.text else ""

        # Detect truncation (hit max_output_tokens)
        truncated = False
        if response.candidates:
            fr = getattr(response.candidates[0], 'finish_reason', None)
            if fr and str(fr).upper() in ("MAX_TOKENS", "2"):
                truncated = True

        # Extract usage if available
        usage = {}
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            um = response.usage_metadata
            usage = {
                "prompt_tokens": getattr(um, 'prompt_token_count', 0) or 0,
                "completion_tokens": getattr(um, 'candidates_token_count', 0) or 0,
                "total_tokens": getattr(um, 'total_token_count', 0) or 0,
            }

        cache_active = cached_content_name is not None
        if tools_enabled:
            return {"text": final_text, "tool_calls": tool_calls_log, "usage": usage,
                    "cache_active": cache_active, "truncated": truncated}
        return {"text": final_text, "truncated": truncated} if truncated else final_text

    # Hit max rounds — return what we have
    final_text = ""
    try:
        final_text = response.text or ""
    except Exception:
        pass
    if tools_enabled:
        return {"text": final_text, "tool_calls": tool_calls_log, "usage": {},
                "cache_active": cached_content_name is not None}
    return final_text


def _call_anthropic(model_name: str, prompt: str, image_b64: str | None = None, max_tokens: int = 16384) -> str:
    import httpx
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    content_blocks: list[dict] = []
    if image_b64:
        content_blocks.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": image_b64},
        })
    content_blocks.append({"type": "text", "text": prompt})

    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model_name, "system": SYSTEM_MSG,
            "messages": [{"role": "user", "content": content_blocks}],
            "temperature": 0.3, "max_tokens": max_tokens,
        },
        timeout=90.0,
    )
    resp.raise_for_status()
    data = resp.json()
    text = data["content"][0]["text"]
    if data.get("stop_reason") == "max_tokens":
        return {"text": text, "truncated": True}
    return text


def _call_openai_compatible(url: str, api_key: str, model: str, prompt: str,
                             image_b64: str | None = None,
                             extra_headers: dict | None = None,
                             max_tokens: int = 16384) -> str:
    import httpx
    if image_b64:
        user_content: list | str = [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
            {"type": "text", "text": prompt},
        ]
    else:
        user_content = prompt

    messages = [
        {"role": "system", "content": SYSTEM_MSG},
        {"role": "user", "content": user_content},
    ]
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    body = {"model": model, "messages": messages, "temperature": 0.3, "max_tokens": max_tokens}

    # Retry with backoff on 429 (rate limit) — up to 3 attempts
    last_exc = None
    for attempt in range(3):
        resp = httpx.post(url, headers=headers, json=body, timeout=90.0)
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("retry-after", 2 ** attempt))
            app.logger.info(f"Rate limited by {url}, retrying in {retry_after}s (attempt {attempt+1}/3)")
            time.sleep(min(retry_after, 30))
            last_exc = httpx.HTTPStatusError(
                f"429 Too Many Requests", request=resp.request, response=resp)
            continue
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        if data["choices"][0].get("finish_reason") == "length":
            return {"text": text, "truncated": True}
        return text
    raise last_exc


def _call_cloudflare(model_name: str, prompt: str, image_b64: str | None = None, max_tokens: int = 16384) -> str:
    import httpx
    api_key = os.environ.get("CLOUDFLARE_API_KEY", "")
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    if not api_key or not account_id:
        raise ValueError("CLOUDFLARE_API_KEY and CLOUDFLARE_ACCOUNT_ID must be set")

    messages = [
        {"role": "system", "content": SYSTEM_MSG},
        {"role": "user", "content": prompt},
    ]

    # Llama 3.2 vision supports image via base64 URL in content array
    if image_b64 and "vision" in model_name:
        messages[-1] = {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                {"type": "text", "text": prompt},
            ],
        }

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model_name}"
    resp = httpx.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"messages": messages, "temperature": 0.3, "max_tokens": max_tokens},
        timeout=90.0,
    )
    resp.raise_for_status()
    data = resp.json()
    result = data.get("result", {})
    if isinstance(result, str):
        return result
    response = result.get("response", "")
    if isinstance(response, dict):
        return json.dumps(response)
    return response or json.dumps(result)


def _call_ollama(model_name: str, prompt: str, image_b64: str | None = None) -> str:
    import ollama
    messages = [
        {"role": "system", "content": SYSTEM_MSG},
        {"role": "user", "content": prompt},
    ]
    if image_b64 and model_name.split(":")[0] in OLLAMA_VISION_MODELS:
        messages[-1]["images"] = [image_b64]

    response = ollama.chat(
        model=model_name, messages=messages,
        options={"temperature": 0.3, "num_predict": 2048},
    )
    return response["message"]["content"]


def _get_copilot_token() -> str:
    """Get a valid Copilot API token, refreshing if needed."""
    global copilot_api_token, copilot_token_expiry
    with copilot_auth_lock:
        if not copilot_oauth_token:
            raise ValueError("Copilot not authenticated. Complete the OAuth flow first.")
        # Refresh if expired or within 5-min safety margin
        if time.time() > copilot_token_expiry - 300:
            import httpx
            resp = httpx.get(
                "https://api.github.com/copilot_internal/v2/token",
                headers={"Authorization": f"token {copilot_oauth_token}",
                         "Accept": "application/json"},
                timeout=30.0,
            )
            if resp.status_code != 200:
                app.logger.error("Copilot token exchange failed: %s %s", resp.status_code, resp.text)
                resp.raise_for_status()
            data = resp.json()
            app.logger.info("Copilot token exchange OK, keys: %s", list(data.keys()))
            copilot_api_token = data["token"]
            copilot_token_expiry = data.get("expires_at", time.time() + 1500)
        return copilot_api_token


def _call_copilot(model_name: str, prompt: str, image_b64: str | None = None) -> str:
    """Call GitHub Copilot Chat completions endpoint."""
    token = _get_copilot_token()
    return _call_openai_compatible(
        url="https://api.githubcopilot.com/chat/completions",
        api_key=token,
        model=model_name,
        prompt=prompt,
        image_b64=image_b64,
        extra_headers={
            "Copilot-Integration-Id": "vscode-chat",
            "editor-version": "vscode/1.100.0",
            "user-agent": "GitHubCopilotChat/0.24.0",
        },
    )


def _throttle_provider(provider: str):
    """Sleep if needed to respect per-provider minimum delay."""
    min_delay = PROVIDER_MIN_DELAY.get(provider, 1.0)
    if min_delay <= 0:
        return
    with _throttle_lock:
        now = time.time()
        last = _provider_last_call.get(provider, 0.0)
        wait = min_delay - (now - last)
        if wait > 0:
            app.logger.info(f"Throttling {provider}: waiting {wait:.1f}s")
            time.sleep(wait)
        _provider_last_call[provider] = time.time()


def _route_model_call(model_key: str, prompt: str, image_b64: str | None = None,
                      tools_enabled: bool = False, session_id: str | None = None,
                      grid=None, prev_grid=None,
                      cached_content_name: str | None = None,
                      thinking_level: str = "low",
                      max_tokens: int = 16384) -> str | dict:
    """Route to the correct provider, passing image if available.

    Returns dict when Gemini tools are active, str otherwise.
    """
    info = MODEL_REGISTRY.get(model_key)

    # If not in registry, try ollama
    if info is None:
        return _call_ollama(model_key, prompt, image_b64)

    provider = info["provider"]
    api_model = info["api_model"]

    # Respect per-provider rate limits
    _throttle_provider(provider)

    # Only pass image if model supports it
    img = image_b64 if info.get("capabilities", {}).get("image") else None

    if provider == "gemini":
        return _call_gemini(api_model, prompt, img,
                            tools_enabled=tools_enabled,
                            session_id=session_id,
                            grid=grid, prev_grid=prev_grid,
                            cached_content_name=cached_content_name,
                            thinking_level=thinking_level,
                            max_tokens=max_tokens)
    if provider == "anthropic":
        return _call_anthropic(api_model, prompt, img, max_tokens=max_tokens)
    if provider == "cloudflare":
        return _call_cloudflare(api_model, prompt, img, max_tokens=max_tokens)
    if provider == "copilot":
        return _call_copilot(api_model, prompt, img)
    if provider == "ollama":
        return _call_ollama(api_model, prompt, img)

    # OpenAI-compatible (Groq, Mistral, HuggingFace) — no image for these
    api_key = os.environ.get(info.get("env_key", ""), "")
    url = info.get("url", "")
    return _call_openai_compatible(url, api_key, api_model, prompt, None, max_tokens=max_tokens)


# ═══════════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════════

@app.after_request
def add_cache_headers(response):
    if response.content_type and "text/html" in response.content_type:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


@app.route("/")
@bot_protection
def index():
    mode = get_mode()
    features = get_enabled_features()
    ts_key = TURNSTILE_SITE_KEY if mode == "online" else ""
    return render_template("index.html", color_map=COLOR_MAP,
                           turnstile_site_key=ts_key,
                           mode=mode, features=features,
                           umami_url=UMAMI_URL, umami_website_id=UMAMI_WEBSITE_ID)


@app.route("/api/turnstile/verify", methods=["POST"])
@bot_protection
def turnstile_verify():
    """Verify a Turnstile token and set a session cookie."""
    payload = request.get_json(force=True)
    token = payload.get("token", "")
    if not token:
        return jsonify({"error": "Token required"}), 400

    ip = _get_client_ip()
    if not _verify_turnstile_token(token, ip):
        return jsonify({"error": "Verification failed"}), 403

    # Generate a session hash and store it
    session_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
    with _token_lock:
        _verified_tokens[session_hash] = time.time() + TURNSTILE_TOKEN_TTL

    resp = make_response(jsonify({"status": "ok"}))
    resp.set_cookie("ts_verified", session_hash,
                     max_age=TURNSTILE_TOKEN_TTL, httponly=True,
                     samesite="Lax", secure=request.is_secure)
    return resp


@app.route("/api/games")
@bot_protection
@turnstile_required
def list_games():
    arc = get_arcade()
    envs = arc.get_environments()
    return jsonify([
        {"game_id": e.game_id, "title": e.title, "default_fps": e.default_fps}
        for e in envs
    ])


@app.route("/api/start", methods=["POST"])
@bot_protection
@turnstile_required
def start_game():
    data = request.get_json(force=True)
    game_id = data.get("game_id")
    if not game_id:
        return jsonify({"error": "game_id required"}), 400
    bare_id = game_id.split("-")[0]
    arc = get_arcade()
    try:
        env = arc.make(bare_id)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    session_id = env._guid if hasattr(env, "_guid") else str(id(env))
    state = env_state_dict(env)
    with session_lock:
        game_sessions[session_id] = env
        session_grids[session_id] = state.get("grid", [])
        session_snapshots[session_id] = []  # reset undo stack
        session_step_counts[session_id] = 0
    _cleanup_tool_session(session_id)
    state["session_id"] = session_id
    state["change_map"] = {"changes": [], "change_count": 0, "change_map_text": "(initial)"}

    # Persist to SQLite
    if feature_enabled("session_db"):
        _db_insert_session(session_id, game_id, get_mode())

    return jsonify(state)


@app.route("/api/step", methods=["POST"])
@bot_protection
@turnstile_required
def step_game():
    payload = request.get_json(force=True)
    session_id = payload.get("session_id")
    action_id = payload.get("action")
    action_data = payload.get("data", {})
    reasoning = payload.get("reasoning")
    if not session_id or action_id is None:
        return jsonify({"error": "session_id and action required"}), 400

    with session_lock:
        env = game_sessions.get(session_id)
    if env is None:
        # Try to recover from DB
        env, recovered_state = _try_recover_session(session_id)
        if env is None:
            return jsonify({"error": "Session not found"}), 404

    try:
        action = GameAction.from_id(int(action_id))
    except ValueError:
        return jsonify({"error": f"Invalid action: {action_id}"}), 400

    with session_lock:
        prev_grid = session_grids.get(session_id, [])
        # Save snapshot for undo before executing the step
        snapshot = {
            "grid": copy.deepcopy(prev_grid),
            "observation_space": copy.deepcopy(env.observation_space) if hasattr(env, "observation_space") else None,
        }
        session_snapshots.setdefault(session_id, []).append(snapshot)

    frame_data = env.step(action, data=action_data or None, reasoning=reasoning)
    if frame_data is None:
        return jsonify({"error": "Step failed"}), 500

    state = env_state_dict(env, frame_data)
    state["session_id"] = session_id
    curr_grid = state.get("grid", [])
    change_map = compute_change_map(prev_grid, curr_grid)
    state["change_map"] = change_map
    state["undo_depth"] = len(session_snapshots.get(session_id, []))
    # Accept client-side LLM response (online mode sends it with the step)
    client_llm_response = payload.get("llm_response")

    with session_lock:
        session_grids[session_id] = curr_grid
        session_step_counts[session_id] = session_step_counts.get(session_id, 0) + 1
        step_num = session_step_counts[session_id]
        # Pop any stashed LLM response, or use client-provided one
        llm_resp = session_last_llm.pop(session_id, None) or client_llm_response

    # Persist step to SQLite
    if feature_enabled("session_db"):
        _db_insert_step(
            session_id, step_num, int(action_id), action_data or {},
            curr_grid, change_map, llm_resp,
        )
        update_kwargs = dict(
            result=state.get("state", "NOT_FINISHED"),
            levels=state.get("levels_completed", 0),
        )
        session_cost = payload.get("session_cost")
        if session_cost is not None:
            update_kwargs["total_cost"] = float(session_cost)
        _db_update_session(session_id, **update_kwargs)

    return jsonify(state)


@app.route("/api/reset", methods=["POST"])
@bot_protection
@turnstile_required
def reset_game():
    payload = request.get_json(force=True)
    session_id = payload.get("session_id")
    with session_lock:
        env = game_sessions.get(session_id)
    if env is None:
        env, _ = _try_recover_session(session_id)
        if env is None:
            return jsonify({"error": "Session not found"}), 404
    frame_data = env.reset()
    state = env_state_dict(env, frame_data)
    state["session_id"] = session_id
    state["change_map"] = {"changes": [], "change_count": 0, "change_map_text": "(reset)"}
    with session_lock:
        session_grids[session_id] = state.get("grid", [])
    return jsonify(state)


@app.route("/api/llm/models")
@bot_protection
@turnstile_required
def llm_models():
    """Return all models with capabilities and availability (mode-aware)."""
    models = []
    mode = get_mode()

    for key, info in MODEL_REGISTRY.items():
        provider = info["provider"]
        # Copilot models need OAuth, not env key
        if provider == "copilot":
            if not feature_enabled("copilot"):
                continue
            available = copilot_oauth_token is not None
        elif mode == "online":
            # In online mode, all server providers shown but marked unavailable
            # (user provides their own key via BYOK)
            available = False
        else:
            env_key = info.get("env_key", "")
            available = bool(not env_key or os.environ.get(env_key))
        models.append({
            "name": key,
            "api_model": info.get("api_model", key),
            "provider": provider,
            "price": info.get("price", "?"),
            "context_window": info.get("context_window", 128000),
            "capabilities": info.get("capabilities", {}),
            "available": available,
        })

    # Discover Ollama models (local only)
    if mode == "local":
        try:
            import ollama
            ollama_list = ollama.list()
            ollama_names = [m.model for m in ollama_list.models] if hasattr(ollama_list, "models") else []
            for name in ollama_names:
                vram = OLLAMA_VRAM.get(name, "local")
                is_vision = name.split(":")[0] in OLLAMA_VISION_MODELS
                models.append({
                    "name": name,
                    "provider": "ollama",
                    "price": f"Free ({vram})",
                    "capabilities": {"image": is_vision, "reasoning": False, "tools": False},
                    "available": True,
                })
        except Exception:
            pass

    return jsonify({"models": models, "mode": mode})


@app.route("/api/llm/summarize", methods=["POST"])
@bot_protection
@turnstile_required
def llm_summarize():
    """Use a cheap/fast model to summarize game history for compact context."""
    if not feature_enabled("server_llm"):
        return jsonify({"error": "Server LLM not available"}), 403
    payload = request.get_json(force=True)
    prompt = payload.get("prompt", "")
    if not prompt:
        return jsonify({"error": "No prompt"}), 400

    # If a specific model is requested, use it directly
    requested_model = payload.get("model")
    if requested_model and requested_model in MODEL_REGISTRY:
        info = MODEL_REGISTRY[requested_model]
        env_key = info.get("env_key", "")
        if not env_key or os.environ.get(env_key):
            try:
                result = _route_model_call(requested_model, prompt, None)
                text = result.get("text", result) if isinstance(result, dict) else result
                return jsonify({"summary": text, "model_used": requested_model})
            except Exception as e:
                app.logger.warning("Summarize with requested %s failed: %s", requested_model, e)

    # Fallback: auto-select model from the same provider as the agent
    agent_model = payload.get("agent_model", "")
    agent_provider = MODEL_REGISTRY.get(agent_model, {}).get("provider", "gemini")
    strategy = payload.get("strategy", "cheapest")  # "cheapest" or "fastest"

    # Priority lists per provider: cheapest first
    CHEAPEST_BY_PROVIDER = {
        "gemini":     ["gemini-2.0-flash-lite", "gemini-2.5-flash-lite", "gemini-2.0-flash"],
        "anthropic":  ["claude-haiku-4-5", "claude-sonnet-4-5"],
        "groq":       ["gemma2-9b", "mixtral-8x7b", "llama-3.3-70b"],
        "mistral":    ["open-mistral-nemo", "mistral-small"],
        "cloudflare": ["llama-3.1-8b", "llama-3.3-70b", "qwen3-30b"],
        "copilot":    ["gpt-5-mini", "gpt-4o", "gpt-4.1"],
        "huggingface":["llama-3.1-70b", "qwen2.5-72b"],
    }
    # Priority lists per provider: fastest (lowest latency) first
    FASTEST_BY_PROVIDER = {
        "gemini":     ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-2.5-flash"],
        "anthropic":  ["claude-haiku-4-5", "claude-sonnet-4-5"],
        "groq":       ["gemma2-9b", "llama-3.3-70b", "mixtral-8x7b"],
        "mistral":    ["open-mistral-nemo", "mistral-small"],
        "cloudflare": ["llama-3.1-8b", "llama-3.3-70b", "qwen3-30b"],
        "copilot":    ["gpt-5-mini", "gpt-4o", "gpt-4.1"],
        "huggingface":["llama-3.1-70b", "qwen2.5-72b"],
    }
    lookup = FASTEST_BY_PROVIDER if strategy == "fastest" else CHEAPEST_BY_PROVIDER

    # Try same provider first, then fall back to any provider
    providers_to_try = [agent_provider] + [p for p in lookup if p != agent_provider]
    for provider in providers_to_try:
        candidates = lookup.get(provider, [])
        for candidate in candidates:
            # Find matching model in registry (partial match)
            matched = None
            for reg_name, reg_info in MODEL_REGISTRY.items():
                if reg_info.get("provider") == provider and candidate in reg_name:
                    env_key = reg_info.get("env_key", "")
                    if env_key and not os.environ.get(env_key):
                        continue
                    matched = reg_name
                    break
            if not matched:
                continue
            try:
                result = _route_model_call(matched, prompt, None)
                text = result.get("text", result) if isinstance(result, dict) else result
                return jsonify({"summary": text, "model_used": matched})
            except Exception as e:
                app.logger.warning("Summarize with %s failed: %s", matched, e)
                continue
    return jsonify({"error": "No summarization model available"}), 500


@app.route("/api/llm/interrupt-check", methods=["POST"])
@bot_protection
@turnstile_required
def llm_interrupt_check():
    """Use a cheap/fast model to check if a plan step went as expected."""
    if not feature_enabled("server_llm"):
        return jsonify({"error": "Server LLM not available"}), 403
    payload = request.get_json(force=True)
    prompt = payload.get("prompt", "")
    if not prompt:
        return jsonify({"error": "No prompt"}), 400

    # If a specific model is requested, use it directly
    requested_model = payload.get("model")
    if requested_model and requested_model in MODEL_REGISTRY:
        info = MODEL_REGISTRY[requested_model]
        env_key = info.get("env_key", "")
        if not env_key or os.environ.get(env_key):
            try:
                result = _route_model_call(requested_model, prompt, None)
                text = result.get("text", result) if isinstance(result, dict) else result
                return jsonify({"result": text, "model_used": requested_model})
            except Exception as e:
                app.logger.warning("Interrupt check with requested %s failed: %s", requested_model, e)

    # Fallback: auto-select model from the same provider as the agent
    agent_model = payload.get("agent_model", "")
    agent_provider = MODEL_REGISTRY.get(agent_model, {}).get("provider", "gemini")
    strategy = payload.get("strategy", "cheapest")

    CHEAPEST_BY_PROVIDER = {
        "gemini":     ["gemini-2.0-flash-lite", "gemini-2.5-flash-lite", "gemini-2.0-flash"],
        "anthropic":  ["claude-haiku-4-5", "claude-sonnet-4-5"],
        "groq":       ["gemma2-9b", "mixtral-8x7b", "llama-3.3-70b"],
        "mistral":    ["open-mistral-nemo", "mistral-small"],
        "cloudflare": ["llama-3.1-8b", "llama-3.3-70b", "qwen3-30b"],
        "copilot":    ["gpt-5-mini", "gpt-4o", "gpt-4.1"],
        "huggingface":["llama-3.1-70b", "qwen2.5-72b"],
    }
    FASTEST_BY_PROVIDER = {
        "gemini":     ["gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-2.5-flash"],
        "anthropic":  ["claude-haiku-4-5", "claude-sonnet-4-5"],
        "groq":       ["gemma2-9b", "llama-3.3-70b", "mixtral-8x7b"],
        "mistral":    ["open-mistral-nemo", "mistral-small"],
        "cloudflare": ["llama-3.1-8b", "llama-3.3-70b", "qwen3-30b"],
        "copilot":    ["gpt-5-mini", "gpt-4o", "gpt-4.1"],
        "huggingface":["llama-3.1-70b", "qwen2.5-72b"],
    }
    lookup = FASTEST_BY_PROVIDER if strategy == "fastest" else CHEAPEST_BY_PROVIDER

    providers_to_try = [agent_provider] + [p for p in lookup if p != agent_provider]
    for provider in providers_to_try:
        candidates = lookup.get(provider, [])
        for candidate in candidates:
            matched = None
            for reg_name, reg_info in MODEL_REGISTRY.items():
                if reg_info.get("provider") == provider and candidate in reg_name:
                    env_key = reg_info.get("env_key", "")
                    if env_key and not os.environ.get(env_key):
                        continue
                    matched = reg_name
                    break
            if not matched:
                continue
            try:
                result = _route_model_call(matched, prompt, None)
                text = result.get("text", result) if isinstance(result, dict) else result
                return jsonify({"result": text, "model_used": matched})
            except Exception as e:
                app.logger.warning("Interrupt check with %s failed: %s", matched, e)
                continue
    return jsonify({"error": "No interrupt check model available"}), 500


@app.route("/api/llm/ask", methods=["POST"])
@bot_protection
@turnstile_required
def llm_ask():
    """Ask LLM for next action.

    Body includes:
      - standard game state fields (grid, state, available_actions, etc.)
      - settings.input: {diff, full_grid, image, color_histogram}
      - settings.thinking_level: "off" | "low" | "med" | "high"
      - settings.tools_mode: "on" | "off" | "adaptive"
      - settings.model: model key
      - image_b64: base64-encoded PNG screenshot (optional)
    """
    # Gate: online mode cannot use server-side LLM
    if not feature_enabled("server_llm"):
        return jsonify({
            "error": "Server-side LLM is not available in online mode. Use Puter.js or BYOK.",
            "mode": get_mode(),
        }), 403

    payload = request.get_json(force=True)
    settings = payload.get("settings", {})
    model_key = settings.get("model") or payload.get("model", "gemini-2.5-flash")

    input_settings = settings.get("input", {"diff": True, "full_grid": True})
    tools_mode = settings.get("tools_mode", "off")

    # Adaptive tools: enable extra analysis after 10+ steps with no level progress
    if tools_mode == "adaptive":
        history = payload.get("history", [])
        if len(history) >= 10:
            # Check if levels changed in last 10 steps
            recent_levels = [h.get("levels", 0) for h in history[-10:]]
            if len(set(recent_levels)) <= 1:
                tools_mode = "on"
            else:
                tools_mode = "off"
        else:
            tools_mode = "off"

    planning_mode = settings.get("planning_mode", "off")
    thinking_level = settings.get("thinking_level", "low")
    interrupt_plan = settings.get("interrupt_plan", False)
    max_tokens = min(int(settings.get("max_tokens", 16384)), 65536)
    prompt = _build_prompt(payload, input_settings, tools_mode, planning_mode, interrupt_plan)

    # Get image if the input setting is on and data was provided
    image_b64 = None
    if input_settings.get("image"):
        image_b64 = payload.get("image_b64")

    # Determine if we should enable real tool execution
    session_id = payload.get("session_id")
    grid = payload.get("grid", [])
    prev_grid = None
    if session_id:
        with session_lock:
            prev_grid = session_grids.get(session_id)

    # Only enable real tools for Gemini models with tools capability
    model_info = MODEL_REGISTRY.get(model_key, {})
    is_gemini = model_info.get("provider") == "gemini"
    model_has_tools = model_info.get("capabilities", {}).get("tools", False)
    real_tools = tools_mode == "on" and is_gemini and model_has_tools

    # Try Gemini context caching for static prompt parts
    cached_content_name = None
    if is_gemini:
        static_content, _ = _build_prompt_parts(payload, input_settings, tools_mode, planning_mode)
        cached_content_name = _get_or_create_gemini_cache(
            model_info.get("api_model", ""), static_content)

    max_retries = 3
    last_error = None
    for attempt in range(max_retries):
        try:
            content = _route_model_call(
                model_key, prompt, image_b64,
                tools_enabled=real_tools,
                session_id=session_id,
                grid=grid, prev_grid=prev_grid,
                cached_content_name=cached_content_name,
                thinking_level=thinking_level,
                max_tokens=max_tokens,
            )

            # Handle dict return (Gemini w/ tools, or truncated) vs str return (others)
            truncated = False
            if isinstance(content, dict):
                text = content.get("text", "")
                truncated = content.get("truncated", False)
                result = _parse_llm_response(text, model_key)
                result["tool_calls"] = content.get("tool_calls", [])
                result["cache_active"] = content.get("cache_active", False)
                if content.get("usage"):
                    result["usage"] = content["usage"]
            else:
                result = _parse_llm_response(content, model_key)
            if truncated:
                result["truncated"] = True

            # Retry if no parseable response (empty or unparseable)
            if not result.get("parsed") and attempt < max_retries - 1:
                app.logger.warning(
                    f"LLM returned no parsed response (attempt {attempt + 1}/{max_retries}), retrying..."
                )
                # If tools were on but produced no parseable answer, retry without tools
                if real_tools:
                    app.logger.info("Disabling tools for retry — model may be stuck in tool loops")
                    real_tools = False
                continue

            result["tools_active"] = tools_mode == "on"
            result["thinking_level"] = thinking_level
            result["prompt_length"] = len(prompt)
            if attempt > 0:
                result["retries"] = attempt

            # Stash LLM response for session DB persistence
            if session_id and feature_enabled("session_db"):
                with session_lock:
                    session_last_llm[session_id] = result
                _db_update_session(session_id, model=model_key)

            return jsonify(result)
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                app.logger.warning(
                    f"LLM call failed (attempt {attempt + 1}/{max_retries}): {e}, retrying..."
                )
                continue
            return jsonify({"error": str(e), "model": model_key}), 500

    return jsonify({"error": str(last_error or "No response after retries"), "model": model_key}), 500


@app.route("/api/tools/execute", methods=["POST"])
@bot_protection
@turnstile_required
def tools_execute():
    """Execute Python code in the server-side sandbox (local mode only).

    Body: {"code": str, "session_id": str, "grid": list, "prev_grid": list|null}
    Returns: {"output": str}
    """
    if not feature_enabled("server_llm"):
        return jsonify({"error": "Not available in online mode"}), 403
    payload = request.get_json(force=True)
    code = payload.get("code", "")
    if not code:
        return jsonify({"error": "code required"}), 400
    session_id = payload.get("session_id", "anonymous")
    grid = payload.get("grid", [[]])
    prev_grid = payload.get("prev_grid")
    output = _execute_python(session_id, code, grid, prev_grid)
    return jsonify({"output": output})


@app.route("/api/llm/test", methods=["POST"])
@bot_protection
def llm_test():
    """Quick probe: send a tiny prompt to a model, return latency + status.

    Body: {"model": "groq/llama-3.3-70b-versatile"}
    Returns: {"model", "provider", "latency_ms", "success", "error", "throttle_delay"}
    """
    if not feature_enabled("server_llm"):
        return jsonify({"error": "Not available in online mode"}), 403

    payload = request.get_json(force=True)
    model_key = payload.get("model", "")
    if not model_key:
        return jsonify({"error": "model required"}), 400

    info = MODEL_REGISTRY.get(model_key)
    provider = info["provider"] if info else "ollama"
    throttle_delay = PROVIDER_MIN_DELAY.get(provider, 1.0)

    test_prompt = 'Reply with exactly: {"action": 1, "observation": "test", "plan": "test"}'

    t0 = time.time()
    try:
        content = _route_model_call(model_key, test_prompt)
        latency = round((time.time() - t0) * 1000)
        return jsonify({
            "model": model_key, "provider": provider,
            "latency_ms": latency, "success": True,
            "throttle_delay": throttle_delay,
            "response_preview": (content[:200] if isinstance(content, str) else str(content)[:200]),
        })
    except Exception as e:
        latency = round((time.time() - t0) * 1000)
        return jsonify({
            "model": model_key, "provider": provider,
            "latency_ms": latency, "success": False,
            "error": str(e), "throttle_delay": throttle_delay,
        })


@app.route("/api/llm/throttle", methods=["GET", "POST"])
@bot_protection
def llm_throttle():
    """GET: return current throttle config. POST: update delays.

    POST body: {"gemini": 5.0, "groq": 3.0, ...}
    """
    if request.method == "GET":
        return jsonify(PROVIDER_MIN_DELAY)

    if get_mode() != "local":
        return jsonify({"error": "Throttle config only editable in local mode"}), 403

    updates = request.get_json(force=True)
    for provider, delay in updates.items():
        if provider in PROVIDER_MIN_DELAY and isinstance(delay, (int, float)) and delay >= 0:
            PROVIDER_MIN_DELAY[provider] = float(delay)
    return jsonify(PROVIDER_MIN_DELAY)


@app.route("/api/undo", methods=["POST"])
@bot_protection
@turnstile_required
def undo_step():
    payload = request.get_json(force=True)
    session_id = payload.get("session_id")
    if not session_id:
        return jsonify({"error": "session_id required"}), 400

    with session_lock:
        env = game_sessions.get(session_id)
        snapshots = session_snapshots.get(session_id, [])

    if env is None:
        env, _ = _try_recover_session(session_id)
        if env is None:
            return jsonify({"error": "Session not found"}), 404
        snapshots = session_snapshots.get(session_id, [])
    if not snapshots:
        return jsonify({"error": "Nothing to undo"}), 400

    count = min(int(payload.get("count", 1)), 50)

    with session_lock:
        snapshot = None
        for _ in range(count):
            if not snapshots:
                break
            snapshot = snapshots.pop()

    if snapshot is None:
        return jsonify({"error": "Nothing to undo"}), 400

    restored_grid = snapshot["grid"]
    # We restore the grid and return the previous state to the UI.
    # The env itself may not support true rollback, so we restore our cached grid.
    with session_lock:
        session_grids[session_id] = restored_grid

    # Build a state dict from the snapshot
    state = env_state_dict(env)
    state["grid"] = restored_grid
    state["session_id"] = session_id
    state["change_map"] = {"changes": [], "change_count": 0, "change_map_text": "(undo)"}
    state["undo_depth"] = len(snapshots)
    return jsonify(state)


# ═══════════════════════════════════════════════════════════════════════════
# API MODE CONFIGURATION (Local vs Official ARC-AGI-3 API)
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/config/mode", methods=["GET", "POST"])
@bot_protection
@turnstile_required
def config_mode():
    if request.method == "POST":
        payload = request.get_json(force=True)
        mode = payload.get("mode", "local")
        client_id = payload.get("client_id", "default")
        if mode not in ("local", "official"):
            return jsonify({"error": "mode must be 'local' or 'official'"}), 400
        with session_lock:
            session_api_mode[client_id] = mode
        return jsonify({"mode": mode})
    else:
        client_id = request.args.get("client_id", "default")
        mode = session_api_mode.get(client_id, "local")
        has_key = bool(session_api_keys.get(client_id) or os.environ.get("ARC_AGI_3_API_KEY"))
        return jsonify({"mode": mode, "has_key": has_key})


@app.route("/api/config/apikey", methods=["POST"])
@bot_protection
@turnstile_required
def config_apikey():
    payload = request.get_json(force=True)
    api_key = payload.get("api_key", "")
    client_id = payload.get("client_id", "default")
    with session_lock:
        session_api_keys[client_id] = api_key
    return jsonify({"status": "ok"})


def _get_arc_api_key(client_id: str = "default") -> str:
    """Get the ARC-AGI-3 API key from session or environment."""
    return session_api_keys.get(client_id, "") or os.environ.get("ARC_AGI_3_API_KEY", "")


def _proxy_to_official_api(endpoint: str, payload: dict, client_id: str = "default") -> dict:
    """Forward a request to the official ARC-AGI-3 API."""
    import httpx
    api_key = _get_arc_api_key(client_id)
    if not api_key:
        return {"error": "ARC-AGI-3 API key not configured"}
    base_url = "https://three.arcprize.org"
    try:
        resp = httpx.post(
            f"{base_url}/{endpoint}",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60.0,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"error": f"Official API error: {str(e)}"}


# ═══════════════════════════════════════════════════════════════════════════
# COPILOT AUTH ENDPOINTS (local only)
# ═══════════════════════════════════════════════════════════════════════════

COPILOT_CLIENT_ID = "Iv1.b507a08c87ecfe98"


@app.route("/api/copilot/auth/start", methods=["POST"])
@bot_protection
@turnstile_required
def copilot_auth_start():
    if not feature_enabled("copilot"):
        return jsonify({"error": "Copilot not available in this mode"}), 403
    global copilot_device_code
    import httpx
    try:
        resp = httpx.post(
            "https://github.com/login/device/code",
            headers={"Accept": "application/json"},
            data={"client_id": COPILOT_CLIENT_ID, "scope": ""},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        with copilot_auth_lock:
            copilot_device_code = data.get("device_code")
        return jsonify({
            "user_code": data.get("user_code"),
            "verification_uri": data.get("verification_uri"),
            "expires_in": data.get("expires_in"),
            "interval": data.get("interval", 5),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/copilot/auth/poll", methods=["POST"])
@bot_protection
@turnstile_required
def copilot_auth_poll():
    if not feature_enabled("copilot"):
        return jsonify({"error": "Copilot not available in this mode"}), 403
    global copilot_oauth_token, copilot_device_code
    import httpx
    with copilot_auth_lock:
        dc = copilot_device_code
    if not dc:
        return jsonify({"error": "No pending auth. Call /api/copilot/auth/start first."}), 400
    try:
        resp = httpx.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": COPILOT_CLIENT_ID,
                "device_code": dc,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        if "access_token" in data:
            with copilot_auth_lock:
                copilot_oauth_token = data["access_token"]
                copilot_device_code = None
            _save_copilot_token(copilot_oauth_token)
            return jsonify({"status": "authenticated"})
        elif data.get("error") == "authorization_pending":
            return jsonify({"status": "pending"})
        elif data.get("error") == "slow_down":
            return jsonify({"status": "slow_down", "interval": data.get("interval", 10)})
        else:
            return jsonify({"status": "error", "error": data.get("error_description", data.get("error", "Unknown"))})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/copilot/auth/status")
@bot_protection
@turnstile_required
def copilot_auth_status():
    if not feature_enabled("copilot"):
        return jsonify({"available": False, "reason": "online_mode"})
    with copilot_auth_lock:
        authenticated = copilot_oauth_token is not None
        pending = copilot_device_code is not None
    return jsonify({
        "available": True,
        "authenticated": authenticated,
        "pending": pending,
    })


# ═══════════════════════════════════════════════════════════════════════════
# MEMORY ENDPOINTS (local mode only)
# ═══════════════════════════════════════════════════════════════════════════

HARD_MEMORY_DEFAULT = """\
- Bar/meter changes along edges tend to be health bars, not real progress.
- Large uniform regions = background/walls. Small shapes = player/items.
- ACTION5 often cycles or toggles something context-dependent.
- ACTION7 is a secondary interact (rotate, swap, etc.).
- ACTION0 = RESET. Only use as a last resort.
- Try all directional actions first to understand movement."""


@app.route("/api/memory", methods=["GET", "POST"])
@bot_protection
def memory_endpoint():
    """GET/POST custom system prompt and hard memory (local mode only)."""
    global _custom_system_prompt, _custom_hard_memory
    if get_mode() != "local":
        return jsonify({"error": "Memory editing only available in local mode"}), 403

    if request.method == "GET":
        return jsonify({
            "system_prompt": _custom_system_prompt or ARC_AGI3_DESCRIPTION,
            "hard_memory": _custom_hard_memory or HARD_MEMORY_DEFAULT,
            "system_prompt_default": ARC_AGI3_DESCRIPTION,
            "hard_memory_default": HARD_MEMORY_DEFAULT,
        })

    payload = request.get_json(force=True)
    sp = payload.get("system_prompt")
    hm = payload.get("hard_memory")
    if sp is not None:
        _custom_system_prompt = sp.strip() if sp.strip() != ARC_AGI3_DESCRIPTION.strip() else None
    if hm is not None:
        _custom_hard_memory = hm.strip() if hm.strip() != HARD_MEMORY_DEFAULT.strip() else None
    return jsonify({"status": "ok"})


# ═══════════════════════════════════════════════════════════════════════════
# SESSION IMPORT + BRANCH ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/sessions/import", methods=["POST", "OPTIONS"])
@bot_protection
def import_session():
    """Import/upsert a session and its steps. Used by puter.kv auto-upload."""
    # CORS for cross-origin uploads (local → Railway)
    cors_headers = {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }
    if request.method == "OPTIONS":
        return ("", 204, cors_headers)
    def _cors_resp(data, status=200):
        resp = make_response(jsonify(data), status)
        resp.headers.update(cors_headers)
        return resp

    if not feature_enabled("session_db"):
        return _cors_resp({"error": "Session DB not enabled"}, 400)
    payload = request.get_json(force=True)
    sess = payload.get("session")
    steps = payload.get("steps", [])
    if not sess or not sess.get("id") or not sess.get("game_id"):
        return _cors_resp({"error": "session.id and session.game_id required"}, 400)
    # Reject short sessions — under 20 steps is noise
    if len(steps) < 20:
        return _cors_resp({"error": "Session too short (min 20 steps)", "skipped": True})
    try:
        conn = _get_db()
        conn.execute(
            """INSERT INTO sessions (id, game_id, model, mode, created_at, result, steps, levels,
                                     parent_session_id, branch_at_step)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                 result = excluded.result, steps = excluded.steps, levels = excluded.levels,
                 model = COALESCE(excluded.model, sessions.model)""",
            (sess["id"], sess["game_id"], sess.get("model", ""),
             sess.get("mode", "online"), sess.get("created_at", time.time()),
             sess.get("result", "NOT_FINISHED"), sess.get("steps", 0),
             sess.get("levels", 0), sess.get("parent_session_id"),
             sess.get("branch_at_step")),
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
        conn.commit()
        conn.close()
        # Also persist to Turso for durable shared replays
        _turso_import_session(payload)
        return _cors_resp({"status": "ok", "session_id": sess["id"], "steps_imported": len(steps)})
    except Exception as e:
        app.logger.warning(f"Session import failed: {e}")
        return _cors_resp({"error": str(e)}, 500)


@app.route("/api/sessions/resume", methods=["POST"])
@bot_protection
@turnstile_required
def resume_session():
    """Resume an unfinished session. Replays all steps and returns live state."""
    if not feature_enabled("session_db"):
        return jsonify({"error": "Session DB not enabled"}), 400
    payload = request.get_json(force=True)
    session_id = payload.get("session_id")
    if not session_id:
        return jsonify({"error": "session_id required"}), 400
    # Fetch session metadata and step rows from DB
    try:
        conn = _get_db()
        sess = conn.execute(
            "SELECT game_id, model, parent_session_id, branch_at_step FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if not sess:
            conn.close()
            return jsonify({"error": "Session not found"}), 404

        # For branched sessions, collect parent steps up to branch point first
        parent_rows = []
        if sess["parent_session_id"] and sess["branch_at_step"] is not None:
            parent_rows = conn.execute(
                "SELECT * FROM session_steps WHERE session_id = ? AND step_num <= ? ORDER BY step_num",
                (sess["parent_session_id"], sess["branch_at_step"]),
            ).fetchall()

        # Then this session's own steps (taken after branching)
        own_rows = conn.execute(
            "SELECT * FROM session_steps WHERE session_id = ? ORDER BY step_num",
            (session_id,),
        ).fetchall()
        conn.close()
    except Exception as e:
        return jsonify({"error": f"DB error: {e}"}), 500

    # Combine: parent steps + own steps = full action history
    all_rows = list(parent_rows) + list(own_rows)

    # Replay all moves to get correct env state + per-step game stats
    actions = [{"action": r["action"], "data": r["data_json"]} for r in all_rows]
    env, state, per_step_states = _reconstruct_session(sess["game_id"], actions, capture_per_step=True)

    # Register the recovered env in global state
    with session_lock:
        game_sessions[session_id] = env
        session_grids[session_id] = state.get("grid", [])
        session_snapshots[session_id] = []
        session_step_counts[session_id] = len(actions)

    state["session_id"] = session_id
    state["change_map"] = {"changes": [], "change_count": 0, "change_map_text": "(resumed)"}
    state["resumed_step_count"] = len(actions)

    # Build step history with per-step game stats from replay
    step_list = [_format_step_row(dict(r)) for r in all_rows]
    for i, s in enumerate(step_list):
        if i < len(per_step_states):
            s["result_state"] = per_step_states[i]["state"]
            s["levels_completed"] = per_step_states[i]["levels_completed"]
    state["steps"] = step_list
    state["model"] = sess["model"] or ""
    return jsonify(state)


@app.route("/api/sessions/<session_id>/event", methods=["POST"])
@bot_protection
def log_session_event(session_id):
    """Log a session event (compact, branch, resume)."""
    if not feature_enabled("session_db"):
        return jsonify({"error": "Session DB not enabled"}), 400
    payload = request.get_json(force=True)
    event_type = payload.get("event_type")
    step_num = payload.get("step_num")
    event_data = payload.get("data", {})
    try:
        conn = _get_db()
        conn.execute(
            "INSERT INTO session_events (session_id, event_type, step_num, data_json, timestamp) VALUES (?, ?, ?, ?, ?)",
            (session_id, event_type, step_num, json.dumps(event_data), time.time()))
        conn.commit()
        conn.close()
    except Exception as e:
        app.logger.warning(f"Event log failed: {e}")
    return jsonify({"status": "ok"})


@app.route("/api/sessions/branch", methods=["POST"])
@bot_protection
@turnstile_required
def branch_session():
    """Branch a session at a given step. Creates a new live session from that point."""
    if not feature_enabled("session_db"):
        return jsonify({"error": "Session DB not enabled"}), 400
    payload = request.get_json(force=True)
    parent_id = payload.get("parent_session_id")
    step_num = payload.get("step_num")
    if not parent_id or step_num is None:
        return jsonify({"error": "parent_session_id and step_num required"}), 400
    try:
        conn = _get_db()
        sess = conn.execute("SELECT game_id FROM sessions WHERE id = ?", (parent_id,)).fetchone()
        if not sess:
            conn.close()
            return jsonify({"error": "Parent session not found"}), 404
        action_rows = conn.execute(
            "SELECT action, data_json FROM session_steps WHERE session_id = ? AND step_num <= ? ORDER BY step_num",
            (parent_id, step_num),
        ).fetchall()
        # Also fetch full step rows for reasoning trace
        full_rows = conn.execute(
            "SELECT * FROM session_steps WHERE session_id = ? AND step_num <= ? ORDER BY step_num",
            (parent_id, step_num),
        ).fetchall()
        conn.close()

        actions = [{"action": r["action"], "data": r["data_json"]} for r in action_rows]
        env, state, per_step_states = _reconstruct_session(sess["game_id"], actions, capture_per_step=True)

        # Generate new session ID
        new_session_id = env._guid if hasattr(env, "_guid") else secrets.token_hex(16)
        with session_lock:
            game_sessions[new_session_id] = env
            session_grids[new_session_id] = state.get("grid", [])
            session_snapshots[new_session_id] = []
            session_step_counts[new_session_id] = len(actions)

        # Persist the branched session
        conn = _get_db()
        conn.execute(
            """INSERT INTO sessions (id, game_id, mode, created_at, result, steps, levels,
                                     parent_session_id, branch_at_step)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (new_session_id, sess["game_id"], get_mode(), time.time(),
             "NOT_FINISHED", len(actions), state.get("levels_completed", 0),
             parent_id, step_num),
        )
        conn.commit()
        conn.close()

        state["session_id"] = new_session_id
        state["parent_session_id"] = parent_id
        state["branch_at_step"] = step_num
        state["change_map"] = {"changes": [], "change_count": 0, "change_map_text": "(branch)"}

        # Include step history with per-step game stats for reasoning trace
        step_list = [_format_step_row(dict(r)) for r in full_rows]
        for i, s in enumerate(step_list):
            if i < len(per_step_states):
                s["result_state"] = per_step_states[i]["state"]
                s["levels_completed"] = per_step_states[i]["levels_completed"]
        state["steps"] = step_list
        return jsonify(state)
    except Exception as e:
        app.logger.warning(f"Session branch failed: {e}")
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════
# SESSION HISTORY ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/sessions")
@bot_protection
@turnstile_required
def list_sessions():
    """List recent sessions (last 100). Merges local SQLite + Turso."""
    if not feature_enabled("session_db"):
        return jsonify({"sessions": []})
    try:
        _sessions_query = (
            "SELECT s.id, s.game_id, s.model, s.mode, s.created_at, s.result, s.steps, s.levels, "
            "s.parent_session_id, s.branch_at_step, s.total_cost, "
            "(SELECT MAX(st.timestamp) - MIN(st.timestamp) FROM session_steps st WHERE st.session_id = s.id) AS duration "
            "FROM sessions s ORDER BY s.created_at DESC LIMIT 100"
        )
        sessions_by_id = {}
        # Local SQLite
        conn = _get_db()
        rows = conn.execute(_sessions_query).fetchall()
        conn.close()
        for r in rows:
            d = dict(r)
            sessions_by_id[d["id"]] = d
        # Turso (merge in, dedup by id)
        turso_conn = _get_turso_db()
        if turso_conn:
            try:
                cur = turso_conn.execute(_sessions_query)
                for d in _turso_dict_fetchall(cur):
                    if d["id"] not in sessions_by_id:
                        sessions_by_id[d["id"]] = d
                turso_conn.close()
            except Exception as e:
                app.logger.warning(f"Turso list_sessions failed: {e}")
        # Sort by created_at desc
        merged = sorted(sessions_by_id.values(), key=lambda s: s.get("created_at", 0), reverse=True)
        return jsonify({"sessions": merged[:100]})
    except Exception as e:
        return jsonify({"sessions": [], "error": str(e)})


def _format_step_row(d: dict) -> dict:
    """Decompress grid and parse JSON fields in a step row dict."""
    if d.get("grid_snapshot"):
        try:
            d["grid"] = _decompress_grid(d["grid_snapshot"])
        except Exception:
            d["grid"] = None
        del d["grid_snapshot"]
    for jf in ("data_json", "change_map_json", "llm_response_json"):
        if d.get(jf):
            try:
                d[jf.replace("_json", "")] = json.loads(d[jf])
            except Exception:
                d[jf.replace("_json", "")] = None
            del d[jf]
    return d


@app.route("/api/sessions/<session_id>")
@bot_protection
@turnstile_required
def get_session(session_id):
    """Get full session with all steps and decompressed grids.
    Tries local SQLite first, falls back to Turso."""
    if not feature_enabled("session_db"):
        return jsonify({"error": "Session DB not enabled"}), 404
    try:
        sess_dict = None
        step_list = []

        # Try local SQLite first
        conn = _get_db()
        sess = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if sess:
            steps = conn.execute(
                "SELECT * FROM session_steps WHERE session_id = ? ORDER BY step_num",
                (session_id,),
            ).fetchall()
            conn.close()
            sess_dict = dict(sess)
            for s in steps:
                step_list.append(_format_step_row(dict(s)))
        else:
            conn.close()

        # Fall back to Turso
        if not sess_dict:
            turso_conn = _get_turso_db()
            if turso_conn:
                try:
                    cur = turso_conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
                    sess_dict = _turso_dict_fetchone(cur)
                    if sess_dict:
                        cur2 = turso_conn.execute(
                            "SELECT * FROM session_steps WHERE session_id = ? ORDER BY step_num",
                            (session_id,),
                        )
                        for s in _turso_dict_fetchall(cur2):
                            step_list.append(_format_step_row(s))
                    turso_conn.close()
                except Exception as e:
                    app.logger.warning(f"Turso get_session failed: {e}")

        if not sess_dict:
            return jsonify({"error": "Session not found"}), 404

        return jsonify({"session": sess_dict, "steps": step_list})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sessions/<session_id>/step/<int:step_num>")
@bot_protection
@turnstile_required
def get_session_step(session_id, step_num):
    """Get a single step from a session."""
    if not feature_enabled("session_db"):
        return jsonify({"error": "Session DB not enabled"}), 404
    try:
        conn = _get_db()
        row = conn.execute(
            "SELECT * FROM session_steps WHERE session_id = ? AND step_num = ?",
            (session_id, step_num),
        ).fetchone()
        conn.close()
        if not row:
            return jsonify({"error": "Step not found"}), 404
        d = _format_step_row(dict(row))
        return jsonify(d)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════
# SHARE — public replay page
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/share/<session_id>")
def share_session(session_id):
    """Public replay page for a session — no auth required.
    Reads from Turso first (persistent), falls back to local SQLite.
    For branched sessions, traces back through parents to include full history."""
    try:
        sess = None
        step_list = []

        # Try Turso first (durable shared DB)
        turso_conn = _get_turso_db()
        if turso_conn:
            try:
                cur = turso_conn.execute(
                    "SELECT id, game_id, model, mode, created_at, result, steps, levels, total_cost, "
                    "parent_session_id, branch_at_step "
                    "FROM sessions WHERE id = ?",
                    (session_id,),
                )
                sess = _turso_dict_fetchone(cur)
                if sess:
                    cur2 = turso_conn.execute(
                        "SELECT * FROM session_steps WHERE session_id = ? ORDER BY step_num",
                        (session_id,),
                    )
                    steps_rows = _turso_dict_fetchall(cur2)
                    step_list = [_format_step_row(s) for s in steps_rows]
                turso_conn.close()
            except Exception as e:
                app.logger.warning(f"Turso share read failed, falling back to local: {e}")
                sess = None

        # Fall back to local SQLite
        if not sess:
            conn = _get_db()
            sess_row = conn.execute(
                "SELECT id, game_id, model, mode, created_at, result, steps, levels, total_cost, "
                "parent_session_id, branch_at_step "
                "FROM sessions WHERE id = ?",
                (session_id,),
            ).fetchone()
            if not sess_row:
                conn.close()
                return """<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Session Not Found</title>
<style>body{background:#0d1117;color:#c9d1d9;font-family:'Courier New',monospace;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;}
.box{text-align:center;padding:40px;border:1px solid #30363d;border-radius:12px;background:#161b22;max-width:400px;}
h1{color:#f85149;font-size:24px;margin-bottom:12px;}p{color:#8b949e;margin-bottom:20px;}
a{color:#58a6ff;text-decoration:none;}a:hover{text-decoration:underline;}</style></head>
<body><div class="box"><h1>Session Not Found</h1><p>This session doesn't exist or hasn't been shared yet.</p>
<a href="/">&#9654; Play ARC-AGI-3</a></div></body></html>""", 404
            sess = dict(sess_row)
            steps_rows = conn.execute(
                "SELECT * FROM session_steps WHERE session_id = ? ORDER BY step_num",
                (session_id,),
            ).fetchall()
            conn.close()
            step_list = [_format_step_row(dict(s)) for s in steps_rows]

        # Trace back through parent sessions to build full history
        parent_steps = []
        trace_id = sess.get("parent_session_id")
        trace_step = sess.get("branch_at_step")
        max_depth = 10  # prevent infinite loops
        while trace_id and trace_step is not None and max_depth > 0:
            max_depth -= 1
            parent_sess = None
            p_steps = []
            # Try local SQLite
            conn = _get_db()
            p_row = conn.execute(
                "SELECT parent_session_id, branch_at_step FROM sessions WHERE id = ?",
                (trace_id,),
            ).fetchone()
            p_steps_rows = conn.execute(
                "SELECT * FROM session_steps WHERE session_id = ? AND step_num <= ? ORDER BY step_num",
                (trace_id, trace_step),
            ).fetchall()
            conn.close()
            if p_row:
                parent_sess = dict(p_row)
            for s in p_steps_rows:
                st = _format_step_row(dict(s))
                st["from_parent"] = True
                p_steps.append(st)
            # Prepend parent steps (oldest ancestor first)
            parent_steps = p_steps + parent_steps
            # Continue tracing
            if parent_sess:
                trace_id = parent_sess.get("parent_session_id")
                trace_step = parent_sess.get("branch_at_step")
            else:
                break

        # Combine: parent steps first, then own steps
        if parent_steps:
            step_list = parent_steps + step_list

        return render_template(
            "share.html",
            session=sess,
            steps=step_list,
            color_map=COLOR_MAP,
            branch_at_step=len(parent_steps) if parent_steps else 0,
            umami_url=UMAMI_URL, umami_website_id=UMAMI_WEBSITE_ID,
        )
    except Exception as e:
        app.logger.warning(f"Share page error: {e}")
        return f"<h1>Error</h1><p>{e}</p>", 500


# ═══════════════════════════════════════════════════════════════════════════
# SCENE EDITOR — fd01 pixel editor
# ═══════════════════════════════════════════════════════════════════════════

import importlib.util as _importlib_util
import numpy as _np

_FD01_PATH = Path(__file__).parent / "environment_files" / "fd01" / "00000001" / "fd01.py"
_CUSTOM_SCENES_FILE = Path(__file__).parent / "environment_files" / "fd01" / "00000001" / "custom_scenes.json"


def _load_fd01_module():
    """Import fd01.py as a module to access its draw functions and constants."""
    spec = _importlib_util.spec_from_file_location("fd01_editor", str(_FD01_PATH))
    mod = _importlib_util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read_custom_scenes() -> dict:
    try:
        if _CUSTOM_SCENES_FILE.exists():
            return json.loads(_CUSTOM_SCENES_FILE.read_text())
    except Exception:
        pass
    return {}


def _write_custom_scenes(data: dict):
    _CUSTOM_SCENES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CUSTOM_SCENES_FILE.write_text(json.dumps(data))


@app.route("/draw")
def draw_editor():
    return render_template("draw.html", color_map=COLOR_MAP, color_names=COLOR_NAMES)


@app.route("/api/draw/scene/<int:level>")
def get_draw_scene(level):
    if level < 0 or level >= 5:
        return jsonify({"error": "Invalid level"}), 400
    custom = _read_custom_scenes()
    if str(level) in custom:
        fd01 = _load_fd01_module()
        diffs = [{"dx": d[0], "dy": d[1], "color": d[2], "side": d[3]}
                 for d in fd01.DIFFS[level]]
        return jsonify({"pixels": custom[str(level)],
                        "width": 30, "height": 62,
                        "custom": True, "diffs": diffs})
    fd01 = _load_fd01_module()
    img = _np.zeros((fd01.IMG_H, fd01.IMG_W), dtype=_np.int16)
    fd01.SCENES[level](img)
    diffs = [{"dx": d[0], "dy": d[1], "color": d[2], "side": d[3]}
             for d in fd01.DIFFS[level]]
    return jsonify({"pixels": img.tolist(),
                    "width": fd01.IMG_W, "height": fd01.IMG_H,
                    "custom": False, "diffs": diffs})


@app.route("/api/draw/save", methods=["POST"])
def save_draw_scene():
    data = request.get_json(force=True)
    level = data.get("level")
    pixels = data.get("pixels")
    if level is None or pixels is None:
        return jsonify({"error": "level and pixels required"}), 400
    custom = _read_custom_scenes()
    custom[str(level)] = pixels
    _write_custom_scenes(custom)
    global arcade_instance
    arcade_instance = None   # force reload on next game start
    return jsonify({"status": "ok"})


@app.route("/api/draw/reset", methods=["POST"])
def reset_draw_scene():
    data = request.get_json(force=True)
    level = data.get("level")
    if level is None:
        return jsonify({"error": "level required"}), 400
    custom = _read_custom_scenes()
    custom.pop(str(level), None)
    _write_custom_scenes(custom)
    global arcade_instance
    arcade_instance = None
    return jsonify({"status": "ok"})


# ═══════════════════════════════════════════════════════════════════════════
# MAIN — dual-port serving
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ARC-AGI-3 Web Player")
    parser.add_argument("--mode", choices=["local", "online", "dual"], default="dual",
                        help="Run mode: local (port 5000), online (port 5001), or dual (both)")
    parser.add_argument("--port", type=int, default=None,
                        help="Override port (for single-mode)")
    parser.add_argument("--port-local", type=int, default=5000, help="Local mode port")
    parser.add_argument("--port-online", type=int, default=5001, help="Online mode port")
    args = parser.parse_args()

    _server_port_local = args.port_local
    _server_port_online = args.port_online

    # Initialize SQLite DB
    _init_db()
    print("  SQLite sessions DB initialized at:", DB_PATH)

    if args.mode == "dual":
        print(f"\n  ARC-AGI-3 Web Player (dual mode)")
        print(f"    Local:  http://localhost:{_server_port_local}")
        print(f"    Online: http://localhost:{_server_port_online}\n")

        # Run online port in a background thread
        def run_online():
            from werkzeug.serving import make_server
            srv = make_server("0.0.0.0", _server_port_online, app)
            srv.serve_forever()

        t = threading.Thread(target=run_online, daemon=True)
        t.start()

        # Run local port in main thread
        app.run(host="0.0.0.0", port=_server_port_local, debug=False)

    elif args.mode == "local":
        port = args.port or _server_port_local
        _server_port_local = port
        print(f"\n  ARC-AGI-3 Web Player (local): http://localhost:{port}\n")
        app.run(host="0.0.0.0", port=port, debug=False)

    elif args.mode == "online":
        port = args.port or _server_port_online
        _server_port_online = port
        print(f"\n  ARC-AGI-3 Web Player (online): http://localhost:{port}\n")
        app.run(host="0.0.0.0", port=port, debug=False)
