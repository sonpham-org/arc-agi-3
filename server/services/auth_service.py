"""Authentication service layer — Magic link, OAuth, and LLM provider auth.

Orchestrates user auth, magic links, token management, and LLM provider credentials.
Pure business logic — Flask context (g, session, request) available inside request context.

Note: Most user auth functions are imported directly from db_auth.
This module adds validation, orchestration, and LLM provider auth logic on top.
"""

import logging
import os

import httpx

import llm_providers
from db_auth import (
    find_or_create_user,
    create_auth_token,
    verify_auth_token,
    create_magic_link,
    verify_magic_link,
    delete_auth_token,
    count_recent_magic_links,
    AUTH_TOKEN_TTL,
    MAGIC_LINK_TTL,
)

log = logging.getLogger(__name__)

# GitHub Copilot OAuth client ID (hardcoded for GitHub app)
COPILOT_CLIENT_ID = "Iv1.b507a08c87ecfe98"


def validate_email(email: str) -> tuple[bool, str]:
    """Validate email format. Returns (is_valid, error_message)."""
    email = (email or "").lower().strip()
    if not email:
        return False, "Email required"
    if "@" not in email or "." not in email.split("@")[-1]:
        return False, "Valid email required"
    return True, ""


def check_magic_link_rate_limit(email: str, max_per_window: int = 3) -> tuple[bool, str]:
    """Check if email has exceeded magic link rate limit."""
    count = count_recent_magic_links(email, window=900)  # 15 minutes
    if count >= max_per_window:
        return False, "Too many requests. Please wait a few minutes."
    return True, ""


def initiate_magic_link(email: str) -> tuple[str | None, str]:
    """Create a magic link code for an email. Returns (code, error_msg)."""
    is_valid, error_msg = validate_email(email)
    if not is_valid:
        return None, error_msg
    
    is_allowed, rate_msg = check_magic_link_rate_limit(email)
    if not is_allowed:
        return None, rate_msg
    
    code = create_magic_link(email)
    if not code:
        return None, "Failed to create magic link"
    
    return code, ""


def verify_and_login(code: str) -> tuple[dict | None, str]:
    """Verify a magic link code and create an auth token. Returns (auth_info, error_msg)."""
    if not code:
        return None, "Code required"
    
    email = verify_magic_link(code)
    if not email:
        return None, "Invalid or expired link"
    
    user = find_or_create_user(email)
    if not user:
        return None, "Failed to create user"
    
    token = create_auth_token(user["id"])
    if not token:
        return None, "Failed to create token"
    
    return {"token": token, "user": user, "ttl": AUTH_TOKEN_TTL}, ""


def logout(token: str):
    """Invalidate an auth token."""
    if token:
        delete_auth_token(token)


def oauth_user_from_google(email: str, display_name: str = "", google_id: str = "") -> tuple[dict | None, str]:
    """Create/find user from Google OAuth and issue auth token. Returns (auth_info, error_msg)."""
    is_valid, error_msg = validate_email(email)
    if not is_valid:
        return None, error_msg
    
    user = find_or_create_user(email, display_name=display_name, google_id=google_id)
    if not user:
        return None, "Failed to create user"
    
    token = create_auth_token(user["id"])
    if not token:
        return None, "Failed to create token"
    
    return {"token": token, "user": user, "ttl": AUTH_TOKEN_TTL}, ""


# ═══════════════════════════════════════════════════════════════════════════
# COPILOT AUTH — GitHub device flow for Copilot access
# ═══════════════════════════════════════════════════════════════════════════

def copilot_auth_start() -> tuple[dict | None, str]:
    """Start GitHub device flow for Copilot OAuth. Returns (response_dict, error_msg)."""
    try:
        resp = httpx.post(
            "https://github.com/login/device/code",
            headers={"Accept": "application/json"},
            data={"client_id": COPILOT_CLIENT_ID, "scope": ""},
            timeout=30.0,
        )
        resp.raise_for_status()
        data = resp.json()
        with llm_providers.copilot_auth_lock:
            llm_providers.copilot_device_code = data.get("device_code")
        return {
            "user_code": data.get("user_code"),
            "verification_uri": data.get("verification_uri"),
            "expires_in": data.get("expires_in"),
            "interval": data.get("interval", 5),
        }, ""
    except Exception as e:
        log.warning(f"Copilot auth start failed: {e}")
        return None, str(e)


def copilot_auth_poll() -> tuple[dict | None, str]:
    """Poll GitHub for Copilot OAuth token. Returns (response_dict, error_msg)."""
    with llm_providers.copilot_auth_lock:
        dc = llm_providers.copilot_device_code
    
    if not dc:
        return None, "No pending auth. Call copilot_auth_start first."
    
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
            with llm_providers.copilot_auth_lock:
                llm_providers.copilot_oauth_token = data["access_token"]
                llm_providers.copilot_device_code = None
            llm_providers._save_copilot_token(llm_providers.copilot_oauth_token)
            return {"status": "authenticated"}, ""
        elif data.get("error") == "authorization_pending":
            return {"status": "pending"}, ""
        elif data.get("error") == "slow_down":
            return {"status": "slow_down", "interval": data.get("interval", 10)}, ""
        else:
            err = data.get("error_description", data.get("error", "Unknown"))
            return {"status": "error", "error": err}, ""
    except Exception as e:
        log.warning(f"Copilot auth poll failed: {e}")
        return None, str(e)


def copilot_auth_status() -> tuple[dict, str]:
    """Check Copilot OAuth status. Returns (response_dict, error_msg)."""
    with llm_providers.copilot_auth_lock:
        authenticated = llm_providers.copilot_oauth_token is not None
        pending = llm_providers.copilot_device_code is not None
    return {
        "available": True,
        "authenticated": authenticated,
        "pending": pending,
    }, ""


# ═══════════════════════════════════════════════════════════════════════════
# LLM PROVIDER AUTH — Claude (Anthropic) and OpenAI API keys
# ═══════════════════════════════════════════════════════════════════════════

def claude_auth_status() -> tuple[dict, str]:
    """Check whether an Anthropic API key is configured (env or session). Returns (response_dict, error_msg)."""
    return {
        "authenticated": bool(llm_providers.claude_api_key),
        "source": "env" if os.environ.get("ANTHROPIC_API_KEY") else "session",
    }, ""


def claude_set_key(api_key: str) -> tuple[dict, str]:
    """Set Anthropic API key for this session. Returns (response_dict, error_msg)."""
    key = (api_key or "").strip()
    if not key.startswith("sk-ant-"):
        return {"error": "Invalid Anthropic API key format (expected sk-ant-...)"}, "Invalid key"
    llm_providers.claude_api_key = key
    return {"status": "ok"}, ""


def openai_auth_status() -> tuple[dict, str]:
    """Check whether an OpenAI API key is configured (env or session). Returns (response_dict, error_msg)."""
    return {
        "authenticated": bool(llm_providers.openai_api_key),
        "source": "env" if os.environ.get("OPENAI_API_KEY") else "session",
    }, ""


def openai_set_key(api_key: str) -> tuple[dict, str]:
    """Set OpenAI API key for this session. Returns (response_dict, error_msg)."""
    key = (api_key or "").strip()
    if not key.startswith("sk-"):
        return {"error": "Invalid OpenAI API key format (expected sk-...)"}, "Invalid key"
    llm_providers.openai_api_key = key
    return {"status": "ok"}, ""
