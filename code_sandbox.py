"""Shared Python sandbox for Gemini function calling (run_python tool).

Extracted from server.py so both the web UI (server.py) and CLI (agent.py)
can use the same sandboxed code execution infrastructure.
"""

import io
import threading
import time

# ── Session storage ───────────────────────────────────────────────────────

_tool_sessions: dict[str, dict] = {}  # session_id → {namespace, created_at}
_tool_session_lock = threading.Lock()


# ── Tool declarations ────────────────────────────────────────────────────

def get_tool_declarations():
    """Return Gemini Tool with a run_python FunctionDeclaration."""
    from google import genai
    return genai.types.Tool(function_declarations=[
        genai.types.FunctionDeclaration(
            name="run_python",
            description=(
                "Execute Python code to analyse the game grid. "
                "Pre-imported: numpy (as np), collections, itertools. "
                "Available variables: `grid` (numpy 2D int array of current grid), "
                "`prev_grid` (numpy 2D int array of previous grid, or None). "
                "Variables you define persist across calls within the same turn. "
                "Use print() to return results. "
                "IMPORTANT: Keep code short and simple — use numpy vectorized ops, "
                "avoid nested loops over large arrays. Combine analyses into one call "
                "when possible. You have max 3 tool calls per turn, so be efficient."
            ),
            parameters={
                "type": "OBJECT",
                "properties": {
                    "code": {
                        "type": "STRING",
                        "description": "Python code to execute. Use print() for output.",
                    }
                },
                "required": ["code"],
            },
        ),
    ])


# ── Import sandboxing ────────────────────────────────────────────────────

BLOCKED_MODULES = frozenset({
    'os', 'sys', 'subprocess', 'shutil', 'pathlib', 'socket', 'http',
    'urllib', 'requests', 'httpx', 'aiohttp', 'ftplib', 'smtplib',
    'ctypes', 'multiprocessing', 'signal', 'importlib', 'code', 'codeop',
    'compileall', 'py_compile', 'zipimport', 'pkgutil', 'pkg_resources',
})


def _safe_import(name, *args, **kwargs):
    """Restricted __import__ that blocks dangerous modules."""
    top_level = name.split('.')[0]
    if top_level in BLOCKED_MODULES:
        raise ImportError(f"Module '{name}' is not allowed in the sandbox")
    return __builtins__['__import__'](name, *args, **kwargs) \
        if isinstance(__builtins__, dict) \
        else __import__(name, *args, **kwargs)


# ── Session management ───────────────────────────────────────────────────

def get_or_create_tool_session(session_id: str, grid, prev_grid) -> dict:
    """Get or create a sandboxed namespace for Python execution."""
    import numpy as np
    import collections
    import itertools

    with _tool_session_lock:
        sess = _tool_sessions.get(session_id)
        if sess is None:
            # Start from real builtins, override dangerous ones
            if isinstance(__builtins__, dict):
                safe_builtins = dict(__builtins__)
            else:
                safe_builtins = {k: getattr(__builtins__, k) for k in dir(__builtins__)
                                 if not k.startswith('_')}
                safe_builtins['__import__'] = __builtins__.__import__

            # Replace/remove dangerous builtins
            safe_builtins['open'] = None
            safe_builtins['eval'] = None
            safe_builtins['exec'] = None
            safe_builtins['compile'] = None
            safe_builtins['breakpoint'] = None
            safe_builtins['exit'] = None
            safe_builtins['quit'] = None
            safe_builtins['__import__'] = _safe_import

            ns = {
                '__builtins__': safe_builtins,
                'np': np,
                'numpy': np,
                'collections': collections,
                'itertools': itertools,
                'Counter': collections.Counter,
                'defaultdict': collections.defaultdict,
            }
            sess = {'namespace': ns, 'created_at': time.time()}
            _tool_sessions[session_id] = sess

    # Always update grid/prev_grid to current values
    ns = sess['namespace']
    ns['grid'] = np.array(grid) if grid else np.array([[]])
    ns['prev_grid'] = np.array(prev_grid) if prev_grid else None
    return sess


def execute_python(session_id: str, code: str, grid, prev_grid, timeout: float = 5.0) -> str:
    """Execute Python code in a sandboxed namespace, capturing print output."""
    sess = get_or_create_tool_session(session_id, grid, prev_grid)
    ns = sess['namespace']

    output_buf = io.StringIO()
    result = [None]  # mutable container for thread result
    error = [None]

    def _run():
        import builtins
        old_print = ns['__builtins__'].get('print', builtins.print) if isinstance(ns['__builtins__'], dict) else builtins.print
        # Override print to capture to buffer
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
        return "[TIMEOUT] Code execution exceeded 5 seconds."

    output = output_buf.getvalue()
    if error[0]:
        output = (output + "\n" + error[0]).strip()

    # Truncate long output
    if len(output) > 4000:
        output = output[:4000] + "\n... [truncated]"

    return output or "(no output)"


def cleanup_tool_session(session_id: str):
    """Remove a tool session when the game session is reset/ended."""
    with _tool_session_lock:
        _tool_sessions.pop(session_id, None)
