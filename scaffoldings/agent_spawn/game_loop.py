"""Agent Spawn game loop — drop-in replacement for play_game."""

import json
import time

from arcengine import GameAction, GameState

from agent import (
    ACTION_NAMES,
    effective_model,
    load_hard_memory,
    _post_game,
)
from agent_history import condense_history
from grid_analysis import compute_change_map
from db import _log_turn

from scaffoldings.agent_spawn.memories import SharedMemories
from scaffoldings.agent_spawn.orchestrator import orchestrator_decide
from scaffoldings.agent_spawn.subagent import run_subagent
from scaffoldings.agent_spawn.observability import AgentObserver
from scaffoldings.agent_spawn.tools import (
    format_grid,
    validate_action,
    make_game_action,
)

# Valid agent types for delegation
VALID_AGENT_TYPES = {"explorer", "theorist", "tester", "solver"}


def play_game_agent_spawn(arcade, game_id: str, cfg: dict, max_steps: int = 200,
                          session_id: str | None = None, step_callback=None) -> str:
    """Agent-spawn scaffolding game loop. Same interface as agent.play_game()."""
    print(f"\n{'='*65}")
    print(f"  PLAYING (agent-spawn scaffold): {game_id}")
    print(f"  Orchestrator: {effective_model(cfg, 'planner')}")
    # Show per-agent-type model overrides if any
    rcfg = cfg.get("reasoning", {})
    for atype in ("explorer", "theorist", "tester", "solver"):
        override = rcfg.get(f"{atype}_model")
        if override:
            print(f"  {atype:12s}: {override}")
        else:
            print(f"  {atype:12s}: {effective_model(cfg, 'planner')}")
    print(f"{'='*65}\n")

    env = arcade.make(game_id)
    frame = env.observation_space
    if frame is None:
        print("  [ERROR] Could not start game.")
        return "ERROR"

    # Initialize shared state
    memories = SharedMemories()
    history = []
    hard_memory = load_hard_memory(cfg)
    step_num = 0
    turn_num = 0
    total_llm_calls = 0
    total_input_tokens = 0
    total_output_tokens = 0
    prev_grid = None

    # Initialize observability (opt-in via cfg["observability"])
    obs = None
    if cfg.get("observability"):
        obs = AgentObserver(game_id=game_id, max_steps=max_steps, session_id=session_id or "")
        obs.update_status(
            planner_model=effective_model(cfg, "planner"),
            executor_model=effective_model(cfg, "executor"),
        )

    mcfg = cfg.get("memory", {})
    condense_every = mcfg.get("condense_every", 0)
    condense_threshold = mcfg.get("condense_threshold", 0)
    steps_since_condense = 0
    consecutive_errors = 0
    MAX_CONSECUTIVE_ERRORS = 5

    # Seed memories with hard memory if available
    if hard_memory:
        memories.add_fact(f"[hard memory] {hard_memory[:500]}")

    while step_num < max_steps:
        grid = frame.frame[-1].tolist() if frame.frame else []
        if obs: obs.update_grid(grid)

        # Check terminal states
        if frame.state == GameState.WIN:
            print(f"\n  >>> WIN! Completed {frame.win_levels} levels in {step_num} steps "
                  f"({total_llm_calls} LLM calls) <<<\n")
            if obs: obs.close("WIN")

            _post_game(arcade, game_id, history, "WIN", step_num,
                       frame.levels_completed, frame.win_levels, cfg)
            return "WIN"
        if frame.state == GameState.GAME_OVER:
            print(f"\n  >>> GAME OVER at step {step_num} ({total_llm_calls} LLM calls) <<<\n")
            if obs: obs.close("GAME_OVER")

            _post_game(arcade, game_id, history, "GAME_OVER", step_num,
                       frame.levels_completed, frame.win_levels, cfg)
            return "GAME_OVER"

        # Context condensation
        raw_history_len = sum(1 for h in history if not h.get("is_summary"))
        should_condense = (
            condense_every > 0 and steps_since_condense >= condense_every
        ) or (
            condense_threshold > 0 and raw_history_len >= condense_threshold
        )
        max_ctx_tokens = cfg.get("context", {}).get("max_context_tokens", 100000)
        if max_ctx_tokens > 0 and raw_history_len > 0 and not should_condense:
            estimated_tokens = len(str(history)) // 4
            if estimated_tokens > max_ctx_tokens * 0.6:
                should_condense = True
        if should_condense and raw_history_len > 0:
            history = condense_history(history, cfg)
            steps_since_condense = 0

        # ── ORCHESTRATOR TURN ──────────────────────────────────────────
        turn_num += 1
        turn_start_time = time.time()
        step_start = step_num + 1
        turn_input_tokens = 0
        turn_output_tokens = 0
        turn_duration_ms = 0
        turn_llm_calls = 0
        turn_steps_executed = 0

        print(f"\n  [turn {turn_num}, step {step_num}] Orchestrator deciding...")

        decision = orchestrator_decide(
            game_id=game_id,
            frame=frame,
            cfg=cfg,
            memories=memories,
            step_num=step_num,
            max_steps=max_steps,
            history=history,
            prev_grid=prev_grid,
            session_id=session_id or "",
        )

        turn_input_tokens += decision.get("input_tokens", 0)
        turn_output_tokens += decision.get("output_tokens", 0)
        turn_duration_ms += decision.get("duration_ms", 0)
        turn_llm_calls += decision.get("llm_calls", 0)

        command = decision.get("command", "think")
        print(f"    [orchestrator] command={command}")

        if obs:
            obs.orchestrator_decide(
                turn=turn_num, step=step_num, command=command,
                agent_type=decision.get("agent_type", ""),
                task=decision.get("task", decision.get("next", "")),
                input_tokens=decision.get("input_tokens", 0),
                output_tokens=decision.get("output_tokens", 0),
                duration_ms=decision.get("duration_ms", 0),
                response=decision.get("raw_response", ""),
            )
            obs.update_level(frame.levels_completed, frame.win_levels)

        # ── HANDLE THINK ───────────────────────────────────────────────
        if command == "think":
            task_text = decision.get("task", decision.get("next", ""))
            is_error = "LLM error" in task_text or "Parse error" in task_text

            if is_error:
                consecutive_errors += 1
                if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                    print(f"    [orchestrator] {consecutive_errors} consecutive LLM errors — aborting game")
                    if obs: obs.close("LLM_ERROR")
                    _post_game(arcade, game_id, history, "LLM_ERROR", step_num,
                               frame.levels_completed, frame.win_levels, cfg)
                    return "LLM_ERROR"
                # Exponential backoff: 2s, 4s, 8s, 16s, 32s
                wait = 2 ** consecutive_errors
                print(f"    [orchestrator] LLM error #{consecutive_errors}, backing off {wait}s...")
                time.sleep(wait)
            else:
                consecutive_errors = 0

            for f in decision.get("facts", []):
                memories.add_fact(f)
                print(f"    [fact] {f[:80]}")
            for h in decision.get("hypotheses", []):
                memories.add_hypothesis(h)
                print(f"    [hypothesis] {h[:80]}")
            # Think doesn't use any steps, loop back for next decision
            total_llm_calls += turn_llm_calls
            total_input_tokens += turn_input_tokens
            total_output_tokens += turn_output_tokens
            if obs: obs.update_totals(total_llm_calls, total_input_tokens, total_output_tokens)
            continue

        # ── HANDLE DELEGATE (spawn subagent) ──────────────────────────
        consecutive_errors = 0  # successful orchestrator call, reset error counter
        if command == "delegate":
            agent_type = decision.get("agent_type", "explorer")
            task = decision.get("task", "explore the game")
            budget = min(decision.get("budget", 3), 10)

            # Validate agent type
            if agent_type not in VALID_AGENT_TYPES:
                print(f"    [orchestrator] WARNING: unknown agent type '{agent_type}', defaulting to explorer")
                agent_type = "explorer"

            # Theorists don't execute game actions — budget controls LLM iterations
            if agent_type == "theorist":
                print(f"    [delegate] {agent_type} — budget={budget} (analysis only) — task: {task[:60]}")
            else:
                print(f"    [delegate] {agent_type} — budget={budget} — task: {task[:60]}")

            sub_result = run_subagent(
                agent_type=agent_type,
                task=task,
                budget=budget,
                env=env,
                frame=frame,
                cfg=cfg,
                memories=memories,
                step_num=step_num,
                max_steps=max_steps,
                session_id=session_id or "",
                history=history,
                step_callback=step_callback,
                observer=obs,
            )

            # Update state from subagent
            step_num = sub_result["step_num"]
            frame = sub_result["frame"]
            history = sub_result["history"]
            steps_since_condense += sub_result["steps_used"]
            turn_steps_executed = sub_result["steps_used"]

            turn_input_tokens += sub_result["input_tokens"]
            turn_output_tokens += sub_result["output_tokens"]
            turn_duration_ms += sub_result["duration_ms"]
            turn_llm_calls += sub_result["llm_calls"]

            # Update grid tracking
            prev_grid = grid

            if sub_result["terminal"]:
                terminal = sub_result["terminal"]
                total_llm_calls += turn_llm_calls
                if terminal == "WIN":
                    print(f"\n  >>> WIN! Completed {frame.win_levels} levels in {step_num} steps "
                          f"({total_llm_calls} LLM calls) <<<\n")
                    if obs: obs.close("WIN")

                    _post_game(arcade, game_id, history, "WIN", step_num,
                               frame.levels_completed, frame.win_levels, cfg)
                    return "WIN"
                elif terminal == "GAME_OVER":
                    print(f"\n  >>> GAME OVER at step {step_num} ({total_llm_calls} LLM calls) <<<\n")
                    if obs: obs.close("GAME_OVER")

                    _post_game(arcade, game_id, history, "GAME_OVER", step_num,
                               frame.levels_completed, frame.win_levels, cfg)
                    return "GAME_OVER"
                else:
                    if obs: obs.close(terminal)
                    return terminal

        # ── LOG TURN ───────────────────────────────────────────────────
        total_llm_calls += turn_llm_calls
        total_input_tokens += turn_input_tokens
        total_output_tokens += turn_output_tokens

        if obs:
            obs.update_totals(total_llm_calls, total_input_tokens, total_output_tokens)
            obs.update_memory_stats(memories)
            obs.dump_memory(memories)

        if session_id:
            _log_turn(
                session_id, turn_num, "agent_spawn",
                goal=f"{command}: {decision.get('task', decision.get('reasoning', decision.get('next', '')))}",
                plan_json=json.dumps(decision, default=str),
                steps_planned=decision.get("budget", 1) if command == "delegate" else 0,
                steps_executed=turn_steps_executed,
                step_start=step_start,
                step_end=step_num,
                llm_calls=turn_llm_calls,
                total_input_tokens=turn_input_tokens,
                total_output_tokens=turn_output_tokens,
                total_duration_ms=turn_duration_ms,
                replan_reason=None,
                world_model_updated=False,
                rules_version=0,
                timestamp_start=turn_start_time,
                timestamp_end=time.time(),
            )

    # Max steps reached
    final_state = frame.state.value if frame and hasattr(frame.state, "value") else "TIMEOUT"
    print(f"\n  >>> Max steps reached ({max_steps}). Final: {final_state} "
          f"({total_llm_calls} LLM calls) <<<\n")
    if obs: obs.close(final_state)
    _post_game(arcade, game_id, history, final_state, step_num,
               frame.levels_completed if frame else 0,
               frame.win_levels if frame else 0, cfg)
    return final_state
