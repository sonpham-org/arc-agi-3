# Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
# Date: 2026-03-12 12:52
# PURPOSE: LLM provider calls and retry logic for ARC-AGI-3. Handles communication
#   with Gemini, Anthropic, Cloudflare, OpenAI-compatible endpoints, Ollama, Groq,
#   Mistral, HuggingFace. Provides retry with exponential backoff and cost tracking.
#   Extracted from agent.py in Phase 11. Depends on models.py and constants.py.
# SRP/DRY check: Pass — all LLM API calls consolidated; agent.py uses as orchestrator
"""LLM provider calls and retry logic for ARC-AGI-3.

Extracted from agent.py (Phase 11).

Handles all provider-specific implementations (Gemini, Anthropic, Cloudflare, etc.),
call routing, and retry with exponential backoff for rate limits and transient errors.
"""

import os
import time
from dataclasses import dataclass

import httpx

from constants import SYSTEM_MSG
from models import MODELS, compute_cost


@dataclass
class LLMResult:
    """Metadata from a single LLM call (text + tokens + timing)."""
    text: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    thinking_text: str | None = None
    duration_ms: int = 0
    model: str = ""
    error: str | None = None
    attempt: int = 0
    cost: float = 0.0


def _call_openai_compatible(url: str, api_key: str, model: str, messages: list,
                             temperature: float, max_tokens: int) -> dict:
    """Call an OpenAI-compatible endpoint (Groq, Mistral, HuggingFace, Ollama, Cloudflare)."""
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    resp = httpx.post(
        url,
        headers=headers,
        json={"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
        timeout=90.0,
    )
    resp.raise_for_status()
    data = resp.json()
    usage = data.get("usage", {})
    return {
        "text": data["choices"][0]["message"]["content"],
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
    }


def _call_anthropic(model: str, messages: list, system: str,
                    temperature: float, max_tokens: int) -> dict:
    """Call Anthropic API (Claude)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "system": system,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=90.0,
    )
    resp.raise_for_status()
    data = resp.json()
    usage = data.get("usage", {})
    return {
        "text": data["content"][0]["text"],
        "input_tokens": usage.get("input_tokens", 0),
        "output_tokens": usage.get("output_tokens", 0),
    }


def _call_gemini(model_name: str, prompt: str, temperature: float, max_tokens: int,
                  tools_enabled: bool = False, session_id: str = "",
                  grid=None, prev_grid=None, thinking_budget: int = 0) -> dict:
    """Call Google Gemini API with optional thinking and tool support."""
    from google import genai
    import re as _re
    api_key = os.environ.get("GEMINI_API_KEY", "")
    client = genai.Client(api_key=api_key)

    # Thinking models (2.5+, 3.x) need an explicit thinking budget,
    # otherwise thinking eats the entire max_output_tokens and the
    # actual response gets truncated.
    is_thinking = bool(_re.search(r"2\.5|3-pro|3-flash|3\.1", model_name))
    thinking_cfg = None
    if is_thinking:
        budget = thinking_budget if thinking_budget > 0 else 1024
        thinking_cfg = genai.types.ThinkingConfig(
            thinking_budget=budget,
            include_thoughts=True,
        )

    config = genai.types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_tokens,
        thinking_config=thinking_cfg,
    )

    # Enable run_python tool if requested and we have a session context
    if tools_enabled and session_id:
        from code_sandbox import get_tool_declarations, execute_python
        config.tools = [get_tool_declarations()]

    contents = [genai.types.Content(
        role="user",
        parts=[genai.types.Part.from_text(text=f"{SYSTEM_MSG}\n\n{prompt}")],
    )]

    total_input = 0
    total_output = 0
    total_thinking = 0
    all_thinking_text = []
    max_rounds = 3 if (tools_enabled and session_id) else 1

    for round_i in range(max_rounds):
        # On the last round, remove tools to force a text answer
        if round_i == max_rounds - 1 and config.tools:
            config.tools = None
            # Add instruction to force JSON text output
            contents.append(genai.types.Content(
                role="user",
                parts=[genai.types.Part.from_text(
                    text="Tool calls are no longer available. Now output your final answer as a JSON object."
                )],
            ))

        response = client.models.generate_content(
            model=model_name, contents=contents, config=config,
        )
        usage = getattr(response, "usage_metadata", None)
        total_input += (getattr(usage, "prompt_token_count", 0) or 0) if usage else 0
        total_output += (getattr(usage, "candidates_token_count", 0) or 0) if usage else 0
        total_thinking += (getattr(usage, "thoughts_token_count", 0) or 0) if usage else 0

        # Extract thinking content from response parts
        if response.candidates and response.candidates[0].content:
            for part in (response.candidates[0].content.parts or []):
                if getattr(part, "thought", False) and hasattr(part, "text") and part.text:
                    all_thinking_text.append(part.text)

        # Handle MALFORMED_FUNCTION_CALL — model tried to call a tool but
        # formatted it as a code block instead of a proper function call
        if response.candidates and tools_enabled and session_id:
            fr = getattr(response.candidates[0], 'finish_reason', None)
            fr_str = str(fr).upper() if fr else ""
            if "MALFORMED" in fr_str:
                raw_text = ""
                try:
                    raw_text = response.text or ""
                except Exception:
                    fm = getattr(response.candidates[0], 'finish_message', None)
                    if fm:
                        raw_text = fm
                code_match = _re.search(r'```python\s*\n(.*?)```', raw_text, _re.DOTALL)
                if code_match:
                    code = code_match.group(1).strip()
                    print(f"  [tools] recovered MALFORMED code ({len(code)} chars), executing")
                    output = execute_python(session_id, code, grid, prev_grid)
                    contents.append(genai.types.Content(
                        role="model",
                        parts=[genai.types.Part.from_function_call(
                            name="run_python", args={"code": code}
                        )],
                    ))
                    contents.append(genai.types.Content(
                        role="user",
                        parts=[genai.types.Part.from_function_response(
                            name="run_python",
                            response={"result": output},
                        )],
                    ))
                    config.tools = None  # force text answer on next round
                    continue
                else:
                    config.tools = None
                    continue

        # Check for function calls in the response
        if response.candidates and response.candidates[0].content and tools_enabled and session_id:
            model_parts = response.candidates[0].content.parts or []
            fn_call_parts = [p for p in model_parts if p.function_call]

            if fn_call_parts:
                contents.append(response.candidates[0].content)
                fn_response_parts = []
                for part in fn_call_parts:
                    fc = part.function_call
                    code = fc.args.get("code", "") if fc.args else ""
                    print(f"  [tools] run_python ({len(code)} chars)")
                    output = execute_python(session_id, code, grid, prev_grid)
                    fn_response_parts.append(
                        genai.types.Part.from_function_response(
                            name=fc.name,
                            response={"result": output},
                        )
                    )
                contents.append(genai.types.Content(
                    role="user",
                    parts=fn_response_parts,
                ))
                continue  # next round

        # No function call — extract final text and return
        break

    # Extract text safely — response may contain function_call parts
    # if the model exhausted all rounds without giving a text answer
    final_text = ""
    try:
        final_text = response.text or ""
    except (ValueError, AttributeError):
        # response.text raises ValueError when there are only non-text parts
        if response.candidates and response.candidates[0].content:
            text_parts = [p.text for p in response.candidates[0].content.parts
                          if hasattr(p, 'text') and p.text]
            final_text = "\n".join(text_parts)

    return {
        "text": final_text,
        "input_tokens": total_input,
        "output_tokens": total_output,
        "thinking_tokens": total_thinking,
        "thinking_text": "\n".join(all_thinking_text) if all_thinking_text else None,
    }


def _call_cloudflare(model: str, messages: list, temperature: float, max_tokens: int) -> dict:
    """Call Cloudflare AI API (OpenAI-compatible wrapper)."""
    api_key = os.environ.get("CLOUDFLARE_API_KEY", "")
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1/chat/completions"
    return _call_openai_compatible(url, api_key, model, messages, temperature, max_tokens)


def call_model(model_key: str, prompt: str, cfg: dict, role: str = "executor",
               tools_enabled: bool = False, session_id: str = "",
               grid=None, prev_grid=None, thinking_budget: int = 0) -> str:
    """Route to the right provider. Returns just the text response (string).

    For metadata (tokens, timing, errors), use call_model_with_metadata() instead.

    Optional kwargs for Gemini tool calling:
        tools_enabled: enable run_python tool
        session_id: sandbox session ID
        grid / prev_grid: current and previous game grids (list-of-lists)
    """
    info = MODELS.get(model_key)
    if info is None:
        raise ValueError(f"Unknown model: {model_key}")

    r = cfg["reasoning"]
    temp = r["temperature"]
    # Role-based max_tokens
    role_token_keys = {
        "executor": "max_tokens",
        "planner": "planner_max_tokens",
        "monitor": "monitor_max_tokens",
        "world_model": "world_model_max_tokens",
        "condenser": "reflection_max_tokens",
        "reflector": "reflection_max_tokens",
    }
    max_tok = r.get(role_token_keys.get(role, "max_tokens"), r["max_tokens"])

    provider = info["provider"]
    api_model = info["api_model"]
    messages = [{"role": "system", "content": SYSTEM_MSG}, {"role": "user", "content": prompt}]

    result = None
    if provider == "gemini":
        result = _call_gemini(api_model, prompt, temp, max_tok,
                            tools_enabled=tools_enabled, session_id=session_id,
                            grid=grid, prev_grid=prev_grid,
                            thinking_budget=thinking_budget)
    elif provider == "anthropic":
        result = _call_anthropic(api_model, [{"role": "user", "content": prompt}],
                                SYSTEM_MSG, temp, max_tok)
    elif provider == "cloudflare":
        result = _call_cloudflare(api_model, messages, temp, max_tok)
    elif provider == "ollama":
        result = _call_openai_compatible(info["url"], "", api_model, messages, temp, max_tok)
    elif provider == "lmstudio":
        result = _call_openai_compatible("http://localhost:1234/v1/chat/completions", "no-key-needed", api_model, messages, temp, max_tok)
    else:
        # Groq / Mistral / HuggingFace (OpenAI-compatible)
        api_key = os.environ.get(info["env_key"], "")
        result = _call_openai_compatible(info["url"], api_key, api_model, messages, temp, max_tok)
    
    # Extract and return just the text
    return result.get("text", "") if result else ""


def call_model_with_metadata(model_key: str, prompt: str, cfg: dict, role: str = "executor",
                              retries: int = 10,
                              tools_enabled: bool = False, session_id: str = "",
                              grid=None, prev_grid=None,
                              thinking_budget: int = 0) -> LLMResult:
    """Call LLM with retries, returning full metadata (tokens, timing, errors).

    Retries up to `retries` times (default 10) with exponential backoff.
    Rate-limit (429) waits scale from 15s to 120s; server errors use shorter waits.
    """
    t0 = time.time()
    for attempt in range(retries + 1):
        try:
            result = call_model(model_key, prompt, cfg, role,
                                tools_enabled=tools_enabled, session_id=session_id,
                                grid=grid, prev_grid=prev_grid,
                                thinking_budget=thinking_budget)
            duration_ms = int((time.time() - t0) * 1000)
            in_tok = result.get("input_tokens", 0)
            out_tok = result.get("output_tokens", 0)
            think_tok = result.get("thinking_tokens", 0)
            cost = compute_cost(model_key, in_tok, out_tok, think_tok)
            return LLMResult(
                text=result["text"],
                input_tokens=in_tok,
                output_tokens=out_tok,
                thinking_tokens=think_tok,
                thinking_text=result.get("thinking_text"),
                duration_ms=duration_ms,
                model=model_key,
                attempt=attempt,
                cost=cost,
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                wait = min(10 * (2 ** attempt), 120)  # exponential: 10, 20, 40, 80, 120, 120...
                print(f"  [Rate limited] attempt {attempt+1}/{retries+1}, waiting {wait}s...")
                time.sleep(wait)
            elif e.response.status_code in (500, 502, 503, 529) and attempt < retries:
                wait = min(5 * (2 ** attempt), 60)  # exponential: 5, 10, 20, 40, 60...
                print(f"  [HTTP {e.response.status_code}] attempt {attempt+1}/{retries+1}, retrying in {wait}s...")
                time.sleep(wait)
            else:
                duration_ms = int((time.time() - t0) * 1000)
                print(f"  [HTTP error {e.response.status_code}]: {e}")
                return LLMResult(error=str(e), duration_ms=duration_ms, model=model_key, attempt=attempt)
        except Exception as e:
            err_str = str(e).lower()
            # Retry on transient errors (quota, timeout, server errors)
            if attempt < retries and any(k in err_str for k in ("429", "quota", "rate", "timeout", "503", "500", "overloaded", "resource_exhausted")):
                is_rate_limit = any(k in err_str for k in ("429", "quota", "rate", "resource_exhausted"))
                wait = min(10 * (2 ** attempt), 120) if is_rate_limit else min(5 * (2 ** attempt), 60)
                print(f"  [LLM error] {e} — attempt {attempt+1}/{retries+1}, retrying in {wait}s...")
                time.sleep(wait)
            else:
                duration_ms = int((time.time() - t0) * 1000)
                print(f"  [LLM error]: {e}")
                return LLMResult(error=str(e), duration_ms=duration_ms, model=model_key, attempt=attempt)
    duration_ms = int((time.time() - t0) * 1000)
    return LLMResult(error="max retries exceeded", duration_ms=duration_ms, model=model_key, attempt=retries)


def call_model_with_retry(model_key: str, prompt: str, cfg: dict, role: str = "executor",
                           retries: int = 10) -> str | None:
    """Thin wrapper: returns just the text (or None). For backward compatibility."""
    result = call_model_with_metadata(model_key, prompt, cfg, role, retries)
    return result.text
