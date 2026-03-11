# Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
# Date: 2026-03-11 13:47
# PURPOSE: LLM prompt construction and response parsing for ARC-AGI-3. Builds
#   config-driven prompts (_build_prompt, _build_prompt_parts) with grid RLE,
#   history, change maps, color histograms, region maps, tool instructions, and
#   planning mode support. Also provides _parse_llm_response and _extract_json
#   for balanced-brace JSON extraction from LLM output. Accepts custom_system_prompt
#   and custom_hard_memory as explicit params to avoid circular imports with server.py.
#   Extracted from server.py in Phase 2b. Depends on constants.py and grid_analysis.py.
# SRP/DRY check: Pass — all prompt building and LLM response parsing consolidated here
"""LLM prompt construction and response parsing for ARC-AGI-3.

Extracted from server.py (Phase 2b).

IMPORTANT: _build_prompt and _build_prompt_parts accept custom_system_prompt
and custom_hard_memory as explicit parameters (not module globals) to avoid
circular imports with server.py.
"""

import json
import re

from constants import ACTION_NAMES, ARC_AGI3_DESCRIPTION
from grid_analysis import compress_row, compute_color_histogram, compute_region_map


def _build_prompt_parts(payload: dict, input_settings: dict, tools_mode: str,
                        planning_mode: str = "off",
                        custom_system_prompt=None,
                        custom_hard_memory=None) -> tuple[str, str]:
    """Split prompt into static (cacheable) and dynamic parts.

    Returns (static_str, dynamic_str).
    """
    # ── Static parts (system description, palette, memory) ────────────
    static_parts = []
    sys_prompt = custom_system_prompt if custom_system_prompt else ARC_AGI3_DESCRIPTION
    static_parts.append(f"""{sys_prompt}

COLOR PALETTE: 0=White 1=LightGray 2=Gray 3=DarkGray 4=VeryDarkGray 5=Black
               6=Magenta 7=LightMagenta 8=Red 9=Blue 10=LightBlue 11=Yellow
               12=Orange 13=Maroon 14=Green 15=Purple""")

    if custom_hard_memory:
        static_parts.append(f"## AGENT MEMORY\n{custom_hard_memory}")

    static_str = "\n\n".join(static_parts)

    # ── Dynamic parts (everything else) are built by _build_prompt ────
    # We return just the static portion; the caller uses the full prompt too
    return static_str, ""  # dynamic not needed separately


def _build_prompt(payload: dict, input_settings: dict, tools_mode: str,
                  planning_mode: str = "off", interrupt_plan: bool = False,
                  custom_system_prompt=None, custom_hard_memory=None) -> str:
    """Build an LLM prompt controlled by the input settings from the UI."""
    grid = payload.get("grid", [])
    state = payload.get("state", "")
    available = payload.get("available_actions", [])
    levels_completed = payload.get("levels_completed", 0)
    win_levels = payload.get("win_levels", 0)
    history = payload.get("history", [])
    game_id = payload.get("game_id", "unknown")
    change_map = payload.get("change_map", {})

    parts: list[str] = []

    sys_prompt = custom_system_prompt if custom_system_prompt else ARC_AGI3_DESCRIPTION
    parts.append(f"""{sys_prompt}

COLOR PALETTE: 0=White 1=LightGray 2=Gray 3=DarkGray 4=VeryDarkGray 5=Black
               6=Magenta 7=LightMagenta 8=Red 9=Blue 10=LightBlue 11=Yellow
               12=Orange 13=Maroon 14=Green 15=Purple""")

    # ── Hard memory (agent priors) ───────────────────────────────────────
    if custom_hard_memory:
        parts.append(f"## AGENT MEMORY\n{custom_hard_memory}")

    # ── State header ──────────────────────────────────────────────────────
    action_desc = ", ".join(f"{a}={ACTION_NAMES.get(a, f'ACTION{a}')}" for a in available)
    parts.append(
        f"## STATE\nGame: {game_id} | State: {state} | "
        f"Levels: {levels_completed}/{win_levels}\n"
        f"Available actions: {action_desc}"
    )

    # ── Compact context (replaces verbose history when provided) ────────
    compact_context = payload.get("compact_context", "")
    if compact_context:
        parts.append(compact_context)

    # ── History (always included) ─────────────────────────────────────────
    if history:
        lines = []
        for h in history:
            aname = ACTION_NAMES.get(h.get("action", 0), "?")
            line = f"  Step {h.get('step', '?')}: {aname} -> {h.get('result_state', '?')}"
            cm = h.get("change_map")
            if cm and cm.get("change_count", 0) > 0:
                line += f" ({cm['change_count']} cells changed)"
                if cm.get("change_map_text"):
                    line += f"\n    Changes: {cm['change_map_text']}"
            elif cm and cm.get("change_count") == 0:
                line += " (no change)"
            grid_snap = h.get("grid")
            if grid_snap:
                rle = "\n".join(f"    Row {i}: {compress_row(r)}" for i, r in enumerate(grid_snap))
                line += f"\n{rle}"
            lines.append(line)
        parts.append(f"## HISTORY ({len(history)} steps)\n" + "\n".join(lines))

    # ── Diff / change map ─────────────────────────────────────────────────
    if input_settings.get("diff") and change_map and change_map.get("change_count", 0) > 0:
        parts.append(
            f"## CHANGES ({change_map['change_count']} cells changed)\n"
            f"{change_map.get('change_map_text', '')}"
        )

    # ── Full grid ─────────────────────────────────────────────────────────
    if input_settings.get("full_grid", True):
        grid_text = "\n".join(f"Row {i}: {compress_row(r)}" for i, r in enumerate(grid))
        parts.append(f"## GRID (RLE, colors 0-15)\n{grid_text}")

    # ── Color histogram ───────────────────────────────────────────────────
    if input_settings.get("color_histogram") or tools_mode == "on":
        histo = compute_color_histogram(grid)
        if histo:
            parts.append(f"## COLOR HISTOGRAM\n{histo}")

    # ── Region map (only with tools=on, or if explicitly requested) ───────
    if tools_mode == "on":
        rmap = compute_region_map(grid)
        if rmap:
            parts.append(f"## REGION MAP\n{rmap}")

    # ── Image note ────────────────────────────────────────────────────────
    if input_settings.get("image"):
        parts.append(
            "## IMAGE\nA screenshot of the current grid is attached. "
            "Use it together with the numeric data above."
        )

    # ── Task block ────────────────────────────────────────────────────────
    tool_extra = ""
    if tools_mode == "on":
        tool_extra = (
            "\n- You have access to a run_python tool. Call it to analyse the grid programmatically "
            "(e.g. find objects, count colors, detect patterns, measure distances). "
            "The grid is available as a numpy array variable `grid`. Use print() to see results."
            '\n- Include "analysis" in your JSON with a summary of what the tool found.'
        )

    analysis_field = ', "analysis": "<detailed spatial analysis>"' if tools_mode == "on" else ''
    is_planning = planning_mode and planning_mode != "off"

    if is_planning:
        plan_n = int(planning_mode)
        expected_field = ', "expected": "<what you expect to see after this plan>"' if interrupt_plan else ''
        expected_rule = '\n- "expected": briefly describe what you expect after the plan completes (e.g. "character at the door", "score increased").' if interrupt_plan else ''
        parts.append(f"""## YOUR TASK
1. Identify key objects (character, walls, targets, items).
2. Determine what must happen next to progress.
3. Plan a sequence of actions (up to {plan_n} steps).

Respond with EXACTLY this JSON (nothing else):
{{"observation": "<what you see>", "reasoning": "<your plan>", "plan": [{{"action": <n>, "data": {{}}}}, ...]{analysis_field}{expected_field}}}

Rules:
- Return a "plan" array of up to {plan_n} steps. Each step has "action" (0-7) and "data" ({{}} or {{"x": <0-63>, "y": <0-63>}}).
- ACTION6: set "data" to {{"x": <0-63>, "y": <0-63>}}.
- Other actions: set "data" to {{}}.{expected_rule}{tool_extra}""")
    else:
        parts.append(f"""## YOUR TASK
1. Identify key objects (character, walls, targets, items).
2. Determine what must happen next to progress.
3. Choose the best action.

Respond with EXACTLY this JSON (nothing else):
{{"observation": "<what you see>", "reasoning": "<your plan>", "action": <number>, "data": {{}}{analysis_field}}}

Rules:
- "action" must be a plain integer (0-7).
- ACTION6: set "data" to {{"x": <0-63>, "y": <0-63>}}.
- Other actions: set "data" to {{}}.{tool_extra}""")

    return "\n\n".join(parts)


def _parse_llm_response(content: str, model_name: str) -> dict:
    if not isinstance(content, str):
        content = json.dumps(content) if content else ""
    thinking = ""
    think_match = re.search(r"<think>(.*?)</think>", content, re.DOTALL)
    if think_match:
        thinking = think_match.group(1).strip()
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

    # Try to extract JSON from the main content
    parsed = _extract_json(content)
    if parsed:
        return {"raw": content, "thinking": thinking[:500] if thinking else None,
                "parsed": parsed, "model": model_name}

    # If main content had no JSON, try inside the thinking block
    if thinking:
        parsed = _extract_json(thinking)
        if parsed:
            return {"raw": content or thinking, "thinking": thinking[:500],
                    "parsed": parsed, "model": model_name}

    return {"raw": content or thinking, "thinking": thinking[:500] if thinking else None,
            "parsed": None, "model": model_name}


def _extract_json(text: str) -> dict | None:
    """Extract first valid JSON object with 'action' or 'plan' using balanced-brace matching."""
    cleaned = re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)
    i = 0
    while i < len(cleaned):
        if cleaned[i] != "{":
            i += 1
            continue
        depth = 0
        in_str = False
        esc = False
        for j in range(i, len(cleaned)):
            ch = cleaned[j]
            if esc:
                esc = False
                continue
            if ch == "\\" and in_str:
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(cleaned[i : j + 1])
                        if "action" in obj or "plan" in obj or "type" in obj or "verdict" in obj:
                            return obj
                    except json.JSONDecodeError:
                        pass
                    break
        i += 1
    return None
