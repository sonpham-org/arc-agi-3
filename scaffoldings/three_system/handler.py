"""Three-System scaffolding web UI handler."""

import logging
import re
import time

from scaffoldings.three_system.prompts import (
    PLANNER_SYSTEM_PROMPT_BODY,
    PLANNER_SYSTEM_PROMPT_BODY_NO_WM,
    PLANNER_CONTEXT_TEMPLATE,
    PLANNER_CONTEXT_TEMPLATE_NO_WM,
    WORLD_MODEL_SYSTEM_PROMPT,
    WORLD_MODEL_CONTEXT_TEMPLATE,
    MONITOR_PROMPT_TEMPLATE,
)

logger = logging.getLogger(__name__)

# Per-session state for the web UI three-system scaffolding
_three_system_state: dict[str, dict] = {}


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


def ts_get_state(session_id: str) -> dict:
    """Get or create per-session three_system state."""
    if session_id not in _three_system_state:
        _three_system_state[session_id] = {
            "rules_doc": "",
            "rules_version": 0,
            "observations": [],
            "snapshots": [],
            "turn_count": 0,
            "plans_since_replan": 99,  # start high so first replan is allowed
        }
    return _three_system_state[session_id]


def ts_run_wm_update(ss: dict, context: dict, settings: dict, session_id: str,
                     *, route_model_call, log_llm_call, extract_json,
                     action_names, compress_row, compute_change_map,
                     compute_color_histogram, arc_agi3_description) -> dict:
    """Run the World Model REPL to update rules. Returns wm log info.

    Dependencies are injected to avoid circular imports with server.py.
    """
    wm_model = settings.get("wm_model") or settings.get("model") or "gemini-2.5-flash"
    wm_thinking = settings.get("wm_thinking_level", "low")
    wm_max_tokens = min(int(settings.get("wm_max_tokens", 16384)), 65536)
    max_turns = int(settings.get("wm_max_turns", 5))

    rules_doc = ss["rules_doc"] or "(No rules yet — this is your first analysis!)"
    obs = ss["observations"]
    obs_lines = []
    for o in obs:
        aname = action_names.get(o.get("action", 0), "?")
        obs_lines.append(f"Step {o['step']}: {aname} -> levels={o.get('levels', '?')}, state={o.get('state', '?')}")
        cm = o.get("change_map_text", "")
        if isinstance(cm, dict):
            cm = cm.get("change_map_text", "") or ""
        if cm and isinstance(cm, str):
            cmap_lines = cm.strip().split("\n")[:4]
            obs_lines.append("  " + "\n  ".join(cmap_lines))
    obs_text = "\n".join(obs_lines) if obs_lines else "(no new observations)"
    obs_start = obs[0]["step"] if obs else 0
    obs_end = obs[-1]["step"] if obs else 0

    conversation = []
    wm_log = []

    for turn in range(1, max_turns + 1):
        ctx_text = WORLD_MODEL_CONTEXT_TEMPLATE.format(
            game_id=context.get("game_id", "?"),
            step_num=context.get("step_num", 0),
            levels_done=context.get("levels_completed", 0),
            win_levels=context.get("win_levels", 0),
            rules_version=ss["rules_version"],
            rules_doc=rules_doc,
            observations_text=obs_text,
            obs_start=obs_start, obs_end=obs_end,
            turn_num=turn, max_turns=max_turns,
        )
        if conversation:
            ctx_text += "\n\n## WORLD MODEL CONVERSATION\n" + "\n\n".join(conversation)
        if turn == max_turns:
            ctx_text += "\n\n!! THIS IS YOUR LAST TURN — you MUST commit your rules document now. !!"

        prompt = WORLD_MODEL_SYSTEM_PROMPT + "\n\n" + ctx_text

        t0 = time.time()
        try:
            response = route_model_call(
                wm_model, prompt, None,
                thinking_level=wm_thinking,
                max_tokens=wm_max_tokens,
            )
            dur_ms = int((time.time() - t0) * 1000)
            raw = response.get("text", "") if isinstance(response, dict) else str(response)
        except Exception as e:
            logger.error(f"[ts_wm] turn {turn} failed: {e}")
            wm_log.append({"turn": turn, "type": "error", "error": str(e), "duration_ms": 0})
            break

        log_llm_call(
            session_id, "ts_world_model", wm_model,
            prompt_preview=prompt[:500], prompt_length=len(prompt),
            response_preview=raw[:1000],
            response_json={"raw": raw},
            duration_ms=dur_ms,
            thinking_level=wm_thinking,
        )

        parsed = extract_json(raw)
        if not parsed or "type" not in parsed:
            recovered = _recover_truncated_rules(raw)
            if recovered:
                ss["rules_doc"] = recovered
                ss["rules_version"] += 1
                ss["observations"] = []
                wm_log.append({"turn": turn, "type": "commit", "confidence": 0.5, "duration_ms": dur_ms, "recovered": True})
                break
            wm_log.append({"turn": turn, "type": "error", "error": "unparseable", "duration_ms": dur_ms})
            break

        msg_type = parsed["type"]

        if msg_type == "query":
            tool = parsed.get("tool", "change_map")
            step = parsed.get("step")
            step_range = parsed.get("step_range")
            result_text = ts_handle_wm_query(ss, tool, step, step_range, context,
                                             compress_row=compress_row,
                                             compute_color_histogram=compute_color_histogram,
                                             action_names=action_names)
            if len(result_text) > 2000:
                result_text = result_text[:2000] + "\n... (truncated)"
            conversation.append(f"[Turn {turn}] Queried '{tool}':\n{result_text}")
            wm_log.append({"turn": turn, "type": "query", "tool": tool, "duration_ms": dur_ms})

        elif msg_type == "commit":
            new_rules = parsed.get("rules_document", "")
            confidence = parsed.get("confidence", 0.5)
            if new_rules:
                ss["rules_doc"] = new_rules
                ss["rules_version"] += 1
                ss["observations"] = []
                wm_log.append({"turn": turn, "type": "commit", "confidence": confidence, "duration_ms": dur_ms})
                break
            wm_log.append({"turn": turn, "type": "commit_empty", "duration_ms": dur_ms})

    return {
        "ran_update": True,
        "wm_log": wm_log,
        "rules_version": ss["rules_version"],
        "rules_preview": (ss["rules_doc"] or "")[:200],
    }


def ts_handle_wm_query(ss: dict, tool: str, step, step_range, context: dict,
                       *, compress_row, compute_color_histogram, action_names) -> str:
    """Handle a WM query for historical step data."""
    snapshots = ss["snapshots"]

    if step is not None:
        snaps = [s for s in snapshots if s["step"] == step]
        if not snaps:
            return f"(no data for step {step})"
        snap = snaps[0]
        if tool == "change_map":
            return snap.get("change_map_text", "(no changes)")
        elif tool == "histogram":
            return compute_color_histogram(snap.get("grid", []))
        elif tool == "grid":
            return "\n".join(f"Row {i}: {compress_row(r)}" for i, r in enumerate(snap.get("grid", [])))
    elif step_range:
        start, end = step_range[0], step_range[-1]
        snaps = [s for s in snapshots if start <= s["step"] <= end]
        if not snaps:
            return f"(no data for steps {start}-{end})"
        lines = []
        for snap in snaps:
            aname = action_names.get(snap.get("action", 0), "?")
            lines.append(f"Step {snap['step']} ({aname}):")
            if tool == "change_map":
                lines.append(snap.get("change_map_text", "  (no changes)"))
            elif tool == "histogram":
                lines.append(compute_color_histogram(snap.get("grid", [])))
            elif tool == "grid":
                lines.append("\n".join(f"  Row {i}: {compress_row(r)}" for i, r in enumerate(snap.get("grid", []))))
        return "\n".join(lines)
    return "(invalid query — specify step or step_range)"


def ts_simulate_actions(actions: list, ss: dict, context: dict, settings: dict, session_id: str,
                        *, route_model_call, log_llm_call, extract_json,
                        action_names) -> list[str]:
    """Use the WM rules to predict outcomes of proposed actions."""
    rules_doc = ss["rules_doc"]
    if not rules_doc:
        return ["unknown — no rules discovered yet, try it and observe"] * len(actions)

    wm_model = settings.get("wm_model") or settings.get("model") or "gemini-2.5-flash"
    wm_thinking = settings.get("wm_thinking_level", "low")
    wm_max_tokens = min(int(settings.get("wm_max_tokens", 8192)), 65536)

    action_descs = []
    for act in actions:
        a = act.get("action", 0)
        aname = action_names.get(a, f"ACTION{a}")
        data = act.get("data", {})
        if a == 6 and data:
            action_descs.append(f"{aname}@({data.get('x', '?')},{data.get('y', '?')})")
        else:
            action_descs.append(aname)

    prompt = f"""You are a World Model predicting game outcomes.

## RULES (v{ss['rules_version']})
{rules_doc}

## CURRENT STATE
Game: {context.get('game_id', '?')} | Step: {context.get('step_num', 0)} | Levels: {context.get('levels_completed', 0)}/{context.get('win_levels', 0)}

## ACTIONS TO PREDICT
{chr(10).join(f'{i+1}. {d}' for i, d in enumerate(action_descs))}

For each action, predict what would happen based on your rules.
Respond with EXACTLY this JSON:
{{"predictions": ["<prediction for action 1>", "<prediction for action 2>", ...]}}

If uncertain, say "uncertain — <best guess>". Keep each prediction under 100 chars."""

    t0 = time.time()
    try:
        response = route_model_call(
            wm_model, prompt, None,
            thinking_level=wm_thinking,
            max_tokens=wm_max_tokens,
        )
        dur_ms = int((time.time() - t0) * 1000)
        raw = response.get("text", "") if isinstance(response, dict) else str(response)
    except Exception:
        return ["prediction unavailable"] * len(actions)

    log_llm_call(
        session_id, "ts_simulate", wm_model,
        prompt_preview=prompt[:500], prompt_length=len(prompt),
        response_preview=raw[:500],
        response_json={"raw": raw},
        duration_ms=dur_ms,
        thinking_level=wm_thinking,
    )

    parsed = extract_json(raw)
    if parsed and "predictions" in parsed:
        preds = parsed["predictions"]
        while len(preds) < len(actions):
            preds.append("no prediction")
        return preds[:len(actions)]
    return ["prediction parse error"] * len(actions)


def handle_three_system_scaffolding(payload: dict, settings: dict, *,
                                    route_model_call, log_llm_call, extract_json,
                                    action_names, compress_row, compute_change_map,
                                    compute_color_histogram, compute_region_map,
                                    arc_agi3_description) -> dict:
    """Run the Planner REPL (with WM update if needed) and return a plan.

    Dependencies are injected to avoid circular imports with server.py.
    """
    t0_total = time.time()

    session_id = payload.get("session_id", "anonymous")
    ss = ts_get_state(session_id)
    ss["turn_count"] += 1

    # Settings
    planner_model = settings.get("planner_model") or settings.get("model") or "gemini-2.5-flash"
    planner_thinking = settings.get("planner_thinking_level") or settings.get("thinking_level", "low")
    planner_max_tokens = min(int(settings.get("planner_max_tokens") or settings.get("max_tokens", 16384)), 65536)
    max_turns = int(settings.get("planner_max_turns", 10))
    max_plan = int(settings.get("max_plan_length", 15))
    min_plan = int(settings.get("min_plan_length", 3))
    wm_update_every = int(settings.get("wm_update_every", 5))
    wm_model = settings.get("wm_model")  # empty/None = WM disabled (two_system mode)
    wm_enabled = bool(wm_model)
    logger.info(f"[ts_planner] min_plan={min_plan}, max_plan={max_plan}, max_turns={max_turns}, wm_enabled={wm_enabled}")
    scaffolding_type = settings.get("scaffolding", "three_system")

    # DEBUG: dump all settings received from frontend
    print(f"\n{'='*60}")
    print(f"[DEBUG ts_planner] SETTINGS RECEIVED:")
    for k, v in sorted(settings.items()):
        print(f"  {k} = {v!r}")
    print(f"[DEBUG ts_planner] RESOLVED: model={planner_model}, thinking={planner_thinking}, max_tokens={planner_max_tokens}")
    print(f"[DEBUG ts_planner] PLAN: min={min_plan}, max={max_plan}, max_turns={max_turns}, wm_enabled={wm_enabled}")
    print(f"{'='*60}")

    # Injected deps for sub-functions
    deps = dict(
        route_model_call=route_model_call, log_llm_call=log_llm_call,
        extract_json=extract_json, action_names=action_names,
        compress_row=compress_row, compute_change_map=compute_change_map,
        compute_color_histogram=compute_color_histogram,
        arc_agi3_description=arc_agi3_description,
    )

    context = {
        "grid": payload.get("grid", []),
        "available_actions": payload.get("available_actions", []),
        "history": payload.get("history", []),
        "change_map": payload.get("change_map", {}),
        "levels_completed": payload.get("levels_completed", 0),
        "win_levels": payload.get("win_levels", 0),
        "game_id": payload.get("game_id", "unknown"),
        "state": payload.get("state", ""),
        "step_num": payload.get("step_num", 0),
        "compact_context": payload.get("compact_context", ""),
    }

    # ── 1. World Model update if enough observations (skip if WM disabled) ──
    wm_info = {"ran_update": False, "wm_log": [], "rules_version": ss["rules_version"], "rules_preview": (ss["rules_doc"] or "")[:200]}
    if wm_enabled and len(ss["observations"]) >= wm_update_every:
        wm_info = ts_run_wm_update(ss, context, settings, session_id, **deps)

    # ── 2. Planner REPL ──
    # Build the full planner system prompt with ARC_AGI3_DESCRIPTION
    plan_len_vars = {"min_plan_length": min_plan, "max_plan_length": max_plan}
    if wm_enabled:
        planner_system_prompt = arc_agi3_description + "\n\n" + PLANNER_SYSTEM_PROMPT_BODY.format(**plan_len_vars)
    else:
        planner_system_prompt = arc_agi3_description + "\n\n" + PLANNER_SYSTEM_PROMPT_BODY_NO_WM.format(**plan_len_vars)

    action_desc = ", ".join(
        f"{a}={action_names.get(a, f'ACTION{a}')}" for a in context["available_actions"]
    )

    # History block — show all history (client controls length)
    history_block = ""
    hist = context["history"]
    if hist:
        lines = []
        for h in hist:
            aname = action_names.get(h.get("action", 0), "?")
            obs = (h.get("observation", "") or "")[:500]
            line = f"  Step {h.get('step', '?'):3d}: {aname} -> levels={h.get('levels', '?')} | {obs}"
            if h.get("reasoning"):
                line += f"\n    Reasoning: {h['reasoning'][:500]}"
            lines.append(line)
        history_block = f"## HISTORY (all {len(hist)})\n" + "\n".join(lines)

    # Change map block
    change_map_block = ""
    cm = context.get("change_map", {})
    if isinstance(cm, dict) and cm.get("change_map_text"):
        change_map_block = cm["change_map_text"]
    elif isinstance(cm, str) and cm:
        change_map_block = cm

    # Grid block
    grid = context["grid"]
    grid_text = "\n".join(f"Row {i}: {compress_row(r)}" for i, r in enumerate(grid)) if grid else "(no grid)"
    grid_block = f"## GRID (RLE)\n{grid_text}"

    rules_doc = ss["rules_doc"] or "(No rules discovered yet — explore to learn!)"

    conversation = []
    planner_log = []

    for turn in range(1, max_turns + 1):
        if wm_enabled:
            ctx_text = PLANNER_CONTEXT_TEMPLATE.format(
                game_id=context["game_id"],
                state=context["state"],
                levels_done=context.get("levels_completed", 0),
                win_levels=context.get("win_levels", 0),
                step_num=context.get("step_num", 0),
                action_desc=action_desc,
                memory_block="",
                history_block=history_block,
                change_map_block=change_map_block,
                grid_block=grid_block,
                rules_version=ss["rules_version"],
                rules_doc=rules_doc,
                turn_num=turn, max_turns=max_turns,
            )
        else:
            ctx_text = PLANNER_CONTEXT_TEMPLATE_NO_WM.format(
                game_id=context["game_id"],
                state=context["state"],
                levels_done=context.get("levels_completed", 0),
                win_levels=context.get("win_levels", 0),
                step_num=context.get("step_num", 0),
                action_desc=action_desc,
                memory_block="",
                history_block=history_block,
                change_map_block=change_map_block,
                grid_block=grid_block,
                turn_num=turn, max_turns=max_turns,
            )
        if conversation:
            ctx_text += "\n\n## PLANNER CONVERSATION\n" + "\n\n".join(conversation)

        prompt = planner_system_prompt + "\n\n" + ctx_text

        t0 = time.time()
        try:
            response = route_model_call(
                planner_model, prompt, None,
                thinking_level=planner_thinking,
                max_tokens=planner_max_tokens,
            )
            dur_ms = int((time.time() - t0) * 1000)
            raw = response.get("text", "") if isinstance(response, dict) else str(response)
        except Exception as e:
            logger.error(f"[ts_planner] turn {turn} failed: {e}")
            planner_log.append({"turn": turn, "type": "error", "error": str(e), "duration_ms": 0})
            break

        log_llm_call(
            session_id, "ts_planner", planner_model,
            prompt_preview=prompt[:500], prompt_length=len(prompt),
            response_preview=raw[:1000],
            response_json={"raw": raw},
            duration_ms=dur_ms,
            thinking_level=planner_thinking,
        )

        parsed = extract_json(raw)
        print(f"\n[DEBUG ts_planner] Turn {turn}: raw length={len(raw)}, raw[:500]={raw[:500]!r}")
        print(f"[DEBUG ts_planner] Turn {turn}: parsed={parsed}")
        if not parsed or "type" not in parsed:
            logger.warning(f"[ts_planner] Turn {turn}: unparseable response (parsed={parsed is not None}, keys={list(parsed.keys()) if parsed else []}). Raw[:300]: {(raw or '')[:300]}")
            planner_log.append({"turn": turn, "type": "error", "error": "unparseable", "duration_ms": dur_ms, "raw": raw})
            if turn == max_turns:
                break
            conversation.append(f"[Turn {turn}] (unparseable response, trying again)")
            continue

        msg_type = parsed["type"]

        if msg_type == "simulate":
            if not wm_enabled:
                conversation.append(f"[Turn {turn}] No World Model available — cannot simulate. Use 'analyze' or 'commit' instead.")
                planner_log.append({"turn": turn, "type": "simulate_skipped", "duration_ms": dur_ms, "raw": raw, "parsed": parsed})
                continue
            actions = parsed.get("actions", [])
            question = parsed.get("question", "")
            predictions = ts_simulate_actions(actions, ss, context, settings, session_id,
                                              route_model_call=route_model_call,
                                              log_llm_call=log_llm_call,
                                              extract_json=extract_json,
                                              action_names=action_names)
            result_text = f"Simulation of {len(actions)} action(s):\n"
            for i, (act, pred) in enumerate(zip(actions, predictions)):
                aname = action_names.get(act.get("action", 0), "?")
                result_text += f"  {i+1}. {aname}: {pred}\n"
            conversation.append(f"[Turn {turn}] You simulated: {question}\nResult: {result_text}")
            planner_log.append({
                "turn": turn, "type": "simulate",
                "actions": [act.get("action", 0) for act in actions],
                "predictions": predictions[:5],
                "duration_ms": dur_ms,
                "raw": raw, "parsed": parsed,
            })

        elif msg_type == "analyze":
            tool = parsed.get("tool", "region_map")
            if tool == "region_map":
                result_text = compute_region_map(grid)
            elif tool == "histogram":
                result_text = compute_color_histogram(grid)
            elif tool == "change_map" and change_map_block:
                result_text = change_map_block
            else:
                result_text = "(no data available)"
            conversation.append(f"[Turn {turn}] Analyzed '{tool}':\n{result_text}")
            planner_log.append({"turn": turn, "type": "analyze", "tool": tool, "duration_ms": dur_ms, "raw": raw, "parsed": parsed})

        elif msg_type == "commit":
            plan = parsed.get("plan", [])
            goal = parsed.get("goal", "")
            observation = parsed.get("observation", "")
            reasoning = parsed.get("reasoning", "")

            print(f"\n[DEBUG ts_planner] COMMIT received:")
            print(f"  goal={goal!r}")
            print(f"  observation={observation[:200]!r}")
            print(f"  reasoning={reasoning[:200]!r}")
            print(f"  plan length={len(plan)}")
            for i, step in enumerate(plan[:20]):
                print(f"  plan[{i}]: {step}")
            print(f"  available_actions={context['available_actions']}")

            valid_plan = []
            avail = set(context["available_actions"])
            for step in plan[:max_plan]:
                action = step.get("action")
                if action is not None and action in avail:
                    valid_plan.append({
                        "action": int(action),
                        "data": step.get("data", {}),
                        "expected": step.get("expected", ""),
                    })
                else:
                    print(f"  [DEBUG] FILTERED OUT action={action} (avail={avail})")

            print(f"  [DEBUG] valid_plan={len(valid_plan)} actions: {[s['action'] for s in valid_plan]}")
            logger.info(f"[ts_planner] LLM committed {len(plan)} raw actions, {len(valid_plan)} valid (min_plan={min_plan})")

            # Reject short plans — force the LLM to think harder (unless last turn)
            if len(valid_plan) < min_plan and turn < max_turns:
                logger.info(f"[ts_planner] REJECTED plan ({len(valid_plan)} < {min_plan}), asking for more")
                conversation.append(
                    f"[Turn {turn}] REJECTED: Your plan has only {len(valid_plan)} action(s). "
                    f"The minimum is {min_plan}. Think further ahead — plan a sequence of "
                    f"at least {min_plan} actions to reach your goal. Try again."
                )
                planner_log.append({
                    "turn": turn, "type": "rejected",
                    "plan_length": len(valid_plan),
                    "min_required": min_plan,
                    "duration_ms": dur_ms,
                    "raw": raw, "parsed": parsed,
                })
                continue

            # Last turn: accept and pad if needed
            if len(valid_plan) < min_plan:
                pad_count = min_plan - len(valid_plan)
                exploratory = [a for a in context["available_actions"] if a != 0]
                idx = 0
                while len(valid_plan) < min_plan and exploratory:
                    valid_plan.append({"action": exploratory[idx % len(exploratory)], "data": {}, "expected": "explore"})
                    idx += 1
                logger.info(f"[ts_planner] last turn, padded {pad_count} exploratory actions -> {len(valid_plan)} total")

            planner_log.append({
                "turn": turn, "type": "commit",
                "plan_length": len(valid_plan),
                "raw_plan_length": len(plan),
                "duration_ms": dur_ms,
                "raw": raw, "parsed": parsed,
            })

            ss["plans_since_replan"] = ss.get("plans_since_replan", 0) + 1
            total_dur = int((time.time() - t0_total) * 1000)
            logger.info(f"[ts_planner] RETURNING plan with {len(valid_plan)} steps: {[s['action'] for s in valid_plan]}")
            print(f"\n[DEBUG ts_planner] RETURNING: {len(valid_plan)} steps, planner_log has {len(planner_log)} entries")
            print(f"  plan actions: {[s['action'] for s in valid_plan]}")
            print(f"  observation: {observation[:100]!r}")
            print(f"  reasoning: {reasoning[:100]!r}")
            print(f"  thinking: None (three_system always returns None)")
            return {
                "raw": raw,
                "thinking": None,
                "parsed": {
                    "observation": observation,
                    "reasoning": reasoning,
                    "action": valid_plan[0]["action"] if valid_plan else 0,
                    "data": valid_plan[0].get("data", {}) if valid_plan else {},
                    "plan": valid_plan,
                },
                "model": planner_model,
                "scaffolding": scaffolding_type,
                "three_system": {
                    "turn": ss["turn_count"],
                    "goal": goal,
                    "planner_log": planner_log,
                    "world_model": wm_info,
                },
                "call_duration_ms": total_dur,
            }

    # ── Fallback: max turns reached or errors — return exploratory plan ──
    logger.info(f"[ts_planner] FALLBACK — planner did not commit, using exploratory plan (min_plan={min_plan})")
    exploratory = [a for a in context["available_actions"] if a != 0]
    fallback_plan = []
    idx = 0
    target = max(min_plan, 6)
    while len(fallback_plan) < target and exploratory:
        fallback_plan.append({"action": exploratory[idx % len(exploratory)], "data": {}, "expected": "explore"})
        idx += 1
    total_dur = int((time.time() - t0_total) * 1000)

    return {
        "raw": "",
        "thinking": None,
        "parsed": {
            "observation": "Planner could not commit a plan",
            "reasoning": "Max REPL turns reached or errors occurred, falling back to exploration",
            "action": fallback_plan[0]["action"] if fallback_plan else 0,
            "data": {},
            "plan": fallback_plan,
        },
        "model": planner_model,
        "scaffolding": scaffolding_type,
        "_fallbackAction": True,
        "three_system": {
            "turn": ss["turn_count"],
            "goal": "explore — planner fallback",
            "planner_log": planner_log,
            "world_model": wm_info,
        },
        "call_duration_ms": total_dur,
    }
