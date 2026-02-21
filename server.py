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
import sys
import threading
import time
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
app.logger.setLevel(logging.INFO)

# ═══════════════════════════════════════════════════════════════════════════
# FEATURE FLAGS — dual-mode gating (local vs online)
# ═══════════════════════════════════════════════════════════════════════════

FEATURES = {
    "copilot":       {"local": True,  "online": False},
    "server_llm":    {"local": True,  "online": False},
    "puter_js":      {"local": False, "online": True},
    "byok":          {"local": False, "online": True},
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

# ── Copilot auth state ────────────────────────────────────────────────────
copilot_oauth_token: Optional[str] = None  # GitHub OAuth access token
copilot_api_token: Optional[str] = None  # Copilot short-lived API token
copilot_token_expiry: float = 0.0  # Unix timestamp when copilot_api_token expires
copilot_device_code: Optional[str] = None  # Pending device code during auth flow
copilot_auth_lock = threading.Lock()

# ── Per-provider throttle ────────────────────────────────────────────────
# Min seconds between calls per provider (tuned for free tiers)
PROVIDER_MIN_DELAY: dict[str, float] = {
    "gemini":      4.0,   # 15 req/min free
    "anthropic":   1.0,   # paid, generous limits
    "groq":        2.5,   # 30 req/min free (varies by model)
    "mistral":     2.0,   # ~1-2 req/sec free
    "huggingface": 6.0,   # ~10 req/min free
    "cloudflare":  0.5,   # neuron-based, no per-minute limit
    "copilot":     1.0,   # unknown exact limit, be safe
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
    # Schema migration: add branch columns (idempotent)
    for col, defn in [("parent_session_id", "TEXT DEFAULT NULL"),
                      ("branch_at_step", "INTEGER DEFAULT NULL")]:
        try:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {col} {defn}")
        except sqlite3.OperationalError:
            pass  # column already exists
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

def _reconstruct_session(game_id: str, actions: list[dict]):
    """Replay a list of {action, data} dicts on a fresh env. Returns (env, state_dict)."""
    bare_id = game_id.split("-")[0]
    arc = get_arcade()
    env = arc.make(bare_id)
    state = env_state_dict(env)
    for act in actions:
        action = GameAction.from_id(int(act["action"]))
        data = act.get("data") or None
        if isinstance(data, str):
            data = json.loads(data)
        frame_data = env.step(action, data=data if data else None)
        if frame_data is not None:
            state = env_state_dict(env, frame_data)
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
controls, rules, and goals by experimenting.

Key facts:
- Actions 1-5, 7 are simple (no parameters). ACTION6 needs x,y coordinates.
- ACTION0 is RESET — restarts the current level. Use sparingly.
- States: NOT_FINISHED (playing), WIN (all levels done), GAME_OVER (failed).
- Large uniform regions = background/walls. Small shapes = interactive objects.
- Edge bars = health/energy/progress indicators.
- ACTIONs 1-4 often map to directional movement. ACTION6 is usually a click."""

SYSTEM_MSG = (
    "You are an expert puzzle-solving AI agent. Analyse game grids and output "
    "ONLY valid JSON — no markdown, no explanation outside JSON."
)

# ═══════════════════════════════════════════════════════════════════════════
# MODEL REGISTRY — capabilities include image/reasoning/tools support
# ═══════════════════════════════════════════════════════════════════════════

MODEL_REGISTRY: dict[str, dict] = {
    # ── Gemini ────────────────────────────────────────────────────────────
    "gemini-2.5-flash": {
        "provider": "gemini", "api_model": "gemini-2.5-flash",
        "env_key": "GEMINI_API_KEY",
        "price": "$0.15/$0.60 per 1M tok",
        "capabilities": {"image": True, "reasoning": True, "tools": True},
    },
    "gemini-2.5-pro": {
        "provider": "gemini", "api_model": "gemini-2.5-pro",
        "env_key": "GEMINI_API_KEY",
        "price": "$1.25/$10 per 1M tok",
        "capabilities": {"image": True, "reasoning": True, "tools": True},
    },
    "gemini-2.0-flash": {
        "provider": "gemini", "api_model": "gemini-2.0-flash",
        "env_key": "GEMINI_API_KEY",
        "price": "$0.10/$0.40 per 1M tok",
        "capabilities": {"image": True, "reasoning": False, "tools": True},
    },
    "gemini-2.0-flash-lite": {
        "provider": "gemini", "api_model": "gemini-2.0-flash-lite",
        "env_key": "GEMINI_API_KEY",
        "price": "Free tier",
        "capabilities": {"image": True, "reasoning": False, "tools": False},
    },
    # ── Anthropic ─────────────────────────────────────────────────────────
    "claude-sonnet-4-6": {
        "provider": "anthropic", "api_model": "claude-sonnet-4-6",
        "env_key": "ANTHROPIC_API_KEY",
        "price": "$3/$15 per 1M tok",
        "capabilities": {"image": True, "reasoning": True, "tools": True},
    },
    "claude-sonnet-4-5": {
        "provider": "anthropic", "api_model": "claude-sonnet-4-5-20241022",
        "env_key": "ANTHROPIC_API_KEY",
        "price": "$3/$15 per 1M tok",
        "capabilities": {"image": True, "reasoning": True, "tools": True},
    },
    "claude-haiku-4-5": {
        "provider": "anthropic", "api_model": "claude-haiku-4-5-20251001",
        "env_key": "ANTHROPIC_API_KEY",
        "price": "$0.80/$4 per 1M tok",
        "capabilities": {"image": True, "reasoning": False, "tools": True},
    },
    # ── Groq (free tier) ──────────────────────────────────────────────────
    "groq/llama-3.3-70b-versatile": {
        "provider": "groq", "api_model": "llama-3.3-70b-versatile",
        "env_key": "GROQ_API_KEY",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "price": "Free tier",
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    "groq/gemma2-9b-it": {
        "provider": "groq", "api_model": "gemma2-9b-it",
        "env_key": "GROQ_API_KEY",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "price": "Free tier",
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    "groq/mixtral-8x7b-32768": {
        "provider": "groq", "api_model": "mixtral-8x7b-32768",
        "env_key": "GROQ_API_KEY",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "price": "Free tier",
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    # ── Mistral (free tier) ───────────────────────────────────────────────
    "mistral/mistral-small-latest": {
        "provider": "mistral", "api_model": "mistral-small-latest",
        "env_key": "MISTRAL_API_KEY",
        "url": "https://api.mistral.ai/v1/chat/completions",
        "price": "Free tier",
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    "mistral/open-mistral-nemo": {
        "provider": "mistral", "api_model": "open-mistral-nemo",
        "env_key": "MISTRAL_API_KEY",
        "url": "https://api.mistral.ai/v1/chat/completions",
        "price": "Free tier",
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    # ── HuggingFace ───────────────────────────────────────────────────────
    "hf/qwen2.5-72b-instruct": {
        "provider": "huggingface", "api_model": "Qwen/Qwen2.5-72B-Instruct",
        "env_key": "HUGGINGFACE_API_KEY",
        "url": "https://router.huggingface.co/v1/chat/completions",
        "price": "Free tier",
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    "hf/llama-3.1-70b-instruct": {
        "provider": "huggingface", "api_model": "meta-llama/Llama-3.1-70B-Instruct",
        "env_key": "HUGGINGFACE_API_KEY",
        "url": "https://router.huggingface.co/v1/chat/completions",
        "price": "Free tier",
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    # ── Cloudflare Workers AI ────────────────────────────────────────────
    "cf/llama-3.3-70b-instruct": {
        "provider": "cloudflare", "api_model": "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        "env_key": "CLOUDFLARE_API_KEY",
        "price": "Free (10k neurons/day)",
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    "cf/llama-3.1-8b-instruct": {
        "provider": "cloudflare", "api_model": "@cf/meta/llama-3.1-8b-instruct-fast",
        "env_key": "CLOUDFLARE_API_KEY",
        "price": "Free (10k neurons/day)",
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    "cf/llama-4-scout-17b": {
        "provider": "cloudflare", "api_model": "@cf/meta/llama-4-scout-17b-16e-instruct",
        "env_key": "CLOUDFLARE_API_KEY",
        "price": "Free (10k neurons/day)",
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    "cf/qwen3-30b": {
        "provider": "cloudflare", "api_model": "@cf/qwen/qwen3-30b-a3b-fp8",
        "env_key": "CLOUDFLARE_API_KEY",
        "price": "Free (10k neurons/day)",
        "capabilities": {"image": False, "reasoning": True, "tools": False},
    },
    "cf/qwq-32b": {
        "provider": "cloudflare", "api_model": "@cf/qwen/qwq-32b",
        "env_key": "CLOUDFLARE_API_KEY",
        "price": "Free (10k neurons/day)",
        "capabilities": {"image": False, "reasoning": True, "tools": False},
    },
    "cf/deepseek-r1-distill-32b": {
        "provider": "cloudflare", "api_model": "@cf/deepseek-ai/deepseek-r1-distill-qwen-32b",
        "env_key": "CLOUDFLARE_API_KEY",
        "price": "Free (10k neurons/day)",
        "capabilities": {"image": False, "reasoning": True, "tools": False},
    },
    "cf/mistral-small-3.1-24b": {
        "provider": "cloudflare", "api_model": "@cf/mistralai/mistral-small-3.1-24b-instruct",
        "env_key": "CLOUDFLARE_API_KEY",
        "price": "Free (10k neurons/day)",
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    "cf/llama-3.2-11b-vision": {
        "provider": "cloudflare", "api_model": "@cf/meta/llama-3.2-11b-vision-instruct",
        "env_key": "CLOUDFLARE_API_KEY",
        "price": "Free (10k neurons/day)",
        "capabilities": {"image": True, "reasoning": False, "tools": False},
    },
    # ── GitHub Copilot (local only, requires OAuth) ──────────────────────
    "copilot/gpt-4.1": {
        "provider": "copilot", "api_model": "gpt-4.1",
        "env_key": "",  # no env key — auth via OAuth
        "price": "Free (unlimited)",
        "capabilities": {"image": True, "reasoning": False, "tools": True},
    },
    "copilot/gpt-4o": {
        "provider": "copilot", "api_model": "gpt-4o",
        "env_key": "",
        "price": "Free (unlimited)",
        "capabilities": {"image": True, "reasoning": False, "tools": True},
    },
    "copilot/gpt-5-mini": {
        "provider": "copilot", "api_model": "gpt-5-mini",
        "env_key": "",
        "price": "Free (unlimited)",
        "capabilities": {"image": True, "reasoning": True, "tools": True},
    },
    "copilot/claude-sonnet-4": {
        "provider": "copilot", "api_model": "claude-sonnet-4",
        "env_key": "",
        "price": "Premium (300/mo)",
        "capabilities": {"image": True, "reasoning": True, "tools": True},
    },
    "copilot/gemini-2.5-pro": {
        "provider": "copilot", "api_model": "gemini-2.5-pro",
        "env_key": "",
        "price": "Premium (300/mo)",
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

def _build_prompt(payload: dict, input_settings: dict, tools_mode: str) -> str:
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

    parts.append(f"""{ARC_AGI3_DESCRIPTION}

COLOR PALETTE: 0=White 1=LightGray 2=Gray 3=DarkGray 4=VeryDarkGray 5=Black
               6=Magenta 7=LightMagenta 8=Red 9=Blue 10=LightBlue 11=Yellow
               12=Orange 13=Maroon 14=Green 15=Purple""")

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
        recent = history[-10:]
        lines = []
        for h in recent:
            aname = ACTION_NAMES.get(h.get("action", 0), "?")
            lines.append(f"  Step {h.get('step', '?')}: {aname} -> {h.get('result_state', '?')}")
        parts.append("## HISTORY (last 10)\n" + "\n".join(lines))

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
            '\n- "analysis": analyse what you see — objects, patterns, spatial relationships, '
            "possible goals, and which areas of the grid are interactive."
        )

    parts.append(f"""## YOUR TASK
1. Identify key objects (character, walls, targets, items).
2. Determine what must happen next to progress.
3. Choose the best action.

Respond with EXACTLY this JSON (nothing else):
{{"observation": "<what you see>", "reasoning": "<your plan>", "action": <number>, "data": {{}}{', "analysis": "<detailed spatial analysis>"' if tools_mode == "on" else ''}}}

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
    try:
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except json.JSONDecodeError:
        pass
    return None


def _call_gemini(model_name: str, prompt: str, image_b64: str | None = None) -> str:
    from google import genai
    api_key = os.environ.get("GEMINI_API_KEY", "")
    client = genai.Client(api_key=api_key)

    if image_b64:
        image_bytes = base64.b64decode(image_b64)
        contents = [
            genai.types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
            f"{SYSTEM_MSG}\n\n{prompt}",
        ]
    else:
        contents = f"{SYSTEM_MSG}\n\n{prompt}"

    # Thinking models (2.5-*) need a large output budget because thinking
    # tokens count against max_output_tokens.  We set a thinking budget so
    # the model doesn't burn all tokens on reasoning and truncate the answer.
    is_thinking = "2.5" in model_name
    config = genai.types.GenerateContentConfig(
        temperature=0.3,
        max_output_tokens=16384 if is_thinking else 2048,
    )
    if is_thinking:
        config.thinking_config = genai.types.ThinkingConfig(
            thinking_budget=8192,  # up to 8k tokens for reasoning
        )

    response = client.models.generate_content(
        model=model_name, contents=contents, config=config,
    )
    return response.text


def _call_anthropic(model_name: str, prompt: str, image_b64: str | None = None) -> str:
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
            "temperature": 0.3, "max_tokens": 2048,
        },
        timeout=90.0,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def _call_openai_compatible(url: str, api_key: str, model: str, prompt: str,
                             image_b64: str | None = None,
                             extra_headers: dict | None = None) -> str:
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
    body = {"model": model, "messages": messages, "temperature": 0.3, "max_tokens": 2048}

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
        return resp.json()["choices"][0]["message"]["content"]
    raise last_exc


def _call_cloudflare(model_name: str, prompt: str, image_b64: str | None = None) -> str:
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
        json={"messages": messages, "temperature": 0.3, "max_tokens": 2048},
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
            resp.raise_for_status()
            data = resp.json()
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


def _route_model_call(model_key: str, prompt: str, image_b64: str | None = None) -> str:
    """Route to the correct provider, passing image if available."""
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
        return _call_gemini(api_model, prompt, img)
    if provider == "anthropic":
        return _call_anthropic(api_model, prompt, img)
    if provider == "cloudflare":
        return _call_cloudflare(api_model, prompt, img)
    if provider == "copilot":
        return _call_copilot(api_model, prompt, img)
    if provider == "ollama":
        return _call_ollama(api_model, prompt, img)

    # OpenAI-compatible (Groq, Mistral, HuggingFace) — no image for these
    api_key = os.environ.get(info.get("env_key", ""), "")
    url = info.get("url", "")
    return _call_openai_compatible(url, api_key, api_model, prompt, None)


# ═══════════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/")
@bot_protection
def index():
    mode = get_mode()
    features = get_enabled_features()
    return render_template("index.html", color_map=COLOR_MAP,
                           turnstile_site_key=TURNSTILE_SITE_KEY,
                           mode=mode, features=features)


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
        _db_update_session(
            session_id,
            result=state.get("state", "NOT_FINISHED"),
            levels=state.get("levels_completed", 0),
        )

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
        # In online mode, skip server-only providers
        if mode == "online" and provider not in ("copilot",):
            # Online mode only shows puter/byok models (handled client-side)
            continue
        # In local mode, include everything
        # Copilot models need OAuth, not env key
        if provider == "copilot":
            if not feature_enabled("copilot"):
                continue
            available = copilot_oauth_token is not None
        else:
            env_key = info.get("env_key", "")
            available = bool(not env_key or os.environ.get(env_key))
        models.append({
            "name": key,
            "provider": provider,
            "price": info.get("price", "?"),
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


@app.route("/api/llm/ask", methods=["POST"])
@bot_protection
@turnstile_required
def llm_ask():
    """Ask LLM for next action.

    Body includes:
      - standard game state fields (grid, state, available_actions, etc.)
      - settings.input: {diff, full_grid, image, color_histogram}
      - settings.reasoning_mode: "on" | "off" | "adaptive"
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

    prompt = _build_prompt(payload, input_settings, tools_mode)

    # Get image if the input setting is on and data was provided
    image_b64 = None
    if input_settings.get("image"):
        image_b64 = payload.get("image_b64")

    try:
        content = _route_model_call(model_key, prompt, image_b64)
        result = _parse_llm_response(content, model_key)
        result["tools_active"] = tools_mode == "on"
        result["prompt_length"] = len(prompt)

        # Stash LLM response for session DB persistence
        session_id = payload.get("session_id")
        if session_id and feature_enabled("session_db"):
            with session_lock:
                session_last_llm[session_id] = result
                # Also update the model on the session record
            _db_update_session(session_id, model=model_key)

        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e), "model": model_key}), 500


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

    with session_lock:
        snapshot = snapshots.pop()

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
            data={"client_id": COPILOT_CLIENT_ID, "scope": "read:user"},
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
# SESSION IMPORT + BRANCH ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/sessions/import", methods=["POST"])
@bot_protection
@turnstile_required
def import_session():
    """Import/upsert a session and its steps. Used by puter.kv auto-upload."""
    if not feature_enabled("session_db"):
        return jsonify({"error": "Session DB not enabled"}), 400
    payload = request.get_json(force=True)
    sess = payload.get("session")
    steps = payload.get("steps", [])
    if not sess or not sess.get("id") or not sess.get("game_id"):
        return jsonify({"error": "session.id and session.game_id required"}), 400
    # Reject short sessions — under 50 steps is noise
    if len(steps) < 50:
        return jsonify({"error": "Session too short (min 50 steps)", "skipped": True}), 200
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
        return jsonify({"status": "ok", "session_id": sess["id"], "steps_imported": len(steps)})
    except Exception as e:
        app.logger.warning(f"Session import failed: {e}")
        return jsonify({"error": str(e)}), 500


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
        rows = conn.execute(
            "SELECT action, data_json FROM session_steps WHERE session_id = ? AND step_num <= ? ORDER BY step_num",
            (parent_id, step_num),
        ).fetchall()
        conn.close()

        actions = [{"action": r["action"], "data": r["data_json"]} for r in rows]
        env, state = _reconstruct_session(sess["game_id"], actions)

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
    """List recent sessions (last 100)."""
    if not feature_enabled("session_db"):
        return jsonify({"sessions": []})
    try:
        conn = _get_db()
        rows = conn.execute(
            "SELECT id, game_id, model, mode, created_at, result, steps, levels, "
            "parent_session_id, branch_at_step "
            "FROM sessions ORDER BY created_at DESC LIMIT 100"
        ).fetchall()
        conn.close()
        return jsonify({"sessions": [dict(r) for r in rows]})
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
    """Get full session with all steps and decompressed grids."""
    if not feature_enabled("session_db"):
        return jsonify({"error": "Session DB not enabled"}), 404
    try:
        conn = _get_db()
        sess = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if not sess:
            conn.close()
            return jsonify({"error": "Session not found"}), 404
        steps = conn.execute(
            "SELECT * FROM session_steps WHERE session_id = ? ORDER BY step_num",
            (session_id,),
        ).fetchall()
        conn.close()
        step_list = []
        # For branched sessions, prepend parent steps up to branch point
        sess_dict = dict(sess)
        parent_id = sess_dict.get("parent_session_id")
        branch_at = sess_dict.get("branch_at_step")
        if parent_id and branch_at is not None:
            parent_steps = conn.execute(
                "SELECT * FROM session_steps WHERE session_id = ? AND step_num <= ? ORDER BY step_num",
                (parent_id, branch_at),
            ).fetchall()
            for s in parent_steps:
                d = _format_step_row(dict(s))
                d["from_parent"] = True
                step_list.append(d)
        for s in steps:
            d = _format_step_row(dict(s))
            step_list.append(d)
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
