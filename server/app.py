# Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
# Date: 2026-03-11 13:47
# PURPOSE: Flask server for ARC-AGI-3 web player. Responsibilities: static file serving,
#   session persistence (save/resume/branch via SQLite), game step proxying, model registry
#   API (/api/llm/models), Cloudflare Workers AI proxy (/api/llm/cf-proxy), observatory,
#   share/replay, admin, and auth endpoints. All LLM orchestration runs CLIENT-SIDE.
#   Phase 2 refactor extracted bot_protection.py, grid_analysis.py, prompt_builder.py,
#   session_manager.py, and constants.py — server.py imports from those modules.
# SRP/DRY check: Pass — model registry in models.py, grid analysis in grid_analysis.py,
#   prompts in prompt_builder.py, sessions in session_manager.py, bot protection in
#   bot_protection.py, DB ops in db.py; server.py is the Flask glue layer only
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
import subprocess
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
from flask import Flask, Response, abort, jsonify, make_response, render_template, request, session as flask_session

import arc_agi
from arcengine import GameAction, GameState

_ROOT = Path(__file__).parent.parent  # project root (one level up from server/)
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
load_dotenv(_ROOT / ".env")

# Model registry and LLM providers extracted to separate modules
from models import (
    MODEL_REGISTRY, DEFAULT_MODEL, SYSTEM_MSG, THINKING_BUDGETS,
    OLLAMA_VRAM, OLLAMA_VISION_MODELS, _discovered_local_models,
)
from llm_providers import (
    _route_model_call, _get_or_create_gemini_cache,
    _execute_python, _cleanup_tool_session,
    PROVIDER_MIN_DELAY,
)
import llm_providers
from constants import COLOR_MAP, COLOR_NAMES, ACTION_NAMES, ARC_AGI3_DESCRIPTION
from grid_analysis import (
    compress_row,
    compute_change_map,
    compute_color_histogram,
    compute_region_map,
)
from prompt_builder import (
    _build_prompt_parts,
    _build_prompt,
    _parse_llm_response,
    _extract_json,
)
from bot_protection import (
    TURNSTILE_SITE_KEY, TURNSTILE_SECRET_KEY,
    TURNSTILE_TOKEN_TTL,
    _rate_buckets, _rate_lock, RATE_LIMIT, RATE_WINDOW,
    _verified_tokens, _token_lock,
    _get_client_ip, _is_bot_ua, _check_rate_limit,
    _verify_turnstile_token, _is_turnstile_verified,
    bot_protection, turnstile_required,
)
from session_manager import (
    game_sessions, session_grids, session_snapshots,
    session_api_mode, session_api_keys,
    session_lock, session_step_counts, session_last_llm,
    _reconstruct_session, _try_recover_session, _action_dict_from_row,
)

# Phase 14: Service layer imports
from server.services import auth_service, game_service, session_service, social_service

app = Flask(__name__,
            template_folder=str(_ROOT / "templates"),
            static_folder=str(_ROOT / "static"))
app.config["TEMPLATES_AUTO_RELOAD"] = True
# Stable secret key — needed for Flask session (Google OAuth CSRF state).
# Derive from GOOGLE_CLIENT_SECRET or env var so all gunicorn workers share the same key.
app.secret_key = os.environ.get("FLASK_SECRET_KEY",
                                 os.environ.get("GOOGLE_CLIENT_SECRET", "arc-dev-fallback-key"))
_STATIC_VERSION = str(int(time.time()))  # cache-bust static files on each deploy
app.logger.setLevel(logging.INFO)

# ═══════════════════════════════════════════════════════════════════════════
# BLUEPRINT REGISTRATION — Phase 10 modularization
# ═══════════════════════════════════════════════════════════════════════════
# NOTE: Route handlers remain in app.py for now (Phase 11 extraction).
# Blueprints registered below but empty. Handlers will be moved in Phase 11.

try:
    from server.auth_routes import auth_bp
    from server.game_routes import game_bp
    from server.session_routes import session_bp
    from server.social_routes import social_bp
    from server.llm_admin_routes import llm_admin_bp
    # app.register_blueprint(auth_bp)
    # app.register_blueprint(game_bp)
    # app.register_blueprint(session_bp)
    # app.register_blueprint(social_bp)
    # app.register_blueprint(llm_admin_bp)
except ImportError as e:
    app.logger.warning(f'Blueprint registration skipped: {e}')


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
HIDDEN_GAMES = ["ab", "fd", "fy", "pt", "sh"]

DEV_SECRET = os.environ.get("DEV_SECRET", "arc-dev-2026")

# Will be set by CLI args; default to staging
_server_mode = "staging"
_server_port_staging = 5000
_server_port_prod = 5001


# ═══════════════════════════════════════════════════════════════════════════
# HELPERS — imported from server.helpers module
# ═══════════════════════════════════════════════════════════════════════════

from server.helpers import (
    get_mode, feature_enabled, get_enabled_features, get_arcade, get_game_version,
    frame_to_grid, env_state_dict, _load_prompts, FEATURES, HIDDEN_GAMES, get_current_user
)

# Service layer imports (Phase 14 refactor)
from server.services import auth_service, game_service, session_service, social_service

# Database layer imports (kept for routes that call db directly for now)
from db import (
    _init_db, _get_db, db_conn,
    create_magic_link, verify_magic_link, count_recent_magic_links,
    find_or_create_user, create_auth_token, delete_auth_token, claim_sessions,
    _db_insert_session, _db_update_session, _db_insert_action,
    AUTH_TOKEN_TTL, DB_PATH,
)

# Configuration from environment
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY", "")
RESEND_FROM = os.environ.get("RESEND_FROM", "noreply@example.com")
UMAMI_URL = os.environ.get("UMAMI_URL", "")
UMAMI_WEBSITE_ID = os.environ.get("UMAMI_WEBSITE_ID", "")

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
            # Prod: no cache — force fresh files after every deploy
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


@app.route("/games/ab")
def game_ab():
    return render_template("ab01.html")


@app.route("/arena")
def arena():
    return render_template("arena.html", static_v=_STATIC_VERSION)


@app.route("/")
def root_redirect():
    from flask import redirect
    return redirect("/obs#human", code=302)


@app.route("/obs")
@bot_protection
def index():
    mode = get_mode()
    features = get_enabled_features()
    ts_key = TURNSTILE_SITE_KEY if mode == "prod" else ""
    return render_template("index.html", color_map=COLOR_MAP,
                           turnstile_site_key=ts_key,
                           mode=mode, features=features,
                           umami_url=UMAMI_URL, umami_website_id=UMAMI_WEBSITE_ID,
                           google_client_id=GOOGLE_CLIENT_ID,
                           prompts=_load_prompts(),
                           static_v=_STATIC_VERSION)


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
    
    # Use auth_service to validate and create magic link
    code, error_msg = auth_service.initiate_magic_link(email)
    if error_msg:
        status_code = 429 if "Too many requests" in error_msg else 400
        return jsonify({"error": error_msg}), status_code
    
    if not code:
        return jsonify({"error": "Service unavailable"}), 503
    
    # Send email via Resend
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
    
    # Use auth_service to verify and login
    auth_info, error_msg = auth_service.verify_and_login(code)
    if error_msg or not auth_info:
        return error_msg or "Service unavailable", 400 if error_msg else 503
    
    token = auth_info["token"]
    resp = make_response("")
    resp.headers["Location"] = "/?logged_in=1"
    resp.status_code = 302
    resp.set_cookie("arc_auth", token,
                     max_age=auth_info["ttl"], httponly=True,
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
        # Use auth_service to logout
        auth_service.logout(token)
        _auth_cache.pop(token, None)
    resp = make_response(jsonify({"status": "ok"}))
    resp.delete_cookie("arc_auth")
    return resp


@app.route("/api/auth/google")
def auth_google_redirect():
    """Redirect to Google OAuth consent screen."""
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return "Google login not configured", 503
    # Use HTTPS in production (Railway terminates SSL at proxy)
    base_url = request.host_url.rstrip("/").replace("http://", "https://", 1)
    redirect_uri = f"{base_url}/api/auth/google/callback"
    # Generate state token to prevent CSRF
    state = secrets.token_urlsafe(32)

    flask_session["google_oauth_state"] = state
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "state": state,
        "prompt": "select_account",
    }
    from urllib.parse import urlencode
    qs = urlencode(params)
    return make_response("", 302, {"Location": f"https://accounts.google.com/o/oauth2/v2/auth?{qs}"})


@app.route("/api/auth/google/callback")
def auth_google_callback():
    """Handle Google OAuth callback — exchange code for tokens and log in."""
    error = request.args.get("error")
    if error:
        app.logger.warning(f"Google OAuth error: {error}")
        return f"Google login failed: {error}", 400
    code = request.args.get("code", "")
    state = request.args.get("state", "")
    if not code:
        return "Missing authorization code", 400
    
    # Verify state token (pop from session)
    expected_state = flask_session.pop("google_oauth_state", None)
    app.logger.info(f"[GOOGLE_AUTH] callback: code={code[:10]}... state_match={state == expected_state if expected_state else 'no_expected'}")
    
    # Call service to handle OAuth token exchange and user creation
    base_url = request.host_url.rstrip("/").replace("http://", "https://", 1)
    auth_info, error_msg = auth_service.google_callback(
        code, state, expected_state, base_url,
        GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET
    )
    if error_msg or not auth_info:
        return error_msg or "Service unavailable", 400 if "Invalid state" in (error_msg or "") else 503
    
    # Set cookie and redirect
    resp = make_response("", 302, {"Location": "/?logged_in=1"})
    # Note: secure=False behind proxy (Railway terminates SSL), but SameSite=Lax is sufficient
    resp.set_cookie("arc_auth", auth_info["token"],
                     max_age=auth_info["ttl"], httponly=True,
                     samesite="Lax", secure=False)
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
    # Limit to 100 at a time
    session_ids = session_ids[:100] if session_ids else []
    
    # Use session_service to claim sessions
    claimed, error_msg = session_service.claim_anonymous_sessions(user["id"], session_ids)
    if error_msg:
        return jsonify({"error": error_msg}), 400
    
    return jsonify({"status": "ok", "claimed": claimed})


@app.route("/api/games")
@bot_protection
@turnstile_required
def list_games():
    arc = get_arcade()
    envs = arc.get_environments()
    # Deduplicate: prefer short IDs (ls20) over old hash IDs (ls20-cb3b57cc),
    # and for observatory games (2-letter dir), keep only the latest version (ac02 > ac01).
    seen = {}
    for e in envs:
        short = e.game_id.split("-")[0]
        prefix = short[:2]
        # Observatory games share a 2-letter directory; group by prefix, keep highest version
        if len(short) == 4 and short[2:].isdigit() and Path(f"environment_files/{prefix}").is_dir():
            key = prefix
        else:
            key = short
        if key not in seen or len(e.game_id) < len(seen[key].game_id) or \
                (len(e.game_id) == len(seen[key].game_id) and e.game_id > seen[key].game_id) or \
                (e.game_id == seen[key].game_id and e.local_dir > seen[key].local_dir):
            seen[key] = e
    games = [
        {"game_id": e.game_id, "title": e.title, "default_fps": e.default_fps,
         "tags": getattr(e, 'tags', [])}
        for e in seen.values()
    ]
    # In prod mode, hide non-foundation games unless ?show_all=1
    if get_mode() == "prod" and request.args.get("show_all") != "1":
        games = [g for g in games if g["game_id"][:2] not in HIDDEN_GAMES]
    return jsonify(games)


@app.route("/api/games/<game_id>/source")
@bot_protection
@turnstile_required
def game_source(game_id):
    """Return the Python source code for a game (for Pyodide client-side execution)."""
    arc = get_arcade()
    envs = arc.get_environments()
    bare_id = game_id.split("-")[0]
    matching = [e for e in envs if e.game_id == game_id or e.game_id == bare_id]
    env_info = max(matching, key=lambda e: e.local_dir) if matching else None
    if env_info is None:
        return jsonify({"error": f"Game {game_id} not found"}), 404
    local_dir = Path(env_info.local_dir)
    # .py file is named after the canonical game_id (e.g. lb03.py, ls20.py, ft09.py)
    canonical_id = env_info.game_id.split("-")[0]
    py_file = local_dir / f"{canonical_id}.py"
    if not py_file.exists():
        return jsonify({"error": f"Source file not found for {game_id}"}), 404
    source = py_file.read_text(encoding="utf-8")
    return jsonify({
        "source": source,
        "class_name": env_info.class_name,
        "game_id": env_info.game_id,
        "default_fps": env_info.default_fps,
        "version": get_game_version(env_info.game_id),
    })


@app.route("/api/start", methods=["POST"])
@bot_protection
@turnstile_required
def start_game():
    data = request.get_json(force=True)
    result, status = game_service.start(
        data,
        get_arcade_fn=get_arcade,
        env_state_dict_fn=env_state_dict,
        session_lock=session_lock,
        game_sessions=game_sessions,
        session_grids=session_grids,
        session_snapshots=session_snapshots,
        session_step_counts=session_step_counts,
        feature_enabled_fn=feature_enabled,
        _db_insert_session_fn=_db_insert_session,
        get_current_user_fn=get_current_user,
        get_mode_fn=get_mode,
        _cleanup_tool_session_fn=_cleanup_tool_session,
    )
    return jsonify(result), status


@app.route("/api/step", methods=["POST"])
@bot_protection
@turnstile_required
def step_game():
    payload = request.get_json(force=True)
    result, status = game_service.step(
        payload,
        get_arcade_fn=get_arcade,
        env_state_dict_fn=env_state_dict,
        session_lock=session_lock,
        game_sessions=game_sessions,
        session_grids=session_grids,
        session_snapshots=session_snapshots,
        session_step_counts=session_step_counts,
        session_last_llm=session_last_llm,
        _try_recover_session_fn=_try_recover_session,
        compute_change_map_fn=compute_change_map,
        feature_enabled_fn=feature_enabled,
        _db_insert_action_fn=_db_insert_action,
        _db_update_session_fn=_db_update_session,
        _compress_grid_fn=_compress_grid,
    )
    return jsonify(result), status


@app.route("/api/reset", methods=["POST"])
@bot_protection
@turnstile_required
def reset_game():
    payload = request.get_json(force=True)
    result, status = game_service.reset(
        payload,
        env_state_dict_fn=env_state_dict,
        session_lock=session_lock,
        game_sessions=game_sessions,
        session_grids=session_grids,
        _try_recover_session_fn=_try_recover_session,
        get_arcade_fn=get_arcade,
    )
    return jsonify(result), status


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


@app.route("/api/llm/lmstudio-proxy", methods=["POST"])
@bot_protection
@turnstile_required
def lmstudio_proxy():
    """CORS proxy for LM Studio — browser can't call localhost:1234 directly due to
    missing Access-Control-Allow-Origin headers. Same pattern as cf_proxy below.
    In staging mode the server and LM Studio share the same machine, so server-to-server
    HTTP works. In prod (Railway) the server can't reach the user's localhost:1234 —
    user must enable CORS in LM Studio settings for that scenario."""
    import httpx as _hx
    body = request.get_json(force=True) or {}
    model = body.get("model", "")
    messages = body.get("messages", [])
    max_tokens = min(int(body.get("max_tokens", 16384)), 65536)
    temperature = float(body.get("temperature", 0.3))
    base_url = body.get("base_url", "http://localhost:1234")
    if not model:
        return jsonify({"error": "model is required"}), 400
    try:
        url = base_url.rstrip("/") + "/v1/chat/completions"
        resp = _hx.post(
            url,
            headers={"Content-Type": "application/json"},
            json={
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": False,
            },
            timeout=600.0,
        )
        # Forward the actual LM Studio response body and status — don't swallow error
        # details with raise_for_status() (e.g. "No user query found in messages").
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 502


@app.route("/api/llm/anthropic-proxy", methods=["POST"])
@bot_protection
@turnstile_required
def anthropic_proxy():
    """CORS proxy for Anthropic OAuth tokens — browser can't send Authorization: Bearer
    to api.anthropic.com directly because the preflight OPTIONS fails (Anthropic only
    allows direct browser access via x-api-key + anthropic-dangerous-direct-browser-access).
    OAuth tokens (sk-ant-oat*) require Bearer auth, so we proxy server-to-server."""
    import httpx as _hx
    body = request.get_json(force=True) or {}
    api_key = body.pop("api_key", "")
    if not api_key or not api_key.startswith("sk-ant-oat"):
        return jsonify({"error": "This proxy is for OAuth tokens (sk-ant-oat*) only"}), 400
    if not body.get("model"):
        return jsonify({"error": "model is required"}), 400
    try:
        resp = _hx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Authorization": f"Bearer {api_key}",
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "oauth-2025-04-20",
                "content-type": "application/json",
                "User-Agent": "sonpham-arc3/1.2.8 (ARC Prize research; https://three.arcprize.org; https://arc.markbarney.net; https://arc3.sonpham.net; contact mark@markbarney.net)",
            },
            json={**body, "metadata": {"user_id": "arc-prize-research"}},
            timeout=120.0,
        )
        return jsonify(resp.json()), resp.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 502


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
    from server.services import llm_admin_service
    result = llm_admin_service.get_models(request.args)
    return jsonify(result)



# LLM routes removed — all LLM calls are now client-side (BYOK/Puter.js)
# Kept: /api/llm/models (model registry, no LLM call)


@app.route("/api/undo", methods=["POST"])
@bot_protection
@turnstile_required
def undo_step():
    payload = request.get_json(force=True)
    result, status = game_service.undo(
        payload,
        env_state_dict_fn=env_state_dict,
        session_lock=session_lock,
        game_sessions=game_sessions,
        session_grids=session_grids,
        session_snapshots=session_snapshots,
        _try_recover_session_fn=_try_recover_session,
        get_arcade_fn=get_arcade,
        feature_enabled_fn=feature_enabled,
        db_conn_fn=db_conn,
    )
    return jsonify(result), status


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

@app.route("/api/copilot/auth/start", methods=["POST"])
@bot_protection
@turnstile_required
def copilot_auth_start():
    if not feature_enabled("copilot"):
        return jsonify({"error": "Copilot not available in this mode"}), 403
    
    # Use auth_service for business logic
    result, error_msg = auth_service.copilot_auth_start()
    if error_msg or not result:
        return jsonify({"error": error_msg or "Service unavailable"}), 500
    return jsonify(result)


@app.route("/api/copilot/auth/poll", methods=["POST"])
@bot_protection
@turnstile_required
def copilot_auth_poll():
    if not feature_enabled("copilot"):
        return jsonify({"error": "Copilot not available in this mode"}), 403
    
    # Use auth_service for business logic
    result, error_msg = auth_service.copilot_auth_poll()
    if error_msg and not result:
        return jsonify({"error": error_msg}), 400 if "No pending" in error_msg else 500
    # result may be {"status": "pending"}, {"status": "authenticated"}, etc.
    return jsonify(result or {"error": error_msg})


@app.route("/api/copilot/auth/status")
@bot_protection
@turnstile_required
def copilot_auth_status():
    if not feature_enabled("copilot"):
        return jsonify({"available": False, "reason": "online_mode"})
    
    # Use auth_service for business logic
    result, _ = auth_service.copilot_auth_status()
    return jsonify(result)


# ═══════════════════════════════════════════════════════════════════════════
# CLAUDE CODE AUTH ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════


@app.route("/api/claude/auth/status")
@bot_protection
def claude_auth_status():
    """Check whether an Anthropic API key is configured (env or session)."""
    # Use auth_service for business logic
    result, _ = auth_service.claude_auth_status()
    return jsonify(result)


@app.route("/api/claude/auth/set-key", methods=["POST"])
@bot_protection
def claude_set_key():
    """Allow the user to supply their own Anthropic API key for this session."""
    data = request.get_json() or {}
    api_key = data.get("api_key", "")
    
    # Use auth_service for validation and setting
    result, error_msg = auth_service.claude_set_key(api_key)
    if error_msg:
        return jsonify(result), 400
    return jsonify(result)


# ═══════════════════════════════════════════════════════════════════════════
# OPENAI / CODEX AUTH ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════


@app.route("/api/openai/auth/status")
@bot_protection
def openai_auth_status():
    """Check whether an OpenAI API key is configured (env or session)."""
    # Use auth_service for business logic
    result, _ = auth_service.openai_auth_status()
    return jsonify(result)


@app.route("/api/openai/auth/set-key", methods=["POST"])
@bot_protection
def openai_set_key():
    """Allow the user to supply their own OpenAI API key for this session."""
    data = request.get_json() or {}
    api_key = data.get("api_key", "")
    
    # Use auth_service for validation and setting
    result, error_msg = auth_service.openai_set_key(api_key)
    if error_msg:
        return jsonify(result), 400
    return jsonify(result)


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
    """Import/upsert a session and its steps. Thin HTTP wrapper — logic in session_service."""
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
    
    user = get_current_user()
    user_id = sess.get("user_id") if sess else None
    if not user_id and user:
        user_id = user["id"]
    
    # Call session_service to do the import
    result, error_msg = session_service.import_session(sess, steps, user_id, get_mode())
    if error_msg:
        status_code = 400 if "required" in error_msg else 413 if "too short" in error_msg.lower() else 500
        return _cors_resp({"error": error_msg, "skipped": result.get("skipped", False)}, status_code)
    
    return _cors_resp(result, 200)


@app.route("/api/sessions/resume", methods=["POST"])
@bot_protection
@turnstile_required
def resume_session():
    """Resume an unfinished session. Thin HTTP wrapper — logic in session_service."""
    if not feature_enabled("session_db"):
        return jsonify({"error": "Session DB not enabled"}), 400
    
    payload = request.get_json(force=True)
    session_id = payload.get("session_id")
    if not session_id:
        return jsonify({"error": "session_id required"}), 400
    
    # Call session_service to resume
    state, error_msg = session_service.resume(
        session_id,
        get_arcade_fn=get_arcade,
        env_state_dict_fn=env_state_dict,
        format_action_row_fn=_format_action_row,
    )
    
    if error_msg:
        status_code = 404 if "not found" in error_msg.lower() else 500
        return jsonify({"error": error_msg}), status_code
    
    return jsonify(state)


@app.route("/api/sessions/<session_id>/event", methods=["POST"])
@bot_protection
def log_session_event(session_id):
    """Log a session event (compact, branch, resume). Deprecated — session_events table removed."""
    # session_events table has been removed; return OK for backward compat
    return jsonify({"status": "ok"})


@app.route("/api/sessions/<session_id>/obs-events", methods=["GET", "POST"])
@bot_protection
def session_obs_events(session_id):
    """GET: reconstruct obs events for replay. POST: no-op (obs_events table removed)."""
    if request.method == "POST":
        payload = request.get_json(force=True)
        cursor = payload.get("cursor", 0)
        events = payload.get("events", [])
        result, error_msg = session_service.obs_events_handle_post(cursor, events)
        if error_msg:
            return jsonify({"error": error_msg}), 500
        return jsonify(result)

    # GET — reconstruct events from llm_calls + session_actions
    result, error_msg = session_service.obs_events_get(session_id)
    if error_msg:
        return jsonify({"error": error_msg}), 500
    return jsonify(result)


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
    """Branch a session at a given step. Thin HTTP wrapper — logic in session_service."""
    if not feature_enabled("session_db"):
        return jsonify({"error": "Session DB not enabled"}), 400
    
    payload = request.get_json(force=True)
    parent_id = payload.get("parent_session_id")
    step_num = payload.get("step_num")
    if not parent_id or step_num is None:
        return jsonify({"error": "parent_session_id and step_num required"}), 400
    
    # Call session_service to branch
    state, error_msg = session_service.branch(
        parent_id, step_num, get_mode(),
        get_arcade_fn=get_arcade,
        env_state_dict_fn=env_state_dict,
        format_action_row_fn=_format_action_row,
    )
    
    if error_msg:
        status_code = 404 if "not found" in error_msg.lower() else 500
        return jsonify({"error": error_msg}), status_code
    
    return jsonify(state)


# ═══════════════════════════════════════════════════════════════════════════
# SESSION HISTORY ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/sessions")
@bot_protection
@turnstile_required
def list_sessions():
    """List recent sessions (last 100).
    Query params: player_type=agent|human, mine=1 (only current user's sessions).
    """
    if not feature_enabled("session_db"):
        return jsonify({"sessions": []})
    try:
        player_type_filter = request.args.get("player_type")
        mine_only = request.args.get("mine") == "1"

        # If mine=1, return only the authenticated user's sessions
        if mine_only:
            user = get_current_user()
            if not user:
                return jsonify({"sessions": [], "error": "Not authenticated"}), 401
            user_sessions = get_user_sessions(user["id"])
            if player_type_filter:
                user_sessions = [s for s in user_sessions if s.get("player_type") == player_type_filter]
            return jsonify({"sessions": user_sessions})

        _sessions_query = (
            "SELECT s.id, s.game_id, s.model, s.mode, s.created_at, s.result, s.steps, s.levels, "
            "s.parent_session_id, s.branch_at_step, s.total_cost, s.player_type, s.duration_seconds, "
            "s.live_mode, s.live_fps, s.game_version, "
            "(SELECT MAX(st.timestamp) - MIN(st.timestamp) FROM session_actions st WHERE st.session_id = s.id) AS duration "
            "FROM sessions s "
        )
        _params = ()
        if player_type_filter:
            _sessions_query += "WHERE s.player_type = ? "
            _params = (player_type_filter,)
        _sessions_query += "ORDER BY s.created_at DESC LIMIT 100"
        conn = _get_db()
        rows = conn.execute(_sessions_query, _params).fetchall()
        conn.close()
        sessions = [dict(r) for r in rows]
        return jsonify({"sessions": sessions})
    except Exception as e:
        return jsonify({"sessions": [], "error": str(e)})


@app.route("/api/leaderboard")
@bot_protection
def leaderboard():
    """Return best AI and human sessions per game for leaderboard display."""
    result, status = social_service.get_leaderboard(get_db_fn=_get_db)
    return jsonify(result), status


@app.route("/api/leaderboard/<game_id>")
@bot_protection
def leaderboard_detail(game_id):
    """Return top AI and human attempts for a specific game."""
    result, status = social_service.get_leaderboard_detail(game_id, get_db_fn=_get_db)
    return jsonify(result), status


# ── Comments API ─────────────────────────────────────────────────────────

@app.route("/api/comments/<game_id>")
def get_comments(game_id):
    """Get comments for a game."""
    voter_id = request.args.get("voter_id", "")
    result, status = social_service.get_comments(game_id, voter_id=voter_id, get_db_fn=_get_db)
    return jsonify(result), status


@app.route("/api/comments", methods=["POST"])
def post_comment():
    """Post a new comment on a game."""
    data = request.json or {}
    result, status = social_service.post_comment(data, get_db_fn=_get_db)
    return jsonify(result), status


@app.route("/api/comments/<int:comment_id>/vote", methods=["POST"])
def vote_comment(comment_id):
    """Upvote or downvote a comment. vote: 1, -1, or 0 (remove)."""
    data = request.json or {}
    voter_id = data.get("voter_id", "").strip()
    vote = data.get("vote", 0)
    result, status = social_service.vote_comment(comment_id, voter_id, vote, get_db_fn=_get_db)
    return jsonify(result), status


@app.route("/api/contributors")
def contributors():
    """Top contributors: most comments, most human sessions, most AI sessions."""
    result, status = social_service.get_contributors(get_db_fn=_get_db)
    return jsonify(result), status


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


def _format_action_row(d: dict) -> dict:
    """Decompress grid from states_json and format an action row dict for API responses."""
    if d.get("states_json"):
        try:
            states = json.loads(d["states_json"])
            if states and isinstance(states, list) and states[0].get("grid"):
                d["grid"] = _decompress_grid(states[0]["grid"])
            else:
                d["grid"] = None
        except Exception:
            d["grid"] = None
        del d["states_json"]
    # Reconstruct data dict from row/col for backward compat
    if d.get("row") is not None and d.get("col") is not None:
        d["data"] = {"x": d["col"], "y": d["row"]}
    else:
        d["data"] = {}
    return d


# Keep old name as alias for any remaining callers
_format_step_row = _format_action_row


@app.route("/api/sessions/<session_id>")
@bot_protection
@turnstile_required
def get_session(session_id):
    """Get full session with all steps and decompressed grids.
    Tries local SQLite first, falls back to per-session file."""
    if not feature_enabled("session_db"):
        return jsonify({"error": "Session DB not enabled"}), 404
    try:
        sess_dict = None
        step_list = []

        # Try local SQLite first
        conn = _get_db()
        sess = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        if sess:
            action_rows = conn.execute(
                "SELECT * FROM session_actions WHERE session_id = ? ORDER BY step_num",
                (session_id,),
            ).fetchall()
            conn.close()
            sess_dict = dict(sess)
            for s in action_rows:
                step_list.append(_format_action_row(dict(s)))
        else:
            conn.close()

        # Fall back to per-session file
        if not sess_dict:
            file_data = _read_session_from_file(session_id)
            if file_data:
                sess_dict = file_data["session"]
                for s in file_data.get("actions", file_data.get("steps", [])):
                    step_list.append(_format_action_row(s))

        if not sess_dict:
            return jsonify({"error": "Session not found"}), 404

        return jsonify({"session": sess_dict, "steps": step_list})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sessions/<session_id>/step/<int:step_num>")
@bot_protection
@turnstile_required
def get_session_step(session_id, step_num):
    """Get a single action from a session."""
    if not feature_enabled("session_db"):
        return jsonify({"error": "Session DB not enabled"}), 404
    try:
        conn = _get_db()
        row = conn.execute(
            "SELECT * FROM session_actions WHERE session_id = ? AND step_num = ?",
            (session_id, step_num),
        ).fetchone()
        conn.close()
        if not row:
            return jsonify({"error": "Step not found"}), 404
        d = _format_action_row(dict(row))
        return jsonify(d)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════
# MEMORY SNAPSHOTS — agent memory inspection API
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/sessions/<session_id>/memory")
@bot_protection
def session_memory(session_id):
    """Return all memory snapshots for a session."""
    from db_memory import get_session_memory_snapshots
    snapshots = get_session_memory_snapshots(session_id)
    return jsonify({"snapshots": snapshots})


@app.route("/api/sessions/<session_id>/memory/<int:step_num>")
@bot_protection
def session_memory_at_step(session_id, step_num):
    """Return memory snapshots at a specific step."""
    from db_memory import get_memory_at_step
    snapshots = get_memory_at_step(session_id, step_num)
    return jsonify({"snapshots": snapshots})


@app.route("/api/sessions/<session_id>/memory", methods=["POST"])
@bot_protection
def save_session_memory(session_id):
    """Save memory snapshots for a session (bulk)."""
    from db_memory import bulk_save_memory_snapshots
    payload = request.get_json(force=True)
    snapshots = payload.get("snapshots", [])
    count = bulk_save_memory_snapshots(session_id, snapshots)
    return jsonify({"status": "ok", "saved": count})


# ═══════════════════════════════════════════════════════════════════════════
# LLM CALL LOG — universal call log API
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/api/sessions/<session_id>/calls")
def session_calls(session_id):
    """Return all LLM calls for a session, ordered by timestamp."""
    calls = _get_session_calls(session_id)
    # Parse output_json back from string
    for c in calls:
        if c.get("output_json"):
            try:
                c["output_json"] = json.loads(c["output_json"])
            except (json.JSONDecodeError, TypeError):
                pass
    return jsonify(calls)


# ═══════════════════════════════════════════════════════════════════════════
# SHARE — public replay page
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/share/<session_id>")
@app.route("/share")
def share_session(session_id=None):
    """Public replay page. Human sessions get a simplified viewer; agent sessions get the full observatory.
    Supports both /share/<id> and /share?id=<id> for shareable links.
    Without an ID, shows the session browser."""
    if session_id is None:
        session_id = request.args.get("id")
    if session_id is None:
        return render_template("obs.html", share_session_id="", browse_mode=True)

    # Look up session metadata
    sess_row = None
    file_data = None
    try:
        conn = _get_db()
        sess_row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        conn.close()
    except Exception:
        pass
    if not sess_row:
        file_data = _read_session_from_file(session_id)

    if not sess_row and not file_data:
        return """<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Session Not Found</title>
<style>body{background:#0d1117;color:#c9d1d9;font-family:'Courier New',monospace;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;}
.box{text-align:center;padding:40px;border:1px solid #30363d;border-radius:12px;background:#161b22;max-width:400px;}
h1{color:#f85149;font-size:24px;margin-bottom:12px;}p{color:#8b949e;margin-bottom:20px;}
a{color:#58a6ff;text-decoration:none;}a:hover{text-decoration:underline;}</style></head>
<body><div class="box"><h1>Session Not Found</h1><p>This session doesn't exist or hasn't been shared yet.</p>
<a href="/share">&#9654; Browse Sessions</a></div></body></html>""", 404

    # Determine player type
    player_type = None
    if sess_row:
        player_type = dict(sess_row).get("player_type")
    elif file_data:
        player_type = file_data.get("session", {}).get("player_type")

    # Human sessions → simplified share page with server-rendered data
    if player_type == "human":
        sess_dict = dict(sess_row) if sess_row else file_data.get("session", {})
        step_list = []
        try:
            if sess_row:
                conn = _get_db()
                rows = conn.execute(
                    "SELECT * FROM session_actions WHERE session_id = ? ORDER BY step_num",
                    (session_id,),
                ).fetchall()
                conn.close()
                step_list = [_format_action_row(dict(r)) for r in rows]
            elif file_data:
                for s in file_data.get("actions", file_data.get("steps", [])):
                    step_list.append(_format_action_row(s))
        except Exception:
            pass
        return render_template("share.html",
                               session=sess_dict, steps=step_list,
                               color_map=COLOR_MAP,
                               umami_url=UMAMI_URL, umami_website_id=UMAMI_WEBSITE_ID)

    # Agent sessions → full observatory view
    return render_template("obs.html", share_session_id=session_id)


@app.route("/api/sessions/public")
def list_public_sessions():
    """List sessions available for public replay (no auth required).
    Returns lightweight metadata only — no grid data."""
    try:
        conn = _get_db()
        rows = conn.execute("""
            SELECT s.id, s.game_id, s.model, s.mode, s.created_at, s.result,
                   s.steps, s.levels, s.player_type, s.duration_seconds,
                   s.live_mode, s.live_fps
            FROM sessions s
            WHERE s.steps > 0
            ORDER BY s.created_at DESC
            LIMIT 200
        """).fetchall()
        conn.close()
        sessions = [dict(r) for r in rows]
        return jsonify({"sessions": sessions})
    except Exception as e:
        return jsonify({"sessions": [], "error": str(e)})


# ═══════════════════════════════════════════════════════════════════════════
# SCENE EDITOR — fd pixel editor
# ═══════════════════════════════════════════════════════════════════════════

import importlib.util as _importlib_util
import numpy as _np

_FD_PATH = _ROOT / "environment_files" / "fd" / "00000001" / "fd.py"
_CUSTOM_SCENES_FILE = _ROOT / "environment_files" / "fd" / "00000001" / "custom_scenes.json"
_CUSTOM_DIFFS_FILE  = _ROOT / "environment_files" / "fd" / "00000001" / "custom_diffs.json"


def _load_fd_module():
    """Import fd.py as a module to access its draw functions and constants."""
    spec = _importlib_util.spec_from_file_location("fd_editor", str(_FD_PATH))
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
    fd_mod = _load_fd_module()
    custom_scenes = _read_custom_scenes()
    custom_diffs  = _read_custom_diffs()

    if str(level) in custom_scenes:
        pixels = custom_scenes[str(level)]
        is_custom_scene = True
    else:
        img = _np.zeros((fd_mod.IMG_H, fd_mod.IMG_W), dtype=_np.int16)
        fd_mod.SCENES[level](img)
        pixels = img.tolist()
        is_custom_scene = False

    if str(level) in custom_diffs:
        diffs = custom_diffs[str(level)]
        is_custom_diffs = True
    else:
        diffs = _builtin_diffs_to_rects(fd_mod.DIFFS[level])
        is_custom_diffs = False

    return jsonify({"pixels": pixels, "width": fd_mod.IMG_W, "height": fd_mod.IMG_H,
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
    from models import MODELS

    data = request.get_json(force=True)
    games = data.get("games", [])
    model = data.get("model")
    concurrency = data.get("concurrency", 4)
    max_steps = data.get("max_steps", 200)
    repeat = data.get("repeat", 1)
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

    # Log game versions
    arc = get_arcade()
    for e in arc.get_environments():
        v = get_game_version(e.game_id)
        print(f"  Game {e.game_id}: v{v}")

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
