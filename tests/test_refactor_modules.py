# Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
# Date: 2026-03-11 14:00
# PURPOSE: Regression tests for Phase 1-5 modular refactor. Verifies that extracted
#   modules (constants, grid_analysis, prompt_builder, session_manager, bot_protection)
#   import correctly, export the expected symbols, and produce correct results.
#   Also verifies server.py re-exports remain intact for backward compatibility.
# SRP/DRY check: Pass — tests the refactored module boundaries, not duplicating test_parse.py
"""Regression tests for modular refactor phases 1-5.

Covers:
  - constants.py exports
  - grid_analysis.py functions (compress_row, compute_change_map, etc.)
  - prompt_builder.py functions (_build_prompt, _extract_json, _parse_llm_response)
  - session_manager.py imports and data structures
  - bot_protection.py imports
  - server.py backward-compatible re-exports
  - file header compliance (Author/Date/PURPOSE/SRP-DRY)
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═══════════════════════════════════════════════════════════════════════════
# constants.py
# ═══════════════════════════════════════════════════════════════════════════

class TestConstants:

    def test_import(self):
        import constants  # noqa: F401

    def test_color_map_has_16_entries(self):
        from constants import COLOR_MAP
        assert len(COLOR_MAP) == 16
        for i in range(16):
            assert i in COLOR_MAP
            assert isinstance(COLOR_MAP[i], str)
            assert COLOR_MAP[i].startswith("#")

    def test_color_names_has_16_entries(self):
        from constants import COLOR_NAMES
        assert len(COLOR_NAMES) == 16
        for i in range(16):
            assert i in COLOR_NAMES
            assert isinstance(COLOR_NAMES[i], str)

    def test_action_names_has_8_entries(self):
        from constants import ACTION_NAMES
        assert len(ACTION_NAMES) == 8
        for i in range(8):
            assert i in ACTION_NAMES

    def test_arc_agi3_description_nonempty(self):
        from constants import ARC_AGI3_DESCRIPTION
        assert isinstance(ARC_AGI3_DESCRIPTION, str)
        assert len(ARC_AGI3_DESCRIPTION) > 50

    def test_system_msg_nonempty(self):
        from constants import SYSTEM_MSG
        assert isinstance(SYSTEM_MSG, str)
        assert "JSON" in SYSTEM_MSG


# ═══════════════════════════════════════════════════════════════════════════
# grid_analysis.py
# ═══════════════════════════════════════════════════════════════════════════

class TestCompressRow:

    def test_import(self):
        from grid_analysis import compress_row  # noqa: F401

    def test_empty_row(self):
        from grid_analysis import compress_row
        assert compress_row([]) == ""

    def test_single_element(self):
        from grid_analysis import compress_row
        assert compress_row([5]) == "5"

    def test_no_runs(self):
        from grid_analysis import compress_row
        assert compress_row([1, 2, 3]) == "1 2 3"

    def test_runs_compressed(self):
        from grid_analysis import compress_row
        assert compress_row([0, 0, 0, 1]) == "0x3 1"

    def test_multiple_runs(self):
        from grid_analysis import compress_row
        assert compress_row([5, 5, 3, 3, 3]) == "5x2 3x3"

    def test_all_same(self):
        from grid_analysis import compress_row
        assert compress_row([7, 7, 7, 7]) == "7x4"


class TestComputeChangeMap:

    def test_import(self):
        from grid_analysis import compute_change_map  # noqa: F401

    def test_empty_grids(self):
        from grid_analysis import compute_change_map
        result = compute_change_map([], [])
        assert result["changes"] == []
        assert result["change_count"] == 0

    def test_identical_grids(self):
        from grid_analysis import compute_change_map
        grid = [[0, 1], [2, 3]]
        result = compute_change_map(grid, grid)
        assert result["change_count"] == 0
        assert result["change_map_text"] == "(no changes)"

    def test_single_cell_changed(self):
        from grid_analysis import compute_change_map
        prev = [[0, 0], [0, 0]]
        curr = [[0, 0], [0, 5]]
        result = compute_change_map(prev, curr)
        assert result["change_count"] == 1
        assert result["changes"][0]["x"] == 1
        assert result["changes"][0]["y"] == 1
        assert result["changes"][0]["from"] == 0
        assert result["changes"][0]["to"] == 5

    def test_all_cells_changed(self):
        from grid_analysis import compute_change_map
        prev = [[0, 0], [0, 0]]
        curr = [[1, 1], [1, 1]]
        result = compute_change_map(prev, curr)
        assert result["change_count"] == 4

    def test_different_size_grids_uses_min(self):
        from grid_analysis import compute_change_map
        prev = [[0, 0, 0], [0, 0, 0]]
        curr = [[1, 1], [1, 1]]
        result = compute_change_map(prev, curr)
        assert result["change_count"] == 4


class TestComputeColorHistogram:

    def test_import(self):
        from grid_analysis import compute_color_histogram  # noqa: F401

    def test_empty_grid(self):
        from grid_analysis import compute_color_histogram
        assert compute_color_histogram([]) == ""

    def test_single_color(self):
        from grid_analysis import compute_color_histogram
        grid = [[0, 0], [0, 0]]
        result = compute_color_histogram(grid)
        assert "4 cells" in result
        assert "White" in result

    def test_multiple_colors(self):
        from grid_analysis import compute_color_histogram
        grid = [[0, 1], [2, 3]]
        result = compute_color_histogram(grid)
        assert "1 cells" in result
        lines = result.strip().split("\n")
        assert len(lines) == 4


class TestComputeRegionMap:

    def test_import(self):
        from grid_analysis import compute_region_map  # noqa: F401

    def test_empty_grid(self):
        from grid_analysis import compute_region_map
        assert compute_region_map([]) == ""

    def test_single_region(self):
        from grid_analysis import compute_region_map
        grid = [[5, 5], [5, 5]]
        result = compute_region_map(grid)
        assert "4 cells" in result
        assert "Black" in result

    def test_two_regions_same_color_disconnected(self):
        from grid_analysis import compute_region_map
        grid = [[1, 0, 1]]
        result = compute_region_map(grid)
        # Should have two separate regions of color 1
        assert "1 cells" in result


# ═══════════════════════════════════════════════════════════════════════════
# prompt_builder.py — direct imports (not via server.py)
# ═══════════════════════════════════════════════════════════════════════════

class TestPromptBuilderImports:

    def test_import_extract_json(self):
        from prompt_builder import _extract_json  # noqa: F401

    def test_import_parse_llm_response(self):
        from prompt_builder import _parse_llm_response  # noqa: F401

    def test_import_build_prompt(self):
        from prompt_builder import _build_prompt  # noqa: F401

    def test_import_build_prompt_parts(self):
        from prompt_builder import _build_prompt_parts  # noqa: F401


class TestPromptBuilderExtractJson:
    """Verify _extract_json works when imported directly from prompt_builder."""

    def test_basic_action(self):
        from prompt_builder import _extract_json
        result = _extract_json('{"action": 1, "reasoning": "test"}')
        assert result is not None
        assert result["action"] == 1

    def test_basic_plan(self):
        from prompt_builder import _extract_json
        result = _extract_json('{"plan": [{"action": 1}], "observation": "x"}')
        assert result is not None
        assert len(result["plan"]) == 1

    def test_empty_returns_none(self):
        from prompt_builder import _extract_json
        assert _extract_json("") is None


class TestPromptBuilderBuildPrompt:

    def test_basic_prompt_generation(self):
        from prompt_builder import _build_prompt
        payload = {
            "grid": [[0, 1], [2, 3]],
            "state": "playing",
            "available_actions": [1, 2, 3, 4],
            "levels_completed": 0,
            "win_levels": 3,
            "history": [],
            "game_id": "test01",
            "change_map": {},
        }
        settings = {"full_grid": True}
        prompt = _build_prompt(payload, settings, tools_mode="off")
        assert isinstance(prompt, str)
        assert "test01" in prompt
        assert "Row 0:" in prompt
        assert "YOUR TASK" in prompt

    def test_planning_mode(self):
        from prompt_builder import _build_prompt
        payload = {
            "grid": [[0]], "state": "playing",
            "available_actions": [1], "levels_completed": 0,
            "win_levels": 1, "history": [], "game_id": "t",
            "change_map": {},
        }
        prompt = _build_prompt(payload, {"full_grid": True}, "off", planning_mode="3")
        assert "plan" in prompt.lower()
        assert "3 steps" in prompt

    def test_custom_system_prompt(self):
        from prompt_builder import _build_prompt
        payload = {
            "grid": [[0]], "state": "playing",
            "available_actions": [1], "levels_completed": 0,
            "win_levels": 1, "history": [], "game_id": "t",
            "change_map": {},
        }
        prompt = _build_prompt(payload, {"full_grid": True}, "off",
                               custom_system_prompt="CUSTOM SYSTEM PROMPT HERE")
        assert "CUSTOM SYSTEM PROMPT HERE" in prompt


# ═══════════════════════════════════════════════════════════════════════════
# server.py backward-compatible re-exports
# ═══════════════════════════════════════════════════════════════════════════

class TestServerReExports:
    """Verify server.py still re-exports symbols that existing code depends on."""

    def test_extract_json_from_server(self):
        from server import _extract_json
        result = _extract_json('{"action": 1}')
        assert result is not None

    def test_parse_llm_response_from_server(self):
        from server import _parse_llm_response
        result = _parse_llm_response('{"action": 1}', "test-model")
        assert result["parsed"] is not None

    def test_extract_json_same_function(self):
        """Verify server._extract_json IS prompt_builder._extract_json (not a copy)."""
        from server import _extract_json as server_fn
        from prompt_builder import _extract_json as pb_fn
        assert server_fn is pb_fn

    def test_parse_llm_response_same_function(self):
        from server import _parse_llm_response as server_fn
        from prompt_builder import _parse_llm_response as pb_fn
        assert server_fn is pb_fn


# ═══════════════════════════════════════════════════════════════════════════
# session_manager.py
# ═══════════════════════════════════════════════════════════════════════════

class TestSessionManager:

    def test_import(self):
        import session_manager  # noqa: F401

    def test_session_dicts_exist(self):
        from session_manager import (
            game_sessions, session_grids, session_snapshots,
            session_api_mode, session_api_keys,
            session_step_counts, session_last_llm,
        )
        assert isinstance(game_sessions, dict)
        assert isinstance(session_grids, dict)
        assert isinstance(session_snapshots, dict)
        assert isinstance(session_api_mode, dict)
        assert isinstance(session_api_keys, dict)
        assert isinstance(session_step_counts, dict)
        assert isinstance(session_last_llm, dict)

    def test_reconstruct_session_exists(self):
        from session_manager import _reconstruct_session
        assert callable(_reconstruct_session)

    def test_try_recover_session_exists(self):
        from session_manager import _try_recover_session
        assert callable(_try_recover_session)


# ═══════════════════════════════════════════════════════════════════════════
# bot_protection.py
# ═══════════════════════════════════════════════════════════════════════════

class TestBotProtection:

    def test_import(self):
        import bot_protection  # noqa: F401

    def test_turnstile_keys_exist(self):
        from bot_protection import TURNSTILE_SITE_KEY, TURNSTILE_SECRET_KEY
        # These may be None in dev, but the symbols must exist
        assert TURNSTILE_SITE_KEY is None or isinstance(TURNSTILE_SITE_KEY, str)
        assert TURNSTILE_SECRET_KEY is None or isinstance(TURNSTILE_SECRET_KEY, str)

    def test_decorators_exist(self):
        from bot_protection import bot_protection, turnstile_required
        assert callable(bot_protection)
        assert callable(turnstile_required)


# ═══════════════════════════════════════════════════════════════════════════
# File header compliance
# ═══════════════════════════════════════════════════════════════════════════

import glob

# All files that should have headers from the refactor
REFACTOR_FILES_PY = [
    "constants.py", "bot_protection.py", "grid_analysis.py",
    "prompt_builder.py", "session_manager.py", "agent.py",
    "agent_llm.py", "agent_history.py", "agent_response_parsing.py",
    "db.py",
]
REFACTOR_FILES_JS = [
    "static/js/utils/formatting.js", "static/js/utils/json-parsing.js",
    "static/js/utils/tokens.js", "static/js/config/scaffolding-schemas.js",
    "static/js/rendering/grid-renderer.js",
    "static/js/observatory/obs-lifecycle.js",
    "static/js/observatory/obs-log-renderer.js",
    "static/js/observatory/obs-scrubber.js",
    "static/js/observatory/obs-swimlane-renderer.js",
    "static/js/scaffolding-linear.js", "static/js/scaffolding-rlm.js",
    "static/js/scaffolding-three-system.js",
    "static/js/scaffolding-agent-spawn.js",
    "static/js/scaffolding.js", "static/js/llm.js",
    "static/js/state.js", "static/js/ui.js",
    "static/js/obs-page.js", "static/js/observatory.js",
    "static/js/reasoning.js", "static/js/share-page.js",
]

PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")


class TestFileHeaders:

    def _read_first_line(self, relpath):
        fullpath = os.path.join(PROJECT_ROOT, relpath)
        with open(fullpath) as f:
            return f.readline().strip()

    def test_python_files_have_author_header(self):
        for relpath in REFACTOR_FILES_PY:
            line = self._read_first_line(relpath)
            assert line.startswith("# Author:"), \
                f"{relpath}: first line should start with '# Author:', got: {line!r}"
            assert "Mark Barney" in line, \
                f"{relpath}: header missing 'Mark Barney', got: {line!r}"
            assert "Cascade" in line, \
                f"{relpath}: header missing 'Cascade', got: {line!r}"

    def test_js_files_have_author_header(self):
        for relpath in REFACTOR_FILES_JS:
            line = self._read_first_line(relpath)
            assert line.startswith("// Author:"), \
                f"{relpath}: first line should start with '// Author:', got: {line!r}"
            assert "Mark Barney" in line, \
                f"{relpath}: header missing 'Mark Barney', got: {line!r}"
            assert "Cascade" in line, \
                f"{relpath}: header missing 'Cascade', got: {line!r}"

    def test_python_files_have_purpose(self):
        for relpath in REFACTOR_FILES_PY:
            fullpath = os.path.join(PROJECT_ROOT, relpath)
            with open(fullpath) as f:
                header = f.read(2000)
            assert "PURPOSE:" in header, \
                f"{relpath}: missing PURPOSE in header"

    def test_js_files_have_purpose(self):
        for relpath in REFACTOR_FILES_JS:
            fullpath = os.path.join(PROJECT_ROOT, relpath)
            with open(fullpath) as f:
                header = f.read(2000)
            assert "PURPOSE:" in header, \
                f"{relpath}: missing PURPOSE in header"

    def test_python_files_have_srp_dry(self):
        for relpath in REFACTOR_FILES_PY:
            fullpath = os.path.join(PROJECT_ROOT, relpath)
            with open(fullpath) as f:
                header = f.read(2000)
            assert "SRP/DRY check:" in header, \
                f"{relpath}: missing SRP/DRY check in header"

    def test_js_files_have_srp_dry(self):
        for relpath in REFACTOR_FILES_JS:
            fullpath = os.path.join(PROJECT_ROOT, relpath)
            with open(fullpath) as f:
                header = f.read(2000)
            assert "SRP/DRY check:" in header, \
                f"{relpath}: missing SRP/DRY check in header"
