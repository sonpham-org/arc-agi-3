# Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
# Date: 2026-03-11 13:47
# PURPOSE: Bot protection middleware for ARC-AGI-3 — Cloudflare Turnstile verification,
#   IP-based rate limiting, and user-agent filtering. Provides bot_protection() and
#   turnstile_required() decorators used by all API routes in server.py.
#   Extracted from server.py in Phase 2c. Uses stdlib logging (not Flask app.logger)
#   to avoid circular imports. get_mode() imported lazily inside decorator bodies.
# SRP/DRY check: Pass — all bot/rate/Turnstile logic consolidated here
"""Bot protection, rate limiting, and Turnstile verification for ARC-AGI-3.

Extracted from server.py (Phase 2c).

Circular import note: get_mode() is imported lazily inside decorator bodies
(not at module level) to avoid server.py → bot_protection.py → server.py cycle.
Flask app.logger is replaced with stdlib logging.
"""

import logging
import os
import threading
import time
from functools import wraps

import httpx as _httpx
from flask import abort, jsonify, request

log = logging.getLogger(__name__)

# ── Turnstile config ───────────────────────────────────────────────────────

TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY", "")
TURNSTILE_SECRET_KEY = os.environ.get("TURNSTILE_SECRET_KEY", "")

# ── Bot UA patterns ────────────────────────────────────────────────────────

BOT_UA_PATTERNS = [
    "bot", "crawler", "spider", "scraper", "wget", "curl", "python-requests",
    "httpx", "aiohttp", "go-http-client", "java/", "libwww", "headlesschrome",
    "phantomjs", "selenium", "puppeteer", "playwright", "mechanize", "scrapy",
    "chatgpt", "gptbot", "claude-web", "anthropic-ai", "bingbot", "googlebot",
    "baiduspider", "yandexbot", "duckduckbot", "facebookexternalhit",
    "twitterbot", "applebot", "semrushbot", "ahrefsbot", "mj12bot",
    "dotbot", "petalbot", "bytespider", "ccbot",
]

# ── Rate limiting state ────────────────────────────────────────────────────

_rate_buckets: dict[str, dict] = {}
_rate_lock = threading.Lock()
RATE_LIMIT = 60
RATE_WINDOW = 60

# ── Turnstile token cache ──────────────────────────────────────────────────

_verified_tokens: dict[str, float] = {}
_token_lock = threading.Lock()
TURNSTILE_TOKEN_TTL = 3600


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
        log.warning(f"Turnstile verification failed: {e}")
        return False


def _is_turnstile_verified() -> bool:
    from server import get_mode  # lazy import to avoid circular dep
    if get_mode() == "staging":
        return True
    if not TURNSTILE_SITE_KEY or not TURNSTILE_SECRET_KEY:
        return True
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
        from server import get_mode  # lazy import to avoid circular dep
        if get_mode() == "staging":
            return f(*args, **kwargs)
        ip = _get_client_ip()
        ua = request.headers.get("User-Agent", "")
        if _is_bot_ua(ua):
            log.info(f"Blocked bot UA from {ip}: {ua[:80]}")
            abort(403)
        if not _check_rate_limit(ip):
            log.info(f"Rate limited {ip}")
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
