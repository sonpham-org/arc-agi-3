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
from flask import Flask, Response, abort, jsonify, make_response, render_template, request

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
    "copilot":       {"staging": False,  "prod": False},
    "server_llm":    {"staging": False,  "prod": False},  # removed: all LLM calls are client-side
    "puter_js":      {"staging": True,   "prod": True},
    "byok":          {"staging": True,   "prod": True},
    "session_db":    {"staging": True,   "prod": True},
    "memory_md":     {"staging": True,   "prod": False},
    "pyodide_game":  {"staging": True,   "prod": True},
}

# Games hidden in prod mode (non-foundation games)
HIDDEN_GAMES = ["fd01", "fy01", "pt01"]

DEV_SECRET = os.environ.get("DEV_SECRET", "arc-dev-2026")

# Will be set by CLI args; default to staging
_server_mode = "staging"
_server_port_staging = 5000
_server_port_prod = 5001


def get_mode() -> str:
    """Determine mode from SERVER_MODE env var or port the request arrived on."""
    env_mode = os.environ.get("SERVER_MODE", "")
    if env_mode in ("staging", "prod"):
        return env_mode
    # Legacy compat: treat "local" as staging, "online" as prod
    if env_mode == "local":
        return "staging"
    if env_mode == "online":
        return "prod"
    try:
        port = int(request.environ.get("SERVER_PORT", _server_port_staging))
        if port == _server_port_prod:
            return "prod"
    except (ValueError, RuntimeError):
        pass
    return "staging"


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

# Magic link email — Resend (free tier: 100 emails/day)
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM = os.environ.get("RESEND_FROM", "noreply@arc3.sonpham.net")

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
    if get_mode() == "staging":
        return True  # skip Turnstile in staging mode
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
    """UA filtering + rate limiting on API routes (prod mode only)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if get_mode() == "staging":
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


# ── Auth helpers ──────────────────────────────────────────────────────────

_auth_cache: dict[str, tuple[dict, float]] = {}  # token → (user_dict, cache_expiry)
_AUTH_CACHE_TTL = 300  # 5 minutes


def get_current_user() -> dict | None:
    """Get the currently authenticated user from the arc_auth cookie, or None."""
    token = request.cookies.get("arc_auth")
    if not token:
        return None
    now = time.time()
    cached = _auth_cache.get(token)
    if cached and cached[1] > now:
        return cached[0]
    user = _turso_verify_auth_token(token)
    if user:
        _auth_cache[token] = (user, now + _AUTH_CACHE_TTL)
    else:
        _auth_cache.pop(token, None)
    return user


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
# SQLite SESSION PERSISTENCE (extracted to db.py)
# ═══════════════════════════════════════════════════════════════════════════

from db import (
    DB_PATH, _init_db, _get_db, _compress_grid, _decompress_grid,
    _db_insert_session, _db_insert_step, _db_update_session,
    _log_llm_call, _get_session_calls, _read_session_from_file,
    _list_file_sessions,
)

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


# DB + Turso initialized at import time via db.py

from db import (
    TURSO_DATABASE_URL, TURSO_AUTH_TOKEN,
    _get_turso_db, _turso_dict_fetchone, _turso_dict_fetchall,
    _init_turso_db, _turso_import_session,
    _turso_find_or_create_user, _turso_create_auth_token,
    _turso_verify_auth_token, _turso_create_magic_link,
    _turso_verify_magic_link, _turso_delete_auth_token,
    _turso_claim_sessions, _turso_get_user_sessions,
    _turso_count_recent_magic_links, AUTH_TOKEN_TTL,
)


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

ARC_AGI3_DESCRIPTION = (Path(__file__).parent / "prompts" / "shared" / "arc_description.txt").read_text().strip()


def _load_prompts():
    """Load all prompt .txt files from prompts/ directory for injection into templates."""
    base = Path(__file__).parent / "prompts"
    result = {}
    for section in sorted(base.iterdir()):
        if section.is_dir():
            result[section.name] = {
                f.stem: f.read_text() for f in sorted(section.glob("*.txt"))
            }
    return result


# Prompts are loaded fresh per-request via _load_prompts() in the index route

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
    "gemini-3.1-flash-lite": {
        "provider": "gemini", "api_model": "gemini-3.1-flash-lite-preview",
        "env_key": "GEMINI_API_KEY",
        "price": "$0.25/$1.50 per 1M tok",
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
    "qwen3.5:35b-a3b": "~24GB",
    "qwen2.5:32b": "~19GB", "qwen2.5:14b": "~9GB", "qwen3-8b:latest": "~5GB",
    "deepseek-r1:latest": "~5GB", "mistral:7b": "~4.4GB",
    "llama3.1:latest": "~4.9GB", "llama3:latest": "~4.7GB",
    "llava:latest": "~5GB",
}

# Models that support vision via Ollama (llava family)
OLLAMA_VISION_MODELS = {"llava", "llava:latest", "llava:13b", "bakllava"}

# Runtime dict of discovered local OpenAI-compatible models (populated by /api/llm/models)
_discovered_local_models: dict = {}


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
# SCAFFOLDING — imported from scaffoldings/ package
# ═══════════════════════════════════════════════════════════════════════════

from scaffoldings.rlm.handler import handle_rlm_scaffolding as _handle_rlm_scaffolding_impl  # noqa: used by agent.py
from scaffoldings.three_system.handler import (  # noqa: used by agent.py
    handle_three_system_scaffolding as _handle_three_system_scaffolding_impl,
)
# Server-side LLM route wrappers removed — all LLM calls are now client-side


_SCAFFOLDING_PLACEHOLDER = True  # inline code moved to scaffoldings/ package
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
                        if "action" in obj or "plan" in obj or "type" in obj or "verdict" in obj:
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

        # Check for MALFORMED_FUNCTION_CALL — model tried to call a tool
        # but formatted it as a code block instead of a proper function call.
        # Extract the code and execute it as if it were a run_python call.
        if response.candidates:
            fr = getattr(response.candidates[0], 'finish_reason', None)
            fr_str = str(fr).upper() if fr else ""
            if "MALFORMED" in fr_str and tools_enabled and session_id:
                # Try to extract code from the malformed response
                raw_text = ""
                try:
                    raw_text = response.text or ""
                except Exception:
                    # content may be empty; try finish_message
                    fm = getattr(response.candidates[0], 'finish_message', None)
                    if fm:
                        raw_text = fm
                # Extract code from ```python ... ``` blocks
                import re as _re
                code_match = _re.search(r'```python\s*\n(.*?)```', raw_text, _re.DOTALL)
                if code_match:
                    code = code_match.group(1).strip()
                    app.logger.info(
                        f"Recovered code from MALFORMED_FUNCTION_CALL (len={len(code)}), executing as run_python"
                    )
                    output = _execute_python(session_id, code, grid, prev_grid)
                    tool_calls_log.append({
                        "name": "run_python",
                        "arguments": {"code": code},
                        "output": output,
                    })
                    # Feed the result back to the model (without tools, to get a text answer)
                    contents.append(genai.types.Content(
                        role="model",
                        parts=[genai.types.Part.from_function_call(
                            name="run_python", args={"code": code}
                        )],
                    ))
                    contents.append(genai.types.Content(
                        role="user",
                        parts=[genai.types.Part.from_function_response(
                            name="run_python",
                            response={"result": output},
                        )],
                    ))
                    config.tools = None  # force text answer on next round
                    continue  # next round
                else:
                    app.logger.warning(
                        "MALFORMED_FUNCTION_CALL but couldn't extract code, retrying without tools"
                    )
                    config.tools = None
                    continue  # retry this round without tools

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

    # Retry with exponential backoff on 429 (rate limit) — up to 10 attempts
    last_exc = None
    for attempt in range(10):
        resp = httpx.post(url, headers=headers, json=body, timeout=90.0)
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("retry-after", min(10 * (2 ** attempt), 120)))
            retry_after = min(retry_after, 120)
            app.logger.info(f"Rate limited by {url}, retrying in {retry_after}s (attempt {attempt+1}/10)")
            time.sleep(retry_after)
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

    # If not in registry, check runtime-discovered local models, then try ollama
    if info is None:
        if model_key in _discovered_local_models:
            local_info = _discovered_local_models[model_key]
            port = local_info["local_port"]
            api_model = local_info.get("api_model", model_key)
            url = f"http://localhost:{port}/v1/chat/completions"
            return _call_openai_compatible(url, "no-key-needed", api_model, prompt, image_b64, max_tokens=max_tokens)
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
    ct = response.content_type or ""
    if "text/html" in ct:
        # HTML is Jinja-rendered — never cache
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    elif request.path.startswith("/static/"):
        if get_mode() == "staging":
            # No caching in staging — always serve fresh files
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        else:
            # Prod: cache 1 day at CDN, 1 hour in browser
            response.headers["Cache-Control"] = "public, max-age=3600, s-maxage=86400"
    return response


@app.route("/games/ab01")
def game_ab01():
    return render_template("ab01.html")


@app.route("/")
@bot_protection
def index():
    mode = get_mode()
    features = get_enabled_features()
    ts_key = TURNSTILE_SITE_KEY if mode == "prod" else ""
    return render_template("index.html", color_map=COLOR_MAP,
                           turnstile_site_key=ts_key,
                           mode=mode, features=features,
                           umami_url=UMAMI_URL, umami_website_id=UMAMI_WEBSITE_ID,
                           prompts=_load_prompts())


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


# ═══════════════════════════════════════════════════════════════════════════
# AUTH — Magic link email login
# ═══════════════════════════════════════════════════════════════════════════

def _send_magic_email(email: str, code: str) -> bool:
    """Send a magic link email via Resend API. Returns True on success."""
    if not RESEND_API_KEY:
        app.logger.warning("RESEND_API_KEY not set — cannot send magic link email")
        return False
    base_url = request.host_url.rstrip("/")
    link = f"{base_url}/api/auth/verify?code={code}"
    try:
        resp = _httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {RESEND_API_KEY}",
                     "Content-Type": "application/json"},
            json={
                "from": RESEND_FROM,
                "to": [email],
                "subject": "Your ARC-AGI-3 login link",
                "html": (
                    f"<p>Click the link below to log in to ARC-AGI-3:</p>"
                    f'<p><a href="{link}">{link}</a></p>'
                    f"<p>This link expires in 15 minutes and can only be used once.</p>"
                    f"<p>If you didn't request this, you can safely ignore this email.</p>"
                ),
            },
            timeout=10.0,
        )
        if resp.status_code >= 400:
            app.logger.warning(f"Resend API error: {resp.status_code} {resp.text}")
            return False
        return True
    except Exception as e:
        app.logger.warning(f"Failed to send magic link email: {e}")
        return False


@app.route("/api/auth/magic-link", methods=["POST"])
@bot_protection
def auth_magic_link():
    """Send a magic link email. Rate limited to 3 per email per 15 min."""
    payload = request.get_json(force=True)
    email = (payload.get("email") or "").lower().strip()
    if not email or "@" not in email or "." not in email.split("@")[-1]:
        return jsonify({"error": "Valid email required"}), 400
    # Rate limit: max 3 magic links per email per 15 minutes
    recent = _turso_count_recent_magic_links(email)
    if recent >= 3:
        return jsonify({"error": "Too many requests. Please wait a few minutes."}), 429
    code = _turso_create_magic_link(email)
    if not code:
        return jsonify({"error": "Service unavailable"}), 503
    sent = _send_magic_email(email, code)
    if not sent:
        # In staging/dev mode, log the code for manual testing
        if get_mode() == "staging":
            app.logger.info(f"[DEV] Magic link code for {email}: {code}")
            return jsonify({"status": "ok", "dev_code": code})
        return jsonify({"error": "Failed to send email"}), 500
    return jsonify({"status": "ok"})


@app.route("/api/auth/verify")
@bot_protection
def auth_verify():
    """Verify a magic link code and log the user in."""
    code = request.args.get("code", "")
    if not code:
        return "Missing code", 400
    email = _turso_verify_magic_link(code)
    if not email:
        return "Invalid or expired link. Please request a new one.", 400
    user = _turso_find_or_create_user(email)
    if not user:
        return "Service unavailable", 503
    token = _turso_create_auth_token(user["id"])
    if not token:
        return "Service unavailable", 503
    resp = make_response("")
    resp.headers["Location"] = "/?logged_in=1"
    resp.status_code = 302
    resp.set_cookie("arc_auth", token,
                     max_age=AUTH_TOKEN_TTL, httponly=True,
                     samesite="Lax", secure=request.is_secure)
    return resp


@app.route("/api/auth/status")
@bot_protection
def auth_status():
    """Return current auth state."""
    user = get_current_user()
    if user:
        return jsonify({"authenticated": True, "user": {
            "id": user["id"], "email": user["email"],
            "display_name": user.get("display_name"),
        }})
    return jsonify({"authenticated": False, "user": None})


@app.route("/api/auth/logout", methods=["POST"])
@bot_protection
def auth_logout():
    """Delete auth token and clear cookie."""
    token = request.cookies.get("arc_auth")
    if token:
        _turso_delete_auth_token(token)
        _auth_cache.pop(token, None)
    resp = make_response(jsonify({"status": "ok"}))
    resp.delete_cookie("arc_auth")
    return resp


@app.route("/api/auth/claim-sessions", methods=["POST"])
@bot_protection
def auth_claim_sessions():
    """Associate anonymous sessions with the current user."""
    user = get_current_user()
    if not user:
        return jsonify({"error": "Not authenticated"}), 401
    payload = request.get_json(force=True)
    session_ids = payload.get("session_ids", [])
    if not session_ids or not isinstance(session_ids, list):
        return jsonify({"error": "session_ids array required"}), 400
    # Limit to 100 at a time
    session_ids = session_ids[:100]
    claimed = _turso_claim_sessions(user["id"], session_ids)
    return jsonify({"status": "ok", "claimed": claimed})


@app.route("/api/games")
@bot_protection
@turnstile_required
def list_games():
    arc = get_arcade()
    envs = arc.get_environments()
    games = [
        {"game_id": e.game_id, "title": e.title, "default_fps": e.default_fps}
        for e in envs
    ]
    # In prod mode, hide non-foundation games unless ?show_all=1
    if get_mode() == "prod" and request.args.get("show_all") != "1":
        games = [g for g in games if g["game_id"].split("-")[0] not in HIDDEN_GAMES]
    return jsonify(games)


@app.route("/api/games/<game_id>/source")
@bot_protection
@turnstile_required
def game_source(game_id):
    """Return the Python source code for a game (for Pyodide client-side execution)."""
    bare_id = game_id.split("-")[0]
    arc = get_arcade()
    envs = arc.get_environments()
    env_info = next((e for e in envs if e.game_id == game_id or e.game_id.split("-")[0] == bare_id), None)
    if env_info is None:
        return jsonify({"error": f"Game {game_id} not found"}), 404
    local_dir = Path(env_info.local_dir)
    py_file = local_dir / f"{bare_id}.py"
    if not py_file.exists():
        return jsonify({"error": f"Source file not found for {game_id}"}), 404
    source = py_file.read_text(encoding="utf-8")
    return jsonify({
        "source": source,
        "class_name": env_info.class_name,
        "game_id": env_info.game_id,
        "default_fps": env_info.default_fps,
    })


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


@app.route("/api/dev/jump-level", methods=["POST"])
def dev_jump_level():
    if not DEV_SECRET or request.headers.get("X-Dev-Secret", "") != DEV_SECRET:
        return jsonify({"error": "Unauthorized"}), 403
    payload = request.get_json(force=True)
    session_id = payload.get("session_id")
    target_level = payload.get("level")
    if session_id is None or target_level is None:
        return jsonify({"error": "session_id and level required"}), 400
    with session_lock:
        env = game_sessions.get(session_id)
    if env is None:
        return jsonify({"error": "Session not found"}), 404
    try:
        from arcengine import FrameDataRaw
        game = env._game
        target_level = int(target_level)
        # Restore clean level state and jump
        game._levels[target_level] = game._clean_levels[target_level].clone()
        game.set_level(target_level)  # calls on_set_level
        game._score = target_level
        game._state = GameState.NOT_FINISHED
        # Render current frame without consuming a game step
        frame = game.camera.render(game.current_level.get_sprites())
        frame_raw = FrameDataRaw(
            game_id=game._game_id,
            state=game._state,
            levels_completed=game._score,
            win_levels=game._win_score,
            guid=getattr(env, "_guid", None),
            available_actions=game._available_actions,
        )
        frame_raw.frame = [frame]
        env._last_response = frame_raw
    except (IndexError, ValueError) as e:
        return jsonify({"error": str(e)}), 400
    state = env_state_dict(env, frame_raw)
    state["session_id"] = session_id
    with session_lock:
        session_grids[session_id] = state.get("grid", [])
        session_snapshots[session_id] = []
    return jsonify(state)


@app.route("/api/llm/cf-proxy", methods=["POST"])
@bot_protection
@turnstile_required
def cf_proxy():
    """Minimal CORS proxy for Cloudflare Workers AI (browser can't call directly)."""
    import httpx as _hx
    body = request.get_json(force=True) or {}
    api_key = body.get("api_key", "")
    account_id = body.get("account_id", "")
    model = body.get("model", "")
    messages = body.get("messages", [])
    max_tokens = min(int(body.get("max_tokens", 16384)), 65536)
    if not api_key or not account_id or not model:
        return jsonify({"error": "api_key, account_id, and model are required"}), 400
    try:
        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model}"
        resp = _hx.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"messages": messages, "temperature": 0.3, "max_tokens": max_tokens},
            timeout=90.0,
        )
        resp.raise_for_status()
        data = resp.json()
        result = data.get("result", {})
        text = result.get("response", "") if isinstance(result, dict) else str(result)
        return jsonify({"result": text})
    except Exception as e:
        return jsonify({"error": str(e)}), 502


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
        elif mode == "prod":
            # In prod mode, all server providers shown but marked unavailable
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

    # Discover Ollama models (staging only)
    if mode == "staging":
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

    # Discover local OpenAI-compatible servers (LM Studio, llama.cpp, vLLM, etc.)
    if mode == "staging":
        import httpx
        LOCAL_PORTS = [
            (1234, "LM Studio"),
            (8080, "Local Server"),
            (8000, "Local Server"),
        ]
        for port, label in LOCAL_PORTS:
            try:
                resp = httpx.get(f"http://localhost:{port}/v1/models", timeout=1.0)
                if resp.status_code == 200:
                    data = resp.json()
                    model_list = data.get("data", [])
                    for m in model_list:
                        mid = m.get("id", "")
                        if not mid:
                            continue
                        entry = {
                            "name": mid,
                            "api_model": mid,
                            "provider": "local",
                            "local_port": port,
                            "local_label": label,
                            "price": f"Free ({label}:{port})",
                            "capabilities": {"image": False, "reasoning": False, "tools": False},
                            "available": True,
                        }
                        models.append(entry)
                        _discovered_local_models[mid] = entry
            except Exception:
                pass

    return jsonify({"models": models, "mode": mode})



# LLM routes removed — all LLM calls are now client-side (BYOK/Puter.js)
# Kept: /api/llm/models (model registry, no LLM call)


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
    """GET/POST custom system prompt and hard memory (staging mode only)."""
    global _custom_system_prompt, _custom_hard_memory
    if get_mode() != "staging":
        return jsonify({"error": "Memory editing only available in staging mode"}), 403

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
    # Reject trivially short sessions
    if len(steps) < 5:
        return _cors_resp({"error": "Session too short (min 5 steps)", "skipped": True})
    try:
        prompts_json = json.dumps(sess.get("prompts")) if sess.get("prompts") else None
        timeline_json = json.dumps(sess.get("timeline")) if sess.get("timeline") else None
        # Tag with authenticated user if present
        user = get_current_user()
        user_id = sess.get("user_id") or (user["id"] if user else None)
        if user_id:
            sess["user_id"] = user_id
        conn = _get_db()
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
        llm_count = sum(1 for s in steps if s.get("llm_response"))
        app.logger.info(f"[import] session={sess['id'][:30]} steps={len(steps)} with_llm={llm_count}")
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
        # Extract timeline events into llm_calls rows (delete existing to avoid duplicates on re-upload)
        conn.execute("DELETE FROM llm_calls WHERE session_id = ?", (sess["id"],))
        calls_imported = 0
        timeline = sess.get("timeline") or []
        if isinstance(timeline, str):
            try:
                timeline = json.loads(timeline)
            except Exception:
                timeline = []

        # Build step_num→timestamp lookup for deriving call timestamps
        step_ts = {}
        for s in steps:
            sn = s.get("step_num")
            if sn is not None:
                step_ts[sn] = s.get("timestamp", 0)

        # Map timeline event types to llm_calls rows
        # Supported: reasoning, compact, interrupt (linear/RLM scaffolds)
        #            as_orch_*, as_sub_* (agent_spawn scaffold)
        for ev in timeline:
            etype = ev.get("type", "")
            # Determine call_type
            if etype in ("reasoning", "compact", "interrupt"):
                call_type = ev.get("call_type", etype)
            elif etype.startswith("as_"):
                call_type = etype  # e.g. as_orch_delegate, as_sub_result
            else:
                continue  # skip non-LLM events (act, game state, etc.)

            # Derive timestamp: explicit > from step > from session start
            ts = ev.get("timestamp") or 0
            if not ts:
                step_num = ev.get("stepStart") or ev.get("step_num")
                if step_num and step_num in step_ts:
                    ts = step_ts[step_num]
            if not ts:
                ts = sess.get("created_at", time.time())

            # Build response_preview from available fields
            preview = (ev.get("response_preview") or ev.get("response")
                       or ev.get("reasoning") or ev.get("summary") or "")
            if len(preview) > 1000:
                preview = preview[:1000]

            conn.execute(
                """INSERT OR IGNORE INTO llm_calls
                   (session_id, call_type, step_num, turn_num, model,
                    prompt_preview, prompt_length, response_preview,
                    input_tokens, output_tokens, cost, duration_ms,
                    thinking_level, cache_active, error, attempt, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (sess["id"], call_type,
                 ev.get("stepStart") or ev.get("step_num"),
                 ev.get("turn") or ev.get("parentTurn"),
                 ev.get("model", ""),
                 (ev.get("task") or "")[:500],  # use task as prompt_preview for agent_spawn
                 ev.get("prompt_length", 0),
                 preview,
                 ev.get("input_tokens", 0), ev.get("output_tokens", 0),
                 ev.get("cost", 0),
                 ev.get("duration") or ev.get("duration_ms") or 0,
                 ev.get("thinking_level"),
                 int(bool(ev.get("cache_active"))),
                 ev.get("error"), ev.get("attempt", 0), ts),
            )
            calls_imported += 1

        conn.commit()
        conn.close()
        # Also persist to Turso for durable shared replays
        _turso_import_session(payload)
        return _cors_resp({"status": "ok", "session_id": sess["id"],
                           "steps_imported": len(steps), "calls_imported": calls_imported})
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
    # Fetch session metadata and step rows from DB (local SQLite, then Turso fallback)
    try:
        conn = _get_db()
        sess = conn.execute(
            "SELECT game_id, model, parent_session_id, branch_at_step, timeline_json FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if sess:
            sess = dict(sess)

        parent_rows = []
        own_rows = []

        if sess:
            if sess.get("parent_session_id") and sess.get("branch_at_step") is not None:
                parent_rows = conn.execute(
                    "SELECT * FROM session_steps WHERE session_id = ? AND step_num <= ? ORDER BY step_num",
                    (sess["parent_session_id"], sess["branch_at_step"]),
                ).fetchall()
            own_rows = conn.execute(
                "SELECT * FROM session_steps WHERE session_id = ? ORDER BY step_num",
                (session_id,),
            ).fetchall()
        conn.close()

        # Turso fallback: if local SQLite doesn't have this session
        if not sess or not own_rows:
            turso_conn = _get_turso_db()
            if turso_conn:
                try:
                    if not sess:
                        cur = turso_conn.execute(
                            "SELECT game_id, model, parent_session_id, branch_at_step FROM sessions WHERE id = ?",
                            (session_id,),
                        )
                        sess = _turso_dict_fetchone(cur)
                    if sess:
                        if not own_rows:
                            cur2 = turso_conn.execute(
                                "SELECT * FROM session_steps WHERE session_id = ? ORDER BY step_num",
                                (session_id,),
                            )
                            own_rows = _turso_dict_fetchall(cur2)
                        if sess.get("parent_session_id") and sess.get("branch_at_step") is not None and not parent_rows:
                            cur3 = turso_conn.execute(
                                "SELECT * FROM session_steps WHERE session_id = ? AND step_num <= ? ORDER BY step_num",
                                (sess["parent_session_id"], sess["branch_at_step"]),
                            )
                            parent_rows = _turso_dict_fetchall(cur3)
                    turso_conn.close()
                except Exception as e:
                    app.logger.warning(f"Turso resume fallback failed: {e}")

        if not sess:
            return jsonify({"error": "Session not found"}), 404
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
    # Include timeline events for obs reconstruction
    tl_raw = sess.get("timeline_json")
    if tl_raw:
        try:
            state["timeline"] = json.loads(tl_raw) if isinstance(tl_raw, str) else tl_raw
        except Exception:
            state["timeline"] = []
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


@app.route("/api/sessions/<session_id>/obs-events", methods=["GET", "POST"])
@bot_protection
def session_obs_events(session_id):
    """GET: reconstruct obs events for replay. POST: save events from client."""
    if request.method == "POST":
        if not feature_enabled("session_db"):
            return jsonify({"error": "Session DB not enabled"}), 400
        payload = request.get_json(force=True)
        events = payload.get("events", [])
        cursor = payload.get("cursor", 0)
        if not events:
            return jsonify({"ok": True, "cursor": cursor})
        try:
            conn = _get_db()
            now = time.time()
            for i, ev in enumerate(events):
                conn.execute(
                    "INSERT OR IGNORE INTO obs_events (session_id, event_idx, event_json, timestamp) VALUES (?, ?, ?, ?)",
                    (session_id, cursor + i, json.dumps(ev), now))
            conn.commit()
            conn.close()
            new_cursor = cursor + len(events)
            return jsonify({"ok": True, "cursor": new_cursor})
        except Exception as e:
            app.logger.warning(f"Obs events save failed: {e}")
            return jsonify({"error": str(e)}), 500

    # GET — reconstruct events from DB for replay
    try:
        conn = _get_db()
        # Try stored obs_events first
        stored = conn.execute(
            "SELECT event_json FROM obs_events WHERE session_id = ? ORDER BY event_idx",
            (session_id,),
        ).fetchall()
        if stored:
            # Enrich events with grid snapshots from session_steps
            grid_rows = conn.execute(
                "SELECT step_num, grid_snapshot FROM session_steps "
                "WHERE session_id = ? AND grid_snapshot IS NOT NULL ORDER BY step_num",
                (session_id,),
            ).fetchall()
            conn.close()
            step_grids = {}
            for gr in grid_rows:
                try:
                    step_grids[gr["step_num"]] = _decompress_grid(gr["grid_snapshot"])
                except Exception:
                    pass
            events = []
            for r in stored:
                ev = json.loads(r["event_json"])
                # Attach grid to events that have a step_num (action events)
                if not ev.get("grid") and ev.get("step_num") is not None:
                    grid = step_grids.get(ev["step_num"])
                    if grid:
                        ev["grid"] = grid
                events.append(ev)
            return jsonify({"events": events})

        # Reconstruct from llm_calls + session_steps
        calls = conn.execute(
            "SELECT * FROM llm_calls WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        ).fetchall()
        steps = conn.execute(
            "SELECT * FROM session_steps WHERE session_id = ? ORDER BY step_num",
            (session_id,),
        ).fetchall()

        # Fallback: if no llm_calls rows, reconstruct from timeline_json
        if not calls:
            sess_row = conn.execute(
                "SELECT timeline_json FROM sessions WHERE id = ?", (session_id,),
            ).fetchone()
            if sess_row and sess_row["timeline_json"]:
                try:
                    timeline = json.loads(sess_row["timeline_json"])
                except Exception:
                    timeline = []
                # Build step_num→timestamp lookup
                step_ts = {}
                for s in steps:
                    sd = dict(s)
                    sn = sd.get("step_num")
                    if sn is not None:
                        step_ts[sn] = sd.get("timestamp", 0)
                # Convert timeline events to pseudo-call dicts
                calls = []
                for ev in timeline:
                    etype = ev.get("type", "")
                    if etype in ("reasoning", "compact", "interrupt") or etype.startswith("as_"):
                        ts = ev.get("timestamp") or 0
                        if not ts:
                            sn = ev.get("stepStart") or ev.get("step_num")
                            if sn and sn in step_ts:
                                ts = step_ts[sn]
                        preview = (ev.get("response_preview") or ev.get("response")
                                   or ev.get("reasoning") or ev.get("summary") or "")
                        calls.append({
                            "timestamp": ts,
                            "call_type": ev.get("call_type", etype),
                            "model": ev.get("model", ""),
                            "input_tokens": ev.get("input_tokens", 0),
                            "output_tokens": ev.get("output_tokens", 0),
                            "cost": ev.get("cost", 0),
                            "duration_ms": ev.get("duration") or ev.get("duration_ms") or 0,
                            "step_num": ev.get("stepStart") or ev.get("step_num"),
                            "turn_num": ev.get("turn") or ev.get("parentTurn"),
                            "thinking_level": ev.get("thinking_level"),
                            "response_preview": preview[:1000] if preview else "",
                            "prompt_preview": (ev.get("task") or "")[:500],
                        })

        conn.close()

        raw_events = []
        for c in [dict(c) if not isinstance(c, dict) else c for c in calls]:
            raw_events.append({
                "ts": c.get("timestamp", 0),
                "agent": c.get("call_type", "planner"),
                "event": "llm_call",
                "model": c.get("model", ""),
                "input_tokens": c.get("input_tokens", 0),
                "output_tokens": c.get("output_tokens", 0),
                "cost": c.get("cost", 0),
                "duration_ms": c.get("duration_ms", 0),
                "step_num": c.get("step_num"),
                "turn_num": c.get("turn_num"),
                "thinking_level": c.get("thinking_level"),
                "response": c.get("response_preview", ""),
                "prompt_preview": c.get("prompt_preview", ""),
            })
        for s in [dict(s) for s in steps]:
            grid = None
            if s.get("grid_snapshot"):
                try:
                    grid = _decompress_grid(s["grid_snapshot"])
                except Exception:
                    pass
            action_id = s.get("action", 0)
            try:
                action_name = GameAction.from_id(int(action_id)).name
            except Exception:
                action_name = str(action_id)
            data = {}
            if s.get("data_json"):
                try:
                    data = json.loads(s["data_json"]) if isinstance(s["data_json"], str) else s["data_json"]
                except Exception:
                    pass
            if data and "x" in data and "y" in data:
                action_name = f"{action_name}@({data['x']},{data['y']})"
            raw_events.append({
                "ts": s.get("timestamp", 0),
                "agent": "executor",
                "event": "act",
                "action": action_name,
                "step_num": s.get("step_num", 0),
                "grid": grid,
            })

        if not raw_events:
            return jsonify({"events": []})

        raw_events.sort(key=lambda e: e.get("ts", 0))
        t0 = raw_events[0]["ts"]
        from datetime import datetime, timezone
        events = []
        for ev in raw_events:
            ts = ev.pop("ts", 0)
            ev["t"] = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
            ev["elapsed_s"] = round(ts - t0, 2)
            events.append(ev)

        return jsonify({"events": events})
    except Exception as e:
        app.logger.warning(f"GET obs-events failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/sessions/browse")
def browse_sessions():
    """List sessions from per-session file exports (meta.json)."""
    try:
        sessions = _list_file_sessions()
        return jsonify({"sessions": sessions})
    except Exception as e:
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
        player_type_filter = request.args.get("player_type")
        _sessions_query = (
            "SELECT s.id, s.game_id, s.model, s.mode, s.created_at, s.result, s.steps, s.levels, "
            "s.parent_session_id, s.branch_at_step, s.total_cost, s.player_type, s.duration_seconds, "
            "(SELECT MAX(st.timestamp) - MIN(st.timestamp) FROM session_steps st WHERE st.session_id = s.id) AS duration "
            "FROM sessions s "
        )
        _params = ()
        if player_type_filter:
            _sessions_query += "WHERE s.player_type = ? "
            _params = (player_type_filter,)
        _sessions_query += "ORDER BY s.created_at DESC LIMIT 100"
        sessions_by_id = {}
        # Local SQLite
        conn = _get_db()
        rows = conn.execute(_sessions_query, _params).fetchall()
        conn.close()
        for r in rows:
            d = dict(r)
            sessions_by_id[d["id"]] = d
        # Turso (merge in, dedup by id)
        turso_conn = _get_turso_db()
        if turso_conn:
            try:
                cur = turso_conn.execute(_sessions_query, _params)
                for d in _turso_dict_fetchall(cur):
                    if d["id"] not in sessions_by_id:
                        sessions_by_id[d["id"]] = d
                turso_conn.close()
            except Exception as e:
                app.logger.warning(f"Turso list_sessions failed: {e}")
        # If authenticated, also include user's sessions from Turso (cross-device)
        user = get_current_user()
        if user:
            for d in _turso_get_user_sessions(user["id"]):
                if d["id"] not in sessions_by_id:
                    sessions_by_id[d["id"]] = d
        # Sort by created_at desc
        merged = sorted(sessions_by_id.values(), key=lambda s: s.get("created_at", 0), reverse=True)
        return jsonify({"sessions": merged[:100]})
    except Exception as e:
        return jsonify({"sessions": [], "error": str(e)})


@app.route("/api/leaderboard")
@bot_protection
def leaderboard():
    """Return best AI and human sessions per game for leaderboard display.

    Uses ROW_NUMBER() window function to pick the single best session per
    (game, player_type) in one pass each — no full table scan + Python grouping.
    Covered by idx_sessions_leaderboard index.
    """
    try:
        conn = _get_db()
        # Best AI session per game (most levels, fewest steps)
        ai_rows = conn.execute("""
            SELECT * FROM (
                SELECT s.id, s.game_id, s.result, s.steps, s.levels, s.model,
                       s.created_at, s.duration_seconds,
                       ROW_NUMBER() OVER (
                           PARTITION BY SUBSTR(s.game_id, 1, INSTR(s.game_id || '-', '-') - 1)
                           ORDER BY s.levels DESC, s.steps ASC
                       ) AS rn
                FROM sessions s
                WHERE COALESCE(s.player_type, 'agent') = 'agent' AND s.steps > 0
            ) WHERE rn = 1
        """).fetchall()
        # Best human session per game
        human_rows = conn.execute("""
            SELECT * FROM (
                SELECT s.id, s.game_id, s.result, s.steps, s.levels,
                       s.created_at, s.duration_seconds,
                       ROW_NUMBER() OVER (
                           PARTITION BY SUBSTR(s.game_id, 1, INSTR(s.game_id || '-', '-') - 1)
                           ORDER BY s.levels DESC, s.duration_seconds ASC, s.steps ASC
                       ) AS rn
                FROM sessions s
                WHERE s.player_type = 'human' AND s.steps > 0
            ) WHERE rn = 1
        """).fetchall()
        conn.close()
        ai_best = {dict(r)["game_id"].split("-")[0]: dict(r) for r in ai_rows}
        human_best = {dict(r)["game_id"].split("-")[0]: dict(r) for r in human_rows}
        all_games = sorted(set(list(ai_best.keys()) + list(human_best.keys())))
        rows = [{"game_id": gid, "ai": ai_best.get(gid), "human": human_best.get(gid)} for gid in all_games]
        return jsonify({"leaderboard": rows})
    except Exception as e:
        return jsonify({"leaderboard": [], "error": str(e)})


@app.route("/api/leaderboard/<game_id>")
@bot_protection
def leaderboard_detail(game_id):
    """Return top AI and human attempts for a specific game."""
    try:
        conn = _get_db()
        ai_rows = conn.execute("""
            SELECT s.id, s.game_id, s.result, s.steps, s.levels, s.model,
                   s.created_at, s.duration_seconds
            FROM sessions s
            WHERE COALESCE(s.player_type, 'agent') = 'agent'
              AND s.steps > 0 AND s.game_id LIKE ? || '%'
            ORDER BY s.levels DESC, s.steps ASC
            LIMIT 20
        """, (game_id,)).fetchall()
        human_rows = conn.execute("""
            SELECT s.id, s.game_id, s.result, s.steps, s.levels,
                   s.created_at, s.duration_seconds
            FROM sessions s
            WHERE s.player_type = 'human'
              AND s.steps > 0 AND s.game_id LIKE ? || '%'
            ORDER BY s.levels DESC, s.duration_seconds ASC, s.steps ASC
            LIMIT 20
        """, (game_id,)).fetchall()
        conn.close()
        return jsonify({
            "game_id": game_id,
            "ai": [dict(r) for r in ai_rows],
            "human": [dict(r) for r in human_rows],
        })
    except Exception as e:
        return jsonify({"game_id": game_id, "ai": [], "human": [], "error": str(e)})


# ── Comments API ─────────────────────────────────────────────────────────

@app.route("/api/comments/<game_id>")
def get_comments(game_id):
    """Get comments for a game."""
    voter_id = request.args.get("voter_id", "")
    try:
        conn = _get_db()
        rows = conn.execute(
            "SELECT * FROM comments WHERE game_id=? ORDER BY created_at DESC LIMIT 200",
            (game_id,),
        ).fetchall()
        # Get voter's votes for these comments
        my_votes = {}
        if voter_id and rows:
            cids = [r["id"] for r in rows]
            ph = ",".join("?" * len(cids))
            vote_rows = conn.execute(
                f"SELECT comment_id, vote FROM comment_votes WHERE voter_id=? AND comment_id IN ({ph})",
                [voter_id] + cids,
            ).fetchall()
            my_votes = {r["comment_id"]: r["vote"] for r in vote_rows}
        conn.close()
        return jsonify([
            {**dict(r), "my_vote": my_votes.get(r["id"], 0)} for r in rows
        ])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/comments", methods=["POST"])
def post_comment():
    """Post a new comment on a game."""
    data = request.json or {}
    game_id = data.get("game_id", "").strip()
    body = data.get("body", "").strip()
    author_id = data.get("author_id", "").strip()
    author_name = data.get("author_name", "").strip()
    if not game_id or not body or not author_id:
        return jsonify({"error": "Missing fields"}), 400
    if len(body) > 2000:
        return jsonify({"error": "Comment too long"}), 400
    if not author_name:
        author_name = f"anon-{author_id[:6]}"
    try:
        conn = _get_db()
        cur = conn.execute(
            "INSERT INTO comments (game_id, author_id, author_name, body, created_at) VALUES (?,?,?,?,?)",
            (game_id, author_id, author_name, body, time.time()),
        )
        cid = cur.lastrowid
        conn.commit()
        row = conn.execute("SELECT * FROM comments WHERE id=?", (cid,)).fetchone()
        conn.close()
        return jsonify({**dict(row), "my_vote": 0})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/comments/<int:comment_id>/vote", methods=["POST"])
def vote_comment(comment_id):
    """Upvote or downvote a comment. vote: 1, -1, or 0 (remove)."""
    data = request.json or {}
    voter_id = data.get("voter_id", "").strip()
    vote = data.get("vote", 0)
    if not voter_id or vote not in (1, -1, 0):
        return jsonify({"error": "Invalid vote"}), 400
    try:
        conn = _get_db()
        # Get existing vote
        existing = conn.execute(
            "SELECT vote FROM comment_votes WHERE comment_id=? AND voter_id=?",
            (comment_id, voter_id),
        ).fetchone()
        old_vote = existing["vote"] if existing else 0
        if old_vote == vote:
            conn.close()
            return jsonify({"ok": True})
        # Remove old vote effect
        if old_vote == 1:
            conn.execute("UPDATE comments SET upvotes = upvotes - 1 WHERE id=?", (comment_id,))
        elif old_vote == -1:
            conn.execute("UPDATE comments SET downvotes = downvotes - 1 WHERE id=?", (comment_id,))
        # Apply new vote
        if vote == 0:
            conn.execute("DELETE FROM comment_votes WHERE comment_id=? AND voter_id=?", (comment_id, voter_id))
        else:
            conn.execute(
                "INSERT OR REPLACE INTO comment_votes (comment_id, voter_id, vote) VALUES (?,?,?)",
                (comment_id, voter_id, vote),
            )
            if vote == 1:
                conn.execute("UPDATE comments SET upvotes = upvotes + 1 WHERE id=?", (comment_id,))
            else:
                conn.execute("UPDATE comments SET downvotes = downvotes + 1 WHERE id=?", (comment_id,))
        conn.commit()
        row = conn.execute("SELECT upvotes, downvotes FROM comments WHERE id=?", (comment_id,)).fetchone()
        conn.close()
        return jsonify({"ok": True, "upvotes": row["upvotes"], "downvotes": row["downvotes"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/contributors")
def contributors():
    """Top contributors: most comments, most human sessions, most AI sessions."""
    try:
        conn = _get_db()
        # Top commenters
        commenters = conn.execute("""
            SELECT author_id, author_name, COUNT(*) as comment_count,
                   SUM(upvotes) as total_upvotes
            FROM comments GROUP BY author_id
            ORDER BY comment_count DESC LIMIT 20
        """).fetchall()
        # Top human players (by number of sessions with >5 steps)
        human_players = conn.execute("""
            SELECT COALESCE(user_id, 'anon') as uid,
                   COUNT(*) as session_count,
                   SUM(duration_seconds) as total_time,
                   SUM(steps) as total_steps,
                   COUNT(DISTINCT SUBSTR(game_id, 1, INSTR(game_id || '-', '-') - 1)) as games_played
            FROM sessions
            WHERE player_type = 'human' AND steps > 5
            GROUP BY uid ORDER BY session_count DESC LIMIT 20
        """).fetchall()
        # Top AI contributors (by number of agent sessions with >5 steps)
        ai_contributors = conn.execute("""
            SELECT COALESCE(user_id, 'anon') as uid, model,
                   COUNT(*) as session_count,
                   SUM(steps) as total_steps,
                   COUNT(DISTINCT SUBSTR(game_id, 1, INSTR(game_id || '-', '-') - 1)) as games_played
            FROM sessions
            WHERE COALESCE(player_type, 'agent') = 'agent' AND steps > 5
            GROUP BY uid ORDER BY session_count DESC LIMIT 20
        """).fetchall()
        conn.close()
        return jsonify({
            "commenters": [dict(r) for r in commenters],
            "human_players": [dict(r) for r in human_players],
            "ai_contributors": [dict(r) for r in ai_contributors],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/game-results")
@bot_protection
def game_results():
    """Return human play results grouped by game and level."""
    if not feature_enabled("session_db"):
        return jsonify({"results": []})
    game_id = request.args.get("game_id")
    try:
        conn = _get_db()
        query = """
            SELECT s.id, s.game_id, s.result, s.steps, s.levels, s.duration_seconds,
                   s.created_at, s.user_id
            FROM sessions s
            WHERE s.player_type = 'human' AND s.result IN ('WIN', 'GAME_OVER')
        """
        params = ()
        if game_id:
            query += " AND s.game_id = ?"
            params = (game_id,)
        query += " ORDER BY s.levels DESC, s.duration_seconds ASC, s.steps ASC LIMIT 200"
        rows = conn.execute(query, params).fetchall()
        conn.close()
        results = [dict(r) for r in rows]
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"results": [], "error": str(e)})


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

        # Fall back to per-session file
        if not sess_dict:
            file_data = _read_session_from_file(session_id)
            if file_data:
                sess_dict = file_data["session"]
                for s in file_data["steps"]:
                    step_list.append(_format_step_row(s))

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
# LLM CALL LOG — universal call log API
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/sessions/<session_id>/calls")
def session_calls(session_id):
    """Return all LLM calls for a session, ordered by timestamp."""
    calls = _get_session_calls(session_id)
    # Parse response_json back from string
    for c in calls:
        if c.get("response_json"):
            try:
                c["response_json"] = json.loads(c["response_json"])
            except (json.JSONDecodeError, TypeError):
                pass
    return jsonify(calls)


# ═══════════════════════════════════════════════════════════════════════════
# SHARE — public replay page
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/share/<session_id>")
def share_session(session_id):
    """Public replay page — renders the observatory view with auto-loaded session.
    Verifies session exists (Turso → local DB → file), then serves obs.html."""
    # Quick existence check (don't load all data — obs.html fetches via API)
    found = False
    try:
        turso_conn = _get_turso_db()
        if turso_conn:
            try:
                cur = turso_conn.execute("SELECT id FROM sessions WHERE id = ?", (session_id,))
                if _turso_dict_fetchone(cur):
                    found = True
                turso_conn.close()
            except Exception:
                pass
        if not found:
            conn = _get_db()
            if conn.execute("SELECT 1 FROM sessions WHERE id = ?", (session_id,)).fetchone():
                found = True
            conn.close()
        if not found:
            file_data = _read_session_from_file(session_id)
            if file_data:
                found = True
    except Exception:
        pass

    if not found:
        return """<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Session Not Found</title>
<style>body{background:#0d1117;color:#c9d1d9;font-family:'Courier New',monospace;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;}
.box{text-align:center;padding:40px;border:1px solid #30363d;border-radius:12px;background:#161b22;max-width:400px;}
h1{color:#f85149;font-size:24px;margin-bottom:12px;}p{color:#8b949e;margin-bottom:20px;}
a{color:#58a6ff;text-decoration:none;}a:hover{text-decoration:underline;}</style></head>
<body><div class="box"><h1>Session Not Found</h1><p>This session doesn't exist or hasn't been shared yet.</p>
<a href="/">&#9654; Play ARC-AGI-3</a></div></body></html>""", 404

    return render_template("obs.html", share_session_id=session_id)


# ═══════════════════════════════════════════════════════════════════════════
# SCENE EDITOR — fd01 pixel editor
# ═══════════════════════════════════════════════════════════════════════════

import importlib.util as _importlib_util
import numpy as _np

_FD01_PATH = Path(__file__).parent / "environment_files" / "fd01" / "00000001" / "fd01.py"
_CUSTOM_SCENES_FILE = Path(__file__).parent / "environment_files" / "fd01" / "00000001" / "custom_scenes.json"
_CUSTOM_DIFFS_FILE  = Path(__file__).parent / "environment_files" / "fd01" / "00000001" / "custom_diffs.json"


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


def _read_custom_diffs() -> dict:
    try:
        if _CUSTOM_DIFFS_FILE.exists():
            return json.loads(_CUSTOM_DIFFS_FILE.read_text())
    except Exception:
        pass
    return {}


def _write_custom_diffs(data: dict):
    _CUSTOM_DIFFS_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CUSTOM_DIFFS_FILE.write_text(json.dumps(data))


@app.route("/draw")
def draw_editor():
    return render_template("draw.html", color_map=COLOR_MAP, color_names=COLOR_NAMES)


def _builtin_diffs_to_rects(raw_diffs):
    """Convert old (dx,dy,rc,side) tuples → {x,y,w,h,color,side} dicts."""
    return [{"x": d[0] - 1, "y": d[1] - 1, "w": 4, "h": 4, "color": d[2], "side": d[3]}
            for d in raw_diffs]


@app.route("/api/draw/scene/<int:level>")
def get_draw_scene(level):
    if level < 0 or level >= 5:
        return jsonify({"error": "Invalid level"}), 400
    fd01 = _load_fd01_module()
    custom_scenes = _read_custom_scenes()
    custom_diffs  = _read_custom_diffs()

    if str(level) in custom_scenes:
        pixels = custom_scenes[str(level)]
        is_custom_scene = True
    else:
        img = _np.zeros((fd01.IMG_H, fd01.IMG_W), dtype=_np.int16)
        fd01.SCENES[level](img)
        pixels = img.tolist()
        is_custom_scene = False

    if str(level) in custom_diffs:
        diffs = custom_diffs[str(level)]
        is_custom_diffs = True
    else:
        diffs = _builtin_diffs_to_rects(fd01.DIFFS[level])
        is_custom_diffs = False

    return jsonify({"pixels": pixels, "width": fd01.IMG_W, "height": fd01.IMG_H,
                    "custom": is_custom_scene, "custom_diffs": is_custom_diffs,
                    "diffs": diffs})


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


@app.route("/api/draw/save_diffs", methods=["POST"])
def save_draw_diffs():
    data = request.get_json(force=True)
    level = data.get("level")
    diffs = data.get("diffs")
    if level is None or diffs is None:
        return jsonify({"error": "level and diffs required"}), 400
    custom = _read_custom_diffs()
    custom[str(level)] = diffs
    _write_custom_diffs(custom)
    global arcade_instance
    arcade_instance = None
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
    custom_d = _read_custom_diffs()
    custom_d.pop(str(level), None)
    _write_custom_diffs(custom_d)
    global arcade_instance
    arcade_instance = None
    return jsonify({"status": "ok"})


# ═══════════════════════════════════════════════════════════════════════════
# BATCH API — bearer token auth + batch endpoints
# ═══════════════════════════════════════════════════════════════════════════

BATCH_API_KEYS = set(
    k.strip() for k in os.environ.get("BATCH_API_KEYS", "").split(",") if k.strip()
)


def _require_batch_auth():
    """Validate bearer token for batch API. Returns error response or None."""
    if not BATCH_API_KEYS:
        return None  # no keys configured = open access (local dev)
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return jsonify({"error": "Missing Authorization header"}), 401
    token = auth[7:]
    if token not in BATCH_API_KEYS:
        return jsonify({"error": "Invalid API key"}), 403
    return None


@app.route("/api/batch/start", methods=["POST"])
def batch_start():
    auth_err = _require_batch_auth()
    if auth_err:
        return auth_err

    from batch_runner import run_batch, load_config as br_load_config
    from agent import MODELS

    data = request.get_json(force=True)
    games = data.get("games", [])
    model = data.get("model")
    concurrency = data.get("concurrency", 4)
    max_steps = data.get("max_steps", 200)
    repeat = data.get("repeat", 1)
    upload_turso = data.get("upload_turso", False)

    cfg = br_load_config()
    if model:
        if model not in MODELS:
            return jsonify({"error": f"Unknown model: {model}"}), 400
        cfg["reasoning"]["executor_model"] = model

    # Resolve game list
    arcade = get_arcade()
    available_games = [e.game_id for e in arcade.get_environments()]
    if games == ["all"] or games == "all":
        resolved_games = available_games
    else:
        resolved_games = []
        for g in games:
            matched = [gid for gid in available_games if gid.startswith(g)]
            resolved_games.extend(matched)

    if not resolved_games:
        return jsonify({"error": "No matching games found"}), 400

    # Launch batch in background thread
    import secrets as _secrets
    batch_id = f"api-{_secrets.token_hex(8)}"

    def _run():
        run_batch(
            games=resolved_games, cfg=cfg,
            concurrency=concurrency, max_steps=max_steps,
            repeat=repeat, resume_batch_id=batch_id,
            upload_turso=upload_turso,
        )

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    return jsonify({"batch_id": batch_id, "games": resolved_games, "status": "started"})


@app.route("/api/batch/<batch_id>")
def batch_status(batch_id):
    auth_err = _require_batch_auth()
    if auth_err:
        return auth_err

    try:
        conn = _get_db()
        batch = conn.execute("SELECT * FROM batch_runs WHERE id = ?", (batch_id,)).fetchone()
        if not batch:
            conn.close()
            return jsonify({"error": "Batch not found"}), 404

        games = conn.execute(
            "SELECT * FROM batch_games WHERE batch_id = ? ORDER BY game_id", (batch_id,)
        ).fetchall()
        conn.close()

        return jsonify({
            "batch_id": batch_id,
            "status": batch["status"],
            "total_games": batch["total_games"],
            "completed_games": batch["completed_games"],
            "wins": batch["wins"],
            "failures": batch["failures"],
            "created_at": batch["created_at"],
            "finished_at": batch["finished_at"],
            "games": [dict(g) for g in games],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500



# ═══════════════════════════════════════════════════════════════════════════
# MAIN — dual-port serving
# ═══════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ARC-AGI-3 Web Player")
    parser.add_argument("--mode", choices=["staging", "prod", "dual"], default="dual",
                        help="Run mode: staging (port 5000), prod (port 5001), or dual (both)")
    parser.add_argument("--port", type=int, default=None,
                        help="Override port (for single-mode)")
    parser.add_argument("--port-staging", type=int, default=5000, help="Staging mode port")
    parser.add_argument("--port-prod", type=int, default=5001, help="Prod mode port")
    args = parser.parse_args()

    _server_port_staging = args.port_staging
    _server_port_prod = args.port_prod

    # Initialize SQLite DB
    _init_db()
    print("  SQLite sessions DB initialized at:", DB_PATH)

    if args.mode == "dual":
        print(f"\n  ARC-AGI-3 Web Player (dual mode)")
        print(f"    Staging: http://localhost:{_server_port_staging}")
        print(f"    Prod:    http://localhost:{_server_port_prod}\n")

        # Run prod port in a background thread
        def run_prod():
            from werkzeug.serving import make_server
            srv = make_server("0.0.0.0", _server_port_prod, app)
            srv.serve_forever()

        t = threading.Thread(target=run_prod, daemon=True)
        t.start()

        # Run staging port in main thread
        app.run(host="0.0.0.0", port=_server_port_staging, debug=False)

    elif args.mode == "staging":
        port = args.port or _server_port_staging
        _server_port_staging = port
        print(f"\n  ARC-AGI-3 Web Player (staging): http://localhost:{port}\n")
        app.run(host="0.0.0.0", port=port, debug=False)

    elif args.mode == "prod":
        port = args.port or _server_port_prod
        _server_port_prod = port
        print(f"\n  ARC-AGI-3 Web Player (prod): http://localhost:{port}\n")
        app.run(host="0.0.0.0", port=port, debug=False)
