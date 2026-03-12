"""SubAgent REPL loop — explorer, theorist, tester, and solver agents with bounded action budgets."""

import json

from arcengine import GameState

from agent import (
    ACTION_NAMES,
    effective_model,
)
from agent_llm import call_model_with_metadata
from agent_response_parsing import _parse_json
from db import _log_llm_call

from scaffoldings.agent_spawn.memories import SharedMemories
from scaffoldings.agent_spawn.prompts import (
    EXPLORER_SYSTEM,
    THEORIST_SYSTEM,
    TESTER_SYSTEM,
    SOLVER_SYSTEM,
    SUBAGENT_TURN_TEMPLATE,
    SUBAGENT_SUMMARY_TEMPLATE,
)
from scaffoldings.agent_spawn.tools import (
    format_grid,
    format_change_map,
    validate_action,
    make_game_action,
    as_dispatch_frame_tool,
)


SYSTEM_PROMPTS = {
    "explorer": EXPLORER_SYSTEM,
    "theorist": THEORIST_SYSTEM,
    "tester": TESTER_SYSTEM,
    "solver": SOLVER_SYSTEM,
}


def run_subagent(
    agent_type: str,
    task: str,
    budget: int,
    env,
    frame,
    cfg: dict,
    memories: SharedMemories,
    step_num: int,
    max_steps: int,
    session_id: str,
    history: list,
    step_callback=None,
    observer=None,
) -> dict:
    """Run a subagent with bounded budget. Returns dict with results.

    Returns:
        {
            "steps_used": int,
            "step_num": int,          # updated step counter
            "frame": frame,           # latest frame
            "history": list,          # updated history
            "report": str,            # subagent's summary
            "findings": list[str],
            "hypotheses": list[str],
            "terminal": str | None,   # "WIN" or "GAME_OVER" if hit terminal
            "llm_calls": int,
            "input_tokens": int,
            "output_tokens": int,
            "duration_ms": int,
        }
    """
    budget = min(budget, 10)  # hard cap
    is_theorist = (agent_type == "theorist")
    # Per-agent-type model override (e.g. explorer_model), fallback to planner model
    agent_model = cfg["reasoning"].get(f"{agent_type}_model")
    model = agent_model if agent_model else effective_model(cfg, "planner")
    system_prompt = SYSTEM_PROMPTS.get(agent_type, EXPLORER_SYSTEM)

    # Per-agent thinking budgets
    THINKING_BUDGETS = {"theorist": 16000, "solver": 16000, "tester": 8000, "explorer": 4000}
    thinking_budget = THINKING_BUDGETS.get(agent_type, 4000)

    session_actions = []
    tool_results = []  # accumulates frame tool results across iterations
    steps_used = 0
    total_input_tokens = 0
    total_output_tokens = 0
    total_duration_ms = 0
    llm_calls = 0
    report = ""
    findings = []
    hypotheses = []
    terminal = None

    grid = frame.frame[-1].tolist() if frame.frame else []
    prev_grid = None

    # For theorists, effective budget is 0 (no game actions), but allow LLM iterations
    max_iterations = (budget + 5) if is_theorist else (budget + 2)

    print(f"      [{agent_type}] starting — task: {task[:60]}, budget: {budget}")
    if observer:
        avail_str = ", ".join(str(a) for a in (frame.available_actions or []))
        level_str = f"{frame.levels_completed}/{frame.win_levels}"
        mem_str = memories.format_for_prompt()[:500] if memories else ""
        observer.subagent_start(agent_type, task, budget, step_num,
                                available_actions=avail_str, level=level_str,
                                memory_summary=mem_str)

    for turn in range(max_iterations):
        # For non-theorists, stop when action budget or global step limit is reached
        if not is_theorist and (steps_used >= budget or step_num >= max_steps):
            break
        # For theorists, limit total LLM calls to prevent infinite loops
        if is_theorist and llm_calls >= budget + 3:
            break

        # Build tool results text
        tool_results_text = "(none)"
        if tool_results:
            tool_results_text = "\n".join(
                f"[{i+1}] {tr['tool']}: {tr['result'][:300]}"
                for i, tr in enumerate(tool_results[-5:])  # last 5 tool results
            )

        # Build prompt
        prompt = system_prompt + "\n\n" + SUBAGENT_TURN_TEMPLATE.format(
            task=task,
            step_num=step_num,
            budget_remaining=0 if is_theorist else (budget - steps_used),
            levels_done=frame.levels_completed,
            win_levels=frame.win_levels,
            state_str=frame.state.value if hasattr(frame.state, "value") else str(frame.state),
            available_actions=frame.available_actions,
            grid_str=format_grid(grid),
            change_map=format_change_map(prev_grid, grid),
            memories=memories.format_for_prompt(max_observations=10),
            session_history=_format_session_actions(session_actions),
            tool_results=tool_results_text,
        )

        # Call LLM (with run_python tool for Gemini models)
        result = call_model_with_metadata(
            model, prompt, cfg, role="executor",
            tools_enabled=True, session_id=session_id,
            grid=grid, prev_grid=prev_grid,
            thinking_budget=thinking_budget,
        )
        llm_calls += 1
        total_input_tokens += result.input_tokens
        total_output_tokens += result.output_tokens
        total_duration_ms += result.duration_ms

        # Log LLM call
        if session_id:
            _log_llm_call(
                session_id, f"subagent_{agent_type}", model,
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

        if result.error or not result.text:
            print(f"      [{agent_type}] LLM error: {result.error}")
            break

        # Parse response
        parsed = _parse_json(result.text)
        if not parsed:
            print(f"      [{agent_type}] failed to parse response")
            break

        command = parsed.get("command", "act")

        # ── Handle report command — yield back to orchestrator ────────
        if command == "report":
            findings = parsed.get("findings", [])
            hypotheses = parsed.get("hypotheses", [])
            report = parsed.get("summary", "")
            for f in findings:
                memories.add_fact(f)
            for h in hypotheses:
                memories.add_hypothesis(h)
            print(f"      [{agent_type}] reporting: {report[:80]}")
            break

        # ── Handle frame_tool command — FREE, no budget cost ──────────
        if command == "frame_tool":
            tool_name = parsed.get("tool", "")
            tool_args = parsed.get("args", {})
            print(f"      [{agent_type}] frame_tool: {tool_name}")
            if observer:
                observer.subagent_frame_tool(agent_type, tool_name)
            tool_result = as_dispatch_frame_tool(tool_name, grid, prev_grid, tool_args)
            tool_results.append({
                "tool": tool_name,
                "result": tool_result,
            })
            # Continue loop — frame tools don't consume budget or end the turn
            continue

        # ── Handle act command ────────────────────────────────────────
        if command == "act":
            # Theorists cannot act — treat as error and continue
            if is_theorist:
                print(f"      [{agent_type}] ERROR: theorists cannot use 'act', ignoring")
                tool_results.append({
                    "tool": "ERROR",
                    "result": "Theorists cannot use the 'act' command. Use 'frame_tool' or 'report' instead.",
                })
                continue

            action_id = parsed.get("action", 1)
            action_data = parsed.get("data", {})
            reasoning = parsed.get("reasoning", "")

            action_id = validate_action(action_id, frame.available_actions)
            action = make_game_action(action_id)

            # Execute
            prev_grid = grid
            step_num += 1
            steps_used += 1

            aname = ACTION_NAMES.get(action_id, f"ACTION{action_id}")
            coord_str = (f"@({action_data.get('x','?')},{action_data.get('y','?')})"
                         if action_id == 6 and action_data else "")
            print(f"      [{agent_type}] step {step_num}: {aname}{coord_str} — {reasoning[:50]}")

            frame = env.step(action, data=action_data or None, reasoning=reasoning)
            if frame is None:
                print(f"      [{agent_type}] env.step returned None")
                terminal = "ERROR"
                break

            new_grid = frame.frame[-1].tolist() if frame.frame else grid
            state_str = frame.state.value if hasattr(frame.state, "value") else str(frame.state)

            # Update grid and log action in dashboard immediately after env.step
            if observer:
                observer.subagent_act(
                    agent_type, step_num, f"{aname}{coord_str}",
                    state=state_str,
                    reasoning=reasoning,
                    input_tokens=result.input_tokens,
                    output_tokens=result.output_tokens,
                    duration_ms=result.duration_ms,
                    grid=new_grid,
                    response=result.text or "",
                )
                observer.update_grid(new_grid)

            # Record observation
            observation = f"{aname}{coord_str} -> state={state_str}"
            memories.add_observation(step_num, action_id, observation, prev_grid, new_grid)
            memories.log_action(step_num, action_id, action_data, agent_type, reasoning)

            session_actions.append({
                "step": step_num,
                "action": action_id,
                "data": action_data,
                "reasoning": reasoning,
                "state": state_str,
            })

            # History entry (same format as play_game)
            history.append({
                "step": step_num,
                "action": action_id,
                "data": action_data,
                "state": state_str,
                "levels": frame.levels_completed,
                "observation": observation,
                "reasoning": f"[{agent_type}] {reasoning}",
            })

            # Step callback for DB persistence
            if step_callback:
                llm_resp = {
                    "observation": observation,
                    "reasoning": f"[{agent_type}] {reasoning}",
                    "action": action_id,
                    "data": action_data,
                }
                try:
                    step_callback(
                        session_id=session_id, step_num=step_num,
                        action=action_id, data=action_data,
                        grid=new_grid, llm_response=llm_resp,
                        state=state_str, levels=frame.levels_completed,
                    )
                except Exception as cb_err:
                    print(f"      [{agent_type}] callback error: {cb_err}")

            grid = new_grid

            # Check terminal
            if frame.state == GameState.WIN:
                terminal = "WIN"
                print(f"      [{agent_type}] >>> WIN! <<<")
                break
            if frame.state == GameState.GAME_OVER:
                terminal = "GAME_OVER"
                print(f"      [{agent_type}] >>> GAME OVER <<<")
                break

    # Build final report if subagent didn't explicitly report
    if not report:
        report = f"Executed {steps_used} actions. " + (
            f"Terminal: {terminal}" if terminal else "Budget exhausted."
        )

    # Push report onto memory stack
    memories.add_to_stack(
        summary=report[:200],
        details="; ".join(findings[:3]) if findings else "",
        agent_type=agent_type,
    )

    print(f"      [{agent_type}] done — {steps_used} steps, {llm_calls} calls")

    if observer:
        observer.subagent_report(
            agent_type, steps_used, llm_calls,
            findings=len(findings), hypotheses=len(hypotheses),
            summary=report[:120],
        )

    return {
        "steps_used": steps_used,
        "step_num": step_num,
        "frame": frame,
        "history": history,
        "report": report,
        "findings": findings,
        "hypotheses": hypotheses,
        "terminal": terminal,
        "llm_calls": llm_calls,
        "input_tokens": total_input_tokens,
        "output_tokens": total_output_tokens,
        "duration_ms": total_duration_ms,
    }


def _format_session_actions(actions: list) -> str:
    """Format actions taken in this subagent session."""
    if not actions:
        return "(none yet)"
    lines = []
    for a in actions:
        aname = ACTION_NAMES.get(a["action"], "?")
        lines.append(f"  Step {a['step']}: {aname} — {a['reasoning'][:60]} -> {a['state']}")
    return "\n".join(lines)
