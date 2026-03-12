"""Authentication and user management — magic links, tokens, user accounts."""
import logging
import secrets
import time
import uuid
from db import _get_db
from exceptions import handle_errors

log = logging.getLogger(__name__)

AUTH_TOKEN_TTL = 30 * 24 * 3600  # 30 days
MAGIC_LINK_TTL = 15 * 60         # 15 minutes


@handle_errors("find_or_create_user", reraise=False, default=None)
def find_or_create_user(email: str, display_name: str = "", google_id: str = "") -> dict | None:
    """Find existing user by email or create a new one. Returns user dict."""
    conn = _get_db()
    email = email.lower().strip()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if row:
        user = dict(row)
        updates = ["last_login_at = ?"]
        params = [time.time()]
        if display_name and not user.get("display_name"):
            updates.append("display_name = ?")
            params.append(display_name)
        if google_id and not user.get("google_id"):
            updates.append("google_id = ?")
            params.append(google_id)
        params.append(user["id"])
        conn.execute(f"UPDATE users SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
        conn.close()
        user["last_login_at"] = time.time()
        if display_name and not user.get("display_name"):
            user["display_name"] = display_name
        return user
    user_id = str(uuid.uuid4())
    now = time.time()
    conn.execute(
        "INSERT INTO users (id, email, created_at, last_login_at, display_name, google_id) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, email, now, now, display_name or None, google_id or None),
    )
    conn.commit()
    conn.close()
    return {"id": user_id, "email": email, "created_at": now,
            "last_login_at": now, "display_name": display_name or None}


@handle_errors("create_auth_token", reraise=False, default=None)
def create_auth_token(user_id: str) -> str | None:
    """Create a 30-day auth token for a user. Returns token string."""
    conn = _get_db()
    token = secrets.token_urlsafe(32)
    now = time.time()
    conn.execute(
        "INSERT INTO auth_tokens (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token, user_id, now, now + AUTH_TOKEN_TTL),
    )
    conn.commit()
    conn.close()
    return token


@handle_errors("verify_auth_token", reraise=False, default=None)
def verify_auth_token(token: str) -> dict | None:
    """Verify an auth token and return the user dict, or None."""
    conn = _get_db()
    row = conn.execute(
        "SELECT u.id, u.email, u.display_name FROM auth_tokens t "
        "JOIN users u ON t.user_id = u.id "
        "WHERE t.token = ? AND t.expires_at > ?",
        (token, time.time()),
    ).fetchone()
    if row:
        conn.execute("UPDATE auth_tokens SET last_used_at = ? WHERE token = ?",
                     (time.time(), token))
        conn.commit()
    conn.close()
    return dict(row) if row else None


@handle_errors("create_magic_link", reraise=False, default=None)
def create_magic_link(email: str) -> str | None:
    """Create a single-use magic link code (15-min expiry). Returns code."""
    conn = _get_db()
    code = secrets.token_urlsafe(32)
    now = time.time()
    conn.execute(
        "INSERT INTO magic_links (code, email, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (code, email.lower().strip(), now, now + MAGIC_LINK_TTL),
    )
    conn.commit()
    conn.close()
    return code


@handle_errors("verify_magic_link", reraise=False, default=None)
def verify_magic_link(code: str) -> str | None:
    """Verify and consume a magic link code. Returns email or None."""
    conn = _get_db()
    row = conn.execute(
        "SELECT email FROM magic_links WHERE code = ? AND expires_at > ? AND used = 0",
        (code, time.time()),
    ).fetchone()
    if not row:
        conn.close()
        return None
    conn.execute("UPDATE magic_links SET used = 1 WHERE code = ?", (code,))
    conn.commit()
    conn.close()
    return row["email"]


@handle_errors("delete_auth_token", reraise=False, default=None)
def delete_auth_token(token: str):
    """Delete an auth token (logout)."""
    conn = _get_db()
    conn.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
    conn.commit()
    conn.close()


@handle_errors("claim_sessions", reraise=False, default=0)
def claim_sessions(user_id: str, session_ids: list[str]) -> int:
    """Claim unowned sessions for a user. Returns count of claimed sessions."""
    if not session_ids:
        return 0
    conn = _get_db()
    placeholders = ",".join("?" for _ in session_ids)
    cur = conn.execute(
        f"UPDATE sessions SET user_id = ? WHERE id IN ({placeholders}) AND user_id IS NULL",
        [user_id] + session_ids,
    )
    count = cur.rowcount if hasattr(cur, 'rowcount') else 0
    conn.commit()
    conn.close()
    return count


@handle_errors("get_user_sessions", reraise=False, default=[])
def get_user_sessions(user_id: str) -> list[dict]:
    """Get all sessions owned by a user."""
    conn = _get_db()
    rows = conn.execute(
        "SELECT id, game_id, model, mode, created_at, result, steps, levels, "
        "parent_session_id, branch_at_step, total_cost, user_id, player_type, "
        "steps_per_level_json, duration_seconds, live_mode, live_fps "
        "FROM sessions WHERE user_id = ? ORDER BY created_at DESC LIMIT 200",
        (user_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@handle_errors("count_recent_magic_links", reraise=False, default=0)
def count_recent_magic_links(email: str, window: float = 900) -> int:
    """Count magic links created for an email in the last `window` seconds."""
    conn = _get_db()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM magic_links WHERE email = ? AND created_at > ?",
        (email.lower().strip(), time.time() - window),
    ).fetchone()
    conn.close()
    return row["cnt"] if row else 0
