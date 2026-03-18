# Author: Claude Opus 4.6
# Date: 2026-03-18 15:00
# PURPOSE: Multi-provider tool-calling loop for arena evolution.
#   Anthropic: prompt caching (system + tools cached across rounds).
#   Gemini: Google GenAI SDK tool calling.
#   Session-level stats (api_calls, tool_calls, tokens, cache hits, cost).
#   Returns {log, stats} — caller logs one session record, not per-call.
#   Per-model max_tokens and timeout scaling for verbose models (Sonnet/Opus).
# SRP/DRY check: Pass — only arena tool-calling loop, no other tool loop exists server-side

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

# Sonnet/Opus are much more verbose than Haiku — need higher limits
_MODEL_MAX_TOKENS = {
    'claude-haiku-4-5-20251001': 8192,
    'claude-sonnet-4-6': 16384,
    'claude-opus-4-6': 16384,
}
_MODEL_TIMEOUT = {
    'claude-haiku-4-5-20251001': 120.0,
    'claude-sonnet-4-6': 180.0,
    'claude-opus-4-6': 300.0,
}

# Cost per 1M tokens (input, output)
_ANTHROPIC_COSTS = {
    'claude-haiku-4-5-20251001': (1.00, 5.00),
    'claude-sonnet-4-6': (3.00, 15.00),
    'claude-opus-4-6': (15.00, 75.00),
}
_GEMINI_COSTS = {
    'gemini-3.1-pro-preview': (1.25, 10.0),
    'gemini-3-pro-preview': (1.25, 10.0),
    'gemini-2.5-pro': (1.25, 10.0),
}
_CACHE_WRITE_MULT = 1.25   # 25% more than base input
_CACHE_READ_MULT = 0.10    # 90% cheaper than base input


# ─── Backward compat (called by arena_heartbeat, now a no-op) ─────────
def set_monitor_context(game_id='snake', generation=0):
    """No-op — kept for backward compatibility. Session stats replace per-call logging."""
    pass


# ═══════════════════════════════════════════════════════════════════════
#   Anthropic tool loop (with prompt caching)
# ═══════════════════════════════════════════════════════════════════════

def run_tool_loop(
    api_key: str,
    system_prompt: str,
    user_message: str,
    tools: list[dict],
    handler,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
) -> dict:
    """Run Anthropic tool-calling loop with prompt caching.

    System prompt and tools are cached across rounds — subsequent rounds
    only pay cache-read price (~90% cheaper) for that content.

    Returns:
        {log: list, stats: {api_calls, tool_calls, input_tokens,
         output_tokens, cache_read_tokens, cache_creation_tokens,
         total_latency_ms, rounds, cost_usd}}
    """
    stats = _empty_stats()
    conversation_log = []

    # Per-model limits: Sonnet/Opus need higher max_tokens and timeout
    effective_max_tokens = _MODEL_MAX_TOKENS.get(model, max_tokens)
    effective_timeout = _MODEL_TIMEOUT.get(model, REQUEST_TIMEOUT)

    # Build tools with cache_control on last tool for prompt caching
    ant_tools = [
        {"name": t["name"], "description": t["description"],
         "input_schema": t["parameters"]}
        for t in tools
    ]
    if ant_tools:
        ant_tools[-1]["cache_control"] = {"type": "ephemeral"}

    messages = [{"role": "user", "content": user_message}]
    headers = _anthropic_auth_headers(api_key)
    # Enable prompt caching — without this header, cache_control fields are silently ignored
    existing_beta = headers.get("anthropic-beta", "")
    cache_beta = "prompt-caching-2024-07-31"
    headers["anthropic-beta"] = f"{existing_beta},{cache_beta}" if existing_beta else cache_beta

    for round_num in range(max_rounds):
        messages = _truncate_messages(messages)

        body = {
            "model": model,
            "max_tokens": effective_max_tokens,
            "system": [
                {"type": "text", "text": system_prompt,
                 "cache_control": {"type": "ephemeral"}}
            ],
            "tools": ant_tools,
            "messages": messages,
        }

        start_ms = time.time() * 1000
        try:
            raw = _call_with_retry(headers, body, timeout=effective_timeout)
        except Exception as exc:
            stats['total_latency_ms'] += time.time() * 1000 - start_ms
            conversation_log.append({"type": "error", "content": str(exc)})
            print(f"    [arena-tool] API error on round {round_num + 1}: {exc}")
            break

        latency = time.time() * 1000 - start_ms

        # Accumulate session stats
        stats['api_calls'] += 1
        stats['rounds'] = round_num + 1
        stats['total_latency_ms'] += latency
        usage = raw.get('usage', {})
        stats['input_tokens'] += usage.get('input_tokens', 0)
        stats['output_tokens'] += usage.get('output_tokens', 0)
        stats['cache_read_tokens'] += usage.get('cache_read_input_tokens', 0)
        stats['cache_creation_tokens'] += usage.get('cache_creation_input_tokens', 0)

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

        if stop_reason == "max_tokens":
            # Response truncated — nudge model to call create_agent on next round
            print(f"    [arena-tool] max_tokens hit on round {round_num + 1}, nudging to call tool")
            messages.append({"role": "user", "content": "Your response was truncated. Please call create_agent now with the code you have. Keep it concise."})
            continue

        if stop_reason != "tool_use":
            cache_info = ""
            if stats['cache_read_tokens']:
                cache_info = f", cache_read={stats['cache_read_tokens']}tok"
            print(f"    [arena-tool] Done: {round_num + 1} rounds, "
                  f"{stats['api_calls']} calls, {stats['tool_calls']} tools{cache_info}")
            break

        tool_results = []
        for block in content:
            if block.get("type") != "tool_use":
                continue

            name = block["name"]
            args = block.get("input", {})
            stats['tool_calls'] += 1

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

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block["id"],
                "content": result_str,
            })

        messages.append({"role": "user", "content": tool_results})

    # Calculate cost
    inp_price, out_price = _ANTHROPIC_COSTS.get(model, (3.0, 15.0))
    stats['cost_usd'] = (
        stats['input_tokens'] * inp_price
        + stats['output_tokens'] * out_price
        + stats['cache_creation_tokens'] * inp_price * _CACHE_WRITE_MULT
        + stats['cache_read_tokens'] * inp_price * _CACHE_READ_MULT
    ) / 1_000_000

    return {'log': conversation_log, 'stats': stats}


# ═══════════════════════════════════════════════════════════════════════
#   Gemini tool loop
# ═══════════════════════════════════════════════════════════════════════

def run_tool_loop_gemini(
    api_key: str,
    system_prompt: str,
    user_message: str,
    tools: list[dict],
    handler,
    model: str = 'gemini-3.1-pro-preview',
    max_tokens: int = DEFAULT_MAX_TOKENS,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
) -> dict:
    """Run Gemini tool-calling loop via Google GenAI SDK.

    Returns same {log, stats} format as run_tool_loop.
    """
    from google import genai

    stats = _empty_stats()
    conversation_log = []

    client = genai.Client(api_key=api_key)

    # Convert tools to Gemini FunctionDeclaration format
    declarations = []
    for t in tools:
        params = _gemini_schema(t.get('parameters', {}))
        declarations.append(genai.types.FunctionDeclaration(
            name=t['name'],
            description=t['description'],
            parameters=params,
        ))
    gemini_tools = genai.types.Tool(function_declarations=declarations)

    config = genai.types.GenerateContentConfig(
        system_instruction=system_prompt,
        tools=[gemini_tools],
        max_output_tokens=max_tokens,
    )

    contents = [user_message]

    for round_num in range(max_rounds):
        start_ms = time.time() * 1000
        try:
            response = client.models.generate_content(
                model=model, contents=contents, config=config,
            )
        except Exception as exc:
            stats['total_latency_ms'] += time.time() * 1000 - start_ms
            conversation_log.append({"type": "error", "content": str(exc)})
            print(f"    [arena-gemini] API error on round {round_num + 1}: {exc}")
            break

        latency = time.time() * 1000 - start_ms
        stats['api_calls'] += 1
        stats['rounds'] = round_num + 1
        stats['total_latency_ms'] += latency

        # Usage metadata
        um = getattr(response, 'usage_metadata', None)
        if um:
            stats['input_tokens'] += getattr(um, 'prompt_token_count', 0) or 0
            stats['output_tokens'] += getattr(um, 'candidates_token_count', 0) or 0
            stats['cache_read_tokens'] += getattr(um, 'cached_content_token_count', 0) or 0

        candidate = response.candidates[0] if response.candidates else None
        if not candidate or not candidate.content or not candidate.content.parts:
            break

        has_function_calls = False
        function_responses = []

        for part in candidate.content.parts:
            if hasattr(part, 'function_call') and part.function_call:
                has_function_calls = True
                fc = part.function_call
                name = fc.name
                args = dict(fc.args) if fc.args else {}
                stats['tool_calls'] += 1

                args_display = dict(args)
                if "code" in args_display:
                    args_display["code"] = str(args_display["code"])[:200] + "..."
                conversation_log.append(
                    {"type": "tool_call", "name": name, "args": args_display}
                )
                print(f"    [arena-gemini] Tool: {name}({json.dumps(args, default=str)[:100]}...)")

                result = handler(name, args)
                result_str = str(result)
                if len(result_str) > 3000:
                    result_str = result_str[:3000] + "\n... (truncated)"

                conversation_log.append(
                    {"type": "tool_result", "name": name, "result": result_str[:500]}
                )
                print(f"    [arena-gemini]   -> {result_str[:150].replace(chr(10), ' ')}")

                function_responses.append(
                    genai.types.Part.from_function_response(
                        name=name,
                        response={"result": result_str},
                    )
                )
            elif hasattr(part, 'text') and part.text:
                conversation_log.append(
                    {"type": "assistant", "content": part.text}
                )

        if not has_function_calls:
            print(f"    [arena-gemini] Done: {round_num + 1} rounds, "
                  f"{stats['api_calls']} calls, {stats['tool_calls']} tools")
            break

        # Add model response + function results to conversation
        contents.append(candidate.content)
        contents.append(genai.types.Content(
            role="user", parts=function_responses,
        ))

    # Calculate cost
    inp_price, out_price = _GEMINI_COSTS.get(model, (1.25, 10.0))
    stats['cost_usd'] = (
        stats['input_tokens'] * inp_price
        + stats['output_tokens'] * out_price
    ) / 1_000_000

    return {'log': conversation_log, 'stats': stats}


# ═══════════════════════════════════════════════════════════════════════
#   Shared helpers
# ═══════════════════════════════════════════════════════════════════════

def _empty_stats():
    return {
        'api_calls': 0, 'tool_calls': 0,
        'input_tokens': 0, 'output_tokens': 0,
        'cache_read_tokens': 0, 'cache_creation_tokens': 0,
        'total_latency_ms': 0, 'rounds': 0,
        'cost_usd': 0.0,
    }


def _gemini_schema(schema):
    """Convert JSON Schema types to Gemini format (uppercase type names)."""
    if isinstance(schema, dict):
        result = {}
        for k, v in schema.items():
            if k == 'type' and isinstance(v, str):
                result[k] = v.upper()
            else:
                result[k] = _gemini_schema(v)
        return result
    elif isinstance(schema, list):
        return [_gemini_schema(item) for item in schema]
    return schema


def _call_with_retry(headers: dict, body: dict, timeout: float = REQUEST_TIMEOUT) -> dict:
    """POST to Anthropic API with exponential backoff on 429/5xx."""
    backoff = INITIAL_BACKOFF
    last_status = 0
    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = httpx.post(
                ANTHROPIC_API_URL, headers=headers, json=body, timeout=timeout,
            )
        except Exception as exc:
            if attempt < MAX_RETRIES:
                print(f"    [arena-tool] Network error attempt {attempt + 1}: {exc}")
                time.sleep(backoff)
                backoff = min(backoff * 2, 300)
                continue
            raise

        if resp.status_code == 200:
            return resp.json()

        last_status = resp.status_code

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
