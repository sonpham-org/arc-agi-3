"""RLM scaffolding web UI handler."""

import json
import logging
import time
import threading

from scaffoldings.rlm.prompts import (
    build_rlm_system_prompt,
    RLM_USER_PROMPT_FIRST,
    RLM_USER_PROMPT_CONTINUE,
    RLM_REPL_CODE_PATTERN,
)
from scaffoldings.rlm.repl import create_rlm_repl, rlm_execute_code, rlm_find_final

logger = logging.getLogger(__name__)

# ── Persistent REPL state across turns (keyed by session_id) ──
_repl_cache: dict[str, dict] = {}
_repl_cache_lock = threading.Lock()
_MAX_CACHED_REPLS = 50  # evict oldest when exceeded


def _get_or_create_repl(session_id: str, context: dict, model_key: str,
                         **kwargs) -> dict:
    """Get persistent REPL for session, or create a new one.

    The REPL namespace persists across turns — variables the LLM creates
    in one turn are available in the next. The `context` dict is updated
    each turn with fresh game state.
    """
    with _repl_cache_lock:
        repl = _repl_cache.get(session_id)
        if repl is not None:
            # Update context with fresh game state
            repl['namespace']['context'] = context
            # Reset per-turn state
            repl['final_answer'] = None
            repl['sub_call_count'] = 0
            repl['parent_call_id'] = None
            return repl

    # Create new REPL
    repl = create_rlm_repl(session_id, context, model_key, **kwargs)

    with _repl_cache_lock:
        # Evict oldest if cache is full
        if len(_repl_cache) >= _MAX_CACHED_REPLS:
            oldest_key = next(iter(_repl_cache))
            del _repl_cache[oldest_key]
        _repl_cache[session_id] = repl

    return repl


def clear_repl_cache(session_id: str | None = None) -> None:
    """Clear REPL cache for a session (or all sessions)."""
    with _repl_cache_lock:
        if session_id:
            _repl_cache.pop(session_id, None)
        else:
            _repl_cache.clear()


def handle_rlm_scaffolding(payload: dict, settings: dict, *,
                           route_model_call, log_llm_call, extract_json,
                           safe_import) -> dict:
    """Run the full RLM iteration loop and return a parsed response dict.

    Dependencies are injected to avoid circular imports with server.py:
      - route_model_call: server._route_model_call
      - log_llm_call: db._log_llm_call
      - extract_json: server._extract_json
      - safe_import: server._safe_import

    Returns the same format as _parse_llm_response for compatibility.
    """
    model_key = settings.get("model") or "gemini-2.5-flash"
    thinking_level = settings.get("thinking_level", "low")
    max_tokens = min(int(settings.get("max_tokens", 16384)), 65536)
    sub_model_key = settings.get("sub_model") or None
    sub_thinking_level = settings.get("sub_thinking_level", "low")
    sub_max_tokens = min(int(settings.get("sub_max_tokens", 8192)), 65536)
    max_depth = int(settings.get("max_depth", 1))
    max_iterations = int(settings.get("max_iterations", 10))
    output_truncation = int(settings.get("output_truncation", 5000))
    planning_mode = settings.get("planning_mode", "off")
    planning_horizon = int(planning_mode) if planning_mode not in ("off", "unlimited") else (999 if planning_mode == "unlimited" else 1)
    session_id = payload.get("session_id", "anonymous")

    # Build the context dict for the REPL
    context = {
        "grid": payload.get("grid", []),
        "available_actions": payload.get("available_actions", []),
        "history": payload.get("history", []),
        "change_map": payload.get("change_map", {}),
        "levels_completed": payload.get("levels_completed", 0),
        "win_levels": payload.get("win_levels", 0),
        "game_id": payload.get("game_id", "unknown"),
        "state": payload.get("state", ""),
        "compact_context": payload.get("compact_context", ""),
    }

    # Get or create persistent REPL (variables survive across turns)
    repl = _get_or_create_repl(
        session_id, context, model_key,
        thinking_level=thinking_level, max_tokens=max_tokens,
        sub_model_key=sub_model_key,
        sub_thinking_level=sub_thinking_level,
        sub_max_tokens=sub_max_tokens,
        max_depth=max_depth,
        route_model_call=route_model_call,
        log_llm_call=log_llm_call,
        safe_import=safe_import,
    )

    # Build conversation history for the iteration loop
    messages = [
        {"role": "system", "content": build_rlm_system_prompt(planning_horizon)},
        {"role": "user", "content": RLM_USER_PROMPT_FIRST.replace("{plan_instruction}", f"Output a plan of 1-{planning_horizon} actions.")},
    ]

    iterations_log = []  # track each iteration for the client
    final_answer = None

    for iteration in range(max_iterations):
        # Build prompt from message history
        prompt = "\n\n".join(
            f"{'[SYSTEM]' if m['role'] == 'system' else '[USER]' if m['role'] == 'user' else '[ASSISTANT]'}: {m['content']}"
            for m in messages
        )

        # Call the main model
        try:
            t0 = time.time()
            response = route_model_call(
                model_key, prompt, None,
                thinking_level=thinking_level,
                max_tokens=max_tokens,
            )
            rlm_dur = int((time.time() - t0) * 1000)
            if isinstance(response, dict):
                response_text = response.get("text", "")
            else:
                response_text = str(response)
            # Log main RLM iteration call and set parent_call_id for sub-calls
            rlm_call_id = log_llm_call(
                session_id, "rlm_main", model_key,
                prompt_preview=prompt[:500], prompt_length=len(prompt),
                response_preview=response_text[:1000],
                duration_ms=rlm_dur,
                thinking_level=thinking_level,
            )
            repl['parent_call_id'] = rlm_call_id
        except Exception as e:
            logger.error(f"RLM iteration {iteration} LLM call failed: {e}")
            log_llm_call(
                session_id, "rlm_main", model_key,
                prompt_preview=prompt[:500], prompt_length=len(prompt),
                error=str(e),
            )
            iterations_log.append({
                "iteration": iteration,
                "error": str(e),
            })
            break

        # Extract and execute code blocks
        code_blocks = RLM_REPL_CODE_PATTERN.findall(response_text)
        repl_outputs = []
        for code in code_blocks:
            output = rlm_execute_code(repl, code, max_output=output_truncation)
            repl_outputs.append(output)

        # Log this iteration
        iter_log = {
            "iteration": iteration,
            "response": response_text[:2000],  # truncate for client
            "code_blocks": len(code_blocks),
            "repl_outputs": [o[:1000] for o in repl_outputs],  # truncate each
            "sub_calls": repl['sub_call_count'],
        }
        iterations_log.append(iter_log)

        # Check for final answer
        final_answer = rlm_find_final(response_text, repl)
        if final_answer:
            break

        # Append to conversation
        messages.append({"role": "assistant", "content": response_text})

        # Build REPL output feedback
        if repl_outputs:
            repl_feedback = "\n\n".join(
                f"[REPL output {i+1}]:\n{out}" for i, out in enumerate(repl_outputs)
            )
            _plan_instr = f"Output a plan of 1-{planning_horizon} actions."
            _continue = RLM_USER_PROMPT_CONTINUE.replace("{plan_instruction}", _plan_instr)
            messages.append({"role": "user", "content": repl_feedback + "\n\n" + _continue})
        else:
            _plan_instr = f"Output a plan of 1-{planning_horizon} actions."
            messages.append({"role": "user", "content": RLM_USER_PROMPT_CONTINUE.replace("{plan_instruction}", _plan_instr)})

    # Parse the final answer into the standard response format
    parsed = _parse_rlm_output(final_answer, iterations_log, extract_json, planning_horizon)

    # Force-action fallback: if parsing failed, pick the first non-RESET action
    available = payload.get("available_actions", [])
    if not parsed and available:
        # Gather whatever reasoning we can from the iterations
        raw_reasoning = ""
        if iterations_log:
            raw_reasoning = iterations_log[-1].get("response", "")[:500]
        safe_action = next((a for a in available if a != 0), available[0])
        parsed = {
            "action": safe_action,
            "data": {},
            "observation": "(RLM did not produce parseable output — forcing action)",
            "reasoning": raw_reasoning or "(no reasoning captured)",
        }
        logger.warning(f"[RLM force-action] No parseable output after {len(iterations_log)} iterations, forcing action={safe_action}")

    total_sub_calls = repl['sub_call_count']
    total_iterations = len(iterations_log)

    result = {
        "raw": final_answer or (iterations_log[-1].get("response", "") if iterations_log else ""),
        "thinking": None,
        "parsed": parsed,
        "model": model_key,
        "scaffolding": "rlm",
        "rlm": {
            "iterations": total_iterations,
            "sub_calls": total_sub_calls,
            "max_iterations": max_iterations,
            "final_answer": final_answer,
            "log": iterations_log,
        },
    }
    return result


def _parse_rlm_output(final_answer: str | None, iterations_log: list,
                       extract_json, planning_horizon: int) -> dict | None:
    """Parse RLM output into a standard action/plan dict.

    Handles these formats:
    1. {"action": N, "data": {}, ...}           → single action
    2. {"plan": [{"action": N, ...}, ...], ...} → multi-step plan
    3. {"actions": [...], ...}                   → alt multi-step format
    4. Raw JSON from last response              → fallback extraction
    """
    parsed = None

    if final_answer:
        parsed = extract_json(final_answer)
        if not parsed:
            try:
                parsed = json.loads(final_answer)
            except (json.JSONDecodeError, TypeError):
                pass

    # Fallback: try to extract from last response
    if not parsed and iterations_log:
        last_resp = iterations_log[-1].get("response", "")
        parsed = extract_json(last_resp)

    if not parsed:
        return None

    # Normalize: ensure we always have either "plan" or "action"
    # If model returned "actions" array, convert to "plan"
    if "actions" in parsed and isinstance(parsed["actions"], list) and "plan" not in parsed:
        parsed["plan"] = parsed.pop("actions")

    # Always wrap single action as 1-step plan
    if "action" in parsed and "plan" not in parsed:
        parsed["plan"] = [{"action": parsed["action"], "data": parsed.get("data", {})}]

    # Validate plan entries have proper structure
    if "plan" in parsed and isinstance(parsed["plan"], list):
        clean_plan = []
        for step in parsed["plan"][:planning_horizon]:
            if isinstance(step, dict) and "action" in step:
                clean_plan.append({
                    "action": int(step["action"]),
                    "data": step.get("data", {}),
                    "observation": step.get("observation", ""),
                })
            elif isinstance(step, (int, float)):
                clean_plan.append({"action": int(step), "data": {}})
        if clean_plan:
            parsed["plan"] = clean_plan

    return parsed
