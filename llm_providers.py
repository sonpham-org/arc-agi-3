"""LLM provider call functions and routing for ARC-AGI-3."""

import base64
import hashlib
import io
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Optional

from models import (
    MODEL_REGISTRY, SYSTEM_MSG, THINKING_BUDGETS,
    OLLAMA_VISION_MODELS, _discovered_local_models,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# COPILOT AUTH STATE
# ═══════════════════════════════════════════════════════════════════════════

_COPILOT_TOKEN_FILE = Path(__file__).parent / "data" / ".copilot_token"


def _load_copilot_token() -> Optional[str]:
    try:
        if _COPILOT_TOKEN_FILE.exists():
            return _COPILOT_TOKEN_FILE.read_text().strip() or None
    except Exception:
        pass
    return None


def _save_copilot_token(token: Optional[str]):
    try:
        _COPILOT_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        if token:
            _COPILOT_TOKEN_FILE.write_text(token)
        elif _COPILOT_TOKEN_FILE.exists():
            _COPILOT_TOKEN_FILE.unlink()
    except Exception:
        pass


copilot_oauth_token: Optional[str] = _load_copilot_token()
copilot_api_token: Optional[str] = None
copilot_token_expiry: float = 0.0
copilot_device_code: Optional[str] = None
copilot_auth_lock = threading.Lock()

# ═══════════════════════════════════════════════════════════════════════════
# PER-PROVIDER THROTTLE
# ═══════════════════════════════════════════════════════════════════════════

PROVIDER_MIN_DELAY: dict[str, float] = {
    "gemini":      4.0,
    "anthropic":   1.0,
    "groq":        2.5,
    "mistral":     2.0,
    "huggingface": 6.0,
    "cloudflare":  0.5,
    "copilot":     4.0,
    "ollama":      0.0,
}
_provider_last_call: dict[str, float] = {}
_throttle_lock = threading.Lock()

# ═══════════════════════════════════════════════════════════════════════════
# TOOL EXECUTION — Python sandbox for Gemini function calling
# ═══════════════════════════════════════════════════════════════════════════

_tool_sessions: dict[str, dict] = {}
_tool_session_lock = threading.Lock()


def _get_tool_declarations():
    from google import genai
    return genai.types.Tool(function_declarations=[
        genai.types.FunctionDeclaration(
            name="run_python",
            description=(
                "Execute Python code to analyse the game grid. "
                "Pre-imported: numpy (as np), collections, itertools. "
                "Available variables: `grid` (numpy 2D int array of current grid), "
                "`prev_grid` (numpy 2D int array of previous grid, or None). "
                "Variables you define persist across calls within the same turn. "
                "Use print() to return results. "
                "IMPORTANT: Keep code short and simple — use numpy vectorized ops, "
                "avoid nested loops over large arrays. Combine analyses into one call "
                "when possible. You have max 3 tool calls per turn, so be efficient."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "code": {
                        "type": "STRING",
                        "description": "Python code to execute. Use print() for output.",
                    }
                },
                "required": ["code"],
            },
        ),
    ])


_BLOCKED_MODULES = frozenset({
    'os', 'sys', 'subprocess', 'shutil', 'pathlib', 'socket', 'http',
    'urllib', 'requests', 'httpx', 'aiohttp', 'ftplib', 'smtplib',
    'ctypes', 'multiprocessing', 'signal', 'importlib', 'code', 'codeop',
    'compileall', 'py_compile', 'zipimport', 'pkgutil', 'pkg_resources',
})


def _safe_import(name, *args, **kwargs):
    top_level = name.split('.')[0]
    if top_level in _BLOCKED_MODULES:
        raise ImportError(f"Module '{name}' is not allowed in the sandbox")
    return __builtins__['__import__'](name, *args, **kwargs) \
        if isinstance(__builtins__, dict) \
        else __import__(name, *args, **kwargs)


def _get_or_create_tool_session(session_id: str, grid, prev_grid) -> dict:
    import numpy as np
    import collections
    import itertools

    with _tool_session_lock:
        sess = _tool_sessions.get(session_id)
        if sess is None:
            if isinstance(__builtins__, dict):
                safe_builtins = dict(__builtins__)
            else:
                safe_builtins = {k: getattr(__builtins__, k) for k in dir(__builtins__)
                                 if not k.startswith('_')}
                safe_builtins['__import__'] = __builtins__.__import__

            safe_builtins['open'] = None
            safe_builtins['eval'] = None
            safe_builtins['exec'] = None
            safe_builtins['compile'] = None
            safe_builtins['breakpoint'] = None
            safe_builtins['exit'] = None
            safe_builtins['quit'] = None
            safe_builtins['__import__'] = _safe_import

            ns = {
                '__builtins__': safe_builtins,
                'np': np,
                'numpy': np,
                'collections': collections,
                'itertools': itertools,
                'Counter': collections.Counter,
                'defaultdict': collections.defaultdict,
            }
            sess = {'namespace': ns, 'created_at': time.time()}
            _tool_sessions[session_id] = sess

    ns = sess['namespace']
    ns['grid'] = np.array(grid) if grid else np.array([[]])
    ns['prev_grid'] = np.array(prev_grid) if prev_grid else None
    return sess


def _execute_python(session_id: str, code: str, grid, prev_grid, timeout: float = 5.0) -> str:
    sess = _get_or_create_tool_session(session_id, grid, prev_grid)
    ns = sess['namespace']

    output_buf = io.StringIO()
    error = [None]

    def _run():
        import builtins
        def captured_print(*args, **kwargs):
            kwargs['file'] = output_buf
            builtins.print(*args, **kwargs)
        if isinstance(ns['__builtins__'], dict):
            ns['__builtins__']['print'] = captured_print
        try:
            exec(code, ns)
        except Exception as e:
            error[0] = f"{type(e).__name__}: {e}"

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        return "[TIMEOUT] Code execution exceeded 5 seconds."

    output = output_buf.getvalue()
    if error[0]:
        output = (output + "\n" + error[0]).strip()

    if len(output) > 4000:
        output = output[:4000] + "\n... [truncated]"

    return output or "(no output)"


def _cleanup_tool_session(session_id: str):
    with _tool_session_lock:
        _tool_sessions.pop(session_id, None)


# ═══════════════════════════════════════════════════════════════════════════
# GEMINI CONTEXT CACHING
# ═══════════════════════════════════════════════════════════════════════════

_gemini_cache_registry: dict[tuple, dict] = {}
_gemini_cache_lock = threading.Lock()
_GEMINI_CACHE_MIN_CHARS = 130_000
_GEMINI_CACHE_TTL_MINUTES = 30


def _get_or_create_gemini_cache(model: str, static_content: str) -> str | None:
    if len(static_content) < _GEMINI_CACHE_MIN_CHARS:
        return None

    content_hash = hashlib.sha256(static_content.encode()).hexdigest()[:16]
    cache_key = (model, content_hash)

    with _gemini_cache_lock:
        cached = _gemini_cache_registry.get(cache_key)
        if cached and time.time() < cached["expires_at"]:
            return cached["cache_name"]

    try:
        from google import genai
        api_key = os.environ.get("GEMINI_API_KEY", "")
        client = genai.Client(api_key=api_key)

        cache = client.caches.create(
            model=model,
            config=genai.types.CreateCachedContentConfig(
                contents=[genai.types.Content(
                    role="user",
                    parts=[genai.types.Part.from_text(text=static_content)],
                )],
                ttl=f"{_GEMINI_CACHE_TTL_MINUTES * 60}s",
                display_name=f"arc-agi-{content_hash[:8]}",
            ),
        )

        with _gemini_cache_lock:
            _gemini_cache_registry[cache_key] = {
                "cache_name": cache.name,
                "expires_at": time.time() + (_GEMINI_CACHE_TTL_MINUTES * 60) - 60,
            }
        logger.info(f"Created Gemini cache: {cache.name} for model {model}")
        return cache.name
    except Exception as e:
        logger.warning(f"Gemini cache creation failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════════════════
# LLM CALL FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def _call_gemini(model_name: str, prompt: str, image_b64: str | None = None,
                  tools_enabled: bool = False, session_id: str | None = None,
                  grid=None, prev_grid=None,
                  cached_content_name: str | None = None,
                  thinking_level: str = "low",
                  max_tokens: int = 16384) -> dict | str:
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY", "")
    client = genai.Client(api_key=api_key)

    parts = []
    if image_b64:
        image_bytes = base64.b64decode(image_b64)
        parts.append(genai.types.Part.from_bytes(data=image_bytes, mime_type="image/png"))
    parts.append(genai.types.Part.from_text(text=f"{SYSTEM_MSG}\n\n{prompt}"))
    contents = [genai.types.Content(role="user", parts=parts)]

    is_thinking_model = any(x in model_name for x in ("2.5", "3-pro", "3-flash", "3.1"))
    budget = THINKING_BUDGETS.get(thinking_level, 1024)
    config = genai.types.GenerateContentConfig(
        temperature=0.3,
        max_output_tokens=max_tokens,
    )
    if is_thinking_model:
        config.thinking_config = genai.types.ThinkingConfig(
            thinking_budget=budget,
        )
    if tools_enabled:
        config.tools = [_get_tool_declarations()]
    if cached_content_name:
        config.cached_content = cached_content_name

    tool_calls_log = []
    max_rounds = 3

    for round_i in range(max_rounds):
        if round_i == max_rounds - 1 and config.tools:
            config.tools = None

        response = client.models.generate_content(
            model=model_name, contents=contents, config=config,
        )

        if response.candidates:
            fr = getattr(response.candidates[0], 'finish_reason', None)
            fr_str = str(fr).upper() if fr else ""
            if "MALFORMED" in fr_str and tools_enabled and session_id:
                raw_text = ""
                try:
                    raw_text = response.text or ""
                except Exception:
                    fm = getattr(response.candidates[0], 'finish_message', None)
                    if fm:
                        raw_text = fm
                code_match = re.search(r'```python\s*\n(.*?)```', raw_text, re.DOTALL)
                if code_match:
                    code = code_match.group(1).strip()
                    logger.info(
                        f"Recovered code from MALFORMED_FUNCTION_CALL (len={len(code)}), executing as run_python"
                    )
                    output = _execute_python(session_id, code, grid, prev_grid)
                    tool_calls_log.append({
                        "name": "run_python",
                        "arguments": {"code": code},
                        "output": output,
                    })
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
                    config.tools = None
                    continue
                else:
                    logger.warning(
                        "MALFORMED_FUNCTION_CALL but couldn't extract code, retrying without tools"
                    )
                    config.tools = None
                    continue

        has_function_call = False
        if response.candidates and response.candidates[0].content:
            model_parts = response.candidates[0].content.parts or []
            fn_call_parts = [p for p in model_parts if p.function_call]

            if fn_call_parts and tools_enabled and session_id:
                has_function_call = True
                contents.append(response.candidates[0].content)

                fn_response_parts = []
                for part in fn_call_parts:
                    fc = part.function_call
                    code = fc.args.get("code", "") if fc.args else ""
                    logger.info(f"Tool call: {fc.name}, code length: {len(code)}")

                    output = _execute_python(session_id, code, grid, prev_grid)

                    tool_calls_log.append({
                        "name": fc.name,
                        "arguments": {"code": code},
                        "output": output,
                    })

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
                continue

        final_text = response.text if response.text else ""

        truncated = False
        if response.candidates:
            fr = getattr(response.candidates[0], 'finish_reason', None)
            if fr and str(fr).upper() in ("MAX_TOKENS", "2"):
                truncated = True

        usage = {}
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            um = response.usage_metadata
            usage = {
                "prompt_tokens": getattr(um, 'prompt_token_count', 0) or 0,
                "completion_tokens": getattr(um, 'candidates_token_count', 0) or 0,
                "total_tokens": getattr(um, 'total_token_count', 0) or 0,
            }

        cache_active = cached_content_name is not None
        if tools_enabled:
            return {"text": final_text, "tool_calls": tool_calls_log, "usage": usage,
                    "cache_active": cache_active, "truncated": truncated}
        return {"text": final_text, "truncated": truncated} if truncated else final_text

    final_text = ""
    try:
        final_text = response.text or ""
    except Exception:
        pass
    if tools_enabled:
        return {"text": final_text, "tool_calls": tool_calls_log, "usage": {},
                "cache_active": cached_content_name is not None}
    return final_text


def _call_anthropic(model_name: str, prompt: str, image_b64: str | None = None, max_tokens: int = 16384) -> str:
    import httpx
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    content_blocks: list[dict] = []
    if image_b64:
        content_blocks.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": image_b64},
        })
    content_blocks.append({"type": "text", "text": prompt})

    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model_name, "system": SYSTEM_MSG,
            "messages": [{"role": "user", "content": content_blocks}],
            "temperature": 0.3, "max_tokens": max_tokens,
        },
        timeout=90.0,
    )
    resp.raise_for_status()
    data = resp.json()
    text = data["content"][0]["text"]
    if data.get("stop_reason") == "max_tokens":
        return {"text": text, "truncated": True}
    return text


def _call_openai_compatible(url: str, api_key: str, model: str, prompt: str,
                             image_b64: str | None = None,
                             extra_headers: dict | None = None,
                             max_tokens: int = 16384) -> str:
    import httpx
    if image_b64:
        user_content: list | str = [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
            {"type": "text", "text": prompt},
        ]
    else:
        user_content = prompt

    messages = [
        {"role": "system", "content": SYSTEM_MSG},
        {"role": "user", "content": user_content},
    ]
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    body = {"model": model, "messages": messages, "temperature": 0.3, "max_tokens": max_tokens}

    last_exc = None
    for attempt in range(10):
        resp = httpx.post(url, headers=headers, json=body, timeout=90.0)
        if resp.status_code == 429:
            retry_after = float(resp.headers.get("retry-after", min(10 * (2 ** attempt), 120)))
            retry_after = min(retry_after, 120)
            logger.info(f"Rate limited by {url}, retrying in {retry_after}s (attempt {attempt+1}/10)")
            time.sleep(retry_after)
            last_exc = httpx.HTTPStatusError(
                f"429 Too Many Requests", request=resp.request, response=resp)
            continue
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        if data["choices"][0].get("finish_reason") == "length":
            return {"text": text, "truncated": True}
        return text
    raise last_exc


def _call_cloudflare(model_name: str, prompt: str, image_b64: str | None = None, max_tokens: int = 16384) -> str:
    import httpx
    api_key = os.environ.get("CLOUDFLARE_API_KEY", "")
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    if not api_key or not account_id:
        raise ValueError("CLOUDFLARE_API_KEY and CLOUDFLARE_ACCOUNT_ID must be set")

    messages = [
        {"role": "system", "content": SYSTEM_MSG},
        {"role": "user", "content": prompt},
    ]

    if image_b64 and "vision" in model_name:
        messages[-1] = {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                {"type": "text", "text": prompt},
            ],
        }

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/{model_name}"
    resp = httpx.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"messages": messages, "temperature": 0.3, "max_tokens": max_tokens},
        timeout=90.0,
    )
    resp.raise_for_status()
    data = resp.json()
    result = data.get("result", {})
    if isinstance(result, str):
        return result
    response = result.get("response", "")
    if isinstance(response, dict):
        return json.dumps(response)
    return response or json.dumps(result)


def _call_ollama(model_name: str, prompt: str, image_b64: str | None = None) -> str:
    import ollama
    messages = [
        {"role": "system", "content": SYSTEM_MSG},
        {"role": "user", "content": prompt},
    ]
    if image_b64 and model_name.split(":")[0] in OLLAMA_VISION_MODELS:
        messages[-1]["images"] = [image_b64]

    response = ollama.chat(
        model=model_name, messages=messages,
        options={"temperature": 0.3, "num_predict": 2048},
    )
    return response["message"]["content"]


def _get_copilot_token() -> str:
    global copilot_api_token, copilot_token_expiry
    with copilot_auth_lock:
        if not copilot_oauth_token:
            raise ValueError("Copilot not authenticated. Complete the OAuth flow first.")
        if time.time() > copilot_token_expiry - 300:
            import httpx
            resp = httpx.get(
                "https://api.github.com/copilot_internal/v2/token",
                headers={"Authorization": f"token {copilot_oauth_token}",
                         "Accept": "application/json"},
                timeout=30.0,
            )
            if resp.status_code != 200:
                logger.error("Copilot token exchange failed: %s %s", resp.status_code, resp.text)
                resp.raise_for_status()
            data = resp.json()
            logger.info("Copilot token exchange OK, keys: %s", list(data.keys()))
            copilot_api_token = data["token"]
            copilot_token_expiry = data.get("expires_at", time.time() + 1500)
        return copilot_api_token


def _call_copilot(model_name: str, prompt: str, image_b64: str | None = None) -> str:
    token = _get_copilot_token()
    return _call_openai_compatible(
        url="https://api.githubcopilot.com/chat/completions",
        api_key=token,
        model=model_name,
        prompt=prompt,
        image_b64=image_b64,
        extra_headers={
            "Copilot-Integration-Id": "vscode-chat",
            "editor-version": "vscode/1.100.0",
            "user-agent": "GitHubCopilotChat/0.24.0",
        },
    )


# ═══════════════════════════════════════════════════════════════════════════
# ROUTING
# ═══════════════════════════════════════════════════════════════════════════

def _throttle_provider(provider: str):
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


def _route_model_call(model_key: str, prompt: str, image_b64: str | None = None,
                      tools_enabled: bool = False, session_id: str | None = None,
                      grid=None, prev_grid=None,
                      cached_content_name: str | None = None,
                      thinking_level: str = "low",
                      max_tokens: int = 16384) -> str | dict:
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
    if provider == "cloudflare":
        return _call_cloudflare(api_model, prompt, img, max_tokens=max_tokens)
    if provider == "copilot":
        return _call_copilot(api_model, prompt, img)
    if provider == "ollama":
        return _call_ollama(api_model, prompt, img)

    # OpenAI-compatible (Groq, Mistral, HuggingFace)
    api_key = os.environ.get(info.get("env_key", ""), "")
    url = info.get("url", "")
    return _call_openai_compatible(url, api_key, api_model, prompt, None, max_tokens=max_tokens)
