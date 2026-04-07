# Author: Claude Opus 4.6
# Date: 2026-04-06 23:10
# PURPOSE: Shared helper functions for Flask blueprints. Provides mode detection,
#   feature flags, arcade instance management, game version resolution, frame-to-grid
#   conversion, env state serialization, prompt loading, auth caching, and on-demand
#   game download via ensure_game_local() (used by list_games and game_source to
#   bootstrap empty environment_files/ on cold start).
# SRP/DRY check: Pass — utility functions only; no business logic here.
"""Shared helper functions for Flask blueprints.

This module contains utility functions needed by multiple blueprints.
"""

import json
import logging
import os
import threading
import time
import subprocess
from pathlib import Path
from typing import Optional

import arc_agi
from flask import request

from server.state import arcade_instance, DEV_SECRET, FEATURES, HIDDEN_GAMES
from constants import ACTION_NAMES
from db import verify_auth_token

_log = logging.getLogger(__name__)


def get_mode() -> str:
    """Determine mode from SERVER_MODE env var or port the request arrived on."""
    env_mode = os.environ.get("SERVER_MODE", "")
    if env_mode in ("staging", "prod"):
        return env_mode
    if env_mode == "local":
        return "staging"
    if env_mode == "online":
        return "prod"
    try:
        port = int(request.environ.get("SERVER_PORT", 5000))
        if port == 5001:
            return "prod"
    except (ValueError, RuntimeError):
        pass
    return "staging"


def feature_enabled(name: str) -> bool:
    """Check if a feature is enabled for the current mode."""
    mode = get_mode()
    return FEATURES.get(name, {}).get(mode, False)


def get_enabled_features() -> dict[str, bool]:
    """Get all enabled features for the current mode."""
    mode = get_mode()
    return {name: feat.get(mode, False) for name, feat in FEATURES.items()}


def get_arcade():
    """Get or initialize the Arcade instance (lazy initialization)."""
    global arcade_instance
    if arcade_instance is None:
        arcade_instance = arc_agi.Arcade()
    return arcade_instance


# Per-game locks so concurrent requests for the same game don't double-download.
# Outer lock guards the dict itself.
_download_locks_dict_lock = threading.Lock()
_download_locks: dict[str, threading.Lock] = {}


def _get_download_lock(bare_id: str) -> threading.Lock:
    with _download_locks_dict_lock:
        lock = _download_locks.get(bare_id)
        if lock is None:
            lock = threading.Lock()
            _download_locks[bare_id] = lock
        return lock


def ensure_game_local(game_id: str):
    """Download a game into environment_files/ if it isn't already there.

    Returns the matching `EnvironmentInfo` (with `local_dir` populated) on
    success, or `None` if the download failed (e.g. unknown game id, network
    error). Idempotent and safe under concurrency: a per-game lock prevents
    two requests from racing the same download.

    The bug: after commit 779ddae gitignored `environment_files/`, fresh
    deploys (Railway included) start with no local game sources. Every
    `EnvironmentInfo` returned by `Arcade.get_environments()` has
    `local_dir=None`, so `list_games()` filters them all out and the
    Play-as-Human sidebar is empty. This helper materializes a game on
    demand using the existing `arc_agi.Arcade.make()` download path.
    """
    bare_id = game_id.split("-")[0]
    arc = get_arcade()

    # Fast path: already local — find the freshest local copy.
    def _find_local() -> Optional[arc_agi.EnvironmentInfo]:
        envs = arc.get_environments()
        candidates = [e for e in envs
                      if (e.game_id == game_id or e.game_id.split("-")[0] == bare_id)
                      and e.local_dir is not None]
        if not candidates:
            return None
        return max(candidates,
                   key=lambda e: (_env_date(e.local_dir), e.local_dir or ""))

    existing = _find_local()
    if existing is not None:
        return existing

    # Slow path: download under per-game lock.
    lock = _get_download_lock(bare_id)
    with lock:
        # Re-check inside the lock — another thread may have downloaded while
        # we were waiting.
        existing = _find_local()
        if existing is not None:
            return existing

        try:
            wrapper = arc.make(bare_id)
        except Exception as exc:
            _log.warning("ensure_game_local: arc.make(%s) raised: %s", bare_id, exc)
            return None
        if wrapper is None:
            _log.warning("ensure_game_local: arc.make(%s) returned None", bare_id)
            return None

        # arc.make() downloads the files but does not refresh the cached
        # EnvironmentInfo objects' local_dir. Force a rescan so the next
        # get_environments() call sees the freshly-downloaded directory.
        try:
            arc._scan_for_environments()
        except Exception as exc:
            _log.warning("ensure_game_local: rescan after %s download failed: %s",
                         bare_id, exc)

        result = _find_local()
        if result is None:
            _log.warning("ensure_game_local: %s downloaded but rescan found no local entry",
                         bare_id)
        else:
            _log.info("ensure_game_local: bootstrapped %s -> %s",
                      bare_id, result.local_dir)
        return result


def _env_date(local_dir: str | None) -> str:
    """Read date_downloaded from a game version directory's metadata.json.

    Returns an ISO date string (e.g. '2026-03-25') for use as a sort key.
    Returns '' if local_dir is None, missing, or unreadable — sorts last.
    """
    if not local_dir:
        return ""
    try:
        meta = Path(local_dir) / "metadata.json"
        if meta.exists():
            return json.loads(meta.read_text()).get("date_downloaded", "")
    except Exception:
        pass
    return ""


def get_game_version(game_id: str) -> str:
    """Return the latest version directory name for a game.

    Version directories are under environment_files/<game_dir>/<version>/
    where version is a zero-padded number (e.g. '00000014') or a commit hash
    (e.g. 'cb3b57cc'). Returns the directory with the newest date_downloaded in
    metadata.json; falls back to alphabetical-descending when dates are equal.
    """
    bare_id = game_id.split("-")[0]
    if not Path(f"environment_files/{bare_id}").is_dir():
        bare_id = bare_id[:2]
    game_dir = Path(f"environment_files/{bare_id}")
    if not game_dir.is_dir():
        return "unknown"
    try:
        dirs = [d for d in game_dir.iterdir() if d.is_dir()]
        if not dirs:
            return "unknown"
        dirs.sort(key=lambda d: (_env_date(str(d)) or d.name), reverse=True)
        return dirs[0].name
    except Exception:
        return "unknown"


def frame_to_grid(frame) -> list[list[int]]:
    """Convert frame to grid (nested list of ints)."""
    return frame.tolist()


def env_state_dict(env, frame_data=None) -> dict:
    """Build environment state dict for sending to client."""
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


def _load_prompts():
    """Load all prompt .txt files from prompts/ directory."""
    base = Path(__file__).parent.parent / "prompts"
    result = {}
    for section in sorted(base.iterdir()):
        if section.is_dir():
            result[section.name] = {
                f.stem: f.read_text() for f in sorted(section.glob("*.txt"))
            }
    return result


# ── Auth cache ─────────────────────────────────────────────────────────

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
    user = verify_auth_token(token)
    if user:
        _auth_cache[token] = (user, now + _AUTH_CACHE_TTL)
    else:
        _auth_cache.pop(token, None)
    return user
