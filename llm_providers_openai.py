"""OpenAI + compatible providers — OpenAI, LM Studio, Cloudflare, Ollama, Groq, Mistral, HuggingFace."""

import json
import logging
import os
import time
from typing import Optional

from models import SYSTEM_MSG, OLLAMA_VISION_MODELS

logger = logging.getLogger(__name__)

# OpenAI API key initialization
openai_api_key: Optional[str] = None


def _call_openai(model_name: str, prompt: str, image_b64: str | None = None, max_tokens: int = 16384) -> str | dict:
    """Call OpenAI API or OpenAI-compatible endpoints."""
    import httpx
    api_key = openai_api_key or ""
    if not api_key:
        raise ValueError("OPENAI_API_KEY not configured")

    # o-series and codex models require max_completion_tokens (not max_tokens) and no temperature
    is_o_series = model_name.startswith(("o1", "o3", "o4", "codex"))

    if image_b64 and not is_o_series:
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
    body: dict = {"model": model_name, "messages": messages}
    if is_o_series:
        body["max_completion_tokens"] = max_tokens
    else:
        body["max_tokens"] = max_tokens
        body["temperature"] = 0.3

    resp = httpx.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=body,
        timeout=120.0,
    )
    resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["message"]["content"]
    if data["choices"][0].get("finish_reason") == "length":
        return {"text": text, "truncated": True}
    return text


def _call_openai_compatible(url: str, api_key: str, model: str, prompt: str,
                             image_b64: str | None = None,
                             extra_headers: dict | None = None,
                             max_tokens: int = 16384) -> str:
    """Call an OpenAI-compatible API endpoint (LM Studio, Groq, Mistral, etc.)."""
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
        resp = httpx.post(url, headers=headers, json=body, timeout=600.0)
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
    """Call Cloudflare Workers AI."""
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
    """Call Ollama local model."""
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
