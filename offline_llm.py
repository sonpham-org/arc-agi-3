# Author: Claude Opus 4.6
# Date: 2026-03-17 23:00
# PURPOSE: Multi-provider LLM tool-calling module for offline arena agent generation.
#   Supports Anthropic, OpenAI, Google Gemini, and LM Studio (OpenAI-compatible).
#   Each provider uses httpx directly (no SDK dependencies). Generic tool-calling loop
#   dispatches to provider-specific callers. Used by offline_agent_runner.py.
# SRP/DRY check: Pass — provider-specific HTTP only, tool loop is generic

import json
import time
import uuid

import httpx

# ═══════════════════════════════════════════════════════════════════════════
# Constants
# ═══════════════════════════════════════════════════════════════════════════

REQUEST_TIMEOUT = 120.0
MAX_RETRIES = 5
INITIAL_BACKOFF = 5
TOOL_RESULT_MAX_CHARS = 3000

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o",
    "gemini": "gemini-2.5-flash",
    "lmstudio": None,  # auto-discover or user-specified
    "ollama": None,  # auto-discover or user-specified
}

PROVIDER_URLS = {
    "anthropic": "https://api.anthropic.com/v1/messages",
    "openai": "https://api.openai.com/v1/chat/completions",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    "lmstudio": "http://localhost:1234/v1/chat/completions",
    "ollama": "http://localhost:11434/v1/chat/completions",
}

_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 529}


# ═══════════════════════════════════════════════════════════════════════════
# Generic tool-calling loop
# ═══════════════════════════════════════════════════════════════════════════

def run_tool_loop(
    provider: str,
    api_key: str,
    system_prompt: str,
    user_message: str,
    tools: list[dict],
    handler,
    model: str | None = None,
    max_tokens: int = 8192,
    max_rounds: int = 10,
    base_url: str | None = None,
) -> list[dict]:
    """Run a multi-turn tool-calling loop with any supported provider.

    Args:
        provider: One of "anthropic", "openai", "gemini", "lmstudio".
        api_key: Provider API key (ignored for lmstudio).
        system_prompt: System-level instructions.
        user_message: Initial user message.
        tools: List of tool dicts: {"name", "description", "parameters": {"type": "object", ...}}.
        handler: Callable(name: str, args: dict) -> str. Executes tools, returns result string.
        model: Model ID. Defaults per provider if None.
        max_tokens: Max tokens per response.
        max_rounds: Max tool-calling iterations before forcing stop.
        base_url: Override base URL (primarily for lmstudio).

    Returns:
        Conversation log: list of dicts with type "assistant"/"tool_call"/"tool_result"/"error".
    """
    provider = provider.lower().strip()
    if provider not in ("anthropic", "openai", "gemini", "lmstudio", "ollama"):
        raise ValueError(f"Unsupported provider: {provider}. Use: anthropic, openai, gemini, lmstudio, ollama")

    if model is None:
        model = _resolve_default_model(provider, api_key, base_url)

    caller = _PROVIDER_CALLERS[provider]
    conversation_log = []

    # Build initial messages in a provider-neutral internal format.
    # Each provider caller converts as needed.
    messages = [{"role": "user", "content": user_message}]

    for round_num in range(max_rounds):
        try:
            kwargs = {
                "api_key": api_key,
                "messages": messages,
                "system_prompt": system_prompt,
                "tools": tools,
                "model": model,
                "max_tokens": max_tokens,
            }
            if provider in ("openai", "lmstudio", "ollama"):
                kwargs["base_url"] = base_url or PROVIDER_URLS.get(provider)

            result = caller(**kwargs)
        except Exception as exc:
            conversation_log.append({"type": "error", "content": str(exc)})
            print(f"  [offline] API error on round {round_num + 1}: {exc}")
            break

        # Extract text response
        if result.get("text"):
            conversation_log.append({"type": "assistant", "content": result["text"]})

        # Append assistant message to provider-specific message history
        messages = _append_assistant_message(provider, messages, result)

        # No tool calls — we are done
        if not result.get("tool_calls"):
            print(f"  [offline] Finished after {round_num + 1} round(s) (stop: {result.get('stop_reason', 'end_turn')})")
            break

        # Execute each tool call
        tool_result_entries = []
        for tc in result["tool_calls"]:
            name = tc["name"]
            args = tc.get("args", {})
            call_id = tc.get("id", str(uuid.uuid4()))

            args_preview = json.dumps(args, default=str)[:120]
            print(f"  [offline] Round {round_num + 1}: {name}({args_preview}...)")

            conversation_log.append({"type": "tool_call", "name": name, "args": args})

            try:
                result_str = str(handler(name, args))
            except Exception as exc:
                result_str = f"Tool execution error: {type(exc).__name__}: {exc}"

            if len(result_str) > TOOL_RESULT_MAX_CHARS:
                result_str = result_str[:TOOL_RESULT_MAX_CHARS] + "\n... (truncated)"

            conversation_log.append({"type": "tool_result", "name": name, "result": result_str[:500]})
            print(f"  [offline]   -> {result_str[:150].replace(chr(10), ' ')}")

            tool_result_entries.append({
                "name": name,
                "id": call_id,
                "result": result_str,
            })

        # Append tool results to message history
        messages = _append_tool_results(provider, messages, tool_result_entries)

    return conversation_log


# ═══════════════════════════════════════════════════════════════════════════
# Message management helpers (provider-specific message formats)
# ═══════════════════════════════════════════════════════════════════════════

def _append_assistant_message(provider: str, messages: list[dict], result: dict) -> list[dict]:
    """Append the assistant's response (text + tool calls) to the message list."""
    if provider == "anthropic":
        messages.append({"role": "assistant", "content": result["_raw_content"]})
    elif provider in ("openai", "lmstudio"):
        messages.append(result["_raw_message"])
    elif provider == "gemini":
        messages.append({"role": "model", "content": result["_raw_parts"]})
    return messages


def _append_tool_results(provider: str, messages: list[dict], entries: list[dict]) -> list[dict]:
    """Append tool results to the message list in provider-specific format."""
    if provider == "anthropic":
        tool_results = [
            {
                "type": "tool_result",
                "tool_use_id": entry["id"],
                "content": entry["result"],
            }
            for entry in entries
        ]
        messages.append({"role": "user", "content": tool_results})

    elif provider in ("openai", "lmstudio"):
        for entry in entries:
            messages.append({
                "role": "tool",
                "tool_call_id": entry["id"],
                "content": entry["result"],
            })

    elif provider == "gemini":
        parts = [
            {
                "functionResponse": {
                    "name": entry["name"],
                    "response": {"result": entry["result"]},
                }
            }
            for entry in entries
        ]
        messages.append({"role": "user", "content": parts})

    return messages


# ═══════════════════════════════════════════════════════════════════════════
# HTTP retry helper
# ═══════════════════════════════════════════════════════════════════════════

def _post_with_retry(url: str, headers: dict, body: dict, timeout: float = REQUEST_TIMEOUT) -> dict:
    """POST JSON with exponential backoff on 429/5xx. Returns parsed JSON response."""
    backoff = INITIAL_BACKOFF
    last_status = 0
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = httpx.post(url, headers=headers, json=body, timeout=timeout)
        except httpx.TimeoutException:
            if attempt < MAX_RETRIES:
                print(f"  [offline] Timeout on attempt {attempt + 1}, retrying in {backoff}s...")
                time.sleep(backoff)
                backoff = min(backoff * 2, 300)
                continue
            raise
        except Exception:
            raise

        if resp.status_code == 200:
            return resp.json()

        last_status = resp.status_code

        if resp.status_code in _RETRYABLE_STATUS_CODES and attempt < MAX_RETRIES:
            retry_after = resp.headers.get("retry-after")
            if retry_after and retry_after.isdigit():
                wait = min(int(retry_after), 300)
            else:
                wait = backoff
            wait = max(wait, backoff)
            print(f"  [offline] {resp.status_code} on attempt {attempt + 1}, retrying in {wait}s...")
            time.sleep(wait)
            backoff = min(backoff * 2, 300)
            continue

        raise Exception(f"API error {resp.status_code}: {resp.text[:500]}")

    raise Exception(f"Max retries exceeded (last status {last_status})")


# ═══════════════════════════════════════════════════════════════════════════
# Tool schema conversion
# ═══════════════════════════════════════════════════════════════════════════

def _tools_to_anthropic(tools: list[dict]) -> list[dict]:
    """Convert generic tool schema to Anthropic native format."""
    return [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["parameters"],
        }
        for t in tools
    ]


def _tools_to_openai(tools: list[dict]) -> list[dict]:
    """Convert generic tool schema to OpenAI function calling format."""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        }
        for t in tools
    ]


def _tools_to_gemini(tools: list[dict]) -> list[dict]:
    """Convert generic tool schema to Gemini function_declarations format."""
    return [
        {
            "function_declarations": [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"],
                }
                for t in tools
            ]
        }
    ]


# ═══════════════════════════════════════════════════════════════════════════
# Anthropic provider
# ═══════════════════════════════════════════════════════════════════════════

def _is_oauth_token(key: str) -> bool:
    """Return True if key is a Claude Code OAuth token (sk-ant-oat*)."""
    return key.startswith("sk-ant-oat")


def _anthropic_auth_headers(api_key: str) -> dict:
    """Build Anthropic auth headers — Bearer for OAuth tokens, x-api-key for API keys."""
    base = {
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    if _is_oauth_token(api_key):
        base["Authorization"] = f"Bearer {api_key}"
        base["anthropic-beta"] = "oauth-2025-04-20"
    else:
        base["x-api-key"] = api_key
    return base


def _call_anthropic(
    api_key: str,
    messages: list[dict],
    system_prompt: str,
    tools: list[dict],
    model: str,
    max_tokens: int,
) -> dict:
    """Call Anthropic Messages API with tool support.

    Returns:
        {"text": str|None, "tool_calls": [{"name", "args", "id"}], "stop_reason": str,
         "_raw_content": list}
    """
    headers = _anthropic_auth_headers(api_key)
    ant_tools = _tools_to_anthropic(tools)

    body = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "tools": ant_tools,
        "messages": messages,
    }

    data = _post_with_retry(PROVIDER_URLS["anthropic"], headers, body)

    stop_reason = data.get("stop_reason", "end_turn")
    content = data.get("content", [])

    # Extract text
    text_parts = [
        block.get("text", "")
        for block in content
        if block.get("type") == "text" and block.get("text")
    ]
    text = "\n".join(text_parts) if text_parts else None

    # Extract tool calls
    tool_calls = []
    for block in content:
        if block.get("type") == "tool_use":
            tool_calls.append({
                "name": block["name"],
                "args": block.get("input", {}),
                "id": block["id"],
            })

    return {
        "text": text,
        "tool_calls": tool_calls,
        "stop_reason": stop_reason,
        "_raw_content": content,
    }


# ═══════════════════════════════════════════════════════════════════════════
# OpenAI provider (also used by LM Studio)
# ═══════════════════════════════════════════════════════════════════════════

def _call_openai(
    api_key: str,
    messages: list[dict],
    system_prompt: str,
    tools: list[dict],
    model: str,
    max_tokens: int,
    base_url: str | None = None,
) -> dict:
    """Call OpenAI-compatible chat completions API with tool support.

    Returns:
        {"text": str|None, "tool_calls": [{"name", "args", "id"}], "stop_reason": str,
         "_raw_message": dict}
    """
    url = base_url or PROVIDER_URLS["openai"]
    if not url.endswith("/chat/completions"):
        url = url.rstrip("/") + "/chat/completions"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Build messages list: prepend system prompt
    api_messages = [{"role": "system", "content": system_prompt}] + messages
    oai_tools = _tools_to_openai(tools)

    body = {
        "model": model,
        "messages": api_messages,
        "max_tokens": max_tokens,
        "tools": oai_tools,
    }

    data = _post_with_retry(url, headers, body)

    choice = data["choices"][0]
    message = choice["message"]
    finish_reason = choice.get("finish_reason", "stop")

    text = message.get("content")
    tool_calls = []

    if message.get("tool_calls"):
        for tc in message["tool_calls"]:
            func = tc["function"]
            try:
                args = json.loads(func.get("arguments", "{}"))
            except (json.JSONDecodeError, TypeError):
                args = {"_raw": func.get("arguments", "")}

            tool_calls.append({
                "name": func["name"],
                "args": args,
                "id": tc["id"],
            })

    return {
        "text": text,
        "tool_calls": tool_calls,
        "stop_reason": finish_reason,
        "_raw_message": message,
    }


# ═══════════════════════════════════════════════════════════════════════════
# LM Studio provider (OpenAI-compatible wrapper)
# ═══════════════════════════════════════════════════════════════════════════

def _call_lmstudio(
    api_key: str,
    messages: list[dict],
    system_prompt: str,
    tools: list[dict],
    model: str,
    max_tokens: int,
    base_url: str | None = None,
) -> dict:
    """Call LM Studio via OpenAI-compatible endpoint.

    LM Studio needs no auth key. Delegates to _call_openai with the right base URL.
    """
    url = base_url or PROVIDER_URLS["lmstudio"]
    # LM Studio doesn't need a real key; pass a dummy if empty
    effective_key = api_key if api_key else "lm-studio"
    return _call_openai(
        api_key=effective_key,
        messages=messages,
        system_prompt=system_prompt,
        tools=tools,
        model=model,
        max_tokens=max_tokens,
        base_url=url,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Ollama provider (OpenAI-compatible wrapper, localhost:11434)
# ═══════════════════════════════════════════════════════════════════════════

def _call_ollama(
    api_key: str,
    messages: list[dict],
    system_prompt: str,
    tools: list[dict],
    model: str,
    max_tokens: int,
    base_url: str | None = None,
) -> dict:
    """Call Ollama via OpenAI-compatible endpoint.

    Ollama needs no auth key and must NOT send Authorization header with empty key.
    Delegates to _call_openai with the right base URL.
    """
    url = base_url or PROVIDER_URLS["ollama"]
    # Ollama must not receive Authorization: Bearer header with empty key
    effective_key = api_key if api_key else "ollama"
    return _call_openai(
        api_key=effective_key,
        messages=messages,
        system_prompt=system_prompt,
        tools=tools,
        model=model,
        max_tokens=max_tokens,
        base_url=url,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Google Gemini provider (raw httpx, no SDK)
# ═══════════════════════════════════════════════════════════════════════════

def _call_gemini(
    api_key: str,
    messages: list[dict],
    system_prompt: str,
    tools: list[dict],
    model: str,
    max_tokens: int,
) -> dict:
    """Call Gemini generateContent API with tool support.

    Returns:
        {"text": str|None, "tool_calls": [{"name", "args", "id"}], "stop_reason": str,
         "_raw_parts": list}
    """
    url_template = PROVIDER_URLS["gemini"]
    url = url_template.format(model=model) + f"?key={api_key}"

    # Build Gemini contents from our internal message format
    contents = _build_gemini_contents(messages)

    gemini_tools = _tools_to_gemini(tools)

    body = {
        "contents": contents,
        "systemInstruction": {
            "parts": [{"text": system_prompt}],
        },
        "tools": gemini_tools,
        "generationConfig": {
            "maxOutputTokens": max_tokens,
        },
    }

    headers = {"Content-Type": "application/json"}
    data = _post_with_retry(url, headers, body)

    # Parse response
    candidates = data.get("candidates", [])
    if not candidates:
        return {
            "text": None,
            "tool_calls": [],
            "stop_reason": "error",
            "_raw_parts": [],
        }

    candidate = candidates[0]
    finish_reason = candidate.get("finishReason", "STOP")
    parts = candidate.get("content", {}).get("parts", [])

    text_parts = []
    tool_calls = []

    for part in parts:
        if "text" in part:
            text_parts.append(part["text"])
        elif "functionCall" in part:
            fc = part["functionCall"]
            tool_calls.append({
                "name": fc["name"],
                "args": fc.get("args", {}),
                "id": str(uuid.uuid4()),  # Gemini doesn't provide IDs, generate one
            })

    text = "\n".join(text_parts) if text_parts else None

    return {
        "text": text,
        "tool_calls": tool_calls,
        "stop_reason": finish_reason,
        "_raw_parts": parts,
    }


def _build_gemini_contents(messages: list[dict]) -> list[dict]:
    """Convert internal message list to Gemini contents format.

    Internal format:
        {"role": "user", "content": str}  -- plain text
        {"role": "user", "content": [tool_result_blocks]}  -- tool results (Anthropic style)
        {"role": "model", "content": [parts]}  -- model response with raw parts
        {"role": "assistant", "content": [raw_content]}  -- Anthropic raw content
        {"role": "tool", ...}  -- OpenAI tool response (should not appear for Gemini)

    Gemini format:
        {"role": "user", "parts": [{"text": ...}]}
        {"role": "model", "parts": [{"text": ...}, {"functionCall": {...}}]}
        {"role": "user", "parts": [{"functionResponse": {...}}]}
    """
    contents = []
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")

        if role == "model":
            # Raw Gemini parts stored directly
            contents.append({"role": "model", "parts": content})

        elif role == "user" and isinstance(content, list):
            # Could be tool results (Gemini functionResponse format) or Anthropic-style tool results
            gemini_parts = []
            for item in content:
                if isinstance(item, dict) and "functionResponse" in item:
                    # Already in Gemini format
                    gemini_parts.append(item)
                elif isinstance(item, dict) and item.get("type") == "tool_result":
                    # Anthropic-style — convert
                    gemini_parts.append({
                        "functionResponse": {
                            "name": item.get("tool_use_id", "unknown"),
                            "response": {"result": item.get("content", "")},
                        }
                    })
                else:
                    gemini_parts.append({"text": str(item)})
            contents.append({"role": "user", "parts": gemini_parts})

        elif role == "assistant" and isinstance(content, list):
            # Anthropic raw content — convert to Gemini model parts
            gemini_parts = []
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        gemini_parts.append({"text": block["text"]})
                    elif block.get("type") == "tool_use":
                        gemini_parts.append({
                            "functionCall": {
                                "name": block["name"],
                                "args": block.get("input", {}),
                            }
                        })
                else:
                    gemini_parts.append({"text": str(block)})
            contents.append({"role": "model", "parts": gemini_parts})

        else:
            # Plain text message
            gemini_role = "model" if role == "assistant" else "user"
            contents.append({"role": gemini_role, "parts": [{"text": str(content)}]})

    return contents


# ═══════════════════════════════════════════════════════════════════════════
# Local model auto-discovery (LM Studio + Ollama)
# ═══════════════════════════════════════════════════════════════════════════

def _discover_local_model(provider: str, base_url: str | None = None) -> str:
    """Query /v1/models on a local OpenAI-compatible server to find a loaded model."""
    default_url = PROVIDER_URLS.get(provider, "")
    url = (base_url or default_url).rstrip("/")
    # Strip /chat/completions if present to get base
    if "/chat/completions" in url:
        url = url.rsplit("/chat/completions", 1)[0]
    models_url = url.rstrip("/") + "/v1/models" if "/v1" not in url else url.rsplit("/v1", 1)[0] + "/v1/models"

    try:
        resp = httpx.get(models_url, timeout=10.0)
        if resp.status_code == 200:
            data = resp.json()
            model_list = data.get("data", [])
            if model_list:
                model_id = model_list[0].get("id", "")
                print(f"  [offline] Auto-discovered {provider} model: {model_id}")
                return model_id
    except Exception as exc:
        print(f"  [offline] {provider} model discovery failed: {exc}")

    raise ValueError(
        f"Could not auto-discover {provider} model. "
        f"Ensure {provider} is running with a model loaded, or specify --model explicitly."
    )


def _resolve_default_model(provider: str, api_key: str, base_url: str | None = None) -> str:
    """Resolve the default model for a provider."""
    default = DEFAULT_MODELS.get(provider)
    if default is not None:
        return default

    # Local providers — auto-discover
    if provider in ("lmstudio", "ollama"):
        return _discover_local_model(provider, base_url)

    raise ValueError(f"No default model for provider {provider}. Specify one explicitly.")


# ═══════════════════════════════════════════════════════════════════════════
# Provider dispatch table
# ═══════════════════════════════════════════════════════════════════════════

_PROVIDER_CALLERS = {
    "anthropic": _call_anthropic,
    "openai": _call_openai,
    "gemini": _call_gemini,
    "lmstudio": _call_lmstudio,
    "ollama": _call_ollama,
}
