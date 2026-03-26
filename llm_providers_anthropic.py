# Author: Claude Opus 4.6
# Date: 2026-03-25 16:30
# PURPOSE: Anthropic Claude provider — LLM calls via Anthropic API. Handles both standard
#   API keys (x-api-key) and OAuth tokens (Bearer + anthropic-beta header). Injects required
#   "You are Claude Code" system preamble for OAuth token routing.
# SRP/DRY check: Pass — single provider module; routing stays in llm_providers.py
"""Anthropic Claude provider — LLM calls via Anthropic API."""

import logging
from typing import Optional

from models import SYSTEM_MSG

logger = logging.getLogger(__name__)

# Claude API key initialization
claude_api_key: Optional[str] = None


def _is_oauth_token(key: str) -> bool:
    """Return True if key is a Claude Code OAuth token (sk-ant-oat*)."""
    return key.startswith("sk-ant-oat")


_UA = "sonpham-arc3/1.2.8 (ARC Prize research; https://three.arcprize.org; https://arc.markbarney.net; https://arc3.sonpham.net; contact mark@markbarney.net)"


def _anthropic_auth_headers(api_key: str) -> dict:
    """Build auth headers — Bearer for OAuth tokens, x-api-key for API keys."""
    base = {"anthropic-version": "2023-06-01", "content-type": "application/json", "User-Agent": _UA}
    if _is_oauth_token(api_key):
        base["Authorization"] = f"Bearer {api_key}"
        base["anthropic-beta"] = "oauth-2025-04-20"
    else:
        base["x-api-key"] = api_key
    return base


def _call_anthropic(model_name: str, prompt: str, image_b64: str | None = None, max_tokens: int = 16384) -> str:
    """Call Anthropic Claude API. Supports both API keys and OAuth tokens."""
    import httpx
    api_key = claude_api_key or ""
    content_blocks: list[dict] = []
    if image_b64:
        content_blocks.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": image_b64},
        })
    content_blocks.append({"type": "text", "text": prompt})

    # OAuth tokens require this system preamble to route Sonnet through the correct
    # quota bucket. Without it, Sonnet returns 400 invalid_request_error.
    if _is_oauth_token(api_key):
        system_payload = [
            {"type": "text", "text": "You are Claude Code, Anthropic's official CLI for Claude."},
            {"type": "text", "text": SYSTEM_MSG},
        ]
    else:
        system_payload = SYSTEM_MSG

    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers=_anthropic_auth_headers(api_key),
        json={
            "model": model_name, "system": system_payload,
            "messages": [{"role": "user", "content": content_blocks}],
            "temperature": 0.3, "max_tokens": max_tokens,
            "metadata": {"user_id": "arc-prize-research"},
        },
        timeout=90.0,
    )
    resp.raise_for_status()
    data = resp.json()
    text = data["content"][0]["text"]
    if data.get("stop_reason") == "max_tokens":
        return {"text": text, "truncated": True}
    return text
