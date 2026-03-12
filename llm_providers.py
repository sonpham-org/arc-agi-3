"""LLM provider routing and shared utilities for ARC-AGI-3.

Per-provider implementations are in separate modules:
- llm_providers_google.py — Gemini calls + function calling
- llm_providers_anthropic.py — Claude calls
- llm_providers_openai.py — OpenAI + compatible (LM Studio, Cloudflare, Ollama)
- llm_providers_copilot.py — GitHub Copilot calls
"""

import logging
import os
import threading
import time
from typing import Optional

from models import MODEL_REGISTRY, _discovered_local_models

logger = logging.getLogger(__name__)

# Local model timeout configuration (seconds)
LOCAL_MODEL_TIMEOUT = float(os.environ.get("LOCAL_MODEL_TIMEOUT", "600.0"))

# ═══════════════════════════════════════════════════════════════════════════
# PROVIDER AUTH STATE INITIALIZATION
# ═══════════════════════════════════════════════════════════════════════════

# Initialize from environment at module load time
import llm_providers_anthropic
import llm_providers_openai
import llm_providers_google
llm_providers_anthropic.claude_api_key = os.environ.get("ANTHROPIC_API_KEY") or None
llm_providers_openai.openai_api_key = os.environ.get("OPENAI_API_KEY") or None

# Re-export globals for backward compatibility
claude_api_key = llm_providers_anthropic.claude_api_key
openai_api_key = llm_providers_openai.openai_api_key
_tool_session_lock = llm_providers_google._tool_session_lock

# ═══════════════════════════════════════════════════════════════════════════
# PER-PROVIDER THROTTLE
# ═══════════════════════════════════════════════════════════════════════════

PROVIDER_MIN_DELAY: dict[str, float] = {
    "gemini":      4.0,
    "anthropic":   1.0,
    "openai":      1.0,
    "groq":        2.5,
    "mistral":     2.0,
    "huggingface": 6.0,
    "cloudflare":  0.5,
    "copilot":     4.0,
    "ollama":      0.0,
}
_provider_last_call: dict[str, float] = {}
_throttle_lock = threading.Lock()


def _throttle_provider(provider: str):
    """Enforce per-provider rate limiting."""
    min_delay = PROVIDER_MIN_DELAY.get(provider, 1.0)
    if min_delay <= 0:
        return
    with _throttle_lock:
        now = time.time()
        last = _provider_last_call.get(provider, 0.0)
        wait = min_delay - (now - last)
        if wait > 0:
            logger.info(f"Throttling {provider}: waiting {wait:.1f}s")
            time.sleep(wait)
        _provider_last_call[provider] = time.time()


# ═══════════════════════════════════════════════════════════════════════════
# ROUTING
# ═══════════════════════════════════════════════════════════════════════════

def _route_model_call(model_key: str, prompt: str, image_b64: str | None = None,
                      tools_enabled: bool = False, session_id: str | None = None,
                      grid=None, prev_grid=None,
                      cached_content_name: str | None = None,
                      thinking_level: str = "low",
                      max_tokens: int = 16384) -> str | dict:
    """Route a model call to the appropriate provider based on model_key."""
    from llm_providers_google import _call_gemini
    from llm_providers_anthropic import _call_anthropic
    from llm_providers_openai import _call_openai, _call_openai_compatible, _call_cloudflare, _call_ollama
    from llm_providers_copilot import _call_copilot

    info = MODEL_REGISTRY.get(model_key)

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

    _throttle_provider(provider)

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
    if provider == "openai":
        return _call_openai(api_model, prompt, img, max_tokens=max_tokens)
    if provider == "cloudflare":
        return _call_cloudflare(api_model, prompt, img, max_tokens=max_tokens)
    if provider == "copilot":
        return _call_copilot(api_model, prompt, img)
    if provider == "ollama":
        return _call_ollama(api_model, prompt, img)
    if provider == "lmstudio":
        url = "http://localhost:1234/v1/chat/completions"
        return _call_openai_compatible(url, "no-key-needed", api_model, prompt, img, max_tokens=max_tokens)

    # OpenAI-compatible (Groq, Mistral, HuggingFace)
    api_key = os.environ.get(info.get("env_key", ""), "")
    url = info.get("url", "")
    return _call_openai_compatible(url, api_key, api_model, prompt, None, max_tokens=max_tokens)


# ═══════════════════════════════════════════════════════════════════════════
# BACKWARD COMPATIBILITY RE-EXPORTS
# ═══════════════════════════════════════════════════════════════════════════
# These re-exports allow code that imports from llm_providers to continue working

from llm_providers_google import (
    _call_gemini,
    _get_or_create_gemini_cache,
    _execute_python,
    _cleanup_tool_session,
    _tool_sessions,
)
from llm_providers_anthropic import _call_anthropic
from llm_providers_openai import (
    _call_openai,
    _call_openai_compatible,
    _call_cloudflare,
    _call_ollama,
)
from llm_providers_copilot import (
    _call_copilot,
    _load_copilot_token,
    _save_copilot_token,
    _COPILOT_TOKEN_FILE,
    copilot_oauth_token,
    copilot_api_token,
    copilot_token_expiry,
    copilot_device_code,
    copilot_auth_lock,
)

__all__ = [
    # Routing
    '_route_model_call',
    'PROVIDER_MIN_DELAY',
    'LOCAL_MODEL_TIMEOUT',
    # Throttle state
    '_provider_last_call',
    # Gemini
    '_call_gemini',
    '_get_or_create_gemini_cache',
    '_execute_python',
    '_cleanup_tool_session',
    '_tool_sessions',
    # Anthropic
    '_call_anthropic',
    # OpenAI
    '_call_openai',
    '_call_openai_compatible',
    '_call_cloudflare',
    '_call_ollama',
    # Copilot
    '_call_copilot',
    '_load_copilot_token',
    '_save_copilot_token',
    '_COPILOT_TOKEN_FILE',
    'copilot_oauth_token',
    'copilot_api_token',
    'copilot_token_expiry',
    'copilot_device_code',
    'copilot_auth_lock',
]
