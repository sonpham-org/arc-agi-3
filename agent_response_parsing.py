# Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
# Date: 2026-03-12 12:52
# PURPOSE: LLM response parsing and action extraction for ARC-AGI-3. Provides
#   JSON parsing with fallback strategies to handle truncation, malformed output,
#   and unparseable responses. Extracted from agent.py in Phase 11.
# SRP/DRY check: Pass — all response parsing logic consolidated; agent.py uses as handler
"""LLM response parsing and action extraction for ARC-AGI-3.

Extracted from agent.py (Phase 11).

Provides JSON extraction with fallback parsing strategies:
1. Direct JSON extraction from model output
2. Fallback model parsing (using a different cheap model)
3. Force extraction (most conservative action)
4. Absolute fallback (pick first non-RESET action)
"""

import json
import os
import re

from agent_llm import call_model
from constants import ACTION_NAMES
from models import MODELS


FALLBACK_PARSE_MODELS = [
    "gemini-2.5-flash",
    "groq/llama-3.3-70b-versatile",
    "mistral/mistral-small-latest",
]


def _parse_json(content: str) -> dict | None:
    """Extract JSON from model output, stripping thinking blocks first."""
    # Strip <think>...</think> blocks (some models emit these)
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    try:
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(content[start:end])
    except json.JSONDecodeError:
        pass
    return None


def _fallback_parse(raw: str, available: list[int], cfg: dict,
                    executor_model: str) -> dict | None:
    """Use a cheap model to extract action from an unparseable LLM response."""
    # Pick a fallback model different from the executor (avoid same failure mode)
    fallback_model = None
    for m in FALLBACK_PARSE_MODELS:
        if m == executor_model:
            continue
        info = MODELS.get(m)
        if not info:
            continue
        env_key = info.get("env_key", "")
        if not env_key or os.environ.get(env_key):
            fallback_model = m
            break
    if not fallback_model:
        return None

    prompt = (
        "An LLM was asked to pick a game action and respond with JSON, but its "
        "response was malformed or truncated. Extract the intended action from "
        "the response below.\n\n"
        f"Available actions: {available}\n"
        f"Raw response (may be truncated):\n{raw[:1500]}\n\n"
        "Respond with ONLY valid JSON: "
        '{"action": <int>, "data": {}, "observation": "<what the model saw>", '
        '"reasoning": "<what the model intended>"}'
    )
    try:
        fallback_result = call_model(fallback_model, prompt, cfg, role="executor")
        fallback_raw = fallback_result["text"]
        parsed = _parse_json(fallback_raw)
        if parsed and "action" in parsed:
            print(f"  [fallback parse] recovered action={parsed['action']} via {fallback_model}")
            return parsed
    except Exception as e:
        print(f"  [fallback parse] failed: {e}")
    return None


def _force_extract_action(raw: str, available: list[int], cfg: dict,
                          executor_model: str) -> dict | None:
    """Last-resort: ask a cheap model to pick the most conservative action
    from unparseable output. Returns parsed dict or None."""
    fallback_model = None
    for m in FALLBACK_PARSE_MODELS:
        if m == executor_model:
            continue
        info = MODELS.get(m)
        if not info:
            continue
        env_key = info.get("env_key", "")
        if not env_key or os.environ.get(env_key):
            fallback_model = m
            break
    if not fallback_model:
        return None

    non_reset = [a for a in available if a != 0]
    safe_default = non_reset[0] if non_reset else (available[0] if available else 1)

    prompt = (
        "An LLM was asked to pick a game action and respond with JSON, but its "
        "response was completely unparseable. Extract the most likely intended action "
        "from the raw output below. If you truly cannot determine one, pick the most "
        f"conservative action (use {safe_default}).\n\n"
        f"Available actions: {available}\n"
        f"Raw response (may be truncated):\n{raw[:2000]}\n\n"
        "Respond with ONLY valid JSON:\n"
        '{"action": <int>, "data": {}, "observation": "<best guess of what model saw>", '
        '"reasoning": "<best guess of what model intended>"}'
    )
    try:
        result = call_model(fallback_model, prompt, cfg, role="executor")
        parsed = _parse_json(result["text"])
        if parsed and "action" in parsed:
            print(f"  [force-action] extracted action={parsed['action']} via {fallback_model}")
            return parsed
    except Exception as e:
        print(f"  [force-action] failed: {e}")
    return None


def _fallback_action(available: list[int]) -> int:
    """Absolute last resort: pick first non-RESET action deterministically."""
    candidates = [a for a in available if a != 0]
    return candidates[0] if candidates else (available[0] if available else 1)
