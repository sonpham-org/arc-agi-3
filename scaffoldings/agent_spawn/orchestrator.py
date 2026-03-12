"""Orchestrator REPL loop — spawns subagents and coordinates gameplay."""

import json

from agent import (
    ACTION_NAMES,
    effective_model,
)
from agent_llm import call_model_with_metadata
from agent_response_parsing import _parse_json
from db import _log_llm_call

from scaffoldings.agent_spawn.memories import SharedMemories
from scaffoldings.agent_spawn.prompts import (
    ORCHESTRATOR_SYSTEM,
    ORCHESTRATOR_TURN_TEMPLATE,
)
from scaffoldings.agent_spawn.tools import (
    format_grid,
    format_change_map,
    format_history,
)


def orchestrator_decide(
    game_id: str,
    frame,
    cfg: dict,
    memories: SharedMemories,
    step_num: int,
    max_steps: int,
    history: list,
    prev_grid: list | None,
    session_id: str,
) -> dict:
    """One orchestrator turn: decide what to do next.

    Returns parsed JSON decision dict with 'command' key.
    Only two valid commands: 'delegate' and 'think'.
    """
    model = effective_model(cfg, "planner")
    grid = frame.frame[-1].tolist() if frame.frame else []

    prompt = ORCHESTRATOR_SYSTEM + "\n\n" + ORCHESTRATOR_TURN_TEMPLATE.format(
        game_id=game_id,
        step_num=step_num,
        max_steps=max_steps,
        levels_done=frame.levels_completed,
        win_levels=frame.win_levels,
        state_str=frame.state.value if hasattr(frame.state, "value") else str(frame.state),
        available_actions=frame.available_actions,
        grid_str=format_grid(grid),
        change_map=format_change_map(prev_grid, grid),
        memories=memories.format_for_prompt(),
        history_len=min(len(history), 15),
        history=format_history(history),
    )

    result = call_model_with_metadata(
        model, prompt, cfg, role="planner",
        tools_enabled=True, session_id=session_id,
        grid=grid, prev_grid=prev_grid,
        thinking_budget=16000,
    )

    # Log LLM call
    if session_id:
        _log_llm_call(
            session_id, "orchestrator", model,
            input_json=prompt[:2000],
            output_json=(result.text or "")[:2000],
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            thinking_tokens=result.thinking_tokens,
            thinking_json=(result.thinking_text or "")[:5000] if result.thinking_text else None,
            cost=result.cost,
            duration_ms=result.duration_ms,
            error=result.error,
        )

    meta = {
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "duration_ms": result.duration_ms,
        "llm_calls": 1,
    }

    if result.error or not result.text:
        print(f"    [orchestrator] LLM error: {result.error}")
        # Fallback: think about what to explore rather than acting directly
        return {
            "command": "think",
            "facts": [],
            "hypotheses": [],
            "next": "LLM error — will retry on next turn",
            **meta,
        }

    parsed = _parse_json(result.text)
    if not parsed:
        print(f"    [orchestrator] failed to parse, falling back to think")
        return {
            "command": "think",
            "facts": [],
            "hypotheses": [],
            "next": "Parse error — will retry on next turn",
            **meta,
        }

    # Normalize: treat "spawn" as "delegate" for backwards compatibility
    if parsed.get("command") == "spawn":
        parsed["command"] = "delegate"

    # If LLM tried to use "act", convert to a think — orchestrator cannot act
    if parsed.get("command") == "act":
        print(f"    [orchestrator] WARNING: LLM tried 'act', converting to 'think'")
        return {
            "command": "think",
            "facts": [],
            "hypotheses": [],
            "next": f"Attempted direct action (not allowed). Will delegate instead. "
                    f"Original reasoning: {parsed.get('reasoning', 'none')}",
            **meta,
        }

    parsed.update(meta)
    parsed["raw_response"] = result.text or ""
    return parsed
