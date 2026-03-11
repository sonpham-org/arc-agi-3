# Phase 2 Plan: Python Extractions (server.py Decomposition)

> **Documentation only — no code changes until this plan is approved.**
> Line numbers reference `server.py` as of 2026-03-10.
> Verify with `grep -n "def compress_row\|def _compress_change_row\|def compute_change_map"` etc. before executing.

---

## Overview

Phase 2 decomposes `server.py` into five focused modules:

| Sub-step | New file | ~Lines extracted |
|---|---|---|
| 2a | `grid_analysis.py` | ~130 lines |
| 2b | `prompt_builder.py` | ~180 lines |
| 2c | `bot_protection.py` | ~100 lines |
| 2d | `session_manager.py` | ~120 lines |
| 2e | `db.py` (context manager added) | ~25 patterns replaced |

---

## 2a — Extract `grid_analysis.py`

### Files affected
- `server.py` (source)
- `grid_analysis.py` (new, create at repo root)

### Exact line numbers to extract from `server.py`

Use `grep -n` to confirm exact lines before extraction:
```
grep -n "def compress_row\|def _compress_change_row\|def compute_change_map\|def compute_color_histogram\|def compute_region_map" server.py
```

**Approximate line ranges** (confirm with grep):
- `compress_row()` — ~lines 363–375
- `compute_change_map()` — ~lines 378–395
- `_compress_change_row()` — ~lines 398–407
- `compute_color_histogram()` — ~lines 410–419
- `compute_region_map()` — ~lines 422–447

Also extract the `COLOR_NAMES` dict (used by `compute_color_histogram` and `compute_region_map`). Currently defined near line 332. **Do not remove it from server.py yet** — it is also used by `env_state_dict`, `_build_prompt`, and the draw editor routes. Instead, import it from `grid_analysis.py` in server.py and remove the local definition.

### Full content of new file

```python
# grid_analysis.py
"""Grid analysis helpers for ARC-AGI-3.

Extracted from server.py (Phase 2a).
No Flask/server dependencies — pure Python + stdlib only.
"""

from collections import deque

COLOR_NAMES = {
    0: "White",        1: "LightGray",   2: "Gray",         3: "DarkGray",
    4: "VeryDarkGray", 5: "Black",       6: "Magenta",      7: "LightMagenta",
    8: "Red",          9: "Blue",       10: "LightBlue",   11: "Yellow",
   12: "Orange",      13: "Maroon",     14: "Green",       15: "Purple",
}


def compress_row(row: list[int]) -> str:
    """RLE-compress a single grid row into a compact string."""
    if not row:
        return ""
    parts = []
    cur, count = row[0], 1
    for v in row[1:]:
        if v == cur:
            count += 1
        else:
            parts.append(f"{cur}x{count}" if count > 1 else str(cur))
            cur, count = v, 1
    parts.append(f"{cur}x{count}" if count > 1 else str(cur))
    return " ".join(parts)


def _compress_change_row(row: str) -> str:
    """RLE-compress a change-map row string (X=changed, .=unchanged)."""
    if not row:
        return ""
    parts = []
    cur, count = row[0], 1
    for ch in row[1:]:
        if ch == cur:
            count += 1
        else:
            parts.append(f"{cur}x{count}" if count > 3 else cur * count)
            cur, count = ch, 1
    parts.append(f"{cur}x{count}" if count > 3 else cur * count)
    return "".join(parts)


def compute_change_map(prev_grid, curr_grid) -> dict:
    """Diff two grids; return changed cells and a compact change-map text."""
    if not prev_grid or not curr_grid:
        return {"changes": [], "change_count": 0, "change_map_text": ""}
    h = min(len(prev_grid), len(curr_grid))
    w = min(len(prev_grid[0]), len(curr_grid[0])) if h > 0 else 0
    changes, rows = [], []
    for y in range(h):
        row_chars = []
        for x in range(w):
            if prev_grid[y][x] != curr_grid[y][x]:
                changes.append({"x": x, "y": y, "from": prev_grid[y][x], "to": curr_grid[y][x]})
                row_chars.append("X")
            else:
                row_chars.append(".")
        row_str = "".join(row_chars)
        if "X" in row_str:
            rows.append(f"Row {y}: {_compress_change_row(row_str)}")
    return {
        "changes": changes,
        "change_count": len(changes),
        "change_map_text": "\n".join(rows) if rows else "(no changes)",
    }


def compute_color_histogram(grid: list) -> str:
    """Return a text summary of color cell counts for a grid."""
    if not grid:
        return ""
    counts: dict[int, int] = {}
    for row in grid:
        for v in row:
            counts[v] = counts.get(v, 0) + 1
    return "\n".join(
        f"  {v} ({COLOR_NAMES.get(v, '?')}): {cnt} cells"
        for v, cnt in sorted(counts.items())
    )


def compute_region_map(grid: list) -> str:
    """BFS-flood-fill to find connected regions per color; return text summary."""
    if not grid:
        return ""
    h, w = len(grid), len(grid[0])
    visited = [[False] * w for _ in range(h)]
    regions: dict[int, list] = {}
    for sy in range(h):
        for sx in range(w):
            if visited[sy][sx]:
                continue
            color = grid[sy][sx]
            queue = deque([(sy, sx)])
            visited[sy][sx] = True
            cells = []
            while queue:
                y, x = queue.popleft()
                cells.append((y, x))
                for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    ny, nx = y + dy, x + dx
                    if 0 <= ny < h and 0 <= nx < w and not visited[ny][nx] and grid[ny][nx] == color:
                        visited[ny][nx] = True
                        queue.append((ny, nx))
            ys = [c[0] for c in cells]
            xs = [c[1] for c in cells]
            regions.setdefault(color, []).append({
                "size": len(cells),
                "bbox": f"rows {min(ys)}-{max(ys)}, cols {min(xs)}-{max(xs)}",
            })
    lines = []
    for color in sorted(regions):
        name = COLOR_NAMES.get(color, str(color))
        top = sorted(regions[color], key=lambda r: -r["size"])[:5]
        for r in top:
            lines.append(f"  {color}={name}: {r['size']} cells at {r['bbox']}")
        if len(regions[color]) > 5:
            lines.append(f"  {color}={name}: ... ({len(regions[color]) - 5} more)")
    return "\n".join(lines)
```

### Import statements to add to `server.py`

After removing the extracted functions and `COLOR_NAMES`, add near the top of `server.py` (after existing module imports, around the `from db import` block):

```python
from grid_analysis import (
    COLOR_NAMES,
    compress_row,
    compute_change_map,
    compute_color_histogram,
    compute_region_map,
)
```

Also remove the local `COLOR_NAMES` dict definition from server.py (currently near line 332, next to `COLOR_MAP`).

### Circular import risk

**None.** `grid_analysis.py` only uses Python stdlib (`collections.deque`). No Flask, no db, no server state.

### Verification command

```bash
cd /path/to/sonpham-arc3
python -c "from grid_analysis import compress_row, compute_change_map, compute_color_histogram, compute_region_map, COLOR_NAMES; print('OK')"
python -c "import server; print('server imports OK')"
# Smoke test:
python -c "from grid_analysis import compress_row; print(compress_row([0,0,1,1,1,5]))"
```

---

## 2b — Extract `prompt_builder.py`

### Files affected
- `server.py` (source)
- `prompt_builder.py` (new, create at repo root)

### Exact line numbers to extract from `server.py`

```
grep -n "def _build_prompt_parts\|def _build_prompt\|def _parse_llm_response\|def _extract_json" server.py
```

**Approximate line ranges:**
- `_build_prompt_parts()` — ~lines 449–470
- `_build_prompt()` — ~lines 483–568
- `_parse_llm_response()` — ~lines 572–585
- `_extract_json()` — ~lines 588–615

### Circular import risk — CRITICAL

`_build_prompt()` and `_build_prompt_parts()` reference two module-level globals from `server.py`:
- `_custom_system_prompt` — set by `POST /api/memory`
- `_custom_hard_memory` — set by `POST /api/memory`

And they also use `ARC_AGI3_DESCRIPTION` (a string constant) and `ACTION_NAMES` (a dict).

**If `prompt_builder.py` imports from `server.py`, you get a circular import:**
```
server.py → prompt_builder.py → server.py  # BOOM
```

**Resolution:** Pass `_custom_system_prompt` and `_custom_hard_memory` as explicit parameters to both functions. Change their signatures:

```python
def _build_prompt(payload, input_settings, tools_mode, planning_mode="off",
                  interrupt_plan=False,
                  custom_system_prompt=None, custom_hard_memory=None) -> str:
    sys_prompt = custom_system_prompt if custom_system_prompt else ARC_AGI3_DESCRIPTION
    ...
```

In `server.py`, all call sites become:
```python
_build_prompt(..., custom_system_prompt=_custom_system_prompt, custom_hard_memory=_custom_hard_memory)
```

`ARC_AGI3_DESCRIPTION` and `ACTION_NAMES` are constants — safe to either duplicate in `prompt_builder.py` or import from a shared `constants.py`. **Recommended:** define both in `prompt_builder.py` directly (they are pure data, no circular risk), and remove them from `server.py` imports, importing them back from `prompt_builder.py` in server.py.

`compress_row`, `compute_color_histogram`, `compute_region_map` (used inside `_build_prompt`) — import from `grid_analysis.py`. No circular risk.

### Full content of new file

```python
# prompt_builder.py
"""LLM prompt construction and response parsing for ARC-AGI-3.

Extracted from server.py (Phase 2b).

IMPORTANT: _build_prompt and _build_prompt_parts accept custom_system_prompt
and custom_hard_memory as explicit parameters (not module globals) to avoid
circular imports with server.py.
"""

import json
import re
from pathlib import Path

from grid_analysis import compress_row, compute_color_histogram, compute_region_map

# ── Constants ─────────────────────────────────────────────────────────────

ACTION_NAMES = {
    0: "RESET", 1: "ACTION1", 2: "ACTION2", 3: "ACTION3",
    4: "ACTION4", 5: "ACTION5", 6: "ACTION6", 7: "ACTION7",
}

ARC_AGI3_DESCRIPTION = (
    Path(__file__).parent / "prompts" / "shared" / "arc_description.txt"
).read_text().strip()


# ── Prompt building ────────────────────────────────────────────────────────

def _build_prompt_parts(payload: dict, input_settings: dict, tools_mode: str,
                        planning_mode: str = "off",
                        custom_system_prompt=None,
                        custom_hard_memory=None) -> tuple[str, str]:
    """Split prompt into static (cacheable) and dynamic parts.

    Returns (static_str, dynamic_str).
    """
    static_parts = []
    sys_prompt = custom_system_prompt if custom_system_prompt else ARC_AGI3_DESCRIPTION
    static_parts.append(f"""{sys_prompt}

COLOR PALETTE: 0=White 1=LightGray 2=Gray 3=DarkGray 4=VeryDarkGray 5=Black
               6=Magenta 7=LightMagenta 8=Red 9=Blue 10=LightBlue 11=Yellow
               12=Orange 13=Maroon 14=Green 15=Purple""")

    if custom_hard_memory:
        static_parts.append(f"## AGENT MEMORY\n{custom_hard_memory}")

    static_str = "\n\n".join(static_parts)
    return static_str, ""


def _build_prompt(payload: dict, input_settings: dict, tools_mode: str,
                  planning_mode: str = "off", interrupt_plan: bool = False,
                  custom_system_prompt=None, custom_hard_memory=None) -> str:
    """Build an LLM prompt controlled by the input settings from the UI."""
    grid = payload.get("grid", [])
    state = payload.get("state", "")
    available = payload.get("available_actions", [])
    levels_completed = payload.get("levels_completed", 0)
    win_levels = payload.get("win_levels", 0)
    history = payload.get("history", [])
    game_id = payload.get("game_id", "unknown")
    change_map = payload.get("change_map", {})

    parts: list[str] = []

    sys_prompt = custom_system_prompt if custom_system_prompt else ARC_AGI3_DESCRIPTION
    parts.append(f"""{sys_prompt}

COLOR PALETTE: 0=White 1=LightGray 2=Gray 3=DarkGray 4=VeryDarkGray 5=Black
               6=Magenta 7=LightMagenta 8=Red 9=Blue 10=LightBlue 11=Yellow
               12=Orange 13=Maroon 14=Green 15=Purple""")

    if custom_hard_memory:
        parts.append(f"## AGENT MEMORY\n{custom_hard_memory}")

    action_desc = ", ".join(f"{a}={ACTION_NAMES.get(a, f'ACTION{a}')}" for a in available)
    parts.append(
        f"## STATE\nGame: {game_id} | State: {state} | "
        f"Levels: {levels_completed}/{win_levels}\n"
        f"Available actions: {action_desc}"
    )

    compact_context = payload.get("compact_context", "")
    if compact_context:
        parts.append(compact_context)

    if history:
        lines = []
        for h in history:
            aname = ACTION_NAMES.get(h.get("action", 0), "?")
            line = f"  Step {h.get('step', '?')}: {aname} -> {h.get('result_state', '?')}"
            cm = h.get("change_map")
            if cm and cm.get("change_count", 0) > 0:
                line += f" ({cm['change_count']} cells changed)"
                if cm.get("change_map_text"):
                    line += f"\n    Changes: {cm['change_map_text']}"
            elif cm and cm.get("change_count") == 0:
                line += " (no change)"
            grid_snap = h.get("grid")
            if grid_snap:
                rle = "\n".join(f"    Row {i}: {compress_row(r)}" for i, r in enumerate(grid_snap))
                line += f"\n{rle}"
            lines.append(line)
        parts.append(f"## HISTORY ({len(history)} steps)\n" + "\n".join(lines))

    if input_settings.get("diff") and change_map and change_map.get("change_count", 0) > 0:
        parts.append(
            f"## CHANGES ({change_map['change_count']} cells changed)\n"
            f"{change_map.get('change_map_text', '')}"
        )

    if input_settings.get("full_grid", True):
        grid_text = "\n".join(f"Row {i}: {compress_row(r)}" for i, r in enumerate(grid))
        parts.append(f"## GRID (RLE, colors 0-15)\n{grid_text}")

    if input_settings.get("color_histogram") or tools_mode == "on":
        histo = compute_color_histogram(grid)
        if histo:
            parts.append(f"## COLOR HISTOGRAM\n{histo}")

    if tools_mode == "on":
        rmap = compute_region_map(grid)
        if rmap:
            parts.append(f"## REGION MAP\n{rmap}")

    if input_settings.get("image"):
        parts.append(
            "## IMAGE\nA screenshot of the current grid is attached. "
            "Use it together with the numeric data above."
        )

    tool_extra = ""
    if tools_mode == "on":
        tool_extra = (
            "\n- You have access to a run_python tool. Call it to analyse the grid programmatically "
            "(e.g. find objects, count colors, detect patterns, measure distances). "
            "The grid is available as a numpy array variable `grid`. Use print() to see results."
            '\n- Include "analysis" in your JSON with a summary of what the tool found.'
        )

    analysis_field = ', "analysis": "<detailed spatial analysis>"' if tools_mode == "on" else ''
    is_planning = planning_mode and planning_mode != "off"

    if is_planning:
        plan_n = int(planning_mode)
        expected_field = ', "expected": "<what you expect to see after this plan>"' if interrupt_plan else ''
        expected_rule = '\n- "expected": briefly describe what you expect after the plan completes (e.g. "character at the door", "score increased").' if interrupt_plan else ''
        parts.append(f"""## YOUR TASK
1. Identify key objects (character, walls, targets, items).
2. Determine what must happen next to progress.
3. Plan a sequence of actions (up to {plan_n} steps).

Respond with EXACTLY this JSON (nothing else):
{{"observation": "<what you see>", "reasoning": "<your plan>", "plan": [{{"action": <n>, "data": {{}}}}, ...]{analysis_field}{expected_field}}}

Rules:
- Return a "plan" array of up to {plan_n} steps. Each step has "action" (0-7) and "data" ({{}} or {{"x": <0-63>, "y": <0-63>}}).
- ACTION6: set "data" to {{"x": <0-63>, "y": <0-63>}}.
- Other actions: set "data" to {{}}.{expected_rule}{tool_extra}""")
    else:
        parts.append(f"""## YOUR TASK
1. Identify key objects (character, walls, targets, items).
2. Determine what must happen next to progress.
3. Choose the best action.

Respond with EXACTLY this JSON (nothing else):
{{"observation": "<what you see>", "reasoning": "<your plan>", "action": <number>, "data": {{}}{analysis_field}}}

Rules:
- "action" must be a plain integer (0-7).
- ACTION6: set "data" to {{"x": <0-63>, "y": <0-63>}}.
- Other actions: set "data" to {{}}.{tool_extra}""")

    return "\n\n".join(parts)


# ── Response parsing ───────────────────────────────────────────────────────

def _parse_llm_response(content: str, model_name: str) -> dict:
    """Parse raw LLM output; extract thinking block and JSON payload."""
    if not isinstance(content, str):
        content = json.dumps(content) if content else ""
    thinking = ""
    think_match = re.search(r"<think>(.*?)</think>", content, re.DOTALL)
    if think_match:
        thinking = think_match.group(1).strip()
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

    parsed = _extract_json(content)
    if parsed:
        return {"raw": content, "thinking": thinking[:500] if thinking else None,
                "parsed": parsed, "model": model_name}

    if thinking:
        parsed = _extract_json(thinking)
        if parsed:
            return {"raw": content or thinking, "thinking": thinking[:500],
                    "parsed": parsed, "model": model_name}

    return {"raw": content or thinking, "thinking": thinking[:500] if thinking else None,
            "parsed": None, "model": model_name}


def _extract_json(text: str) -> dict | None:
    """Extract first valid JSON object with 'action' or 'plan' using balanced-brace matching."""
    cleaned = re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)
    i = 0
    while i < len(cleaned):
        if cleaned[i] != "{":
            i += 1
            continue
        depth = 0
        in_str = False
        esc = False
        for j in range(i, len(cleaned)):
            ch = cleaned[j]
            if esc:
                esc = False
                continue
            if ch == "\\" and in_str:
                esc = True
                continue
            if ch == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(cleaned[i : j + 1])
                        if "action" in obj or "plan" in obj or "type" in obj or "verdict" in obj:
                            return obj
                    except json.JSONDecodeError:
                        pass
                    break
        i += 1
    return None
```

### Import statements to add to `server.py`

```python
from prompt_builder import (
    ACTION_NAMES,
    ARC_AGI3_DESCRIPTION,
    _build_prompt_parts,
    _build_prompt,
    _parse_llm_response,
    _extract_json,
)
```

Remove from server.py:
- `ACTION_NAMES` dict definition
- `ARC_AGI3_DESCRIPTION` Path().read_text() call
- The four function bodies

All call sites of `_build_prompt` and `_build_prompt_parts` in server.py must add `custom_system_prompt=_custom_system_prompt, custom_hard_memory=_custom_hard_memory` as keyword arguments.

Search for call sites:
```bash
grep -n "_build_prompt\|_build_prompt_parts" server.py
```

### Circular import risk

**MEDIUM RISK — mitigated by parameter passing.**

Do NOT import `_custom_system_prompt`, `_custom_hard_memory`, or anything from `server.py` inside `prompt_builder.py`. These must be passed as function parameters. Any scaffolding handlers that call `_build_prompt` must also accept and pass these values from server.py's module scope at call time.

### Verification command

```bash
python -c "from prompt_builder import _build_prompt, _parse_llm_response, _extract_json; print('OK')"
python -c "import server; print('server imports OK')"
```

---

## 2c — Extract `bot_protection.py`

### Files affected
- `server.py` (source)
- `bot_protection.py` (new, create at repo root)

### Exact line numbers to extract from `server.py`

```
grep -n "BOT_UA_PATTERNS\|_rate_buckets\|_rate_lock\|RATE_LIMIT\|RATE_WINDOW\|_verified_tokens\|_token_lock\|TURNSTILE_TOKEN_TTL\|def _get_client_ip\|def _is_bot_ua\|def _check_rate_limit\|def _verify_turnstile_token\|def _is_turnstile_verified\|def bot_protection\|def turnstile_required" server.py
```

**Approximate line ranges:**
- `TURNSTILE_SITE_KEY`, `TURNSTILE_SECRET_KEY` env reads — ~lines 116–117
- `BOT_UA_PATTERNS` list — ~lines 120–135
- `_rate_buckets`, `_rate_lock`, `RATE_LIMIT`, `RATE_WINDOW` — ~lines 136–140
- `_verified_tokens`, `_token_lock`, `TURNSTILE_TOKEN_TTL` — ~lines 141–144
- `def _get_client_ip()` — ~lines 146–150
- `def _is_bot_ua()` — ~lines 152–154
- `def _check_rate_limit()` — ~lines 157–165
- `def _verify_turnstile_token()` — ~lines 167–178
- `def _is_turnstile_verified()` — ~lines 180–193
- `def bot_protection(f)` — ~lines 195–207
- `def turnstile_required(f)` — ~lines 210–215

### Circular import risk — CRITICAL

`bot_protection` and `turnstile_required` decorators reference:
- `app.logger.info(...)` — from `server.py`'s Flask `app`
- `get_mode()` — defined in `server.py`
- `abort`, `jsonify` — from Flask (fine, import directly)
- `request` — from Flask (fine)

**If `bot_protection.py` imports `app` or `get_mode` from `server.py`, you get a circular import.**

**Resolution options (choose one):**
1. **Pass `get_mode` as a callable parameter at decoration time** — complex, changes decorator signature.
2. **Move `get_mode()` to its own tiny `server_mode.py` module** — cleanest. Both `server.py` and `bot_protection.py` import from `server_mode.py`.
3. **Use a `logging.getLogger(__name__)` instead of `app.logger`** — eliminates the Flask `app` dependency.
4. **Import `app` lazily inside the decorator** — use `from flask import current_app; current_app.logger` instead of `app.logger`.

**Recommended:** Option 3 + 4 combined. Use stdlib logger for `bot_protection.py`; use `current_app.logger` instead of `app.logger` inside the decorator body. `get_mode()` can be imported lazily inside the decorator (inside the `decorated()` function body) to break the import-time circular dep:

```python
def bot_protection(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        from server import get_mode   # lazy import — only executed at request time, not import time
        if get_mode() == "staging":
            return f(*args, **kwargs)
        ...
    return decorated
```

This works because by the time any request hits the decorator, both modules are fully loaded.

### Full content of new file

```python
# bot_protection.py
"""Bot protection, rate limiting, and Turnstile verification for ARC-AGI-3.

Extracted from server.py (Phase 2c).

Circular import note: get_mode() is imported lazily inside decorator bodies
(not at module level) to avoid server.py → bot_protection.py → server.py cycle.
Flask app.logger is replaced with stdlib logging.
"""

import logging
import os
import threading
import time
from functools import wraps

import httpx as _httpx
from flask import abort, jsonify, request

log = logging.getLogger(__name__)

# ── Turnstile config ───────────────────────────────────────────────────────

TURNSTILE_SITE_KEY = os.environ.get("TURNSTILE_SITE_KEY", "")
TURNSTILE_SECRET_KEY = os.environ.get("TURNSTILE_SECRET_KEY", "")

# ── Bot UA patterns ────────────────────────────────────────────────────────

BOT_UA_PATTERNS = [
    "bot", "crawler", "spider", "scraper", "wget", "curl", "python-requests",
    "httpx", "aiohttp", "go-http-client", "java/", "libwww", "headlesschrome",
    "phantomjs", "selenium", "puppeteer", "playwright", "mechanize", "scrapy",
    "chatgpt", "gptbot", "claude-web", "anthropic-ai", "bingbot", "googlebot",
    "baiduspider", "yandexbot", "duckduckbot", "facebookexternalhit",
    "twitterbot", "applebot", "semrushbot", "ahrefsbot", "mj12bot",
    "dotbot", "petalbot", "bytespider", "ccbot",
]

# ── Rate limiting state ────────────────────────────────────────────────────

_rate_buckets: dict[str, dict] = {}
_rate_lock = threading.Lock()
RATE_LIMIT = 60
RATE_WINDOW = 60

# ── Turnstile token cache ──────────────────────────────────────────────────

_verified_tokens: dict[str, float] = {}
_token_lock = threading.Lock()
TURNSTILE_TOKEN_TTL = 3600


# ── Helper functions ───────────────────────────────────────────────────────

def _get_client_ip() -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _is_bot_ua(ua: str) -> bool:
    ua_lower = ua.lower()
    return any(pat in ua_lower for pat in BOT_UA_PATTERNS)


def _check_rate_limit(ip: str) -> bool:
    now = time.time()
    with _rate_lock:
        bucket = _rate_buckets.get(ip)
        if bucket is None or now - bucket["window_start"] > RATE_WINDOW:
            _rate_buckets[ip] = {"count": 1, "window_start": now}
            return True
        bucket["count"] += 1
        return bucket["count"] <= RATE_LIMIT


def _verify_turnstile_token(token: str, ip: str) -> bool:
    if not TURNSTILE_SECRET_KEY:
        return True
    try:
        resp = _httpx.post(
            "https://challenges.cloudflare.com/turnstile/v0/siteverify",
            data={"secret": TURNSTILE_SECRET_KEY, "response": token, "remoteip": ip},
            timeout=10.0,
        )
        return resp.json().get("success", False)
    except Exception as e:
        log.warning(f"Turnstile verification failed: {e}")
        return False


def _is_turnstile_verified() -> bool:
    from server import get_mode  # lazy import to avoid circular dep
    if get_mode() == "staging":
        return True
    if not TURNSTILE_SITE_KEY or not TURNSTILE_SECRET_KEY:
        return True
    token_hash = request.cookies.get("ts_verified", "")
    if not token_hash:
        return False
    now = time.time()
    with _token_lock:
        expiry = _verified_tokens.get(token_hash)
        if expiry and now < expiry:
            return True
        _verified_tokens.pop(token_hash, None)
    return False


# ── Decorators ─────────────────────────────────────────────────────────────

def bot_protection(f):
    """UA filtering + rate limiting on API routes (prod mode only)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        from server import get_mode  # lazy import to avoid circular dep
        if get_mode() == "staging":
            return f(*args, **kwargs)
        ip = _get_client_ip()
        ua = request.headers.get("User-Agent", "")
        if _is_bot_ua(ua):
            log.info(f"Blocked bot UA from {ip}: {ua[:80]}")
            abort(403)
        if not _check_rate_limit(ip):
            log.info(f"Rate limited {ip}")
            return jsonify({"error": "Rate limit exceeded. Try again later."}), 429
        return f(*args, **kwargs)
    return decorated


def turnstile_required(f):
    """Require Turnstile verification for protected routes."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not _is_turnstile_verified():
            return jsonify({"error": "Human verification required", "need_turnstile": True}), 403
        return f(*args, **kwargs)
    return decorated
```

### Import statements to add to `server.py`

```python
from bot_protection import (
    TURNSTILE_SITE_KEY, TURNSTILE_SECRET_KEY,
    TURNSTILE_TOKEN_TTL,
    _rate_buckets, _rate_lock, RATE_LIMIT, RATE_WINDOW,
    _verified_tokens, _token_lock,
    _get_client_ip, _is_bot_ua, _check_rate_limit,
    _verify_turnstile_token, _is_turnstile_verified,
    bot_protection, turnstile_required,
)
```

Note: `TURNSTILE_SITE_KEY` is also referenced in the `/` route and `turnstile_verify` endpoint. These will now resolve via the import above. Search for all uses:
```bash
grep -n "TURNSTILE_SITE_KEY\|TURNSTILE_SECRET_KEY\|_verified_tokens\|_token_lock\|TURNSTILE_TOKEN_TTL" server.py
```

Remove local definitions of all extracted symbols from server.py.

### Verification command

```bash
python -c "from bot_protection import bot_protection, turnstile_required, _get_client_ip; print('OK')"
python -c "import server; print('server imports OK')"
```

---

## 2d — Extract `session_manager.py`

### Files affected
- `server.py` (source)
- `session_manager.py` (new, create at repo root)

### Exact line numbers to extract from `server.py`

```
grep -n "game_sessions\|session_grids\|session_snapshots\|session_lock\|def _reconstruct_session\|def _try_recover_session" server.py
```

**Approximate line ranges:**
- `game_sessions`, `session_grids`, `session_snapshots`, `session_api_mode`, `session_api_keys`, `session_lock`, `session_step_counts`, `session_last_llm` — ~lines 234–246
- `def _reconstruct_session()` — ~lines 267–290
- `def _try_recover_session()` — ~lines 293–318

**Note:** `session_api_mode`, `session_api_keys`, `session_step_counts`, `session_last_llm` are closely related — include them all.

### Circular import risk — CRITICAL

`_try_recover_session()` references:
- `_get_db()` — from `db.py` (fine, no circular risk)
- `app.logger.info/warning(...)` — from server.py's `app` **→ circular import risk**
- `get_arcade()` — defined in `server.py` **→ circular import risk**
- `env_state_dict()` — defined in `server.py` **→ circular import risk**
- `session_step_counts` — the dict we're moving to session_manager.py (fine)
- `GameAction` — from `arcengine` (fine)
- `json` — stdlib (fine)

`_reconstruct_session()` references:
- `get_arcade()` — server.py **→ circular import risk**
- `env_state_dict()` — server.py **→ circular import risk**
- `GameAction` — arcengine (fine)
- `json` — stdlib (fine)

**Resolution:**
1. Replace `app.logger.info/warning(...)` with `logging.getLogger(__name__).info/warning(...)`.
2. Pass `get_arcade` and `env_state_dict` as callable parameters to both functions:

```python
def _reconstruct_session(game_id, actions, capture_per_step=False,
                         *, get_arcade_fn, env_state_dict_fn): ...

def _try_recover_session(session_id,
                         *, get_arcade_fn, env_state_dict_fn): ...
```

In server.py, call sites become:
```python
_reconstruct_session(game_id, actions, get_arcade_fn=get_arcade, env_state_dict_fn=env_state_dict)
_try_recover_session(session_id, get_arcade_fn=get_arcade, env_state_dict_fn=env_state_dict)
```

Alternatively, **move `get_arcade()` and `env_state_dict()` to session_manager.py** (they have no server dependencies themselves) and import them back in server.py. This is cleaner but changes which file "owns" them.

### Full content of new file

```python
# session_manager.py
"""In-memory session state and DB-backed session recovery for ARC-AGI-3.

Extracted from server.py (Phase 2d).

Circular import note: get_arcade and env_state_dict are passed as callable
parameters to avoid server.py → session_manager.py → server.py cycle.
Use stdlib logging instead of app.logger.
"""

import json
import logging
import threading
from typing import Any, Optional

from arcengine import GameAction

from db import _get_db

log = logging.getLogger(__name__)

# ── In-memory session state ────────────────────────────────────────────────

game_sessions: dict[str, Any] = {}
session_grids: dict[str, list[list[int]]] = {}
session_snapshots: dict[str, list[dict]] = {}
session_api_mode: dict[str, str] = {}
session_api_keys: dict[str, str] = {}
session_lock = threading.Lock()
session_step_counts: dict[str, int] = {}
session_last_llm: dict[str, dict] = {}


# ── Session reconstruction and recovery ───────────────────────────────────

def _reconstruct_session(game_id: str, actions: list[dict],
                          capture_per_step: bool = False,
                          *, get_arcade_fn, env_state_dict_fn):
    """Replay a list of {action, data} dicts on a fresh env. Returns (env, state_dict).
    If capture_per_step=True, also returns list of per-step state dicts."""
    bare_id = game_id.split("-")[0]
    arc = get_arcade_fn()
    env = arc.make(bare_id)
    state = env_state_dict_fn(env)
    per_step_states = [] if capture_per_step else None
    for act in actions:
        action = GameAction.from_id(int(act["action"]))
        data = act.get("data") or None
        if isinstance(data, str):
            data = json.loads(data)
        frame_data = env.step(action, data=data if data else None)
        if frame_data is not None:
            state = env_state_dict_fn(env, frame_data)
        if capture_per_step:
            per_step_states.append({
                "state": state.get("state", "NOT_FINISHED"),
                "levels_completed": state.get("levels_completed", 0),
            })
    if capture_per_step:
        return env, state, per_step_states
    return env, state


def _try_recover_session(session_id: str,
                          *, get_arcade_fn, env_state_dict_fn):
    """Try to recover a session from DB by replaying its actions.
    Returns (env, state) or (None, None)."""
    try:
        conn = _get_db()
        sess = conn.execute(
            "SELECT game_id FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if not sess:
            conn.close()
            return None, None
        rows = conn.execute(
            "SELECT action, row, col FROM session_actions WHERE session_id = ? ORDER BY step_num",
            (session_id,),
        ).fetchall()
        conn.close()

        if not rows:
            bare_id = sess["game_id"].split("-")[0]
            arc = get_arcade_fn()
            env = arc.make(bare_id)
            state = env_state_dict_fn(env)
            with session_lock:
                game_sessions[session_id] = env
                session_grids[session_id] = state.get("grid", [])
                session_snapshots[session_id] = []
                session_step_counts[session_id] = 0
            log.info(f"Recovered session {session_id} (0 actions)")
            return env, state

        actions = []
        for r in rows:
            act = {"action": r["action"]}
            if r["row"] is not None and r["col"] is not None:
                act["data"] = json.dumps({"x": r["col"], "y": r["row"]})
            else:
                act["data"] = None
            actions.append(act)

        env, state = _reconstruct_session(
            sess["game_id"], actions,
            get_arcade_fn=get_arcade_fn,
            env_state_dict_fn=env_state_dict_fn,
        )
        with session_lock:
            game_sessions[session_id] = env
            session_grids[session_id] = state.get("grid", [])
            session_snapshots[session_id] = []
            session_step_counts[session_id] = len(actions)
        log.info(f"Recovered session {session_id} ({len(actions)} actions replayed)")
        return env, state
    except Exception as e:
        log.warning(f"Session recovery failed for {session_id}: {e}")
        return None, None
```

### Import statements to add to `server.py`

```python
from session_manager import (
    game_sessions, session_grids, session_snapshots,
    session_api_mode, session_api_keys,
    session_lock, session_step_counts, session_last_llm,
    _reconstruct_session, _try_recover_session,
)
```

Update all call sites in server.py that call `_reconstruct_session` and `_try_recover_session` to pass `get_arcade_fn=get_arcade, env_state_dict_fn=env_state_dict`:

```bash
grep -n "_reconstruct_session\|_try_recover_session" server.py
```

There are approximately 5–6 call sites (resume_session, branch_session, _try_recover_session itself, step_game, reset_game, undo_step).

### Verification command

```bash
python -c "from session_manager import game_sessions, session_lock, _reconstruct_session, _try_recover_session; print('OK')"
python -c "import server; print('server imports OK')"
```

---

## 2e — DB Connection Context Manager in `db.py`

### Files affected
- `db.py` (modify)
- `server.py` (update call sites)
- `batch_runner.py` (update call sites)

### What to add to `db.py`

Add after the `_get_db()` function definition (~line 220 in db.py):

```python
from contextlib import contextmanager

@contextmanager
def _db():
    """Context manager for SQLite connections.

    Usage:
        with _db() as conn:
            conn.execute(...)
            # commit happens automatically on clean exit
            # connection closes on exit (clean or exception)

    WARNING: Do NOT use for transactions that need conditional commits
    (e.g. verify_magic_link which commits only if row found).
    Those functions keep manual open/commit/close.
    """
    conn = _get_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
```

### Every open/close pattern to replace

Below is every location where `conn = _get_db() ... conn.commit() ... conn.close()` appears, with before/after snippet. Functions marked **SKIP** have edge cases that make a simple context manager unsafe — see notes.

---

#### db.py — `_db_insert_session()`

**File:** `db.py`
**Approximate lines:** ~235–245

**Before:**
```python
conn = _get_db()
conn.execute(
    "INSERT OR IGNORE INTO sessions ...",
    (session_id, game_id, mode, time.time(), user_id),
)
conn.commit()
conn.close()
```

**After:**
```python
with _db() as conn:
    conn.execute(
        "INSERT OR IGNORE INTO sessions ...",
        (session_id, game_id, mode, time.time(), user_id),
    )
```

---

#### db.py — `_db_insert_action()`

**File:** `db.py`
**Approximate lines:** ~255–275

**Before:**
```python
conn = _get_db()
conn.execute("INSERT OR REPLACE INTO session_actions ...", (...))
conn.execute("UPDATE sessions SET steps = ? WHERE id = ?", (step_num, session_id))
conn.commit()
conn.close()
```

**After:**
```python
with _db() as conn:
    conn.execute("INSERT OR REPLACE INTO session_actions ...", (...))
    conn.execute("UPDATE sessions SET steps = ? WHERE id = ?", (step_num, session_id))
```

---

#### db.py — `_db_update_session()`

**File:** `db.py`
**Approximate lines:** ~280–290

**Before:**
```python
conn = _get_db()
sets = ", ".join(f"{k} = ?" for k in kwargs)
conn.execute(f"UPDATE sessions SET {sets} WHERE id = ?", (*kwargs.values(), session_id))
conn.commit()
conn.close()
```

**After:**
```python
with _db() as conn:
    sets = ", ".join(f"{k} = ?" for k in kwargs)
    conn.execute(f"UPDATE sessions SET {sets} WHERE id = ?", (*kwargs.values(), session_id))
```

---

#### db.py — `_log_llm_call()`

**File:** `db.py`
**Approximate lines:** ~310–330

**Before:**
```python
conn = _get_db()
cur = conn.execute("INSERT INTO llm_calls ...", (...))
call_id = cur.lastrowid
conn.commit()
conn.close()
return call_id
```

**After:**
```python
with _db() as conn:
    cur = conn.execute("INSERT INTO llm_calls ...", (...))
    call_id = cur.lastrowid
return call_id
```

Note: `lastrowid` is still accessible after the with-block exits because the cursor object (`cur`) persists. The `return` must be outside the `with` block.

---

#### db.py — `_get_session_calls()` — read-only, no commit

**File:** `db.py`
**Approximate lines:** ~335–345

**Before:**
```python
conn = _get_db()
rows = conn.execute("SELECT * FROM llm_calls ...", (session_id,)).fetchall()
conn.close()
return [dict(r) for r in rows]
```

**After:**
```python
with _db() as conn:
    rows = conn.execute("SELECT * FROM llm_calls ...", (session_id,)).fetchall()
return [dict(r) for r in rows]
```

The gratuitous `conn.commit()` on a read is harmless; the context manager always commits before close.

---

#### db.py — `_log_tool_execution()`

**File:** `db.py`
**Approximate lines:** ~360–380

**Before:**
```python
conn = _get_db()
cur = conn.execute("INSERT INTO tool_executions ...", (...))
exec_id = cur.lastrowid
conn.commit()
conn.close()
return exec_id
```

**After:**
```python
with _db() as conn:
    cur = conn.execute("INSERT INTO tool_executions ...", (...))
    exec_id = cur.lastrowid
return exec_id
```

---

#### db.py — `_get_session_tool_executions()` — read-only

**File:** `db.py`

**Before:**
```python
conn = _get_db()
rows = conn.execute("SELECT * FROM tool_executions ...", (session_id,)).fetchall()
conn.close()
return [dict(r) for r in rows]
```

**After:**
```python
with _db() as conn:
    rows = conn.execute("SELECT * FROM tool_executions ...", (session_id,)).fetchall()
return [dict(r) for r in rows]
```

---

#### db.py — `find_or_create_user()` — **SKIP (complex, two code paths)**

**File:** `db.py`
**Reason:** This function has two branches, each with their own commit/close. One branch does a SELECT + conditional UPDATE, the other does an INSERT. Both paths need error isolation. The existing manual pattern is clearer here. **Do not convert.**

**Keep as-is.** If desired later, split into `_find_user()` and `_create_user()` helpers, each wrapped with `_db()`.

---

#### db.py — `create_auth_token()`

**File:** `db.py`

**Before:**
```python
conn = _get_db()
conn.execute("INSERT INTO auth_tokens ...", (...))
conn.commit()
conn.close()
return token
```

**After:**
```python
with _db() as conn:
    conn.execute("INSERT INTO auth_tokens ...", (...))
return token
```

---

#### db.py — `verify_auth_token()`

**File:** `db.py`

**Before:**
```python
conn = _get_db()
row = conn.execute("SELECT u.id, ... WHERE t.token = ? AND t.expires_at > ?", ...).fetchone()
if row:
    conn.execute("UPDATE auth_tokens SET last_used_at = ? WHERE token = ?", (...))
    conn.commit()
conn.close()
return dict(row) if row else None
```

**After — SKIP for context manager.**

**Reason:** Commit is conditional on whether a row was found. A simple `with _db()` always commits. While a gratuitous commit on no-op is harmless, restructuring the conditional is tricky and reduces clarity. **Keep manual.**

---

#### db.py — `create_magic_link()`

**File:** `db.py`

**Before:**
```python
conn = _get_db()
conn.execute("INSERT INTO magic_links ...", (...))
conn.commit()
conn.close()
return code
```

**After:**
```python
with _db() as conn:
    conn.execute("INSERT INTO magic_links ...", (...))
return code
```

---

#### db.py — `verify_magic_link()` — **SKIP (conditional commit)**

**File:** `db.py`

**Reason:** Returns early with `conn.close()` if no row found (before any write). Only commits if a row was found and marked used. A naive context manager would commit the empty transaction either way (harmless), but the early-return pattern with `conn.close()` before the `with` block exits would need restructuring. **Keep manual for clarity.**

---

#### db.py — `delete_auth_token()`

**Before:**
```python
conn = _get_db()
conn.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
conn.commit()
conn.close()
```

**After:**
```python
with _db() as conn:
    conn.execute("DELETE FROM auth_tokens WHERE token = ?", (token,))
```

---

#### db.py — `claim_sessions()`

**Before:**
```python
conn = _get_db()
cur = conn.execute(f"UPDATE sessions SET user_id = ? WHERE id IN ({placeholders}) ...", ...)
count = cur.rowcount if hasattr(cur, 'rowcount') else 0
conn.commit()
conn.close()
return count
```

**After:**
```python
with _db() as conn:
    cur = conn.execute(f"UPDATE sessions SET user_id = ? WHERE id IN ({placeholders}) ...", ...)
    count = cur.rowcount if hasattr(cur, 'rowcount') else 0
return count
```

---

#### db.py — `get_user_sessions()` — read-only

**Before:**
```python
conn = _get_db()
rows = conn.execute("SELECT ... FROM sessions WHERE user_id = ? ...", (user_id,)).fetchall()
conn.close()
return [dict(r) for r in rows]
```

**After:**
```python
with _db() as conn:
    rows = conn.execute("SELECT ... FROM sessions WHERE user_id = ? ...", (user_id,)).fetchall()
return [dict(r) for r in rows]
```

---

#### db.py — `count_recent_magic_links()` — read-only

**Before:**
```python
conn = _get_db()
row = conn.execute("SELECT COUNT(*) as cnt FROM magic_links WHERE ...", (...)).fetchone()
conn.close()
return row["cnt"] if row else 0
```

**After:**
```python
with _db() as conn:
    row = conn.execute("SELECT COUNT(*) as cnt FROM magic_links WHERE ...", (...)).fetchone()
return row["cnt"] if row else 0
```

---

#### db.py — `_export_session_to_file()` — **SKIP (dual-connection function)**

**File:** `db.py`

**Reason:** Opens `conn` (main DB, read-only) and then opens a separate `out_conn` (per-session file DB, write). The `out_conn` is an entirely different SQLite file; it would need its own context manager. The main `conn` only reads — refactoring to `with _db() as conn` for the read portion is safe but the `out_conn` must remain manual or get its own `@contextmanager`. **Recommended:** convert the main DB read to `with _db() as conn`, keep `out_conn` manual.

---

#### server.py — `import_session()` endpoint

**File:** `server.py`
**Function:** `import_session()`
**Approximate lines:** the `conn = _get_db()` block inside the try clause of `import_session`

**Before:**
```python
conn = _get_db()
conn.execute("INSERT INTO sessions ...", (...))
...
for s in steps:
    conn.execute("INSERT OR REPLACE INTO session_actions ...", (...))
conn.execute("DELETE FROM llm_calls WHERE session_id = ?", ...)
...
for ev in timeline:
    conn.execute("INSERT OR IGNORE INTO llm_calls ...", (...))
conn.commit()
conn.close()
```

**After:**
```python
with _db() as conn:
    conn.execute("INSERT INTO sessions ...", (...))
    ...
    for s in steps:
        conn.execute("INSERT OR REPLACE INTO session_actions ...", (...))
    conn.execute("DELETE FROM llm_calls WHERE session_id = ?", ...)
    ...
    for ev in timeline:
        conn.execute("INSERT OR IGNORE INTO llm_calls ...", (...))
```

This is actually the cleanest conversion — the entire import is one atomic transaction.

---

#### server.py — `resume_session()` endpoint — **SKIP (read-only, complex flow)**

**File:** `server.py`
**Reason:** Opens conn for SELECT only; has early return paths. Safe to convert the read portion to `with _db() as conn`, but the try/except structure wrapping it returns JSON error responses on exception — restructuring would add noise. **Keep manual.**

---

#### server.py — `session_obs_events()` — read-only

**File:** `server.py`

**Before:**
```python
conn = _get_db()
calls = conn.execute(...).fetchall()
action_rows = conn.execute(...).fetchall()
conn.close()
```

**After:**
```python
with _db() as conn:
    calls = conn.execute(...).fetchall()
    action_rows = conn.execute(...).fetchall()
```

---

#### server.py — `list_sessions()` — read-only

**Before:**
```python
conn = _get_db()
rows = conn.execute(_sessions_query, _params).fetchall()
conn.close()
```

**After:**
```python
with _db() as conn:
    rows = conn.execute(_sessions_query, _params).fetchall()
```

---

#### server.py — `leaderboard()` — read-only

**Before:**
```python
conn = _get_db()
ai_rows = conn.execute(...).fetchall()
human_rows = conn.execute(...).fetchall()
conn.close()
```

**After:**
```python
with _db() as conn:
    ai_rows = conn.execute(...).fetchall()
    human_rows = conn.execute(...).fetchall()
```

---

#### server.py — `leaderboard_detail()` — read-only

Same pattern. Convert to `with _db() as conn`.

---

#### server.py — `branch_session()` — **SKIP (two separate conn usages)**

**File:** `server.py`
**Reason:** Opens `conn` to read parent session, closes it, does heavy computation (replay), then opens a new `conn` to INSERT the branched session. The two `conn` usages are intentionally separated. Convert each one individually:

**First conn (read):**
```python
with _db() as conn:
    sess = conn.execute("SELECT game_id FROM sessions WHERE id = ?", (parent_id,)).fetchone()
    ...
    action_rows = conn.execute("SELECT * FROM session_actions ...", (...)).fetchall()
```

**Second conn (write):**
```python
with _db() as conn:
    conn.execute("INSERT INTO sessions ...", (...))
```

---

#### server.py — `get_session()` — read-only

**Before:**
```python
conn = _get_db()
sess = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
if sess:
    action_rows = conn.execute(...).fetchall()
    conn.close()
    ...
else:
    conn.close()
```

**After:** The conditional close is awkward. With context manager:
```python
with _db() as conn:
    sess = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
    action_rows = []
    if sess:
        action_rows = conn.execute(...).fetchall()
```

---

#### server.py — `get_session_step()` — read-only

Simple conversion to `with _db() as conn`.

---

#### server.py — `vote_comment()` — write with conditional branches

**Before:** Multiple `conn.execute` calls, one `conn.commit()`, one `conn.close()`.

**After:** This is safe to convert — all paths either do writes or are no-ops, and unconditional commit is fine.

```python
with _db() as conn:
    existing = conn.execute(...).fetchone()
    old_vote = existing["vote"] if existing else 0
    if old_vote == vote:
        return jsonify({"ok": True})  # NOTE: exits before context manager closes cleanly
    ...
    conn.execute("UPDATE comments ...")
    ...
    row = conn.execute("SELECT upvotes, downvotes FROM comments WHERE id=?", ...).fetchone()
```

**Edge case:** The early `return jsonify({"ok": True})` inside the `with` block will still trigger `conn.commit()` and `conn.close()` via the context manager's `finally` clause — this is correct behavior.

---

#### server.py — `get_comments()` — read-only

Simple conversion to `with _db() as conn`.

---

#### server.py — `post_comment()` — write

**Before:**
```python
conn = _get_db()
cur = conn.execute("INSERT INTO comments ...", (...))
cid = cur.lastrowid
conn.commit()
row = conn.execute("SELECT * FROM comments WHERE id=?", (cid,)).fetchone()
conn.close()
```

**After:**
```python
with _db() as conn:
    cur = conn.execute("INSERT INTO comments ...", (...))
    cid = cur.lastrowid
    conn.commit()  # commit before re-reading so the new row is visible
    row = conn.execute("SELECT * FROM comments WHERE id=?", (cid,)).fetchone()
```

**Edge case:** The explicit `conn.commit()` mid-block before re-reading the inserted row. The context manager will commit again on exit (idempotent for SQLite in WAL mode). Alternatively, use `conn.execute("INSERT...RETURNING *")` on SQLite 3.35+.

---

#### server.py — `batch_status()` — read-only

Simple conversion to `with _db() as conn`.

---

#### server.py — `_try_recover_session()` — two `conn.close()` paths

**Before:**
```python
conn = _get_db()
sess = conn.execute(...).fetchone()
if not sess:
    conn.close()
    return None, None
rows = conn.execute(...).fetchall()
conn.close()
```

**After:** This is safe to convert — both early return and normal path close cleanly:
```python
with _db() as conn:
    sess = conn.execute(...).fetchone()
    if not sess:
        return None, None  # context manager closes conn in finally
    rows = conn.execute(...).fetchall()
```

---

### Summary: conversions by file

| File | Pattern count | Converted | Skipped (reason) |
|---|---|---|---|
| `db.py` | ~16 | ~12 | 4 (find_or_create_user, verify_auth_token, verify_magic_link, _export_session_to_file main conn) |
| `server.py` | ~10 | ~8 | 2 (resume_session, branch_session first conn) |

### Import to add to `db.py`

At top of `db.py`, add:
```python
from contextlib import contextmanager
```

### Import to add to `server.py` (and batch_runner.py)

`_db` is already in db.py; just add to the `from db import (...)` block in server.py:
```python
from db import (
    ...,
    _db,  # context manager
)
```

Do the same in `batch_runner.py`:
```bash
grep -n "_get_db\|conn = _get_db" batch_runner.py
```
Then convert those call sites using the same pattern.

### Verification command

```bash
python -c "from db import _db; print('context manager OK')"
python -c "
from db import _db
with _db() as conn:
    rows = conn.execute('SELECT 1 as test').fetchall()
    print('query OK:', rows[0]['test'])
"
python -c "import server; print('server imports OK')"
```

---

## Cross-Cutting Notes

### Circular import summary

| Module pair | Risk | Mitigation |
|---|---|---|
| `server.py` → `bot_protection.py` → `server.py` | HIGH | Lazy import of `get_mode` inside decorator bodies (not at module level) |
| `server.py` → `session_manager.py` → `server.py` | HIGH | `get_arcade` and `env_state_dict` passed as callable parameters |
| `server.py` → `prompt_builder.py` → `server.py` | HIGH | `_custom_system_prompt` and `_custom_hard_memory` passed as function parameters |
| `server.py` → `grid_analysis.py` | NONE | Pure stdlib, no back-references |
| `server.py` → `db.py` | NONE | Already extracted in Phase 1 |

### DB context manager edge cases

The following patterns **break** a simple `with _db() as conn: ... conn.commit()` idiom and should keep manual open/commit/close:

1. **`find_or_create_user()`** — two distinct code paths, each with their own commit. Split into sub-helpers or keep manual.
2. **`verify_auth_token()`** — conditional commit (only if row found). Gratuitous commit is harmless but misleading; keep manual.
3. **`verify_magic_link()`** — early return before any write; conditional commit after. Keep manual.
4. **`_export_session_to_file()`** — dual-connection function (main DB + per-session file DB). Main DB read can use `_db()`; `out_conn` must stay manual.
5. **`post_comment()`** — explicit mid-block `conn.commit()` before re-reading inserted row. Workable with context manager but requires inline `conn.commit()` plus context-manager commit on exit (idempotent in WAL mode). Document clearly.

### Execution order

Execute sub-steps in this order to minimize broken states:
1. **2a** (grid_analysis.py) — no circular risks, safest first
2. **2e** (db.py context manager) — DB layer is stable, affects all others
3. **2b** (prompt_builder.py) — depends on grid_analysis
4. **2c** (bot_protection.py) — depends on nothing new
5. **2d** (session_manager.py) — depends on db

Run the verification command for each sub-step before proceeding to the next.
