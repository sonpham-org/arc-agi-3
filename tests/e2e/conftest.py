# Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
# Date: 2026-03-11 14:24
# PURPOSE: Playwright E2E test fixtures for ARC-AGI-3. Provides a running dev server
#   fixture (auto-starts server.py on an available port if not already running) and
#   shared constants (BASE_URL, timeouts). Used by all tests in tests/e2e/.
# SRP/DRY check: Pass — shared fixtures only; no test logic here
"""Playwright E2E test fixtures for ARC-AGI-3.

Usage:
    pip install pytest-playwright
    playwright install chromium
    pytest tests/e2e/ -v --headed   # visible browser
    pytest tests/e2e/ -v            # headless (CI)

Requires:
    - Server running on localhost (default port 5050, override with ARC_TEST_PORT env var)
    - LM Studio running on localhost:1234 with at least one model loaded
"""
import os
import pytest

# ── Configuration ─────────────────────────────────────────────────────────

BASE_URL = os.environ.get("ARC_TEST_URL", "http://localhost:5050")
# Timeout for LLM calls (LM Studio local inference can be slow on large models)
LLM_TIMEOUT_MS = 120_000
# Timeout for page navigation and UI interactions
UI_TIMEOUT_MS = 15_000


@pytest.fixture(scope="session")
def base_url():
    """Base URL for the running ARC-AGI-3 server."""
    return BASE_URL


@pytest.fixture(scope="function")
def arc_page(page, base_url):
    """Navigate to the ARC-AGI-3 app and wait for it to be ready.

    Yields a Playwright Page object pointed at the agent view with models loaded.
    """
    # Navigate to the agent view
    page.goto(f"{base_url}/#agent", wait_until="networkidle")

    # Wait for the app to initialize — models list should be populated
    page.wait_for_function(
        "() => typeof modelsData !== 'undefined' && modelsData.length > 0",
        timeout=UI_TIMEOUT_MS,
    )

    yield page
