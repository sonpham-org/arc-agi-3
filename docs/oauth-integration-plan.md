# Auth Integration Plan — Claude Code & OpenAI Codex

**Author:** Bubba (OpenClaw agent)  
**Date:** 2026-03-11  
**Branch:** refactor/phase-1-modularization  
**Status:** Design document — not yet implemented  
**Sources:** Official Anthropic API docs (platform.claude.com), Official OpenAI API docs (platform.openai.com), Claude Code docs (code.claude.com)

---

## Important Clarification Up Front

> **Claude Code (the CLI tool) and the Anthropic API are two different things.**  
> Adding "Claude Code auth" to this project means allowing users to call Claude models via the Anthropic API — using an API key. Claude Code's own login flow (browser OAuth to claude.ai) is for the CLI tool itself and is not relevant to integrating Claude as an LLM backend in a web application.

This document uses only official documentation as its source. It does not borrow patterns from unrelated OAuth flows already in this codebase (Google, GitHub Copilot).

---

## How Claude (Anthropic API) Authentication Actually Works

**Source:** https://platform.claude.com/docs/en/api/overview

The Anthropic API uses **API key authentication** exclusively. There is no OAuth flow for third-party apps to access the Anthropic API.

Every request requires these HTTP headers:

```
x-api-key: YOUR_ANTHROPIC_API_KEY
anthropic-version: 2023-06-01
content-type: application/json
```

API keys are obtained from the Anthropic Console at **https://platform.claude.com/settings/keys**.

Keys are prefixed with `sk-ant-`.

### Claude Code CLI Authentication (for reference only — not used here)

When a user runs the `claude` CLI for the first time, it opens a browser window to log in via their Claude.ai account (Pro/Max/Teams/Enterprise) or Console credentials. The CLI handles this flow internally and stores credentials in the macOS Keychain. **This is the Claude Code CLI's own login system — it is not an OAuth API that third-party apps can implement.**

---

## How OpenAI (Codex) Authentication Actually Works

**Source:** https://developers.openai.com/api/reference/overview#authentication

The OpenAI API uses **API key authentication via HTTP Bearer token**. There is no user-facing OAuth flow for standard API access.

Every request requires:

```
Authorization: Bearer YOUR_OPENAI_API_KEY
```

Optional headers for multi-organization setups:

```
OpenAI-Organization: YOUR_ORG_ID
OpenAI-Project: YOUR_PROJECT_ID
```

API keys are obtained from **https://platform.openai.com/settings/organization/api-keys**.

Keys are prefixed with `sk-`.

Codex models (`codex-mini-latest`, `o3`, `o4-mini`) use the same auth as all other OpenAI models — no separate key or flow.

---

## Implementation Plan for sonpham-arc3

Since both providers use API keys, the integration pattern is the same for both. The question is where the key comes from:

### Option A — Environment Variables (Server-side, simplest)

Set keys on the server before launch. No user interaction required.

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export OPENAI_API_KEY="sk-..."
```

Add to `constants.py`:
```python
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
```

**Best for:** Single-user deployments, development, or when the server operator controls billing.

### Option B — Per-Session Key Injection (User supplies their own key)

Match the existing pattern already in `session_api_keys` in this codebase.

#### Step 1 — API routes in `server.py`

```python
@app.route("/api/anthropic/auth/set-key", methods=["POST"])
def anthropic_set_key():
    """Store user-supplied Anthropic API key for this session."""
    data = request.get_json() or {}
    key = data.get("api_key", "").strip()
    if not key.startswith("sk-ant-"):
        return jsonify({"error": "Invalid Anthropic API key. Must start with sk-ant-"}), 400
    sid = _get_or_create_session_id()
    session_api_keys.setdefault(sid, {})["anthropic"] = key
    return jsonify({"status": "ok"})


@app.route("/api/anthropic/auth/status")
def anthropic_auth_status():
    """Check if an Anthropic API key is available for this session."""
    sid = _get_or_create_session_id()
    has_session_key = bool(session_api_keys.get(sid, {}).get("anthropic"))
    has_env_key = bool(ANTHROPIC_API_KEY)
    return jsonify({
        "authenticated": has_session_key or has_env_key,
        "source": "session" if has_session_key else ("env" if has_env_key else "none")
    })


@app.route("/api/openai/auth/set-key", methods=["POST"])
def openai_set_key():
    """Store user-supplied OpenAI API key for this session."""
    data = request.get_json() or {}
    key = data.get("api_key", "").strip()
    if not key.startswith("sk-"):
        return jsonify({"error": "Invalid OpenAI API key. Must start with sk-"}), 400
    sid = _get_or_create_session_id()
    session_api_keys.setdefault(sid, {})["openai"] = key
    return jsonify({"status": "ok"})


@app.route("/api/openai/auth/status")
def openai_auth_status():
    """Check if an OpenAI API key is available for this session."""
    sid = _get_or_create_session_id()
    has_session_key = bool(session_api_keys.get(sid, {}).get("openai"))
    has_env_key = bool(OPENAI_API_KEY)
    return jsonify({
        "authenticated": has_session_key or has_env_key,
        "source": "session" if has_session_key else ("env" if has_env_key else "none")
    })
```

#### Step 2 — Model registry in `models.py`

```python
# Anthropic / Claude models
"claude-3-5-sonnet": {
    "provider": "anthropic",
    "model_id": "claude-3-5-sonnet-20241022",
    "api_base": "https://api.anthropic.com/v1",
},
"claude-3-7-sonnet": {
    "provider": "anthropic",
    "model_id": "claude-3-7-sonnet-20250219",
    "api_base": "https://api.anthropic.com/v1",
},

# OpenAI / Codex models
"codex-mini": {
    "provider": "openai",
    "model_id": "codex-mini-latest",
    "api_base": "https://api.openai.com/v1",
},
"o4-mini": {
    "provider": "openai",
    "model_id": "o4-mini",
    "api_base": "https://api.openai.com/v1",
},
```

#### Step 3 — Provider dispatch in `llm_providers.py`

```python
# Anthropic
elif provider == "anthropic":
    import anthropic
    api_key = session_api_keys.get(sid, {}).get("anthropic") or ANTHROPIC_API_KEY
    if not api_key:
        raise ValueError("No Anthropic API key available")
    client = anthropic.Anthropic(
        api_key=api_key,
        default_headers={"anthropic-version": "2023-06-01"}
    )
    response = client.messages.create(
        model=model_id,
        max_tokens=max_tokens,
        messages=messages,
    )
    return response.content[0].text

# OpenAI / Codex
elif provider == "openai":
    from openai import OpenAI
    api_key = session_api_keys.get(sid, {}).get("openai") or OPENAI_API_KEY
    if not api_key:
        raise ValueError("No OpenAI API key available")
    client = OpenAI(api_key=api_key)
    # o-series models use max_completion_tokens, not max_tokens
    if model_id.startswith("o"):
        response = client.chat.completions.create(
            model=model_id,
            messages=messages,
            max_completion_tokens=max_tokens,
        )
    else:
        response = client.chat.completions.create(
            model=model_id,
            messages=messages,
            max_tokens=max_tokens,
        )
    return response.choices[0].message.content
```

#### Step 4 — Install dependencies

```bash
pip install anthropic openai
```

Add to `requirements.txt`:
```
anthropic>=0.40.0
openai>=1.50.0
```

---

## Environment Variables

Add to `.env.example`:

```bash
# Anthropic / Claude
ANTHROPIC_API_KEY=sk-ant-...

# OpenAI / Codex  
OPENAI_API_KEY=sk-...
```

---

## Security Notes

1. **Never log API keys** — mask them in all server logs
2. **Validate key format before storing** — `sk-ant-` for Anthropic, `sk-` for OpenAI
3. **Session-scoped keys expire** when the session ends — they are not persisted to disk
4. **Server-side only** — keys must never be sent to the browser or included in client-side JS
5. **o-series models** (o3, o4-mini) use `max_completion_tokens`, not `max_tokens` — the dispatch code handles this

---

## What This Is NOT

- **Not OAuth.** Neither Anthropic nor OpenAI expose an OAuth 2.0 authorization flow for third-party web apps to access their APIs on behalf of users. Their APIs use API keys only.
- **Not Claude Code CLI auth.** Claude Code's browser login (claude.ai) is for the CLI tool — it is not an API that other applications can call.
- **Not like GitHub Copilot** (device-code flow) or **Google OAuth** (authorization code flow) — those patterns in this codebase are for different services and are not applicable here.

---

*Document authored by Bubba — OpenClaw agent on Mac Mini M4 Pro. Sources: Anthropic API docs (platform.claude.com), OpenAI API docs (platform.openai.com), Claude Code docs (code.claude.com).*
