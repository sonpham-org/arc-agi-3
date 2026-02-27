"""ARC-AGI-3 Autonomous Agent — config-driven, memory-aware."""

import argparse
import json
import os
import re
import sys
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import httpx
import yaml
from dotenv import load_dotenv

import arc_agi
from arcengine import GameAction, GameState

load_dotenv(Path(__file__).parent / ".env")

ROOT = Path(__file__).parent

# Thread-safety locks for shared file writes
_memory_lock = threading.Lock()
_session_log_lock = threading.Lock()

# ── Palette & action labels ────────────────────────────────────────────────

COLOR_NAMES = {
    0: "White", 1: "LightGray", 2: "Gray", 3: "DarkGray",
    4: "VeryDarkGray", 5: "Black", 6: "Magenta", 7: "LightMagenta",
    8: "Red", 9: "Blue", 10: "LightBlue", 11: "Yellow",
    12: "Orange", 13: "Maroon", 14: "Green", 15: "Purple",
}

ACTION_NAMES = {
    0: "RESET", 1: "ACTION1", 2: "ACTION2", 3: "ACTION3",
    4: "ACTION4", 5: "ACTION5", 6: "ACTION6", 7: "ACTION7",
}

ARC_AGI3_DESCRIPTION = """\
ARC-AGI-3 is an interactive reasoning benchmark. Each game is a 64x64 pixel
grid with 16 colors (0-15).  There are NO instructions — you must discover the
rules and goals by experimenting.

Action mappings:
- ACTION1 = UP, ACTION2 = RIGHT, ACTION3 = DOWN, ACTION4 = LEFT (directional movement)
- ACTION5 = context-dependent (cycle, toggle, interact — varies by game)
- ACTION6 = CLICK at (x, y) — for selecting, placing, or interacting with specific cells
- ACTION7 = context-dependent (secondary interact, rotate, swap — varies by game)
- ACTION0 = RESET — restarts the current level. Use only as a last resort.

Key facts:
- States: NOT_FINISHED (playing), WIN (all levels done), GAME_OVER (failed).
- Large uniform regions = background/walls. Small shapes = player/items.
- Edge bars = health/energy/progress meters.
- You can lose by running out of lives, energy, or moves."""

SYSTEM_MSG = (
    "You are an expert puzzle-solving AI. Analyse game grids and output ONLY "
    "valid JSON — no markdown, no explanation outside JSON."
)

# ── Model registry ─────────────────────────────────────────────────────────

MODELS = {
    # Groq (free tier, OpenAI-compatible)
    "groq/llama-3.3-70b-versatile": {
        "provider": "groq",
        "api_model": "llama-3.3-70b-versatile",
        "env_key": "GROQ_API_KEY",
        "url": "https://api.groq.com/openai/v1/chat/completions",
    },
    "groq/gemma2-9b-it": {
        "provider": "groq",
        "api_model": "gemma2-9b-it",
        "env_key": "GROQ_API_KEY",
        "url": "https://api.groq.com/openai/v1/chat/completions",
    },
    "groq/mixtral-8x7b-32768": {
        "provider": "groq",
        "api_model": "mixtral-8x7b-32768",
        "env_key": "GROQ_API_KEY",
        "url": "https://api.groq.com/openai/v1/chat/completions",
    },
    # Mistral (free tier, OpenAI-compatible)
    "mistral/mistral-small-latest": {
        "provider": "mistral",
        "api_model": "mistral-small-latest",
        "env_key": "MISTRAL_API_KEY",
        "url": "https://api.mistral.ai/v1/chat/completions",
    },
    "mistral/open-mistral-nemo": {
        "provider": "mistral",
        "api_model": "open-mistral-nemo",
        "env_key": "MISTRAL_API_KEY",
        "url": "https://api.mistral.ai/v1/chat/completions",
    },
    # Gemini (google-genai SDK)
    "gemini-2.0-flash":      {"provider": "gemini", "api_model": "gemini-2.0-flash",      "env_key": "GEMINI_API_KEY"},
    "gemini-2.5-flash-lite": {"provider": "gemini", "api_model": "gemini-2.5-flash-lite",  "env_key": "GEMINI_API_KEY"},
    "gemini-2.5-flash":      {"provider": "gemini", "api_model": "gemini-2.5-flash",       "env_key": "GEMINI_API_KEY"},
    "gemini-2.5-pro":        {"provider": "gemini", "api_model": "gemini-2.5-pro",         "env_key": "GEMINI_API_KEY"},
    "gemini-3.1-pro":        {"provider": "gemini", "api_model": "gemini-3.1-pro-preview",  "env_key": "GEMINI_API_KEY"},
    # Anthropic (direct API via httpx)
    "claude-haiku-4-5":      {"provider": "anthropic", "api_model": "claude-haiku-4-5-20251001", "env_key": "ANTHROPIC_API_KEY"},
    "claude-sonnet-4-5":     {"provider": "anthropic", "api_model": "claude-sonnet-4-5",         "env_key": "ANTHROPIC_API_KEY"},
    "claude-sonnet-4-6":     {"provider": "anthropic", "api_model": "claude-sonnet-4-6",         "env_key": "ANTHROPIC_API_KEY"},
    # Cloudflare Workers AI (OpenAI-compatible)
    "cloudflare/llama-3.3-70b": {
        "provider": "cloudflare",
        "api_model": "@cf/meta/llama-3.3-70b-instruct-fp8-fast",
        "env_key": "CLOUDFLARE_API_KEY",
        "env_account": "CLOUDFLARE_ACCOUNT_ID",
    },
    # HuggingFace (OpenAI-compatible)
    "hf/meta-llama-3.3-70b": {
        "provider": "huggingface",
        "api_model": "meta-llama/Llama-3.3-70B-Instruct",
        "env_key": "HUGGINGFACE_API_KEY",
        "url": "https://router.huggingface.co/v1/chat/completions",
    },
    # Ollama (local)
    "ollama/llama3.3": {
        "provider": "ollama",
        "api_model": "llama3.3",
        "url": "http://localhost:11434/v1/chat/completions",
    },
    "ollama/llama3.1": {
        "provider": "ollama",
        "api_model": "llama3.1",
        "url": "http://localhost:11434/v1/chat/completions",
    },
}

DEFAULT_MODEL = "groq/llama-3.3-70b-versatile"

# ═══════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════

_DEFAULT_CONFIG = {
    "context": {
        "full_grid": True,
        "change_map": True,
        "color_histogram": False,
        "region_map": False,
        "history_length": 10,
        "memory_injection": True,
        "memory_injection_max_chars": 1500,
    },
    "reasoning": {
        "executor_model": DEFAULT_MODEL,
        "condenser_model": None,
        "reflector_model": None,
        "temperature": 0.3,
        "max_tokens": 2048,
        "reflection_max_tokens": 1024,
    },
    "memory": {
        "hard_memory_file": "memory/MEMORY.md",
        "session_log_file": "memory/sessions.json",
        "allow_inline_memory_writes": True,
        "reflect_after_game": True,
        "condense_every": 25,
        "condense_threshold": 50,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config(path: Path | None = None) -> dict:
    cfg = _DEFAULT_CONFIG
    resolved = path or (ROOT / "config.yaml")
    if resolved.exists():
        with open(resolved) as f:
            file_cfg = yaml.safe_load(f) or {}
        cfg = _deep_merge(cfg, file_cfg)
    return cfg


def effective_model(cfg: dict, role: str) -> str:
    """Return the model key for executor / condenser / reflector roles."""
    key = f"{role}_model"
    m = cfg["reasoning"].get(key)
    return m if m else cfg["reasoning"]["executor_model"]


# ═══════════════════════════════════════════════════════════════════════════
# HARD MEMORY
# ═══════════════════════════════════════════════════════════════════════════

def _memory_path(cfg: dict) -> Path:
    return ROOT / cfg["memory"]["hard_memory_file"]


def _sessions_path(cfg: dict) -> Path:
    return ROOT / cfg["memory"]["session_log_file"]


def load_hard_memory(cfg: dict) -> str:
    p = _memory_path(cfg)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return ""


def save_hard_memory(cfg: dict, content: str) -> None:
    p = _memory_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def append_memory_bullet(cfg: dict, game_id: str, bullet: str) -> None:
    """Append a bullet under the game's section in MEMORY.md (thread-safe)."""
    with _memory_lock:
        _append_memory_bullet_unsafe(cfg, game_id, bullet)


def _append_memory_bullet_unsafe(cfg: dict, game_id: str, bullet: str) -> None:
    content = load_hard_memory(cfg)
    bullet = bullet.strip().lstrip("-").strip()
    section_header = f"## {game_id}"
    if section_header in content:
        # Insert after the section header line
        lines = content.splitlines()
        new_lines = []
        inserted = False
        for line in lines:
            new_lines.append(line)
            if not inserted and line.strip() == section_header:
                new_lines.append(f"- {bullet}")
                inserted = True
        content = "\n".join(new_lines) + "\n"
    else:
        content = content.rstrip() + f"\n\n{section_header}\n\n- {bullet}\n"
    save_hard_memory(cfg, content)


def log_session(cfg: dict, record: dict) -> None:
    with _session_log_lock:
        p = _sessions_path(cfg)
        p.parent.mkdir(parents=True, exist_ok=True)
        sessions = []
        if p.exists():
            try:
                sessions = json.loads(p.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError):
                sessions = []
        sessions.append(record)
        p.write_text(json.dumps(sessions, indent=2), encoding="utf-8")


def relevant_memory_section(hard_memory: str, game_id: str, max_chars: int) -> str:
    """Return the General + Strategies sections + game-specific section."""
    if not hard_memory:
        return ""
    # Strip comment header lines
    lines = [l for l in hard_memory.splitlines() if not l.startswith("#")]
    text = "\n".join(lines).strip()

    # Extract general + strategies + game section
    sections_to_keep = ["## General", "## Strategies", f"## {game_id}"]
    result_parts = []
    current_section = None
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("## "):
            if current_section in sections_to_keep and current_lines:
                result_parts.append("\n".join(current_lines))
            current_section = line.strip()
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_section in sections_to_keep and current_lines:
        result_parts.append("\n".join(current_lines))

    combined = "\n\n".join(result_parts).strip()
    if len(combined) > max_chars:
        combined = combined[:max_chars] + "\n... (truncated)"
    return combined


# ═══════════════════════════════════════════════════════════════════════════
# GRID ANALYSIS
# ═══════════════════════════════════════════════════════════════════════════

def compress_row(row: list[int]) -> str:
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


def compute_change_map(prev_grid: list, curr_grid: list) -> str:
    if not prev_grid or not curr_grid:
        return ""
    h = min(len(prev_grid), len(curr_grid))
    w = min(len(prev_grid[0]), len(curr_grid[0])) if h > 0 else 0
    changed_cells, rows = 0, []
    for y in range(h):
        row_chars = []
        for x in range(w):
            if prev_grid[y][x] != curr_grid[y][x]:
                row_chars.append("X")
                changed_cells += 1
            else:
                row_chars.append(".")
        row_str = "".join(row_chars)
        if "X" in row_str:
            parts, cur, c = [], row_str[0], 1
            for ch in row_str[1:]:
                if ch == cur:
                    c += 1
                else:
                    parts.append(f"{cur}x{c}" if c > 3 else cur * c)
                    cur, c = ch, 1
            parts.append(f"{cur}x{c}" if c > 3 else cur * c)
            rows.append(f"Row {y}: {''.join(parts)}")
    if not rows:
        return ""
    return f"\n## CHANGE MAP ({changed_cells} cells changed since last action)\n" + "\n".join(rows)


def compute_color_histogram(grid: list) -> str:
    if not grid:
        return ""
    counts: dict[int, int] = {}
    for row in grid:
        for v in row:
            counts[v] = counts.get(v, 0) + 1
    lines = [
        f"  {v}={COLOR_NAMES.get(v, str(v))}: {cnt}"
        for v, cnt in sorted(counts.items())
    ]
    return "\n## COLOR HISTOGRAM\n" + "\n".join(lines)


def compute_region_map(grid: list) -> str:
    """BFS flood-fill connected components per color."""
    if not grid:
        return ""
    h, w = len(grid), len(grid[0])
    visited = [[False] * w for _ in range(h)]
    regions: dict[int, list[tuple[int, int, int]]] = {}  # color -> [(y, x, size)]

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
            bbox = f"rows {min(ys)}-{max(ys)}, cols {min(xs)}-{max(xs)}"
            entry = (min(ys), min(xs), len(cells), bbox)
            regions.setdefault(color, []).append(entry)

    lines = ["\n## REGION MAP (connected components)"]
    for color in sorted(regions):
        name = COLOR_NAMES.get(color, str(color))
        sorted_regions = sorted(regions[color], key=lambda r: -r[2])  # largest first
        top = sorted_regions[:5]  # show at most 5 regions per color
        for r in top:
            lines.append(f"  {color}={name}: {r[2]} cells at {r[3]}")
        if len(sorted_regions) > 5:
            lines.append(f"  {color}={name}: ... ({len(sorted_regions) - 5} more regions)")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════
# LLM API CALLS
# ═══════════════════════════════════════════════════════════════════════════

def _call_openai_compatible(url: str, api_key: str, model: str, messages: list,
                             temperature: float, max_tokens: int) -> str:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    resp = httpx.post(
        url,
        headers=headers,
        json={"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens},
        timeout=90.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _call_anthropic(model: str, messages: list, system: str,
                    temperature: float, max_tokens: int) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "system": system,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=90.0,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def _call_gemini(model_name: str, prompt: str, temperature: float, max_tokens: int) -> str:
    from google import genai
    api_key = os.environ.get("GEMINI_API_KEY", "")
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model_name,
        contents=f"{SYSTEM_MSG}\n\n{prompt}",
        config=genai.types.GenerateContentConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        ),
    )
    return response.text


def _call_cloudflare(model: str, messages: list, temperature: float, max_tokens: int) -> str:
    api_key = os.environ.get("CLOUDFLARE_API_KEY", "")
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID", "")
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/v1/chat/completions"
    return _call_openai_compatible(url, api_key, model, messages, temperature, max_tokens)


def call_model(model_key: str, prompt: str, cfg: dict, role: str = "executor") -> str:
    """Route to the right provider.  role affects temperature/max_tokens."""
    info = MODELS.get(model_key)
    if info is None:
        raise ValueError(f"Unknown model: {model_key}")

    r = cfg["reasoning"]
    temp = r["temperature"]
    max_tok = r["reflection_max_tokens"] if role != "executor" else r["max_tokens"]

    provider = info["provider"]
    api_model = info["api_model"]
    messages = [{"role": "system", "content": SYSTEM_MSG}, {"role": "user", "content": prompt}]

    if provider == "gemini":
        return _call_gemini(api_model, prompt, temp, max_tok)
    if provider == "anthropic":
        return _call_anthropic(api_model, [{"role": "user", "content": prompt}],
                                SYSTEM_MSG, temp, max_tok)
    if provider == "cloudflare":
        return _call_cloudflare(api_model, messages, temp, max_tok)
    if provider == "ollama":
        return _call_openai_compatible(info["url"], "", api_model, messages, temp, max_tok)

    # Groq / Mistral / HuggingFace (OpenAI-compatible)
    api_key = os.environ.get(info["env_key"], "")
    return _call_openai_compatible(info["url"], api_key, api_model, messages, temp, max_tok)


def call_model_with_retry(model_key: str, prompt: str, cfg: dict, role: str = "executor",
                           retries: int = 2) -> str | None:
    for attempt in range(retries + 1):
        try:
            return call_model(model_key, prompt, cfg, role)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                wait = 10 * (attempt + 1)
                print(f"  [Rate limited] waiting {wait}s...")
                time.sleep(wait)
            else:
                print(f"  [HTTP error {e.response.status_code}]: {e}")
                return None
        except Exception as e:
            print(f"  [LLM error]: {e}")
            return None
    return None


# ═══════════════════════════════════════════════════════════════════════════
# PROMPT BUILDING
# ═══════════════════════════════════════════════════════════════════════════

def build_context_block(
    grid: list,
    state_str: str,
    available_actions: list[int],
    levels_done: int,
    win_levels: int,
    game_id: str,
    history: list[dict],
    cfg: dict,
    prev_grid: list | None = None,
    hard_memory: str = "",
) -> str:
    ctx = cfg["context"]
    parts: list[str] = []

    # ── Game metadata ─────────────────────────────────────────────────────
    action_desc = ", ".join(f"{a}={ACTION_NAMES.get(a, f'ACTION{a}')}" for a in available_actions)
    parts.append(
        f"## CURRENT STATE\n"
        f"Game: {game_id} | State: {state_str} | "
        f"Levels: {levels_done}/{win_levels}\n"
        f"Available actions: {action_desc}"
    )

    # ── Hard memory injection ─────────────────────────────────────────────
    if ctx["memory_injection"] and hard_memory:
        mem_text = relevant_memory_section(
            hard_memory, game_id, ctx["memory_injection_max_chars"]
        )
        if mem_text:
            parts.append(f"## MEMORY (what you already know)\n{mem_text}")

    # ── History ───────────────────────────────────────────────────────────
    n = ctx["history_length"]
    if history and n > 0:
        recent = history[-n:]
        lines = []
        for h in recent:
            action_name = ACTION_NAMES.get(h["action"], f"ACTION{h['action']}")
            data_str = ""
            if h.get("data"):
                d = h["data"]
                if "x" in d and "y" in d:
                    data_str = f"@({d['x']},{d['y']})"
            lvl = h.get("levels", "?")
            obs_short = (h.get("observation", "") or "")[:80]
            lines.append(f"  Step {h['step']:3d}: {action_name}{data_str} -> levels={lvl}  | {obs_short}")
        # Include any condensed summaries at the front
        condensed = [h for h in history if h.get("is_summary")]
        summary_block = ""
        if condensed:
            summary_block = "\n  [Earlier summary]:\n" + "\n".join(
                f"    {s['summary']}" for s in condensed
            ) + "\n"
        parts.append(f"## HISTORY (last {n} of {len(history)} steps){summary_block}\n" + "\n".join(lines))

    # ── Change map ────────────────────────────────────────────────────────
    if ctx["change_map"] and prev_grid:
        change_text = compute_change_map(prev_grid, grid)
        if change_text:
            parts.append(change_text.strip())

    # ── Color histogram ───────────────────────────────────────────────────
    if ctx["color_histogram"]:
        parts.append(compute_color_histogram(grid).strip())

    # ── Region map ────────────────────────────────────────────────────────
    if ctx["region_map"]:
        parts.append(compute_region_map(grid).strip())

    # ── Full grid ─────────────────────────────────────────────────────────
    if ctx["full_grid"]:
        grid_text = "\n".join(f"Row {i}: {compress_row(r)}" for i, r in enumerate(grid))
        parts.append(f"## GRID (RLE, colors 0-15)\n{grid_text}")

    return "\n\n".join(parts)


def build_action_prompt(context_block: str) -> str:
    return f"""{ARC_AGI3_DESCRIPTION}

COLOR PALETTE: 0=White 1=LightGray 2=Gray 3=DarkGray 4=VeryDarkGray 5=Black
               6=Magenta 7=LightMagenta 8=Red 9=Blue 10=LightBlue 11=Yellow
               12=Orange 13=Maroon 14=Green 15=Purple

{context_block}

YOUR TASK
---------
1. Identify key objects (character, walls, targets, items).
2. Determine what must happen next to make progress.
3. Choose the best action.

Respond with EXACTLY this JSON (nothing else):
{{"observation": "<what you see>", "reasoning": "<your plan>", "action": <number>, "data": {{}}, "memory_update": null}}

Rules:
- "action" must be a plain integer (0-7).
- For ACTION6 set "data" to {{"x": <0-63>, "y": <0-63>}}.
- For all other actions set "data" to {{}}.
- "memory_update": if you discovered a NEW rule/fact worth remembering, write it as a short string (≤ 120 chars). Otherwise null."""


# ═══════════════════════════════════════════════════════════════════════════
# HISTORY CONDENSATION
# ═══════════════════════════════════════════════════════════════════════════

def condense_history(history: list[dict], cfg: dict) -> list[dict]:
    """Summarise all non-summary entries via LLM, replacing them with one summary entry."""
    raw_entries = [h for h in history if not h.get("is_summary")]
    if not raw_entries:
        return history

    model_key = effective_model(cfg, "condenser")
    lines = []
    for h in raw_entries:
        aname = ACTION_NAMES.get(h["action"], f"ACTION{h['action']}")
        obs = (h.get("observation", "") or "")[:60]
        lines.append(f"Step {h['step']}: {aname} -> levels={h.get('levels','?')}  | {obs}")

    prompt = (
        "You are summarising an ARC-AGI-3 game history for an AI agent.\n\n"
        "Raw history:\n" + "\n".join(lines) + "\n\n"
        "Write a compact tactical summary (≤ 8 bullet points, ≤ 120 chars each) "
        "capturing: what actions were tried, what each did, what level progress was made, "
        "and any rules/patterns discovered.\n"
        "Respond with ONLY a JSON object: {\"summary\": \"bullet1\\nbullet2\\n...\"}"
    )

    print(f"  [memory] condensing {len(raw_entries)} history entries...")
    raw = call_model_with_retry(model_key, prompt, cfg, role="condenser")
    summary_text = ""
    if raw:
        parsed = _parse_json(raw)
        if parsed:
            summary_text = parsed.get("summary", "")
    if not summary_text:
        summary_text = f"(condensed {len(raw_entries)} steps — summary unavailable)"

    summary_entry = {
        "is_summary": True,
        "step_range": f"{raw_entries[0]['step']}-{raw_entries[-1]['step']}",
        "summary": summary_text,
    }
    # Keep existing summary entries at the front, then the new one
    existing_summaries = [h for h in history if h.get("is_summary")]
    return existing_summaries + [summary_entry]


# ═══════════════════════════════════════════════════════════════════════════
# POST-GAME REFLECTION
# ═══════════════════════════════════════════════════════════════════════════

def reflect_and_update_memory(
    game_id: str,
    history: list[dict],
    result: str,
    steps_taken: int,
    levels_done: int,
    win_levels: int,
    cfg: dict,
) -> None:
    """Ask the reflector LLM to extract learnings and append them to MEMORY.md."""
    if not cfg["memory"]["reflect_after_game"]:
        return

    model_key = effective_model(cfg, "reflector")
    raw_entries = [h for h in history if not h.get("is_summary")]

    history_text = "\n".join(
        f"Step {h['step']}: {ACTION_NAMES.get(h['action'], str(h['action']))} -> "
        f"levels={h.get('levels','?')} | {(h.get('observation','') or '')[:80]}"
        for h in raw_entries[-40:]  # last 40 entries is enough for reflection
    )

    existing_memory = load_hard_memory(cfg)
    game_section_exists = f"## {game_id}" in existing_memory

    prompt = (
        f"You played ARC-AGI-3 game '{game_id}'.\n"
        f"Result: {result} | Steps: {steps_taken} | Levels: {levels_done}/{win_levels}\n\n"
        f"Game history (last 40 steps):\n{history_text}\n\n"
        f"Based on this run, extract 2-5 concise, NOVEL facts worth remembering for future runs.\n"
        f"Focus on: what each action does, how levels advance, obstacles, winning strategies.\n"
        f"{'Existing game-specific notes are already stored — only add NEW facts.' if game_section_exists else ''}\n\n"
        f"Respond with ONLY JSON: "
        f"{{\"learnings\": [\"fact1\", \"fact2\", ...]}}"
    )

    print(f"  [memory] running post-game reflection with {model_key}...")
    raw = call_model_with_retry(model_key, prompt, cfg, role="reflector")
    if not raw:
        return
    parsed = _parse_json(raw)
    if not parsed or "learnings" not in parsed:
        return

    for bullet in parsed["learnings"]:
        bullet = bullet.strip()
        if bullet:
            append_memory_bullet(cfg, game_id, bullet)
            print(f"  [memory] stored: {bullet[:80]}")


# ═══════════════════════════════════════════════════════════════════════════
# RESPONSE PARSING
# ═══════════════════════════════════════════════════════════════════════════

def _parse_json(content: str) -> dict | None:
    # Strip <think>...</think> blocks (some models emit these)
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    try:
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(content[start:end])
    except json.JSONDecodeError:
        pass
    return None


def _fallback_action(available: list[int]) -> int:
    import random
    candidates = [a for a in available if a != 0]
    return random.choice(candidates) if candidates else (available[0] if available else 1)


# ═══════════════════════════════════════════════════════════════════════════
# GAME LOOP
# ═══════════════════════════════════════════════════════════════════════════

def play_game(arcade, game_id: str, cfg: dict, max_steps: int = 200,
              session_id: str | None = None, step_callback=None) -> str:
    print(f"\n{'='*65}")
    print(f"  PLAYING: {game_id}")
    print(f"  Executor: {effective_model(cfg, 'executor')}")
    print(f"  Context: grid={cfg['context']['full_grid']} change={cfg['context']['change_map']} "
          f"hist={cfg['context']['history_length']} "
          f"hist_cmap={cfg['context']['color_histogram']} region={cfg['context']['region_map']}")
    print(f"  Memory:  inject={cfg['context']['memory_injection']} "
          f"condense_every={cfg['memory']['condense_every']} "
          f"reflect={cfg['memory']['reflect_after_game']}")
    print(f"{'='*65}\n")

    env = arcade.make(game_id)
    frame = env.observation_space
    if frame is None:
        print("  [ERROR] Could not start game.")
        return "ERROR"

    hard_memory = load_hard_memory(cfg)
    history: list[dict] = []
    prev_grid: list | None = None
    step_num = 0
    steps_since_condense = 0

    mcfg = cfg["memory"]
    condense_every = mcfg["condense_every"]
    condense_threshold = mcfg["condense_threshold"]

    while step_num < max_steps:
        grid = frame.frame[-1].tolist() if frame.frame else []
        state_str = frame.state.value if hasattr(frame.state, "value") else str(frame.state)
        available = frame.available_actions
        levels_done = frame.levels_completed
        win_levels = frame.win_levels

        # Terminal states
        if frame.state == GameState.WIN:
            print(f"\n  >>> WIN!  Completed {win_levels} levels in {step_num} steps <<<\n")
            _post_game(arcade, game_id, history, "WIN", step_num, levels_done, win_levels, cfg)
            return "WIN"
        if frame.state == GameState.GAME_OVER:
            print(f"\n  >>> GAME OVER at step {step_num}  (levels {levels_done}/{win_levels}) <<<\n")
            _post_game(arcade, game_id, history, "GAME_OVER", step_num, levels_done, win_levels, cfg)
            return "GAME_OVER"

        # ── Context condensation ────────────────────────────────────────
        raw_history_len = sum(1 for h in history if not h.get("is_summary"))
        should_condense = (
            condense_every > 0 and steps_since_condense >= condense_every
        ) or (
            condense_threshold > 0 and raw_history_len >= condense_threshold
        )
        if should_condense and raw_history_len > 0:
            history = condense_history(history, cfg)
            steps_since_condense = 0

        # ── Build prompt ────────────────────────────────────────────────
        context_block = build_context_block(
            grid, state_str, available, levels_done, win_levels,
            game_id, history, cfg, prev_grid, hard_memory,
        )
        prompt = build_action_prompt(context_block)

        # ── Call LLM ────────────────────────────────────────────────────
        t0 = time.time()
        model_key = effective_model(cfg, "executor")
        raw = call_model_with_retry(model_key, prompt, cfg, role="executor")
        elapsed = time.time() - t0

        parsed = _parse_json(raw) if raw else None
        if parsed is None:
            action_id = _fallback_action(available)
            action_data = {}
            observation = "parse error / LLM unavailable"
            reasoning = "fallback"
        else:
            action_id = parsed.get("action", 1)
            action_data = parsed.get("data") or {}
            observation = parsed.get("observation", "")
            reasoning = parsed.get("reasoning", "")
            memory_update = parsed.get("memory_update")

            # Inline memory write
            if (
                mcfg["allow_inline_memory_writes"]
                and memory_update
                and isinstance(memory_update, str)
                and memory_update.strip()
            ):
                append_memory_bullet(cfg, game_id, memory_update)
                hard_memory = load_hard_memory(cfg)  # reload
                print(f"  [memory inline] {memory_update[:80]}")

        # Validate action
        if action_id not in available:
            action_id = available[0] if available else 1

        # ── Execute ─────────────────────────────────────────────────────
        try:
            action = GameAction.from_id(int(action_id))
        except (ValueError, KeyError):
            action = GameAction.ACTION1

        step_num += 1
        steps_since_condense += 1
        aname = ACTION_NAMES.get(action_id, f"ACTION{action_id}")
        coord_str = f"@({action_data.get('x','?')},{action_data.get('y','?')})" if action_id == 6 and action_data else ""
        print(f"  Step {step_num:3d} | {aname}{coord_str:12s} | lvl {levels_done}/{win_levels} | {elapsed:.1f}s")
        if observation:
            print(f"           obs: {observation[:100]}")
        if reasoning:
            print(f"           why: {reasoning[:100]}")

        prev_grid = grid
        frame = env.step(action, data=action_data or None, reasoning=reasoning)
        if frame is None:
            print("  [ERROR] env.step returned None")
            break

        new_levels = frame.levels_completed if frame else levels_done
        new_grid = frame.frame[-1].tolist() if frame.frame else grid
        state_val = frame.state.value if frame and hasattr(frame.state, "value") else "?"
        history.append({
            "step": step_num,
            "action": action_id,
            "data": action_data,
            "state": state_val,
            "levels": new_levels,
            "observation": observation,
        })

        # Invoke step callback (used by batch_runner for DB persistence)
        if step_callback:
            llm_resp = {"observation": observation, "reasoning": reasoning,
                        "action": action_id, "data": action_data} if parsed else None
            try:
                step_callback(
                    session_id=session_id, step_num=step_num,
                    action=action_id, data=action_data,
                    grid=new_grid, llm_response=llm_resp,
                    state=state_val, levels=new_levels,
                )
            except Exception as cb_err:
                print(f"  [callback error] {cb_err}")

    # Timed out
    final_state = frame.state.value if frame and hasattr(frame.state, "value") else "TIMEOUT"
    print(f"\n  >>> Max steps reached ({max_steps}).  Final: {final_state} <<<\n")
    _post_game(arcade, game_id, history, final_state, step_num,
               frame.levels_completed if frame else 0,
               frame.win_levels if frame else 0, cfg)
    return final_state


def _post_game(arcade, game_id: str, history: list, result: str,
               steps: int, levels_done: int, win_levels: int, cfg: dict) -> None:
    # Session log
    log_session(cfg, {
        "timestamp": datetime.utcnow().isoformat(),
        "game_id": game_id,
        "result": result,
        "steps": steps,
        "levels_completed": levels_done,
        "win_levels": win_levels,
        "executor_model": effective_model(cfg, "executor"),
    })
    # Post-game reflection
    reflect_and_update_memory(game_id, history, result, steps, levels_done, win_levels, cfg)


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="ARC-AGI-3 Autonomous Agent (config-driven)")
    parser.add_argument("--game", default="all", help="Game ID or 'all'")
    parser.add_argument("--model", default=None, help="Override executor model")
    parser.add_argument("--max-steps", type=int, default=200)
    parser.add_argument("--config", default=None, help="Path to config.yaml")
    parser.add_argument("--list-models", action="store_true")
    parser.add_argument("--show-config", action="store_true", help="Print resolved config and exit")
    args = parser.parse_args()

    cfg = load_config(Path(args.config) if args.config else None)

    # CLI overrides
    if args.model:
        cfg["reasoning"]["executor_model"] = args.model

    if args.list_models:
        print("\nAvailable models:\n")
        for key, info in MODELS.items():
            env_key = info.get("env_key", "")
            status = "OK" if (not env_key or os.environ.get(env_key)) else "MISSING KEY"
            print(f"  {key:45s}  [{info['provider']:12s}]  {status}")
        print()
        return

    if args.show_config:
        print("\nResolved config:\n")
        print(yaml.dump(cfg, default_flow_style=False))
        return

    exec_model = cfg["reasoning"]["executor_model"]
    if exec_model not in MODELS:
        print(f"Unknown model: {exec_model}")
        sys.exit(1)

    info = MODELS[exec_model]
    if info.get("env_key") and not os.environ.get(info["env_key"]):
        print(f"ERROR: {info['env_key']} not set in .env")
        sys.exit(1)

    arcade = arc_agi.Arcade()
    available_games = [e.game_id for e in arcade.get_environments()]

    def resolve_id(query):
        if query in available_games:
            return query
        for gid in available_games:
            if gid.startswith(query):
                return gid
        return None

    games = available_games if args.game == "all" else []
    if args.game != "all":
        resolved = resolve_id(args.game)
        if not resolved:
            print(f"Unknown game: {args.game}  (available: {', '.join(available_games)})")
            sys.exit(1)
        games = [resolved]

    print(f"\n{'#'*65}")
    print(f"  ARC-AGI-3 Autonomous Agent")
    print(f"  Executor model : {exec_model}")
    print(f"  Games          : {', '.join(games)}")
    print(f"  Max steps/game : {args.max_steps}")
    print(f"  Config file    : {args.config or 'config.yaml (default)'}")
    print(f"{'#'*65}")

    results = {}
    for game_id in games:
        results[game_id] = play_game(arcade, game_id, cfg, args.max_steps)

    print(f"\n{'='*65}")
    print("  RESULTS")
    print(f"{'='*65}")
    for gid, res in results.items():
        print(f"  {gid:15s} -> {res}")
    print(f"\n  Scorecard: {arcade.get_scorecard()}\n")


if __name__ == "__main__":
    main()
