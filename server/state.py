"""Shared in-memory state for the Flask application.

All mutable shared state lives here so Flask blueprints can import it
without circular dependencies.
"""

import threading
import time
from typing import Optional

import arc_agi

# ── Configuration ──────────────────────────────────────────────────────────
_STATIC_VERSION = None  # Set at app initialization
_server_mode = "staging"
_server_port_staging = 5000
_server_port_prod = 5001

# ── Feature flags ──────────────────────────────────────────────────────────
FEATURES = {
    "copilot":       {"staging": False,  "prod": False},
    "server_llm":    {"staging": False,  "prod": False},
    "puter_js":      {"staging": True,   "prod": True},
    "byok":          {"staging": True,   "prod": True},
    "session_db":    {"staging": True,   "prod": True},
    "memory_md":     {"staging": True,   "prod": False},
    "pyodide_game":  {"staging": True,   "prod": True},
}

HIDDEN_GAMES = ["ab", "fd", "fy", "pt", "sh"]

DEV_SECRET = None  # Set from env at startup

# ── Auth cache ─────────────────────────────────────────────────────────────
_auth_cache: dict[str, tuple[dict, float]] = {}  # token → (user_dict, cache_expiry)
_AUTH_CACHE_TTL = 300  # 5 minutes

# ── Arcade instance ────────────────────────────────────────────────────────
arcade_instance: Optional[arc_agi.Arcade] = None

# ── Custom prompts/memory ──────────────────────────────────────────────────
_custom_system_prompt: Optional[str] = None  # overrides ARC_AGI3_DESCRIPTION when set
_custom_hard_memory: Optional[str] = None    # extra agent memory injected into prompt

# ── Draw/FD environment ────────────────────────────────────────────────────
# Populated at import time
_FD_PATH = None  # Path to fd.py
_CUSTOM_SCENES_FILE = None  # Path to custom_scenes.json
_CUSTOM_DIFFS_FILE = None  # Path to custom_diffs.json
