# Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
# Date: 2026-03-12 12:52
# PURPOSE: CLI autonomous agent for ARC-AGI-3 coordinator. Config-driven, memory-aware game
#   player that calls LLM providers (Gemini, Anthropic, OpenAI, local) to solve
#   ARC puzzles via the arcengine API. Delegates to agent_llm.py (provider calls),
#   agent_response_parsing.py (response handling), and agent_history.py (memory).
#   Supports RLM scaffolding with Pyodide REPL, planning modes, tool use, persistent memory.
#   Standalone entry point — does not depend on Flask server.
# SRP/DRY check: Pass — LLM calls (Phase 11), response parsing, and history management
#   extracted to focused modules; agent.py retains config, memory I/O, prompt building,
#   and game loop orchestration.
"""ARC-AGI-3 Autonomous Agent — config-driven, memory-aware."""

import argparse
import json
import os
import re
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import httpx
import yaml
from dotenv import load_dotenv

import arc_agi
from arcengine import GameAction, GameState

load_dotenv(Path(__file__).parent / ".env")

ROOT = Path(__file__).parent

from constants import COLOR_NAMES, ACTION_NAMES, ARC_AGI3_DESCRIPTION, SYSTEM_MSG
from models import MODELS, compute_cost, DEFAULT_MODEL
from agent_llm import LLMResult, call_model_with_metadata, call_model_with_retry, call_model
from grid_analysis import compress_row, compute_change_map, compute_color_histogram, compute_region_map
from agent_response_parsing import _parse_json, _fallback_parse, _force_extract_action, _fallback_action
from agent_history import condense_history, reflect_and_update_memory

# Thread-safety locks for shared file writes
_memory_lock = threading.Lock()
_session_log_lock = threading.Lock()




# ═══════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════

_DEFAULT_CONFIG = {
    "context": {
        "full_grid": True,
        "change_map": True,
        "color_histogram": False,
        "region_map": False,
        "history_length": 0,
        "reasoning_trace": False,
        "max_context_tokens": 100000,
        "memory_injection": True,
        "memory_injection_max_chars": 1500,
    },
    "reasoning": {
        "executor_model": DEFAULT_MODEL,
        "condenser_model": None,
        "reflector_model": None,
        "planner_model": None,
        "monitor_model": None,
        "world_model_model": None,
        "temperature": 0.3,
        "max_tokens": 2048,
        "planning_horizon": 1,
        "reflection_max_tokens": 1024,
        "planner_max_tokens": 4096,
        "monitor_max_tokens": 512,
        "world_model_max_tokens": 2048,
    },
    "memory": {
        "hard_memory_file": "memory/MEMORY.md",
        "session_log_file": "memory/sessions.json",
        "allow_inline_memory_writes": True,
        "reflect_after_game": True,
        "condense_every": 0,
        "condense_threshold": 0,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config(path: Path | None = None) -> dict:
    cfg = _DEFAULT_CONFIG
    resolved = path or (ROOT / "config.yaml")
    if resolved.exists():
        with open(resolved, encoding="utf-8") as f:
            file_cfg = yaml.safe_load(f) or {}
        cfg = _deep_merge(cfg, file_cfg)
    return cfg


def effective_model(cfg: dict, role: str) -> str:
    """Return the model key for executor / condenser / reflector roles."""
    key = f"{role}_model"
    m = cfg["reasoning"].get(key)
    return m if m else cfg["reasoning"]["executor_model"]


# ═══════════════════════════════════════════════════════════════════════════
# HARD MEMORY
# ═══════════════════════════════════════════════════════════════════════════

def _memory_path(cfg: dict) -> Path:
    return ROOT / cfg["memory"]["hard_memory_file"]


def _sessions_path(cfg: dict) -> Path:
    return ROOT / cfg["memory"]["session_log_file"]


def load_hard_memory(cfg: dict) -> str:
    p = _memory_path(cfg)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


def save_hard_memory(cfg: dict, content: str) -> None:
    p = _memory_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def append_memory_bullet(cfg: dict, game_id: str, bullet: str) -> None:
    """Append a bullet under the game's section in MEMORY.md (thread-safe)."""
    with _memory_lock:
        _append_memory_bullet_unsafe(cfg, game_id, bullet)


def _append_memory_bullet_unsafe(cfg: dict, game_id: str, bullet: str) -> None:
    content = load_hard_memory(cfg)
    bullet = bullet.strip().lstrip("-").strip()
    section_header = f"## {game_id}"
    if section_header in content:
        # Insert after the section header line
        lines = content.splitlines()
        new_lines = []
        inserted = False
        for line in lines:
            new_lines.append(line)
            if not inserted and line.strip() == section_header:
                new_lines.append(f"- {bullet}")
                inserted = True
        content = "\n".join(new_lines) + "\n"
    else:
        content = content.rstrip() + f"\n\n{section_header}\n\n- {bullet}\n"
    save_hard_memory(cfg, content)


def log_session(cfg: dict, record: dict) -> None:
    with _session_log_lock:
        p = _sessions_path(cfg)
        p.parent.mkdir(parents=True, exist_ok=True)
        sessions = []
        if p.exists():
            try:
                sessions = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                sessions = []
        sessions.append(record)
        p.write_text(json.dumps(sessions, indent=2), encoding="utf-8")


def relevant_memory_section(hard_memory: str, game_id: str, max_chars: int) -> str:
    """Return the General + Strategies sections + game-specific section."""
    if not hard_memory:
        return ""
    # Strip comment header lines
    lines = [l for l in hard_memory.splitlines() if not l.startswith("#")]
    text = "\n".join(lines).strip()

    # Extract general + strategies + game section
    sections_to_keep = ["## General", "## Strategies", f"## {game_id}"]
    result_parts = []
    current_section = None
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("## "):
            if current_section in sections_to_keep and current_lines:
                result_parts.append("\n".join(current_lines))
            current_section = line.strip()
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_section in sections_to_keep and current_lines:
        result_parts.append("\n".join(current_lines))

    combined = "\n\n".join(result_parts).strip()
    if len(combined) > max_chars:
        combined = combined[:max_chars] + "\n... (truncated)"
    return combined


# ═══════════════════════════════════════════════════════════════════════════
# GRID ANALYSIS (imported from grid_analysis.py)
# ═══════════════════════════════════════════════════════════════════════════
# Grid analysis functions are maintained in grid_analysis.py and used by both
# prompt building and server. Not imported here as agent.py uses prompt_builder.py
# for prompt construction which already handles grid analysis utilities.


# ═══════════════════════════════════════════════════════════════════════════
# LLM API CALLS (imported from agent_llm.py)
# ═══════════════════════════════════════════════════════════════════════════
# All LLM provider calls, retry logic, and cost tracking extracted to agent_llm.py
# in Phase 11. Imported above: call_model_with_metadata, call_model_with_retry.


# ═══════════════════════════════════════════════════════════════════════════
# PROMPT BUILDING
# ═══════════════════════════════════════════════════════════════════════════

def build_context_block(
    grid: list,
    state_str: str,
    available_actions: list[int],
    levels_done: int,
    win_levels: int,
    game_id: str,
    history: list[dict],
    cfg: dict,
    prev_grid: list | None = None,
    hard_memory: str = "",
) -> str:
    ctx = cfg["context"]
    parts: list[str] = []

    # ── Game metadata ─────────────────────────────────────────────────────
    action_desc = ", ".join(f"{a}={ACTION_NAMES.get(a, f'ACTION{a}')}" for a in available_actions)
    parts.append(
        f"## CURRENT STATE\n"
        f"Game: {game_id} | State: {state_str} | "
        f"Levels: {levels_done}/{win_levels}\n"
        f"Available actions: {action_desc}"
    )

    # ── Hard memory injection ─────────────────────────────────────────────
    if ctx["memory_injection"] and hard_memory:
        mem_text = relevant_memory_section(
            hard_memory, game_id, ctx["memory_injection_max_chars"]
        )
        if mem_text:
            parts.append(f"## MEMORY (what you already know)\n{mem_text}")

    # ── History ───────────────────────────────────────────────────────────
    n = ctx["history_length"]
    reasoning_trace = ctx.get("reasoning_trace", False)
    if history and n >= 0:  # 0 = show all, positive = last N, negative = disabled
        recent = history[-n:] if n > 0 else history
        lines = []
        for h in recent:
            if h.get("is_summary"):
                lines.append(f"  [Summary]: {h.get('summary', '')}")
                continue
            action_name = ACTION_NAMES.get(h["action"], f"ACTION{h['action']}")
            data_str = ""
            if h.get("data"):
                d = h["data"]
                if "x" in d and "y" in d:
                    data_str = f"@({d['x']},{d['y']})"
            lvl = h.get("levels", "?")
            obs = (h.get("observation", "") or "")[:500]
            line = f"  Step {h['step']:3d}: {action_name}{data_str} -> levels={lvl}  | {obs}"
            if reasoning_trace and h.get("reasoning"):
                line += f"\n    Reasoning: {h['reasoning'][:500]}"
            lines.append(line)
        non_summary = [h for h in recent if not h.get("is_summary")]
        label = f"all {len(non_summary)}" if n == 0 else f"last {len(non_summary)} of {len(history)}"
        parts.append(f"## HISTORY ({label} steps)\n" + "\n".join(lines))

    # ── Change map ────────────────────────────────────────────────────────
    if ctx["change_map"] and prev_grid:
        change_result = compute_change_map(prev_grid, grid)
        change_text = change_result.get("change_map_text", "")
        if change_text and change_text != "(no changes)":
            parts.append(f"## CHANGE MAP\n{change_text}".strip())

    # ── Color histogram ───────────────────────────────────────────────────
    if ctx["color_histogram"]:
        parts.append(compute_color_histogram(grid).strip())

    # ── Region map ────────────────────────────────────────────────────────
    if ctx["region_map"]:
        parts.append(compute_region_map(grid).strip())

    # ── Full grid ─────────────────────────────────────────────────────────
    if ctx["full_grid"]:
        grid_text = "\n".join(f"Row {i}: {compress_row(r)}" for i, r in enumerate(grid))
        parts.append(f"## GRID (RLE, colors 0-15)\n{grid_text}")

    return "\n\n".join(parts)


def build_action_prompt(context_block: str, planning_horizon: int = 1) -> str:
    header = f"""{ARC_AGI3_DESCRIPTION}

COLOR PALETTE: 0=White 1=LightGray 2=Gray 3=DarkGray 4=VeryDarkGray 5=Black
               6=Magenta 7=LightMagenta 8=Red 9=Blue 10=LightBlue 11=Yellow
               12=Orange 13=Maroon 14=Green 15=Purple

{context_block}

YOUR TASK
---------
1. Identify key objects (character, walls, targets, items).
2. Determine what must happen next to make progress.
3. Choose the best action."""

    return header + f"""

Output a plan of 1-{planning_horizon} actions. If the next steps are obvious (e.g. "move right 3 times"), include them all. If unsure, output a plan of just 1 action.

Respond with EXACTLY this JSON (nothing else):
{{"observation": "<what you see>", "reasoning": "<your plan>", "actions": [{{"action": <number>, "data": {{}}}}], "memory_update": null}}

Rules:
- "actions" is an array of 1-{planning_horizon} action objects, each with "action" (int 0-7) and "data".
- For ACTION6 set "data" to {{"x": <0-63>, "y": <0-63>}}.
- For all other actions set "data" to {{}}.
- "memory_update": if you discovered a NEW rule/fact worth remembering, write it as a short string (≤ 120 chars). Otherwise null."""


# ═══════════════════════════════════════════════════════════════════════════
# HISTORY CONDENSATION
# ═══════════════════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════════════════
# HISTORY MANAGEMENT (imported from agent_history.py)
# ═══════════════════════════════════════════════════════════════════════════
# History condensation and post-game reflection extracted to agent_history.py
# in Phase 11. Imported above: condense_history, reflect_and_update_memory.


# ═══════════════════════════════════════════════════════════════════════════
# RESPONSE PARSING (imported from agent_response_parsing.py)
# ═══════════════════════════════════════════════════════════════════════════
# Response parsing and action extraction extracted to agent_response_parsing.py
# in Phase 11. Imported above: _parse_json, _fallback_parse, _force_extract_action, _fallback_action.


# ═══════════════════════════════════════════════════════════════════════════
# GAME LOOP — HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════

def _setup_game_session(arcade, game_id: str, cfg: dict) -> tuple:
    """Initialize game environment and session state.
    
    Returns:
        tuple: (env, frame, hard_memory, history, step_num, steps_since_condense, mcfg)
               or None if game setup fails.
    """
    print(f"\n{'='*65}")
    print(f"  PLAYING: {game_id}")
    print(f"  Executor: {effective_model(cfg, 'executor')}")
    print(f"  Context: grid={cfg['context']['full_grid']} change={cfg['context']['change_map']} "
          f"hist={cfg['context']['history_length']} "
          f"hist_cmap={cfg['context']['color_histogram']} region={cfg['context']['region_map']}")
    planning_horizon = cfg["reasoning"].get("planning_horizon", 1)
    print(f"  Memory:  inject={cfg['context']['memory_injection']} "
          f"condense_every={cfg['memory']['condense_every']} "
          f"reflect={cfg['memory']['reflect_after_game']}")
    if planning_horizon > 1:
        print(f"  Planning horizon: {planning_horizon}")
    print(f"{'='*65}\n")

    env = arcade.make(game_id)
    frame = env.observation_space
    if frame is None:
        print("  [ERROR] Could not start game.")
        return None

    hard_memory = load_hard_memory(cfg)
    history: list[dict] = []
    step_num = 0
    steps_since_condense = 0
    mcfg = cfg["memory"]

    return (env, frame, hard_memory, history, step_num, steps_since_condense, mcfg)


def _maybe_condense_history(
    history: list[dict],
    cfg: dict,
    steps_since_condense: int,
    condense_every: int,
    condense_threshold: int,
) -> tuple:
    """Check and apply history condensation if needed.
    
    Returns:
        tuple: (updated_history, updated_steps_since_condense)
    """
    raw_history_len = sum(1 for h in history if not h.get("is_summary"))
    
    # Step-count triggers (legacy, disabled when 0)
    should_condense = (
        condense_every > 0 and steps_since_condense >= condense_every
    ) or (
        condense_threshold > 0 and raw_history_len >= condense_threshold
    )
    
    # Token-based trigger: compact when history portion exceeds ~60% of budget
    max_ctx_tokens = cfg["context"].get("max_context_tokens", 100000)
    if max_ctx_tokens > 0 and raw_history_len > 0 and not should_condense:
        estimated_tokens = len(str(history)) // 4  # rough estimate
        if estimated_tokens > max_ctx_tokens * 0.6:
            should_condense = True
    
    if should_condense and raw_history_len > 0:
        history = condense_history(history, cfg)
        steps_since_condense = 0
    
    return (history, steps_since_condense)


def _prepare_prompt_and_call_llm(
    grid: list,
    state_str: str,
    available: list[int],
    levels_done: int,
    win_levels: int,
    game_id: str,
    history: list[dict],
    cfg: dict,
    prev_grid: list | None,
    hard_memory: str,
    session_id: str | None,
    step_num: int,
) -> tuple:
    """Build context/prompt and call LLM; handle logging.
    
    Returns:
        tuple: (llm_result, prompt, elapsed_ms, turn_num)
    """
    context_block = build_context_block(
        grid, state_str, available, levels_done, win_levels,
        game_id, history, cfg, prev_grid, hard_memory,
    )
    prompt = build_action_prompt(context_block, cfg["reasoning"].get("planning_horizon", 1))

    model_key = effective_model(cfg, "executor")
    turn_start_time = time.time()
    llm_result = call_model_with_metadata(model_key, prompt, cfg, role="executor")
    elapsed_ms = llm_result.duration_ms
    turn_num = step_num + 1

    if session_id:
        from db import _log_llm_call
        _log_llm_call(
            session_id, "executor", model_key,
            step_num=step_num + 1,
            turn_num=turn_num,
            input_json=prompt[:500],
            output_json=(llm_result.text or "")[:1000],
            input_tokens=llm_result.input_tokens,
            output_tokens=llm_result.output_tokens,
            thinking_tokens=llm_result.thinking_tokens,
            thinking_json=(llm_result.thinking_text or "")[:5000] if llm_result.thinking_text else None,
            cost=llm_result.cost,
            duration_ms=llm_result.duration_ms,
            error=llm_result.error,
        )

    return (llm_result, prompt, elapsed_ms, turn_num)


def _parse_and_build_action_list(
    llm_result: LLMResult,
    available: list[int],
    planning_horizon: int,
    game_id: str,
    cfg: dict,
) -> tuple:
    """Parse LLM response and build action list.
    
    Returns:
        tuple: (action_list, observation, reasoning, raw_reasoning_saved, hard_memory)
    """
    raw = llm_result.text
    mcfg = cfg["memory"]

    parsed = _parse_json(raw) if raw else None
    if parsed is None and raw:
        parsed = _fallback_parse(raw, available, cfg, effective_model(cfg, "executor"))
    if parsed is None and raw:
        parsed = _force_extract_action(raw, available, cfg, effective_model(cfg, "executor"))

    raw_reasoning_saved = None
    hard_memory = load_hard_memory(cfg)

    if parsed is None:
        action_id = _fallback_action(available)
        action_data = {}
        observation = "parse error / LLM unavailable"
        reasoning = "fallback"
        if raw:
            raw_reasoning_saved = raw[:2000]
            print(f"  [force-action] could not parse, forcing action={action_id}, reasoning saved")
    else:
        observation = parsed.get("observation", "")
        reasoning = parsed.get("reasoning", "")
        memory_update = parsed.get("memory_update")

        # Inline memory write
        if (
            mcfg["allow_inline_memory_writes"]
            and memory_update
            and isinstance(memory_update, str)
            and memory_update.strip()
        ):
            append_memory_bullet(cfg, game_id, memory_update)
            hard_memory = load_hard_memory(cfg)  # reload
            print(f"  [memory inline] {memory_update[:80]}")

    # Build action list from parsed response
    if parsed and "actions" in parsed and isinstance(parsed["actions"], list):
        action_list = []
        for a in parsed["actions"][:planning_horizon]:
            aid = a.get("action", 1) if isinstance(a, dict) else int(a)
            adata = (a.get("data") or {}) if isinstance(a, dict) else {}
            action_list.append((aid, adata))
    elif parsed:
        action_list = [(parsed.get("action", 1), parsed.get("data") or {})]
    else:
        action_list = [(action_id, action_data)]

    return (action_list, observation, reasoning, raw_reasoning_saved, hard_memory)


def _execute_and_log_action_plan(
    action_list: list,
    env,
    frame,
    available: list[int],
    grid: list,
    levels_done: int,
    win_levels: int,
    elapsed_ms: int,
    step_num: int,
    observation: str,
    reasoning: str,
    raw_reasoning_saved: str | None,
    parsed,
    history: list[dict],
    session_id: str | None,
    llm_result: LLMResult,
    step_callback=None,
    max_steps: int = 200,
) -> tuple:
    """Execute action plan, update history, handle callbacks, log turn.
    
    Returns:
        tuple: (updated_step_num, updated_frame, updated_grid, updated_available, 
                updated_levels_done, updated_history, terminal_hit, steps_executed)
    """
    steps_planned = len(action_list)
    steps_executed = 0
    turn_step_start = step_num + 1
    terminal_hit = False
    prev_grid = grid
    elapsed_sec = elapsed_ms / 1000
    turn_num = step_num + 1

    for action_idx, (act_id, act_data) in enumerate(action_list):
        # Validate action against currently available actions
        if act_id not in available:
            act_id = available[0] if available else 1

        try:
            action = GameAction.from_id(int(act_id))
        except (ValueError, KeyError):
            action = GameAction.ACTION1

        step_num += 1
        steps_executed += 1
        aname = ACTION_NAMES.get(act_id, f"ACTION{act_id}")
        coord_str = f"@({act_data.get('x','?')},{act_data.get('y','?')})" if act_id == 6 and act_data else ""
        plan_tag = f" [{action_idx+1}/{steps_planned}]" if steps_planned > 1 else ""
        print(f"  Step {step_num:3d} | {aname}{coord_str:12s} | lvl {levels_done}/{win_levels} | {elapsed_sec:.1f}s{plan_tag}")

        if action_idx == 0:
            if observation:
                print(f"           obs: {observation[:100]}")
            if reasoning:
                print(f"           why: {reasoning[:100]}")
            if raw_reasoning_saved:
                print(f"           raw: {raw_reasoning_saved[:100]}...")

        prev_grid = grid
        frame = env.step(action, data=act_data or None, reasoning=reasoning if action_idx == 0 else None)
        if frame is None:
            print("  [ERROR] env.step returned None")
            terminal_hit = True
            break

        new_levels = frame.levels_completed if frame else levels_done
        new_grid = frame.frame[-1].tolist() if frame.frame else grid
        state_val = frame.state.value if frame and hasattr(frame.state, "value") else "?"
        levels_done = new_levels
        grid = new_grid
        available = frame.available_actions

        hist_entry = {
            "step": step_num,
            "action": act_id,
            "data": act_data,
            "state": state_val,
            "levels": new_levels,
            "observation": observation if action_idx == 0 else "",
            "reasoning": reasoning if action_idx == 0 else "",
        }
        if raw_reasoning_saved and action_idx == 0:
            hist_entry["raw_reasoning"] = raw_reasoning_saved
        history.append(hist_entry)

        # Invoke step callback (used by batch_runner for DB persistence)
        if step_callback:
            llm_resp = {"observation": observation, "reasoning": reasoning,
                        "action": act_id, "data": act_data} if parsed else None
            try:
                step_callback(
                    session_id=session_id, step_num=step_num,
                    action=act_id, data=act_data,
                    grid=new_grid, llm_response=llm_resp,
                    state=state_val, levels=new_levels,
                )
            except Exception as cb_err:
                print(f"  [callback error] {cb_err}")

        # Check for terminal state — break plan early
        if frame.state in (GameState.WIN, GameState.GAME_OVER):
            terminal_hit = True
            break

        # Check step budget
        if step_num >= max_steps:
            break

    # Log single-agent turn (1 turn, possibly multiple steps)
    if session_id:
        from db import _log_turn as _log_turn_db
        _log_turn_db(
            session_id, turn_num, "single_agent",
            goal=reasoning,
            steps_planned=steps_planned, steps_executed=steps_executed,
            step_start=turn_step_start, step_end=step_num,
            llm_calls=1,
            total_input_tokens=llm_result.input_tokens,
            total_output_tokens=llm_result.output_tokens,
            total_duration_ms=elapsed_ms,
            timestamp_start=time.time() - (elapsed_ms / 1000),
            timestamp_end=time.time(),
        )

    return (step_num, frame, grid, available, levels_done, history, terminal_hit, steps_executed)


def _check_terminal_and_post_game(
    frame,
    step_num: int,
    max_steps: int,
    levels_done: int,
    win_levels: int,
    history: list[dict],
    arcade,
    game_id: str,
    cfg: dict,
) -> tuple:
    """Check for terminal state and handle post-game.
    
    Returns:
        tuple: (done, result_str) or (False, None) if continuing
    """
    if frame.state == GameState.WIN:
        print(f"\n  >>> WIN!  Completed {win_levels} levels in {step_num} steps <<<\n")
        _post_game(arcade, game_id, history, "WIN", step_num, levels_done, win_levels, cfg)
        return (True, "WIN")
    
    if frame.state == GameState.GAME_OVER:
        print(f"\n  >>> GAME OVER at step {step_num}  (levels {levels_done}/{win_levels}) <<<\n")
        _post_game(arcade, game_id, history, "GAME_OVER", step_num, levels_done, win_levels, cfg)
        return (True, "GAME_OVER")
    
    if step_num >= max_steps:
        final_state = frame.state.value if frame and hasattr(frame.state, "value") else "TIMEOUT"
        print(f"\n  >>> Max steps reached ({max_steps}).  Final: {final_state} <<<\n")
        _post_game(arcade, game_id, history, final_state, step_num,
                   frame.levels_completed if frame else 0,
                   frame.win_levels if frame else 0, cfg)
        return (True, final_state)
    
    return (False, None)


def play_game(arcade, game_id: str, cfg: dict, max_steps: int = 200,
              session_id: str | None = None, step_callback=None) -> str:
    """Orchestrator for game play loop.
    
    Manages session setup → main loop (prompt/LLM/parse/execute) → termination checks.
    """
    # Session initialization
    setup_result = _setup_game_session(arcade, game_id, cfg)
    if setup_result is None:
        return "ERROR"

    env, frame, hard_memory, history, step_num, steps_since_condense, mcfg = setup_result
    condense_every = mcfg["condense_every"]
    condense_threshold = mcfg["condense_threshold"]
    planning_horizon = cfg["reasoning"].get("planning_horizon", 1)
    
    prev_grid: list | None = None
    
    # Main game loop
    while step_num < max_steps:
        # Extract current frame state
        grid = frame.frame[-1].tolist() if frame.frame else []
        state_str = frame.state.value if hasattr(frame.state, "value") else str(frame.state)
        available = frame.available_actions
        levels_done = frame.levels_completed
        win_levels = frame.win_levels

        # Check for terminal states at loop start
        done, result = _check_terminal_and_post_game(
            frame, step_num, max_steps, levels_done, win_levels, history, arcade, game_id, cfg
        )
        if done:
            return result

        # Maybe condense history
        history, steps_since_condense = _maybe_condense_history(
            history, cfg, steps_since_condense, condense_every, condense_threshold
        )

        # Prepare prompt and call LLM
        llm_result, prompt, elapsed_ms, turn_num = _prepare_prompt_and_call_llm(
            grid, state_str, available, levels_done, win_levels,
            game_id, history, cfg, prev_grid, hard_memory, session_id, step_num
        )

        # Parse response and build action list
        action_list, observation, reasoning, raw_reasoning_saved, hard_memory = _parse_and_build_action_list(
            llm_result, available, planning_horizon, game_id, cfg
        )

        # Execute actions and update history
        (step_num, frame, grid, available, levels_done, history, 
         terminal_hit, steps_executed) = _execute_and_log_action_plan(
            action_list, env, frame, available, grid, levels_done, win_levels,
            elapsed_ms, step_num, observation, reasoning, raw_reasoning_saved,
            None, history, session_id, llm_result, step_callback, max_steps
        )
        
        # Update steps_since_condense based on steps executed
        steps_since_condense += steps_executed

        # If terminal state was hit during action execution, check again at top of loop
        if terminal_hit:
            continue

    # Final check (max_steps exceeded)
    final_state = frame.state.value if frame and hasattr(frame.state, "value") else "TIMEOUT"
    print(f"\n  >>> Max steps reached ({max_steps}).  Final: {final_state} <<<\n")
    _post_game(arcade, game_id, history, final_state, step_num,
               frame.levels_completed if frame else 0,
               frame.win_levels if frame else 0, cfg)
    return final_state


def _post_game(arcade, game_id: str, history: list, result: str,
               steps: int, levels_done: int, win_levels: int, cfg: dict) -> None:
    # Session log
    log_session(cfg, {
        "timestamp": datetime.utcnow().isoformat(),
        "game_id": game_id,
        "result": result,
        "steps": steps,
        "levels_completed": levels_done,
        "win_levels": win_levels,
        "executor_model": effective_model(cfg, "executor"),
    })
    # Post-game reflection
    reflect_and_update_memory(game_id, history, result, steps, levels_done, win_levels, cfg)


# ═══════════════════════════════════════════════════════════════════════════
# OBSERVABILITY SERVER (auto-started with --obs)
# ═══════════════════════════════════════════════════════════════════════════

_obs_server = None


def _start_obs_server(port: int = 5111):
    """Start the Flask server in a background thread for the /obs dashboard."""
    global _obs_server
    try:
        from server import app
        from werkzeug.serving import make_server
        _obs_server = make_server("0.0.0.0", port, app)
        t = threading.Thread(target=_obs_server.serve_forever, daemon=True)
        t.start()
        print(f"\n  Observatory dashboard: http://localhost:{port}/obs\n")
    except Exception as e:
        print(f"  [obs] Failed to start dashboard server: {e}")


def _obs_keepalive(seconds: int = 60):
    """Keep the process alive so the dashboard remains accessible after the run."""
    if _obs_server is None:
        return
    print(f"\n  Run complete. Dashboard still live for {seconds}s — Ctrl+C to exit early.")
    try:
        time.sleep(seconds)
    except KeyboardInterrupt:
        pass
    print("  Observatory shutting down.")


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="ARC-AGI-3 Autonomous Agent (config-driven)")
    parser.add_argument("--game", default="all", help="Game ID or 'all'")
    parser.add_argument("--model", default=None, help="Override executor model")
    parser.add_argument("--max-steps", type=int, default=200)
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    parser.add_argument("--list-models", action="store_true")
    parser.add_argument("--show-config", action="store_true", help="Print resolved config and exit")
    parser.add_argument("--scaffolding", action="store_true", help="Use 3-system scaffold agent")
    parser.add_argument("--planning-horizon", type=int, default=None,
                        help="Max actions per LLM call (1=single-action, >1=multi-action planning)")
    parser.add_argument("--obs", action="store_true",
                        help="Enable observability dashboard (writes to .agent_obs/)")
    args = parser.parse_args()

    cfg = load_config(Path(args.config) if args.config else None)

    # CLI overrides
    if args.model:
        cfg["reasoning"]["executor_model"] = args.model
    if args.planning_horizon is not None:
        cfg["reasoning"]["planning_horizon"] = args.planning_horizon
    if args.obs:
        cfg["observability"] = True
        _start_obs_server()

    if args.list_models:
        print("\nAvailable models:\n")
        for key, info in MODELS.items():
            env_key = info.get("env_key", "")
            status = "OK" if (not env_key or os.environ.get(env_key)) else "MISSING KEY"
            print(f"  {key:45s}  [{info['provider']:12s}]  {status}")
        print()
        return

    if args.show_config:
        print("\nResolved config:\n")
        print(yaml.dump(cfg, default_flow_style=False))
        return

    exec_model = cfg["reasoning"]["executor_model"]
    if exec_model not in MODELS:
        print(f"Unknown model: {exec_model}")
        sys.exit(1)

    info = MODELS[exec_model]
    if info.get("env_key") and not os.environ.get(info["env_key"]):
        print(f"ERROR: {info['env_key']} not set in .env")
        sys.exit(1)

    arcade = arc_agi.Arcade()
    available_games = [e.game_id for e in arcade.get_environments()]

    def resolve_id(query):
        if query in available_games:
            return query
        for gid in available_games:
            if gid.startswith(query):
                return gid
        return None

    games = available_games if args.game == "all" else []
    if args.game != "all":
        resolved = resolve_id(args.game)
        if not resolved:
            print(f"Unknown game: {args.game}  (available: {', '.join(available_games)})")
            sys.exit(1)
        games = [resolved]

    print(f"\n{'#'*65}")
    print(f"  ARC-AGI-3 Autonomous Agent")
    print(f"  Executor model : {exec_model}")
    print(f"  Games          : {', '.join(games)}")
    print(f"  Max steps/game : {args.max_steps}")
    print(f"  Config file    : {args.config or 'config.yaml (default)'}")
    print(f"{'#'*65}")

    # Select game loop
    game_fn = play_game
    if args.scaffolding:
        from agent_scaffold import play_game_scaffold
        game_fn = play_game_scaffold
        cfg.setdefault("scaffolding", {}).setdefault("mode", "three_system")

    results = {}
    for game_id in games:
        results[game_id] = game_fn(arcade, game_id, cfg, args.max_steps)

    print(f"\n{'='*65}")
    print("  RESULTS")
    print(f"{'='*65}")
    for gid, res in results.items():
        print(f"  {gid:15s} -> {res}")
    print(f"\n  Scorecard: {arcade.get_scorecard()}\n")

    if args.obs:
        _obs_keepalive(60)


if __name__ == "__main__":
    main()
