"""Three-System CLI/batch game loop — drop-in replacement for play_game."""

import json
import time

from arcengine import GameAction, GameState

from agent import (
    ACTION_NAMES,
    effective_model,
    load_hard_memory,
    _post_game,
    append_memory_bullet,
)
from agent_history import condense_history
from grid_analysis import (
    compute_change_map,
    compress_row,
)
from db import _log_turn

from scaffoldings.three_system.systems import (
    StepSnapshot,
    GameContext,
    PlannerSystem,
    MonitorSystem,
    WorldModelSystem,
)


def play_game_scaffold(arcade, game_id: str, cfg: dict, max_steps: int = 200,
                       session_id: str | None = None, step_callback=None) -> str:
    """Three-system agent game loop. Same interface as agent.play_game()."""
    scfg = cfg.get("scaffolding", {})

    print(f"\n{'='*65}")
    print(f"  PLAYING (3-system scaffold): {game_id}")
    print(f"  Planner:     {effective_model(cfg, 'planner')}")
    print(f"  Monitor:     {effective_model(cfg, 'monitor')}")
    print(f"  World Model: {effective_model(cfg, 'world_model')}")
    print(f"{'='*65}\n")

    env = arcade.make(game_id)
    frame = env.observation_space
    if frame is None:
        print("  [ERROR] Could not start game.")
        return "ERROR"

    # Initialize context
    world_model = WorldModelSystem()
    monitor = MonitorSystem()
    planner = PlannerSystem(world_model)

    ctx = GameContext(
        game_id=game_id,
        cfg=cfg,
        hard_memory=load_hard_memory(cfg),
        session_id=session_id or "",
    )

    mcfg = cfg["memory"]
    condense_every = mcfg["condense_every"]
    condense_threshold = mcfg["condense_threshold"]
    turn_num = 0

    while ctx.step_num < max_steps:
        # Update context from frame
        ctx.grid = frame.frame[-1].tolist() if frame.frame else []
        ctx.state_str = frame.state.value if hasattr(frame.state, "value") else str(frame.state)
        ctx.available_actions = frame.available_actions
        ctx.levels_done = frame.levels_completed
        ctx.win_levels = frame.win_levels

        # Terminal states
        if frame.state == GameState.WIN:
            print(f"\n  >>> WIN! Completed {ctx.win_levels} levels in {ctx.step_num} steps "
                  f"({ctx.llm_calls} LLM calls) <<<\n")
            _post_game(arcade, game_id, ctx.history, "WIN", ctx.step_num,
                       ctx.levels_done, ctx.win_levels, cfg)
            return "WIN"
        if frame.state == GameState.GAME_OVER:
            print(f"\n  >>> GAME OVER at step {ctx.step_num} ({ctx.llm_calls} LLM calls) <<<\n")
            _post_game(arcade, game_id, ctx.history, "GAME_OVER", ctx.step_num,
                       ctx.levels_done, ctx.win_levels, cfg)
            return "GAME_OVER"

        # ── Context condensation ────────────────────────────────────────
        raw_history_len = sum(1 for h in ctx.history if not h.get("is_summary"))
        should_condense = (
            condense_every > 0 and ctx.steps_since_condense >= condense_every
        ) or (
            condense_threshold > 0 and raw_history_len >= condense_threshold
        )
        # Token-based trigger: compact when history portion exceeds ~60% of budget
        max_ctx_tokens = cfg["context"].get("max_context_tokens", 100000)
        if max_ctx_tokens > 0 and raw_history_len > 0 and not should_condense:
            estimated_tokens = len(str(ctx.history)) // 4
            if estimated_tokens > max_ctx_tokens * 0.6:
                should_condense = True
        if should_condense and raw_history_len > 0:
            ctx.history = condense_history(ctx.history, cfg)
            ctx.steps_since_condense = 0

        # ── PLANNER: generate plan ──────────────────────────────────────
        turn_num += 1
        ctx.current_turn_num = turn_num
        turn_start_time = time.time()
        step_start = ctx.step_num + 1
        # Reset per-turn accumulators
        ctx.turn_input_tokens = 0
        ctx.turn_output_tokens = 0
        ctx.turn_duration_ms = 0
        ctx.turn_llm_calls = 0
        replan_reason = None

        print(f"\n  [step {ctx.step_num}] Generating plan...")
        plan_result = planner.generate_plan(ctx)
        ctx.current_plan = plan_result["plan"]
        ctx.plan_goal = plan_result["goal"]
        ctx.plan_index = 0
        ctx.plans_since_replan += 1

        print(f"  [plan] goal: {ctx.plan_goal[:80]}")
        print(f"  [plan] {len(ctx.current_plan)} steps: "
              + " → ".join(ACTION_NAMES.get(s["action"], "?") for s in ctx.current_plan))

        # ── EXECUTOR: run planned steps ─────────────────────────────────
        for plan_step in ctx.current_plan:
            if ctx.step_num >= max_steps:
                break

            action_id = plan_step["action"]
            action_data = plan_step.get("data", {})
            expected = plan_step.get("expected", "")

            # Validate action
            if action_id not in ctx.available_actions:
                action_id = ctx.available_actions[0] if ctx.available_actions else 1

            try:
                action = GameAction.from_id(int(action_id))
            except (ValueError, KeyError):
                action = GameAction.ACTION1

            # Execute
            pre_grid = ctx.grid
            ctx.step_num += 1
            ctx.steps_since_condense += 1
            ctx.plan_index += 1

            aname = ACTION_NAMES.get(action_id, f"ACTION{action_id}")
            coord_str = (f"@({action_data.get('x','?')},{action_data.get('y','?')})"
                         if action_id == 6 and action_data else "")
            print(f"    Step {ctx.step_num:3d} | {aname}{coord_str:12s} | "
                  f"lvl {ctx.levels_done}/{ctx.win_levels} | "
                  f"plan {ctx.plan_index}/{len(ctx.current_plan)}")

            ctx.prev_grid = ctx.grid
            frame = env.step(action, data=action_data or None, reasoning=expected)
            if frame is None:
                print("  [ERROR] env.step returned None")
                _post_game(arcade, game_id, ctx.history, "ERROR", ctx.step_num,
                           ctx.levels_done, ctx.win_levels, cfg)
                return "ERROR"

            # Update state from frame
            new_grid = frame.frame[-1].tolist() if frame.frame else ctx.grid
            ctx.grid = new_grid
            ctx.state_str = frame.state.value if hasattr(frame.state, "value") else str(frame.state)
            ctx.available_actions = frame.available_actions
            ctx.levels_done = frame.levels_completed
            ctx.win_levels = frame.win_levels

            # Compute change map for this step
            step_change_map = compute_change_map(pre_grid, new_grid)

            # Record snapshot
            snapshot = StepSnapshot(
                step=ctx.step_num, action=action_id, data=action_data,
                grid=new_grid, prev_grid=pre_grid,
                change_map=step_change_map,
                levels=ctx.levels_done, state=ctx.state_str,
            )
            ctx.snapshots.append(snapshot)
            ctx.observations_buffer.append(snapshot)

            # Record history
            ctx.history.append({
                "step": ctx.step_num,
                "action": action_id,
                "data": action_data,
                "state": ctx.state_str,
                "levels": ctx.levels_done,
                "observation": expected,
                "reasoning": ctx.plan_goal,
            })

            # Step callback (batch_runner DB persistence)
            if step_callback:
                llm_resp = {"observation": expected, "reasoning": ctx.plan_goal,
                            "action": action_id, "data": action_data}
                try:
                    step_callback(
                        session_id=session_id, step_num=ctx.step_num,
                        action=action_id, data=action_data,
                        grid=new_grid, llm_response=llm_resp,
                        state=ctx.state_str, levels=ctx.levels_done,
                    )
                except Exception as cb_err:
                    print(f"    [callback error] {cb_err}")

            # Check terminal states
            if frame.state == GameState.WIN:
                print(f"\n  >>> WIN! Completed {ctx.win_levels} levels in {ctx.step_num} steps "
                      f"({ctx.llm_calls} LLM calls) <<<\n")
                _post_game(arcade, game_id, ctx.history, "WIN", ctx.step_num,
                           ctx.levels_done, ctx.win_levels, cfg)
                return "WIN"
            if frame.state == GameState.GAME_OVER:
                print(f"\n  >>> GAME OVER at step {ctx.step_num} ({ctx.llm_calls} LLM calls) <<<\n")
                _post_game(arcade, game_id, ctx.history, "GAME_OVER", ctx.step_num,
                           ctx.levels_done, ctx.win_levels, cfg)
                return "GAME_OVER"

            # ── MONITOR: check each step ────────────────────────────────
            monitor_result = monitor.check(ctx, expected, pre_grid, new_grid)

            # Handle discoveries
            if monitor_result.get("discovery") and cfg["memory"]["allow_inline_memory_writes"]:
                disc = monitor_result["discovery"]
                append_memory_bullet(cfg, game_id, disc)
                ctx.hard_memory = load_hard_memory(cfg)
                print(f"      [discovery] {disc[:80]}")

            # Replan if monitor says so
            if monitor_result["verdict"] == "REPLAN":
                replan_reason = monitor_result.get("reason", "monitor triggered replan")
                print(f"    [replan] breaking plan at step {ctx.plan_index}/{len(ctx.current_plan)}")
                break

        # ── WORLD MODEL: update rules periodically ──────────────────────
        wm_updated = False
        if world_model.should_update(ctx):
            print(f"\n  [world_model] updating rules (buffer={len(ctx.observations_buffer)} obs)...")
            world_model.update(ctx)
            wm_updated = True

        # ── LOG TURN ─────────────────────────────────────────────────────
        if ctx.session_id:
            _log_turn(
                ctx.session_id, turn_num, "three_system",
                goal=ctx.plan_goal,
                plan_json=json.dumps(ctx.current_plan),
                steps_planned=len(ctx.current_plan),
                steps_executed=ctx.plan_index,
                step_start=step_start,
                step_end=ctx.step_num,
                llm_calls=ctx.turn_llm_calls,
                total_input_tokens=ctx.turn_input_tokens,
                total_output_tokens=ctx.turn_output_tokens,
                total_duration_ms=ctx.turn_duration_ms,
                replan_reason=replan_reason,
                world_model_updated=wm_updated,
                rules_version=ctx.rules_version,
                timestamp_start=turn_start_time,
                timestamp_end=time.time(),
            )

    # Timed out
    final_state = frame.state.value if frame and hasattr(frame.state, "value") else "TIMEOUT"
    print(f"\n  >>> Max steps reached ({max_steps}). Final: {final_state} "
          f"({ctx.llm_calls} LLM calls) <<<\n")
    _post_game(arcade, game_id, ctx.history, final_state, ctx.step_num,
               frame.levels_completed if frame else 0,
               frame.win_levels if frame else 0, cfg)
    return final_state
