# Author: Claude Opus 4.6
# Date: 2026-03-16 14:00
# PURPOSE: Generic Anthropic tool-calling loop for arena evolution.
#   Replaces external snake_autoresearch/llm_client.py dependency.
#   Uses httpx directly (same approach as llm_providers_anthropic.py).
#   Supports both API keys (x-api-key) and OAuth tokens (Bearer).
#   Reuses auth header logic from llm_providers_anthropic.py.
#   Instruments every API call for monitoring (success/failure/tokens/latency).
# SRP/DRY check: Pass — reuses _anthropic_auth_headers, no other tool loop exists server-side

import json
import time

import httpx

from llm_providers_anthropic import _anthropic_auth_headers, _is_oauth_token

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_MAX_TOKENS = 8192
DEFAULT_MAX_ROUNDS = 6
REQUEST_TIMEOUT = 120.0
MAX_RETRIES = 5
INITIAL_BACKOFF = 5

# Thread-local-ish context for monitoring — set by caller before run_tool_loop
_monitor_ctx = {
    'game_id': 'snake',
    'generation': 0,
}


def set_monitor_context(game_id='snake', generation=0):
    """Set context for LLM call monitoring. Called by arena_heartbeat before each evolution."""
    _monitor_ctx['game_id'] = game_id
    _monitor_ctx['generation'] = generation


def run_tool_loop(
    api_key: str,
    system_prompt: str,
    user_message: str,
    tools: list[dict],
    handler,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
) -> list[dict]:
    """Run a multi-turn Anthropic tool-calling loop.

    Args:
        api_key: Anthropic API key or OAuth token (sk-ant-oat*).
        system_prompt: System-level instructions.
        user_message: Initial user message.
        tools: List of tool dicts with {name, description, parameters}.
        handler: Callable(name: str, args: dict) -> str. Executes tools.
        model: Anthropic model ID.
        max_tokens: Max tokens per response.
        max_rounds: Max tool-calling iterations.

    Returns:
        Conversation log list.
    """
    conversation_log = []
    ant_tools = [
        {
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["parameters"],
        }
        for t in tools
    ]

    auth_type = 'oauth' if _is_oauth_token(api_key) else 'api_key'
    messages = [{"role": "user", "content": user_message}]
    headers = _anthropic_auth_headers(api_key)

    for round_num in range(max_rounds):
        messages = _truncate_messages(messages)

        body = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system_prompt,
            "tools": ant_tools,
            "messages": messages,
        }

        try:
            raw = _call_with_retry(headers, body, model=model, auth_type=auth_type)
        except Exception as exc:
            conversation_log.append({"type": "error", "content": str(exc)})
            print(f"    [arena-tool] API error on round {round_num + 1}: {exc}")
            break

        stop_reason = raw.get("stop_reason", "end_turn")
        content = raw.get("content", [])

        text_parts = [
            b.get("text", "")
            for b in content
            if b.get("type") == "text" and b.get("text")
        ]
        if text_parts:
            conversation_log.append(
                {"type": "assistant", "content": "\n".join(text_parts)}
            )

        messages.append({"role": "assistant", "content": content})

        if stop_reason != "tool_use":
            print(f"    [arena-tool] Finished after {round_num + 1} rounds")
            break

        tool_results = []
        for block in content:
            if block.get("type") != "tool_use":
                continue

            name = block["name"]
            args = block.get("input", {})

            args_display = dict(args)
            if "code" in args_display:
                args_display["code"] = args_display["code"][:200] + "..."
            conversation_log.append(
                {"type": "tool_call", "name": name, "args": args_display}
            )
            print(f"    [arena-tool] Tool: {name}({json.dumps(args)[:100]}...)")

            result = handler(name, args)
            result_str = str(result)
            if len(result_str) > 3000:
                result_str = result_str[:3000] + "\n... (truncated)"

            conversation_log.append(
                {"type": "tool_result", "name": name, "result": result_str[:500]}
            )
            print(f"    [arena-tool]   -> {result_str[:150].replace(chr(10), ' ')}")

            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block["id"],
                    "content": result_str,
                }
            )

        messages.append({"role": "user", "content": tool_results})

    return conversation_log


def _log_call(model, status, http_status, input_tokens=0, output_tokens=0,
              latency_ms=0, error_message=None, auth_type=None):
    """Log an API call to the monitoring table. Non-blocking, never raises."""
    try:
        from db_arena import arena_log_llm_call
        arena_log_llm_call(
            game_id=_monitor_ctx.get('game_id', 'snake'),
            generation=_monitor_ctx.get('generation', 0),
            model=model,
            status=status,
            http_status=http_status,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=latency_ms,
            error_message=error_message,
            auth_type=auth_type,
        )
    except Exception as exc:
        print(f"    [arena-monitor] Log failed (non-fatal): {exc}")


def _call_with_retry(headers: dict, body: dict, model: str = '', auth_type: str = '') -> dict:
    """POST to Anthropic API with exponential backoff on 429/5xx."""
    backoff = INITIAL_BACKOFF
    last_status = 0
    for attempt in range(MAX_RETRIES + 1):
        start_ms = time.time() * 1000
        try:
            resp = httpx.post(
                ANTHROPIC_API_URL, headers=headers, json=body, timeout=REQUEST_TIMEOUT,
            )
        except Exception as exc:
            latency = time.time() * 1000 - start_ms
            _log_call(model, 'error', 0, latency_ms=latency,
                      error_message=str(exc)[:500], auth_type=auth_type)
            raise

        latency = time.time() * 1000 - start_ms

        if resp.status_code == 200:
            data = resp.json()
            usage = data.get('usage', {})
            _log_call(
                model, 'success', 200,
                input_tokens=usage.get('input_tokens', 0),
                output_tokens=usage.get('output_tokens', 0),
                latency_ms=latency, auth_type=auth_type,
            )
            return data

        last_status = resp.status_code

        if resp.status_code == 429:
            log_status = 'rate_limited'
        elif resp.status_code in (500, 502, 503, 529) and attempt < MAX_RETRIES:
            log_status = 'retry'
        else:
            log_status = 'error'

        error_text = resp.text[:500] if resp.text else ''
        _log_call(model, log_status, resp.status_code, latency_ms=latency,
                  error_message=error_text, auth_type=auth_type)

        if resp.status_code in (429, 500, 502, 503, 529) and attempt < MAX_RETRIES:
            retry_after = resp.headers.get("retry-after")
            if retry_after and retry_after.isdigit():
                wait = min(int(retry_after), 300)
            else:
                wait = backoff
            wait = max(wait, backoff)
            print(f"    [arena-tool] {resp.status_code} on attempt {attempt + 1}, retrying in {wait}s...")
            time.sleep(wait)
            backoff = min(backoff * 2, 300)
            continue

        raise Exception(f"Anthropic API error {resp.status_code}: {resp.text[:300]}")
    raise Exception(f"Anthropic API: max retries exceeded (last status {last_status})")


def _truncate_messages(messages: list[dict], max_chars: int = 20000) -> list[dict]:
    """Truncate conversation to fit within context limits."""
    for msg in messages:
        if msg.get("role") == "user" and isinstance(msg.get("content"), list):
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    content = block.get("content", "")
                    if isinstance(content, str) and len(content) > 1500:
                        block["content"] = content[:1500] + "\n... (truncated)"
        if msg.get("role") == "assistant" and isinstance(msg.get("content"), list):
            for block in msg["content"]:
                if isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text", "")
                    if len(text) > 1500:
                        block["text"] = text[:1500] + "\n... (truncated)"

    total = sum(len(json.dumps(m, default=str)) for m in messages)
    if total <= max_chars:
        return messages
    if len(messages) <= 6:
        return messages
    head = messages[:1]
    tail = messages[-4:]
    return head + tail
