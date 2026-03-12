"""Pytest configuration and shared fixtures for ARC-AGI-3 test suite."""

import os
import pytest
import arc_agi


@pytest.fixture
def arcade():
    """Minimal arcade instance for tests that need it."""
    return arc_agi.Arcade()


@pytest.fixture
def cfg():
    """Default config for tests."""
    from agent import load_config
    c = load_config()
    c["reasoning"]["temperature"] = 0.0
    c["reasoning"]["max_tokens"] = 50
    return c


def pytest_generate_tests(metafunc):
    """Parametrize tests that use special fixtures."""
    if "provider" in metafunc.fixturenames:
        providers = ["groq", "mistral", "gemini", "anthropic", "cloudflare", "huggingface", "ollama"]
        metafunc.parametrize("provider", providers)
    
    if "game_id" in metafunc.fixturenames:
        # Provide a minimal set of games for testing
        game_ids = ["game_id_1"]
        metafunc.parametrize("game_id", game_ids)
    
    if "model_key" in metafunc.fixturenames:
        # Use a cheap model for testing, or None for dry-run
        model_keys = [None]  # None means dry-run mode
        metafunc.parametrize("model_key", model_keys)
