"""RLM scaffolding web UI handler."""

import json
import logging
import time

from scaffoldings.rlm.prompts import (
    RLM_SYSTEM_PROMPT,
    RLM_USER_PROMPT_FIRST,
    RLM_USER_PROMPT_CONTINUE,
    RLM_REPL_CODE_PATTERN,
)
from scaffoldings.rlm.repl import create_rlm_repl, rlm_execute_code, rlm_find_final

logger = logging.getLogger(__name__)


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

    # Create REPL
    repl = create_rlm_repl(
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
        {"role": "system", "content": RLM_SYSTEM_PROMPT},
        {"role": "user", "content": RLM_USER_PROMPT_FIRST},
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
            messages.append({"role": "user", "content": repl_feedback + "\n\n" + RLM_USER_PROMPT_CONTINUE})
        else:
            messages.append({"role": "user", "content": RLM_USER_PROMPT_CONTINUE})

    # Parse the final answer into the standard response format
    if final_answer:
        # Try to parse as JSON action
        parsed = extract_json(final_answer)
        if not parsed:
            # Try wrapping in braces
            try:
                parsed = json.loads(final_answer)
            except (json.JSONDecodeError, TypeError):
                parsed = None
    else:
        # No FINAL — try to parse last response for action
        parsed = None
        if iterations_log:
            last_resp = iterations_log[-1].get("response", "")
            parsed = extract_json(last_resp)

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
