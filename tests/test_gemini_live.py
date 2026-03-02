"""Live integration tests against the Gemini API.

Requires GEMINI_API_KEY env var. Run with:
    pytest tests/test_gemini_live.py -v

These tests make real API calls (~free with Gemini Flash).
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).parent.parent / ".env")

from agent import call_model, load_config
from server import _extract_json

pytestmark = pytest.mark.skipif(
    not os.environ.get("GEMINI_API_KEY"),
    reason="GEMINI_API_KEY not set",
)

MODEL = "gemini-2.5-flash"
CFG = load_config()
CFG["reasoning"]["temperature"] = 0.0
CFG["reasoning"]["max_tokens"] = 1024


class TestGeminiBasic:
    """Basic connectivity and response parsing."""

    def test_returns_nonempty_string(self):
        raw = call_model(MODEL, "Say hello in exactly one word.", CFG, role="executor")
        assert isinstance(raw, str)
        assert len(raw.strip()) > 0

    def test_json_response_parseable(self):
        prompt = (
            'Respond with EXACTLY this JSON and nothing else: '
            '{"status": "ok", "action": 1, "data": {}}'
        )
        raw = call_model(MODEL, prompt, CFG, role="executor")
        parsed = _extract_json(raw)
        assert parsed is not None
        assert parsed.get("action") == 1

    def test_plan_json_response(self):
        prompt = (
            'Respond with EXACTLY this JSON and nothing else: '
            '{"observation": "test", "reasoning": "test", '
            '"plan": [{"action": 1, "data": {}}, {"action": 3, "data": {}}]}'
        )
        raw = call_model(MODEL, prompt, CFG, role="executor")
        parsed = _extract_json(raw)
        assert parsed is not None
        assert "plan" in parsed
        assert len(parsed["plan"]) == 2


class TestGeminiGamePrompt:
    """Test with a prompt closer to real game usage."""

    def test_action_in_valid_range(self):
        prompt = """You are playing a grid game. Available actions:
0=idle, 1=right, 2=up, 3=left, 4=down, 5=action1, 6=action2, 7=action3

The grid is 8x8 with a character at position (2,3) and a door at (7,7).

Respond with EXACTLY this JSON format:
{"observation": "<what you see>", "reasoning": "<your plan>", "action": <number>, "data": {}}

Choose the best action to move toward the door."""
        raw = call_model(MODEL, prompt, CFG, role="executor")
        parsed = _extract_json(raw)
        assert parsed is not None, f"Failed to parse: {raw[:200]}"
        assert "action" in parsed, f"No 'action' key in: {parsed}"
        assert isinstance(parsed["action"], int)
        assert 0 <= parsed["action"] <= 7

    def test_plan_mode_response(self):
        prompt = """You are playing a grid game. Available actions:
0=idle, 1=right, 2=up, 3=left, 4=down, 5=action1, 6=action2, 7=action3

The grid is 8x8 with a character at position (2,3) and a door at (7,7).

Respond with EXACTLY this JSON format:
{"observation": "<what you see>", "reasoning": "<your plan>", "plan": [{"action": <n>, "data": {}}, ...]}

Plan 3 steps to move toward the door."""
        raw = call_model(MODEL, prompt, CFG, role="executor")
        parsed = _extract_json(raw)
        assert parsed is not None, f"Failed to parse: {raw[:200]}"
        assert "plan" in parsed, f"No 'plan' key in: {parsed}"
        assert isinstance(parsed["plan"], list)
        assert len(parsed["plan"]) >= 1
        for step in parsed["plan"]:
            assert "action" in step
            assert 0 <= step["action"] <= 7
