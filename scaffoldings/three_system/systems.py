"""Three-System core classes — Planner, Monitor, World Model + shared state."""

import re
import time
from dataclasses import dataclass, field

from agent import (
    ARC_AGI3_DESCRIPTION,
    ACTION_NAMES,
    effective_model,
    relevant_memory_section,
)
from agent_llm import (
    call_model_with_metadata,
    call_model_with_retry,
)
from agent_response_parsing import _parse_json
from grid_analysis import (
    compress_row,
    compute_change_map,
    compute_color_histogram,
    compute_region_map,
)
from db import _log_llm_call

from scaffoldings.three_system.prompts import (
    PLANNER_SYSTEM_PROMPT_BODY,
    PLANNER_CONTEXT_TEMPLATE,
    WORLD_MODEL_SYSTEM_PROMPT,
    WORLD_MODEL_CONTEXT_TEMPLATE,
    MONITOR_PROMPT_TEMPLATE,
)


def _recover_truncated_rules(raw: str) -> str | None:
    """Try to extract rules_document from a truncated JSON commit response."""
    if not raw:
        return None
    m = re.search(r'"rules_document"\s*:\s*"', raw)
    if not m:
        return None
    start = m.end()
    result = []
    i = start
    while i < len(raw):
        c = raw[i]
        if c == '\\' and i + 1 < len(raw):
            nc = raw[i + 1]
            if nc == 'n':
                result.append('\n')
            elif nc == 't':
                result.append('\t')
            elif nc == '"':
                result.append('"')
            elif nc == '\\':
                result.append('\\')
            else:
                result.append(nc)
            i += 2
        elif c == '"':
            break
        else:
            result.append(c)
            i += 1
    text = "".join(result).strip()
    return text if len(text) > 20 else None


def _compact_grid(grid: list) -> str:
    """Return a grid showing only rows with non-background content (skips uniform rows)."""
    if not grid:
        return "(empty)"
    counts: dict[int, int] = {}
    for row in grid:
        for v in row:
            counts[v] = counts.get(v, 0) + 1
    bg_color = max(counts, key=counts.get) if counts else 0
    lines = []
    for i, r in enumerate(grid):
        if all(v == bg_color for v in r):
            continue
        lines.append(f"  Row {i}: {compress_row(r)}")
    if not lines:
        return f"(all background color {bg_color})"
    if len(lines) > 30:
        lines = lines[:15] + [f"  ... ({len(lines) - 30} more rows)"] + lines[-15:]
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# GAME CONTEXT (shared state across all 3 systems)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class StepSnapshot:
    """Record of one executed step for World Model queries."""
    step: int
    action: int
    data: dict
    grid: list
    prev_grid: list | None
    change_map: str
    levels: int
    state: str


@dataclass
class GameContext:
    """Shared mutable state passed between Planner, Monitor, and World Model."""
    game_id: str
    cfg: dict

    # Current game state
    grid: list = field(default_factory=list)
    prev_grid: list | None = None
    state_str: str = "NOT_FINISHED"
    available_actions: list = field(default_factory=list)
    levels_done: int = 0
    win_levels: int = 0
    step_num: int = 0

    # Plan state
    current_plan: list = field(default_factory=list)
    plan_index: int = 0
    plan_goal: str = ""

    # World model state
    rules_doc: str = ""
    rules_version: int = 0
    observations_buffer: list = field(default_factory=list)

    # Step history (same format as play_game)
    history: list = field(default_factory=list)
    snapshots: list = field(default_factory=list)
    hard_memory: str = ""

    # Session tracking
    session_id: str = ""
    steps_since_condense: int = 0
    llm_calls: int = 0

    # Replan cooldown
    plans_since_replan: int = 99  # start high so first replan is allowed

    # Per-turn accumulators (reset each turn)
    current_turn_num: int = 0
    turn_input_tokens: int = 0
    turn_output_tokens: int = 0
    turn_duration_ms: int = 0
    turn_llm_calls: int = 0


# Build the full planner system prompt with ARC_AGI3_DESCRIPTION for CLI path
# Note: PLANNER_SYSTEM_PROMPT_BODY has {min_plan_length}/{max_plan_length} placeholders
# that get formatted at call time in _build_prompt()
_PLANNER_SYSTEM_PROMPT_TEMPLATE = ARC_AGI3_DESCRIPTION + "\n\n" + PLANNER_SYSTEM_PROMPT_BODY


# ═══════════════════════════════════════════════════════════════════════════
# PLANNER SYSTEM (REPL loop — simulate, analyze, commit)
# ═══════════════════════════════════════════════════════════════════════════

class PlannerSystem:
    """REPL loop that simulates, analyzes, and commits action plans."""

    def __init__(self, world_model: "WorldModelSystem"):
        self.world_model = world_model

    def generate_plan(self, ctx: GameContext) -> dict:
        """Run the planner REPL. Returns {goal, plan}."""
        scfg = ctx.cfg.get("scaffolding", {})
        max_turns = scfg.get("planner_max_turns", 10)
        max_plan = scfg.get("max_plan_length", 15)
        min_plan = scfg.get("min_plan_length", 3)

        model_key = effective_model(ctx.cfg, "planner")
        conversation: list[str] = []

        for turn in range(1, max_turns + 1):
            prompt = self._build_prompt(ctx, turn, max_turns, conversation)

            llm_result = call_model_with_metadata(model_key, prompt, ctx.cfg, role="planner")
            raw = llm_result.text
            elapsed = llm_result.duration_ms / 1000
            ctx.llm_calls += 1
            ctx.turn_llm_calls += 1
            ctx.turn_input_tokens += llm_result.input_tokens
            ctx.turn_output_tokens += llm_result.output_tokens
            ctx.turn_duration_ms += llm_result.duration_ms

            if ctx.session_id:
                _log_llm_call(
                    ctx.session_id, "planner", model_key,
                    step_num=ctx.step_num,
                    turn_num=ctx.current_turn_num,
                    input_json=prompt[:500],
                    output_json=(raw or "")[:1000],
                    input_tokens=llm_result.input_tokens,
                    output_tokens=llm_result.output_tokens,
                    thinking_tokens=llm_result.thinking_tokens,
                    thinking_json=(llm_result.thinking_text or "")[:5000] if llm_result.thinking_text else None,
                    cost=llm_result.cost,
                    duration_ms=llm_result.duration_ms,
                    error=llm_result.error,
                )

            print(f"    [planner] turn {turn}/{max_turns} ({elapsed:.1f}s)")

            if not raw:
                print("    [planner] LLM returned nothing, using exploratory plan")
                return self._exploratory_plan(ctx)

            parsed = _parse_json(raw)
            if not parsed or "type" not in parsed:
                print(f"    [planner] unparseable response, using exploratory plan")
                return self._exploratory_plan(ctx)

            msg_type = parsed["type"]

            if msg_type == "simulate":
                actions = parsed.get("actions", [])
                question = parsed.get("question", "")
                predictions = self.world_model.simulate(actions, ctx)
                result_text = f"Simulation of {len(actions)} action(s):\n"
                for i, (act, pred) in enumerate(zip(actions, predictions)):
                    aname = ACTION_NAMES.get(act.get("action", 0), "?")
                    result_text += f"  {i+1}. {aname}: {pred}\n"
                conversation.append(f"[Turn {turn}] You simulated: {question}\nResult: {result_text}")
                print(f"    [planner] simulated {len(actions)} actions")

            elif msg_type == "analyze":
                tool = parsed.get("tool", "region_map")
                result_text = self._run_analysis(ctx, tool)
                conversation.append(f"[Turn {turn}] Analyzed '{tool}':\n{result_text}")
                print(f"    [planner] analyzed: {tool}")

            elif msg_type == "commit":
                plan = parsed.get("plan", [])
                goal = parsed.get("goal", "")
                valid_plan = []
                for step in plan[:max_plan]:
                    action = step.get("action")
                    if action is not None and action in ctx.available_actions:
                        valid_plan.append({
                            "action": int(action),
                            "data": step.get("data", {}),
                            "expected": step.get("expected", ""),
                        })

                # Reject short plans — force the LLM to think harder (unless last turn)
                if len(valid_plan) < min_plan and turn < max_turns:
                    print(f"    [planner] REJECTED plan ({len(valid_plan)} steps < min {min_plan}), asking for more")
                    conversation.append(
                        f"[Turn {turn}] REJECTED: Your plan has only {len(valid_plan)} action(s). "
                        f"The minimum is {min_plan}. Think further ahead — plan a sequence of "
                        f"at least {min_plan} actions to reach your goal. Try again."
                    )
                    continue

                # Last turn: accept and pad if needed
                if len(valid_plan) < min_plan:
                    valid_plan = self._pad_plan(valid_plan, ctx, min_plan)
                print(f"    [planner] committed plan: {len(valid_plan)} steps, goal='{goal[:60]}'")
                return {"goal": goal, "plan": valid_plan}

        print(f"    [planner] max turns reached, using exploratory plan")
        return self._exploratory_plan(ctx)

    def _build_prompt(self, ctx: GameContext, turn: int, max_turns: int,
                      conversation: list[str]) -> str:
        action_desc = ", ".join(
            f"{a}={ACTION_NAMES.get(a, f'ACTION{a}')}" for a in ctx.available_actions
        )

        memory_block = ""
        if ctx.cfg["context"]["memory_injection"] and ctx.hard_memory:
            mem_text = relevant_memory_section(
                ctx.hard_memory, ctx.game_id,
                ctx.cfg["context"]["memory_injection_max_chars"],
            )
            if mem_text:
                memory_block = f"## MEMORY\n{mem_text}"

        history_block = ""
        n = ctx.cfg["context"]["history_length"]
        reasoning_trace = ctx.cfg["context"].get("reasoning_trace", False)
        if ctx.history and n >= 0:  # 0 = show all, positive = last N
            recent = ctx.history[-n:] if n > 0 else ctx.history
            lines = []
            for h in recent:
                if h.get("is_summary"):
                    lines.append(f"  [Summary]: {h.get('summary', '')}")
                    continue
                aname = ACTION_NAMES.get(h["action"], f"ACTION{h['action']}")
                obs = (h.get("observation", "") or "")[:500]
                line = f"  Step {h['step']:3d}: {aname} -> levels={h.get('levels','?')} | {obs}"
                if reasoning_trace and h.get("reasoning"):
                    line += f"\n    Reasoning: {h['reasoning'][:500]}"
                lines.append(line)
            non_summary = [h for h in recent if not h.get("is_summary")]
            label = f"all {len(non_summary)}" if n == 0 else f"last {len(non_summary)}"
            history_block = f"## HISTORY ({label})\n" + "\n".join(lines)

        change_map_block = ""
        if ctx.prev_grid:
            cmap = compute_change_map(ctx.prev_grid, ctx.grid)
            if cmap:
                change_map_block = cmap.strip()

        grid_text = "\n".join(f"Row {i}: {compress_row(r)}" for i, r in enumerate(ctx.grid))
        grid_block = f"## GRID (RLE)\n{grid_text}"

        rules_doc = ctx.rules_doc or "(No rules discovered yet — explore to learn!)"

        context = PLANNER_CONTEXT_TEMPLATE.format(
            game_id=ctx.game_id, state=ctx.state_str,
            levels_done=ctx.levels_done, win_levels=ctx.win_levels,
            step_num=ctx.step_num, action_desc=action_desc,
            memory_block=memory_block, history_block=history_block,
            change_map_block=change_map_block, grid_block=grid_block,
            rules_version=ctx.rules_version, rules_doc=rules_doc,
            turn_num=turn, max_turns=max_turns,
        )

        if conversation:
            context += "\n\n## PLANNER CONVERSATION\n" + "\n\n".join(conversation)

        scfg = ctx.cfg.get("scaffolding", {})
        system_prompt = _PLANNER_SYSTEM_PROMPT_TEMPLATE.format(
            min_plan_length=scfg.get("min_plan_length", 3),
            max_plan_length=scfg.get("max_plan_length", 15),
        )
        return system_prompt + "\n\n" + context

    def _run_analysis(self, ctx: GameContext, tool: str) -> str:
        if tool == "region_map":
            return compute_region_map(ctx.grid)
        elif tool == "histogram":
            return compute_color_histogram(ctx.grid)
        elif tool == "change_map" and ctx.prev_grid:
            return compute_change_map(ctx.prev_grid, ctx.grid)
        return "(no data available for this tool)"

    def _exploratory_plan(self, ctx: GameContext) -> dict:
        """Fallback: try each direction + action5."""
        actions = [a for a in ctx.available_actions if a != 0]
        plan = [{"action": a, "data": {}, "expected": "explore"} for a in actions[:6]]
        return {"goal": "explore — discover game mechanics", "plan": plan}

    def _pad_plan(self, plan: list, ctx: GameContext, min_len: int) -> list:
        """Pad a short plan with exploratory actions."""
        actions = [a for a in ctx.available_actions if a != 0]
        idx = 0
        while len(plan) < min_len and actions:
            plan.append({"action": actions[idx % len(actions)], "data": {}, "expected": "explore"})
            idx += 1
        return plan


# ═══════════════════════════════════════════════════════════════════════════
# MONITOR SYSTEM (single-shot, cheap check each step)
# ═══════════════════════════════════════════════════════════════════════════

class MonitorSystem:
    """Single-shot check: does the actual outcome match the expected?"""

    def check(self, ctx: GameContext, expected: str, prev_grid: list,
              new_grid: list) -> dict:
        """Returns {verdict, reason, discovery}."""
        model_key = effective_model(ctx.cfg, "monitor")

        cmap = compute_change_map(prev_grid, new_grid)
        if cmap:
            change_summary = cmap.split("\n")[0] if cmap else "no changes"
        else:
            change_summary = "no cells changed"

        new_levels = ctx.levels_done
        old_levels = ctx.history[-1]["levels"] if ctx.history else 0
        level_change = "LEVEL UP!" if new_levels > old_levels else "same level"

        action_id = ctx.current_plan[ctx.plan_index - 1]["action"] if ctx.plan_index > 0 else 0
        action_name = ACTION_NAMES.get(action_id, f"ACTION{action_id}")

        scfg = ctx.cfg.get("scaffolding", {})
        replan_cooldown = scfg.get("replan_cooldown", 3)
        on_cooldown = ctx.plans_since_replan < replan_cooldown
        cooldown_line = (
            f"Replan cooldown: ON COOLDOWN ({ctx.plans_since_replan}/{replan_cooldown} plans) — you MUST return CONTINUE"
            if on_cooldown else
            f"Replan cooldown: available ({ctx.plans_since_replan}/{replan_cooldown} plans since last replan)"
        )

        prompt = MONITOR_PROMPT_TEMPLATE.format(
            game_id=ctx.game_id, step_num=ctx.step_num,
            levels_done=ctx.levels_done, win_levels=ctx.win_levels,
            action_name=action_name, expected=expected,
            change_summary=change_summary, level_change=level_change,
            state=ctx.state_str,
            replan_cooldown=replan_cooldown,
            cooldown_line=cooldown_line,
        )

        llm_result = call_model_with_metadata(model_key, prompt, ctx.cfg, role="monitor")
        raw = llm_result.text
        elapsed = llm_result.duration_ms / 1000
        ctx.llm_calls += 1
        ctx.turn_llm_calls += 1
        ctx.turn_input_tokens += llm_result.input_tokens
        ctx.turn_output_tokens += llm_result.output_tokens
        ctx.turn_duration_ms += llm_result.duration_ms

        if ctx.session_id:
            _log_llm_call(
                ctx.session_id, "monitor", model_key,
                step_num=ctx.step_num,
                turn_num=ctx.current_turn_num,
                input_json=prompt[:500],
                output_json=(raw or "")[:1000],
                input_tokens=llm_result.input_tokens,
                output_tokens=llm_result.output_tokens,
                thinking_tokens=llm_result.thinking_tokens,
                thinking_json=(llm_result.thinking_text or "")[:5000] if llm_result.thinking_text else None,
                cost=llm_result.cost,
                duration_ms=llm_result.duration_ms,
                error=llm_result.error,
            )

        if not raw:
            return {"verdict": "CONTINUE", "reason": "monitor unavailable", "discovery": None}

        parsed = _parse_json(raw)
        if not parsed:
            return {"verdict": "CONTINUE", "reason": "monitor parse error", "discovery": None}

        verdict = parsed.get("verdict", "CONTINUE").upper()
        if verdict not in ("CONTINUE", "REPLAN"):
            verdict = "CONTINUE"

        # Server-side cooldown enforcement
        if verdict == "REPLAN" and on_cooldown:
            print(f"      [monitor] REPLAN suppressed by cooldown ({ctx.plans_since_replan}/{replan_cooldown})")
            verdict = "CONTINUE"
        elif verdict == "REPLAN":
            ctx.plans_since_replan = 0
            print(f"      [monitor] REPLAN allowed ({elapsed:.1f}s) — {parsed.get('reason', '')[:60]}")
        else:
            print(f"      [monitor] {verdict} ({elapsed:.1f}s) — {parsed.get('reason', '')[:60]}")

        return {
            "verdict": verdict,
            "reason": parsed.get("reason", ""),
            "discovery": parsed.get("discovery"),
        }


# ═══════════════════════════════════════════════════════════════════════════
# WORLD MODEL SYSTEM (REPL loop — builds rules, provides simulate())
# ═══════════════════════════════════════════════════════════════════════════

class WorldModelSystem:
    """REPL loop that builds game understanding from observations."""

    def should_update(self, ctx: GameContext) -> bool:
        """Check if enough new observations have accumulated."""
        scfg = ctx.cfg.get("scaffolding", {})
        update_every = scfg.get("world_model_update_every", 5)
        return len(ctx.observations_buffer) >= update_every

    def update(self, ctx: GameContext) -> str:
        """Run the World Model REPL to update the rules document."""
        scfg = ctx.cfg.get("scaffolding", {})
        max_turns = scfg.get("world_model_max_turns", 5)
        model_key = effective_model(ctx.cfg, "world_model")

        conversation: list[str] = []

        for turn in range(1, max_turns + 1):
            prompt = self._build_prompt(ctx, turn, max_turns, conversation)

            llm_result = call_model_with_metadata(model_key, prompt, ctx.cfg, role="world_model")
            raw = llm_result.text
            elapsed = llm_result.duration_ms / 1000
            ctx.llm_calls += 1
            ctx.turn_llm_calls += 1
            ctx.turn_input_tokens += llm_result.input_tokens
            ctx.turn_output_tokens += llm_result.output_tokens
            ctx.turn_duration_ms += llm_result.duration_ms

            if ctx.session_id:
                _log_llm_call(
                    ctx.session_id, "world_model", model_key,
                    step_num=ctx.step_num,
                    turn_num=ctx.current_turn_num,
                    input_json=prompt[:500],
                    output_json=(raw or "")[:1000],
                    input_tokens=llm_result.input_tokens,
                    output_tokens=llm_result.output_tokens,
                    thinking_tokens=llm_result.thinking_tokens,
                    thinking_json=(llm_result.thinking_text or "")[:5000] if llm_result.thinking_text else None,
                    cost=llm_result.cost,
                    duration_ms=llm_result.duration_ms,
                    error=llm_result.error,
                )

            print(f"    [world_model] turn {turn}/{max_turns} ({elapsed:.1f}s)")

            if not raw:
                break

            parsed = _parse_json(raw)
            if not parsed or "type" not in parsed:
                rules = _recover_truncated_rules(raw)
                if rules:
                    ctx.rules_doc = rules
                    ctx.rules_version += 1
                    ctx.observations_buffer.clear()
                    print(f"    [world_model] rules v{ctx.rules_version} recovered from truncated response")
                    return rules
                print(f"    [world_model] unparseable response (len={len(raw)}), breaking")
                break

            msg_type = parsed["type"]

            if msg_type == "query":
                tool = parsed.get("tool", "change_map")
                result_text = self._handle_query(ctx, parsed)
                if len(result_text) > 2000:
                    result_text = result_text[:2000] + "\n... (truncated)"
                conversation.append(f"[Turn {turn}] Queried '{tool}':\n{result_text}")
                print(f"    [world_model] queried: {tool}")

            elif msg_type == "commit":
                new_rules = parsed.get("rules_document", "")
                confidence = parsed.get("confidence", 0.5)
                if new_rules:
                    ctx.rules_doc = new_rules
                    ctx.rules_version += 1
                    ctx.observations_buffer.clear()
                    print(f"    [world_model] rules v{ctx.rules_version} committed (confidence={confidence})")
                    return new_rules

        print(f"    [world_model] max turns reached, keeping rules v{ctx.rules_version}")
        ctx.observations_buffer.clear()
        return ctx.rules_doc

    def simulate(self, actions: list[dict], ctx: GameContext) -> list[str]:
        """Use rules_doc to predict outcomes (no actual game execution)."""
        if not ctx.rules_doc:
            return ["unknown — no rules discovered yet, try it and observe"] * len(actions)

        model_key = effective_model(ctx.cfg, "world_model")

        action_descs = []
        for act in actions:
            a = act.get("action", 0)
            aname = ACTION_NAMES.get(a, f"ACTION{a}")
            data = act.get("data", {})
            if a == 6 and data:
                action_descs.append(f"{aname}@({data.get('x','?')},{data.get('y','?')})")
            else:
                action_descs.append(aname)

        prompt = f"""You are a World Model predicting game outcomes.

## RULES (v{ctx.rules_version})
{ctx.rules_doc}

## CURRENT STATE
Game: {ctx.game_id} | Step: {ctx.step_num} | Levels: {ctx.levels_done}/{ctx.win_levels}

## ACTIONS TO PREDICT
{chr(10).join(f'{i+1}. {d}' for i, d in enumerate(action_descs))}

For each action, predict what would happen based on your rules.
Respond with EXACTLY this JSON:
{{"predictions": ["<prediction for action 1>", "<prediction for action 2>", ...]}}

If uncertain, say "uncertain — <best guess>". Keep each prediction under 100 chars."""

        llm_result = call_model_with_metadata(model_key, prompt, ctx.cfg, role="world_model")
        raw = llm_result.text
        ctx.llm_calls += 1
        ctx.turn_llm_calls += 1
        ctx.turn_input_tokens += llm_result.input_tokens
        ctx.turn_output_tokens += llm_result.output_tokens
        ctx.turn_duration_ms += llm_result.duration_ms

        if ctx.session_id:
            _log_llm_call(
                ctx.session_id, "simulate", model_key,
                step_num=ctx.step_num,
                turn_num=ctx.current_turn_num,
                input_json=prompt[:500],
                output_json=(raw or "")[:1000],
                input_tokens=llm_result.input_tokens,
                output_tokens=llm_result.output_tokens,
                thinking_tokens=llm_result.thinking_tokens,
                thinking_json=(llm_result.thinking_text or "")[:5000] if llm_result.thinking_text else None,
                cost=llm_result.cost,
                duration_ms=llm_result.duration_ms,
                error=llm_result.error,
            )

        if not raw:
            return ["prediction unavailable"] * len(actions)

        parsed = _parse_json(raw)
        if parsed and "predictions" in parsed:
            preds = parsed["predictions"]
            while len(preds) < len(actions):
                preds.append("no prediction")
            return preds[:len(actions)]

        return ["prediction parse error"] * len(actions)

    def _build_prompt(self, ctx: GameContext, turn: int, max_turns: int,
                      conversation: list[str]) -> str:
        rules_doc = ctx.rules_doc or "(No rules yet — this is your first analysis!)"

        obs_lines = []
        for snap in ctx.observations_buffer:
            aname = ACTION_NAMES.get(snap.action, f"ACTION{snap.action}")
            obs_lines.append(f"Step {snap.step}: {aname} -> levels={snap.levels}, state={snap.state}")
            if snap.change_map:
                cmap_lines = snap.change_map.strip().split("\n")[:4]
                obs_lines.append("  " + "\n  ".join(cmap_lines))

        obs_text = "\n".join(obs_lines) if obs_lines else "(no new observations)"
        obs_start = ctx.observations_buffer[0].step if ctx.observations_buffer else ctx.step_num
        obs_end = ctx.observations_buffer[-1].step if ctx.observations_buffer else ctx.step_num

        context = WORLD_MODEL_CONTEXT_TEMPLATE.format(
            game_id=ctx.game_id, step_num=ctx.step_num,
            levels_done=ctx.levels_done, win_levels=ctx.win_levels,
            rules_version=ctx.rules_version, rules_doc=rules_doc,
            observations_text=obs_text, obs_start=obs_start, obs_end=obs_end,
            turn_num=turn, max_turns=max_turns,
        )

        if conversation:
            context += "\n\n## WORLD MODEL CONVERSATION\n" + "\n\n".join(conversation)

        if turn == max_turns:
            context += "\n\n!! THIS IS YOUR LAST TURN — you MUST commit your rules document now. !!"

        return WORLD_MODEL_SYSTEM_PROMPT + "\n\n" + context

    def _handle_query(self, ctx: GameContext, parsed: dict) -> str:
        """Handle a query for historical step data."""
        tool = parsed.get("tool", "change_map")
        step = parsed.get("step")
        step_range = parsed.get("step_range")

        if step is not None:
            snaps = [s for s in ctx.snapshots if s.step == step]
            if not snaps:
                return f"(no data for step {step})"
            snap = snaps[0]
            if tool == "change_map":
                return snap.change_map or "(no changes)"
            elif tool == "histogram":
                return compute_color_histogram(snap.grid)
            elif tool == "grid":
                return _compact_grid(snap.grid)

        elif step_range:
            start, end = step_range[0], step_range[-1]
            snaps = [s for s in ctx.snapshots if start <= s.step <= end]
            if not snaps:
                return f"(no data for steps {start}-{end})"
            lines = []
            for snap in snaps:
                aname = ACTION_NAMES.get(snap.action, f"ACTION{snap.action}")
                lines.append(f"Step {snap.step} ({aname}):")
                if tool == "change_map":
                    lines.append(snap.change_map or "  (no changes)")
                elif tool == "histogram":
                    lines.append(compute_color_histogram(snap.grid))
                elif tool == "grid":
                    lines.append(_compact_grid(snap.grid))
            return "\n".join(lines)

        return "(invalid query — specify step or step_range)"
