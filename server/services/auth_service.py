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


# ═══════════════════════════════════════════════════════════════════════════
# GOOGLE OAUTH CALLBACK — Exchange code for auth token
# ═══════════════════════════════════════════════════════════════════════════

def google_callback(code: str, state: str, expected_state: str | None, base_url: str,
                   google_client_id: str, google_client_secret: str) -> tuple[dict | None, str]:
    """Handle Google OAuth callback — exchange code for tokens and create user.
    
    Args:
        code: authorization code from Google
        state: state token from callback
        expected_state: expected state token (from session)
        base_url: base URL for redirect_uri (e.g., "https://example.com")
        google_client_id: Google OAuth client ID
        google_client_secret: Google OAuth client secret
    
    Returns:
        ({"token": ..., "user": ..., "ttl": ...}, error_msg)
    """
    if not code:
        return None, "Missing authorization code"
    
    # Verify state token
    if not expected_state or state != expected_state:
        log.warning(f"[GOOGLE_AUTH] state mismatch: expected={expected_state}, got={state[:20] if state else 'none'}...")
        return None, "Invalid state token — please try again"
    
    redirect_uri = f"{base_url.rstrip('/')}/api/auth/google/callback"
    
    # Exchange authorization code for tokens
    try:
        token_resp = httpx.post(
            "https://oauth2.googleapis.com/token",
            data={
                "code": code,
                "client_id": google_client_id,
                "client_secret": google_client_secret,
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
        if token_resp.status_code != 200:
            log.warning(f"Google token exchange failed: {token_resp.text}")
            return None, "Google login failed — token exchange error"
        tokens = token_resp.json()
    except Exception as e:
        log.warning(f"Google token exchange error: {e}")
        return None, "Google login failed — network error"
    
    # Verify the ID token
    id_token = tokens.get("id_token", "")
    try:
        info_resp = httpx.get(
            "https://oauth2.googleapis.com/tokeninfo",
            params={"id_token": id_token},
            timeout=10,
        )
        if info_resp.status_code != 200:
            return None, "Google login failed — invalid token"
        token_info = info_resp.json()
    except Exception as e:
        log.warning(f"Google tokeninfo failed: {e}")
        return None, "Google login failed — verification error"
    
    if token_info.get("aud") != google_client_id:
        return None, "Google login failed — audience mismatch"
    
    email = token_info.get("email", "").lower().strip()
    email_verified = token_info.get("email_verified")
    if not email or email_verified not in ("true", True):
        return None, "Google login failed — email not verified"
    
    # Create/find user and issue auth token using oauth_user_from_google
    google_name = token_info.get("name", "")
    google_sub = token_info.get("sub", "")
    auth_info, error_msg = oauth_user_from_google(
        email, display_name=google_name, google_id=google_sub
    )
    if error_msg or not auth_info:
        return None, error_msg or "Service unavailable"
    
    log.info(f"[GOOGLE_AUTH] login success: email={email} user_id={auth_info['user']['id'][:8]}...")
    return auth_info, ""
