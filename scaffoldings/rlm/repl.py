"""RLM REPL environment — create, execute code, find final answer."""

import io
import threading
import time

from scaffoldings.rlm.prompts import RLM_REPL_CODE_PATTERN, RLM_FINAL_PATTERN, RLM_FINAL_VAR_PATTERN


def create_rlm_repl(session_id: str, context: dict, model_key: str,
                     thinking_level: str, max_tokens: int,
                     sub_model_key: str | None = None,
                     sub_thinking_level: str = "low",
                     sub_max_tokens: int = 8192,
                     max_depth: int = 1, current_depth: int = 0,
                     *, route_model_call, log_llm_call, safe_import) -> dict:
    """Create an RLM REPL environment with llm_query/rlm_query injected.

    Dependencies are injected to avoid circular imports with server.py:
      - route_model_call: server._route_model_call
      - log_llm_call: db._log_llm_call
      - safe_import: server._safe_import
    """
    import numpy as np
    import collections
    import itertools

    # Build safe builtins (same as tool sessions)
    if isinstance(__builtins__, dict):
        safe_builtins = dict(__builtins__)
    else:
        safe_builtins = {k: getattr(__builtins__, k) for k in dir(__builtins__)
                         if not k.startswith('_')}
        safe_builtins['__import__'] = __builtins__.__import__
    safe_builtins['open'] = None
    safe_builtins['eval'] = None
    safe_builtins['exec'] = None
    safe_builtins['compile'] = None
    safe_builtins['breakpoint'] = None
    safe_builtins['exit'] = None
    safe_builtins['quit'] = None
    safe_builtins['__import__'] = safe_import

    ns = {
        '__builtins__': safe_builtins,
        'np': np,
        'numpy': np,
        'collections': collections,
        'itertools': itertools,
        'Counter': collections.Counter,
        'defaultdict': collections.defaultdict,
        'context': context,
    }

    # Track final answer
    repl_state = {
        'namespace': ns,
        'final_answer': None,
        'sub_call_count': 0,
        'max_sub_calls': 50,  # safety limit
        'session_id': session_id,
        'parent_call_id': None,  # set by handler per iteration
    }

    # ── llm_query: single LLM call (no REPL, no recursion) ──
    def llm_query(prompt: str) -> str:
        if repl_state['sub_call_count'] >= repl_state['max_sub_calls']:
            return "[ERROR] Maximum sub-LLM call limit reached."
        repl_state['sub_call_count'] += 1
        _model = sub_model_key or model_key
        try:
            t0 = time.time()
            result = route_model_call(
                _model, prompt, None,
                thinking_level=sub_thinking_level,
                max_tokens=sub_max_tokens,
            )
            dur = int((time.time() - t0) * 1000)
            text = result.get("text", "") if isinstance(result, dict) else str(result)
            log_llm_call(
                repl_state['session_id'], "rlm_sub", _model,
                parent_call_id=repl_state.get('parent_call_id'),
                prompt_preview=prompt[:500], prompt_length=len(prompt),
                response_preview=text[:1000] if text else None,
                duration_ms=dur,
            )
            return text
        except Exception as e:
            return f"[LLM ERROR] {e}"

    # ── llm_query_batched: concurrent batch ──
    def llm_query_batched(prompts: list) -> list:
        import concurrent.futures
        results = [None] * len(prompts)
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(prompts), 4)) as ex:
            futures = {ex.submit(llm_query, p): i for i, p in enumerate(prompts)}
            for f in concurrent.futures.as_completed(futures):
                results[futures[f]] = f.result()
        return results

    # ── SHOW_VARS ──
    def show_vars() -> str:
        user_vars = {k: type(v).__name__ for k, v in ns.items()
                     if not k.startswith('_') and k not in (
                         'np', 'numpy', 'collections', 'itertools',
                         'Counter', 'defaultdict', 'context',
                         'llm_query', 'llm_query_batched', 'SHOW_VARS',
                         'FINAL', 'FINAL_VAR')}
        lines = [f"  {k}: {t}" for k, t in sorted(user_vars.items())]
        result = "User variables:\n" + ("\n".join(lines) if lines else "  (none)")
        return result

    # ── FINAL_VAR ──
    def final_var(var_name: str):
        val = ns.get(var_name)
        if val is None:
            return f"[ERROR] Variable '{var_name}' not found. Use SHOW_VARS() to see available variables."
        repl_state['final_answer'] = str(val) if not isinstance(val, str) else val
        return repl_state['final_answer']

    ns['llm_query'] = llm_query
    ns['llm_query_batched'] = llm_query_batched
    ns['SHOW_VARS'] = show_vars
    ns['FINAL_VAR'] = final_var
    # FINAL is parsed from text, not a callable — the LM writes FINAL(...) in prose

    return repl_state


def rlm_execute_code(repl_state: dict, code: str, timeout: float = 10.0,
                     max_output: int = 20_000) -> str:
    """Execute code in the RLM REPL, capturing output."""
    ns = repl_state['namespace']
    output_buf = io.StringIO()
    error = [None]

    def _run():
        import builtins
        def captured_print(*args, **kwargs):
            kwargs['file'] = output_buf
            builtins.print(*args, **kwargs)
        if isinstance(ns['__builtins__'], dict):
            ns['__builtins__']['print'] = captured_print
        try:
            exec(code, ns)
        except Exception as e:
            error[0] = f"{type(e).__name__}: {e}"

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    t.join(timeout=timeout)

    if t.is_alive():
        return "[TIMEOUT] Code execution exceeded time limit."

    output = output_buf.getvalue()
    if error[0]:
        output = (output + "\n" + error[0]).strip()

    # Truncate
    if len(output) > max_output:
        truncated = len(output) - max_output
        output = output[:max_output] + f"\n... [{truncated} chars truncated]"

    return output or "(no output)"


def rlm_find_final(text: str, repl_state: dict) -> str | None:
    """Check for FINAL() or FINAL_VAR() in LLM response text (outside code blocks)."""
    # Strip code blocks before checking
    stripped = RLM_REPL_CODE_PATTERN.sub("", text)

    # FINAL_VAR first
    m = RLM_FINAL_VAR_PATTERN.search(stripped)
    if m:
        var_name = m.group(1).strip()
        val = repl_state['namespace'].get(var_name)
        if val is not None:
            return str(val) if not isinstance(val, str) else val

    # FINAL(...)
    m = RLM_FINAL_PATTERN.search(stripped)
    if m:
        return m.group(1).strip()

    # Check if FINAL_VAR was called inside code (sets repl_state['final_answer'])
    if repl_state.get('final_answer'):
        return repl_state['final_answer']

    return None
