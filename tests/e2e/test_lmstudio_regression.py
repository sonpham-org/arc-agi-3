# Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
# Date: 2026-03-11 14:24
# PURPOSE: Playwright E2E regression tests for LM Studio integration in ARC-AGI-3.
#   Tests the full user flow: navigate to #agent view, start a new session, select a
#   game, select the first available local LM Studio model, click Agent Autoplay, and
#   verify that LLM proxy calls actually fire to the server. Covers model discovery,
#   dummy key injection, provider routing, CORS proxy, and system-message promotion.
#   Depends on: running server (localhost:5050), running LM Studio (localhost:1234).
# SRP/DRY check: Pass — E2E tests only; unit tests for extracted modules are in test_refactor_modules.py
"""Playwright E2E regression tests for LM Studio integration.

Requires:
    - ARC-AGI-3 server running (default: localhost:5050)
    - LM Studio running on localhost:1234 with at least one model loaded

Usage:
    pytest tests/e2e/test_lmstudio_regression.py -v --headed
    pytest tests/e2e/test_lmstudio_regression.py -v  # headless
    pytest tests/e2e/test_lmstudio_regression.py -k test_model_discovery -v --headed
"""
import os
import re
import sys
from pathlib import Path

import pytest

# Skip all tests if playwright not available or server not running
try:
    from playwright.sync_api import expect
    # Import conftest constants by adding the test directory to sys.path
    _e2e_dir = Path(__file__).parent
    if str(_e2e_dir) not in sys.path:
        sys.path.insert(0, str(_e2e_dir))

    # Now import the constants from conftest
    import conftest as _conftest
    LLM_TIMEOUT_MS = _conftest.LLM_TIMEOUT_MS
    UI_TIMEOUT_MS = _conftest.UI_TIMEOUT_MS
    _HAS_PLAYWRIGHT = True
except (ImportError, ModuleNotFoundError):
    _HAS_PLAYWRIGHT = False
    LLM_TIMEOUT_MS = 120_000
    UI_TIMEOUT_MS = 15_000

# Mark module to skip if playwright not available or ARC_TEST_URL not set
pytestmark = pytest.mark.skipif(
    not _HAS_PLAYWRIGHT or not os.environ.get("ARC_TEST_URL"),
    reason="Requires pytest-playwright and running ARC-AGI-3 server (ARC_TEST_URL)"
)


# ═══════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def navigate_to_agent_view(page, base_url):
    """Navigate to /#agent and wait for the app to initialize."""
    page.goto(f"{base_url}/#agent", wait_until="networkidle")
    # Wait for models to be loaded (modelsData populated by loadModels())
    page.wait_for_function(
        "() => typeof modelsData !== 'undefined' && modelsData.length > 0",
        timeout=UI_TIMEOUT_MS,
    )


def create_new_session(page):
    """Click 'New Session' from the menu/empty state and wait for the session UI."""
    # The app may show the menu view (with .menu-new-btn) or the empty app state
    # (with .new-session-hero). Try the menu button first, fall back to hero.
    menu_btn = page.locator(".menu-new-btn")
    hero_btn = page.locator(".new-session-hero")
    new_tab_btn = page.locator(".session-tab-new")

    if menu_btn.is_visible():
        menu_btn.click()
    elif hero_btn.is_visible():
        hero_btn.click()
    elif new_tab_btn.is_visible():
        new_tab_btn.click()
    else:
        # Fallback: call createNewSession() directly
        page.evaluate("createNewSession()")

    # Wait for the game sidebar to appear with game cards
    page.locator("#gameList .game-card").first.wait_for(state="visible", timeout=UI_TIMEOUT_MS)


def select_first_game(page):
    """Click the first game card in the sidebar to load it."""
    first_game = page.locator("#gameList .game-card").first
    first_game.click()
    # Wait for the game to initialize — the canvas or grid area should appear
    page.locator("#autoPlayBtn").wait_for(state="visible", timeout=UI_TIMEOUT_MS)


def get_active_model_select_id(page):
    """Return the ID of the currently active model <select> based on scaffolding type.

    Different scaffolding types use different model selects:
      - linear / linear_interrupt → #modelSelect
      - three_system → #sf_ts_plannerModelSelect
      - two_system → #sf_2s_plannerModelSelect
      - rlm → #sf_rlm_modelSelect
      - agent_spawn → #sf_as_orchestratorModelSelect
    """
    scaffolding_type = page.evaluate("activeScaffoldingType")
    select_map = {
        "linear": "modelSelect",
        "linear_interrupt": "modelSelect",
        "three_system": "sf_ts_plannerModelSelect",
        "two_system": "sf_2s_plannerModelSelect",
        "rlm": "sf_rlm_modelSelect",
        "agent_spawn": "sf_as_orchestratorModelSelect",
    }
    return select_map.get(scaffolding_type, "modelSelect")


def select_first_lmstudio_model(page):
    """Select the first LM Studio model in the active model dropdown.

    Finds the first <option> inside an <optgroup> labeled 'Lmstudio' in the
    currently active model select element.
    """
    select_id = get_active_model_select_id(page)
    sel = page.locator(f"#{select_id}")

    # Wait for the select to have LM Studio options
    page.wait_for_function(
        f"""() => {{
            const sel = document.getElementById('{select_id}');
            if (!sel) return false;
            const opts = sel.querySelectorAll('optgroup[label*="Lmstudio"] option, optgroup[label*="lmstudio"] option, optgroup[label*="LM Studio"] option');
            return opts.length > 0;
        }}""",
        timeout=UI_TIMEOUT_MS,
    )

    # Get the value of the first LM Studio option
    first_lms_value = page.evaluate(
        f"""() => {{
            const sel = document.getElementById('{select_id}');
            // Try multiple possible optgroup label formats
            for (const label of ['Lmstudio', 'lmstudio', 'LM Studio']) {{
                const grp = sel.querySelector(`optgroup[label*="${{label}}"]`);
                if (grp) {{
                    const opt = grp.querySelector('option');
                    if (opt) return opt.value;
                }}
            }}
            return null;
        }}"""
    )

    assert first_lms_value, f"No LM Studio model found in #{select_id}"

    # Select the model
    sel.select_option(first_lms_value)

    # Trigger change event (some listeners may need it)
    page.evaluate(
        f"document.getElementById('{select_id}').dispatchEvent(new Event('change', {{bubbles: true}}))"
    )

    return first_lms_value


def switch_scaffolding(page, scaffolding_type):
    """Switch to a specific scaffolding type via the dropdown."""
    page.locator("#scaffoldingSelect").select_option(scaffolding_type)
    # Wait for the settings panel to re-render
    page.wait_for_timeout(500)


def click_autoplay(page):
    """Click the Agent Autoplay button."""
    page.locator("#autoPlayBtn").click()


# ═══════════════════════════════════════════════════════════════════════════
# TESTS — Model Discovery
# ═══════════════════════════════════════════════════════════════════════════

class TestModelDiscovery:
    """Verify LM Studio models appear in the model dropdowns."""

    def test_lmstudio_models_in_models_data(self, arc_page):
        """modelsData should contain at least one LM Studio model."""
        lms_count = arc_page.evaluate(
            "modelsData.filter(m => m.provider === 'lmstudio').length"
        )
        assert lms_count > 0, "No LM Studio models discovered — is LM Studio running on localhost:1234?"

    def test_lmstudio_dummy_key_set(self, arc_page):
        """localStorage should have the dummy key for LM Studio."""
        key = arc_page.evaluate("localStorage.getItem('byok_key_lmstudio')")
        assert key == "local-no-key-needed", f"Expected dummy key, got: {key!r}"

    def test_lmstudio_models_in_main_select(self, arc_page):
        """Main model selector should have an Lmstudio optgroup with options."""
        has_lms = arc_page.evaluate("""() => {
            const sel = document.getElementById('modelSelect');
            if (!sel) return false;
            const grp = sel.querySelector('optgroup[label*="Lmstudio"], optgroup[label*="lmstudio"]');
            return grp && grp.querySelectorAll('option').length > 0;
        }""")
        assert has_lms, "No LM Studio optgroup in #modelSelect"


# ═══════════════════════════════════════════════════════════════════════════
# TESTS — Session + Game Selection
# ═══════════════════════════════════════════════════════════════════════════

class TestSessionSetup:
    """Verify session creation and game selection flow."""

    def test_navigate_to_agent_view(self, page, base_url):
        """Navigating to /#agent should show the agent/play view."""
        navigate_to_agent_view(page, base_url)
        # The outer layout or menu/empty state should be visible
        visible = page.evaluate("""() => {
            return document.getElementById('emptyAppState')?.offsetParent !== null
                || document.getElementById('menuView')?.offsetParent !== null
                || document.getElementById('outerLayout')?.offsetParent !== null;
        }""")
        assert visible, "Agent view not visible after navigation"

    def test_create_new_session(self, page, base_url):
        """Creating a new session should show the game sidebar."""
        navigate_to_agent_view(page, base_url)
        create_new_session(page)
        # Game sidebar should be visible with at least one game
        game_count = page.locator("#gameList .game-card").count()
        assert game_count > 0, "No games in sidebar after creating session"

    def test_select_game(self, page, base_url):
        """Selecting a game should load it and show the transport controls."""
        navigate_to_agent_view(page, base_url)
        create_new_session(page)
        select_first_game(page)
        # Autoplay button should be visible
        expect(page.locator("#autoPlayBtn")).to_be_visible()


# ═══════════════════════════════════════════════════════════════════════════
# TESTS — LM Studio Integration (Linear scaffolding)
# ═══════════════════════════════════════════════════════════════════════════

class TestLMStudioLinear:
    """Test LM Studio calls via the default Linear scaffolding."""

    def test_select_lmstudio_model_linear(self, page, base_url):
        """Should be able to select an LM Studio model in the linear scaffolding."""
        navigate_to_agent_view(page, base_url)
        create_new_session(page)
        select_first_game(page)
        # Ensure we're on linear scaffolding (default)
        scaffolding = page.evaluate("activeScaffoldingType")
        if scaffolding != "linear":
            switch_scaffolding(page, "linear")
        model = select_first_lmstudio_model(page)
        assert model, "Failed to select LM Studio model"

    def test_autoplay_fires_lmstudio_proxy(self, page, base_url):
        """Clicking Autoplay with an LM Studio model should fire a /api/llm/lmstudio-proxy request."""
        navigate_to_agent_view(page, base_url)
        create_new_session(page)
        select_first_game(page)
        scaffolding = page.evaluate("activeScaffoldingType")
        if scaffolding != "linear":
            switch_scaffolding(page, "linear")
        select_first_lmstudio_model(page)

        # Listen for the proxy request
        proxy_requests = []

        def on_request(request):
            if "/api/llm/lmstudio-proxy" in request.url:
                proxy_requests.append(request)

        page.on("request", on_request)

        # Click autoplay
        click_autoplay(page)

        # Wait for at least one proxy request (with generous timeout for LM Studio inference)
        page.wait_for_function(
            "() => document.getElementById('autoPlayBtn')?.textContent?.includes('Stop')"
            " || document.getElementById('autoPlayBtn')?.textContent?.includes('Pause')",
            timeout=UI_TIMEOUT_MS,
        )

        # Give LM Studio time to receive the call
        page.wait_for_timeout(5000)

        assert len(proxy_requests) > 0, (
            "No /api/llm/lmstudio-proxy request detected. "
            "LM Studio calls are not reaching the server proxy."
        )

    def test_autoplay_gets_response(self, page, base_url):
        """Autoplay should get a response from LM Studio and increment the step count."""
        navigate_to_agent_view(page, base_url)
        create_new_session(page)
        select_first_game(page)
        scaffolding = page.evaluate("activeScaffoldingType")
        if scaffolding != "linear":
            switch_scaffolding(page, "linear")
        select_first_lmstudio_model(page)

        # Listen for proxy responses
        proxy_responses = []

        def on_response(response):
            if "/api/llm/lmstudio-proxy" in response.url:
                proxy_responses.append(response)

        page.on("response", on_response)

        click_autoplay(page)

        # Wait for at least one completed LLM response
        try:
            page.wait_for_function(
                """() => {
                    const ss = typeof getActiveSession === 'function' ? getActiveSession() : null;
                    return ss && ss.stepCount > 0;
                }""",
                timeout=LLM_TIMEOUT_MS,
            )
        except Exception:
            # Stop autoplay before failing
            page.evaluate("if (typeof stopAutoPlay === 'function') stopAutoPlay()")
            raise AssertionError(
                f"Step count did not increment after {LLM_TIMEOUT_MS}ms. "
                f"Proxy responses received: {len(proxy_responses)}. "
                "LM Studio may not be responding."
            )

        # Stop autoplay
        page.evaluate("if (typeof stopAutoPlay === 'function') stopAutoPlay()")

        assert len(proxy_responses) > 0, "No proxy responses received"
        # Verify at least one response was successful
        ok_responses = [r for r in proxy_responses if r.status == 200]
        assert len(ok_responses) > 0, (
            f"All {len(proxy_responses)} proxy responses failed. "
            f"Statuses: {[r.status for r in proxy_responses]}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# TESTS — LM Studio Integration (Three-System scaffolding)
# ═══════════════════════════════════════════════════════════════════════════

class TestLMStudioThreeSystem:
    """Test LM Studio calls via Three-System scaffolding (planner/monitor/wm)."""

    def test_select_lmstudio_model_three_system(self, page, base_url):
        """Should be able to select an LM Studio model in the three-system planner."""
        navigate_to_agent_view(page, base_url)
        create_new_session(page)
        select_first_game(page)
        switch_scaffolding(page, "three_system")
        model = select_first_lmstudio_model(page)
        assert model, "Failed to select LM Studio model in three-system planner"

    def test_three_system_autoplay_fires_proxy(self, page, base_url):
        """Three-system autoplay should fire LM Studio proxy requests."""
        navigate_to_agent_view(page, base_url)
        create_new_session(page)
        select_first_game(page)
        switch_scaffolding(page, "three_system")
        select_first_lmstudio_model(page)

        proxy_requests = []

        def on_request(request):
            if "/api/llm/lmstudio-proxy" in request.url:
                proxy_requests.append(request)

        page.on("request", on_request)

        click_autoplay(page)

        # Wait for proxy requests — three-system may take longer due to multi-agent turns
        page.wait_for_timeout(10000)

        # Stop autoplay
        page.evaluate("if (typeof stopAutoPlay === 'function') stopAutoPlay()")

        assert len(proxy_requests) > 0, (
            "No /api/llm/lmstudio-proxy requests from three-system scaffolding. "
            "The planner LLM call is not routing through the proxy."
        )


# ═══════════════════════════════════════════════════════════════════════════
# TESTS — Error Handling
# ═══════════════════════════════════════════════════════════════════════════

class TestLMStudioErrors:
    """Test error handling when LM Studio returns errors."""

    def test_no_empty_error_objects_in_console(self, page, base_url):
        """Console errors should contain actual messages, not empty {} objects."""
        navigate_to_agent_view(page, base_url)
        create_new_session(page)
        select_first_game(page)
        scaffolding = page.evaluate("activeScaffoldingType")
        if scaffolding != "linear":
            switch_scaffolding(page, "linear")
        select_first_lmstudio_model(page)

        # Capture console errors
        console_errors = []

        def on_console(msg):
            if msg.type == "error":
                console_errors.append(msg.text)

        page.on("console", on_console)

        click_autoplay(page)
        page.wait_for_timeout(8000)
        page.evaluate("if (typeof stopAutoPlay === 'function') stopAutoPlay()")

        # Check that no console errors are just empty "{}"
        empty_errors = [e for e in console_errors if e.strip() == "{}" or e.endswith(": {}")]
        assert len(empty_errors) == 0, (
            f"Found {len(empty_errors)} console errors with empty '{{}}' objects. "
            "Error messages are being swallowed. "
            f"Empty errors: {empty_errors[:5]}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# TESTS — Proxy Request Validation
# ═══════════════════════════════════════════════════════════════════════════

class TestProxyRequestFormat:
    """Verify the proxy request has the correct format."""

    def test_proxy_request_has_required_fields(self, page, base_url):
        """The lmstudio-proxy request body should have model, messages, base_url."""
        navigate_to_agent_view(page, base_url)
        create_new_session(page)
        select_first_game(page)
        scaffolding = page.evaluate("activeScaffoldingType")
        if scaffolding != "linear":
            switch_scaffolding(page, "linear")
        select_first_lmstudio_model(page)

        captured_body = []

        def on_request(request):
            if "/api/llm/lmstudio-proxy" in request.url and request.method == "POST":
                try:
                    captured_body.append(request.post_data)
                except Exception:
                    pass

        page.on("request", on_request)

        click_autoplay(page)
        page.wait_for_timeout(8000)
        page.evaluate("if (typeof stopAutoPlay === 'function') stopAutoPlay()")

        assert len(captured_body) > 0, "No proxy POST requests captured"

        import json
        body = json.loads(captured_body[0])
        assert "model" in body, "Proxy request missing 'model' field"
        assert "messages" in body, "Proxy request missing 'messages' field"
        assert "base_url" in body, "Proxy request missing 'base_url' field"
        assert isinstance(body["messages"], list), "'messages' should be a list"
        assert len(body["messages"]) > 0, "'messages' should not be empty"

        # Verify at least one message has role 'user' (system promotion should work)
        roles = [m["role"] for m in body["messages"]]
        assert "user" in roles, (
            f"No 'user' role in messages (roles: {roles}). "
            "System-message-to-user promotion may not be working."
        )

    def test_proxy_request_base_url_is_lmstudio(self, page, base_url):
        """The base_url in the proxy request should point to LM Studio."""
        navigate_to_agent_view(page, base_url)
        create_new_session(page)
        select_first_game(page)
        scaffolding = page.evaluate("activeScaffoldingType")
        if scaffolding != "linear":
            switch_scaffolding(page, "linear")
        select_first_lmstudio_model(page)

        captured_body = []

        def on_request(request):
            if "/api/llm/lmstudio-proxy" in request.url and request.method == "POST":
                try:
                    captured_body.append(request.post_data)
                except Exception:
                    pass

        page.on("request", on_request)

        click_autoplay(page)
        page.wait_for_timeout(8000)
        page.evaluate("if (typeof stopAutoPlay === 'function') stopAutoPlay()")

        if captured_body:
            import json
            body = json.loads(captured_body[0])
            assert "localhost:1234" in body.get("base_url", ""), (
                f"base_url should contain localhost:1234, got: {body.get('base_url')}"
            )
