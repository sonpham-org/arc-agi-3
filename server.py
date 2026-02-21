"""ARC-AGI-3 Web Player + LLM Reasoning Server."""

import base64
import json
import logging
import os
import re
import sys
import threading
from collections import deque
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

import arc_agi
from arcengine import GameAction, GameState

load_dotenv(Path(__file__).parent / ".env")

app = Flask(__name__, template_folder="templates", static_folder="static")
app.logger.setLevel(logging.INFO)

# ── Global state ───────────────────────────────────────────────────────────

arcade_instance: Optional[arc_agi.Arcade] = None
game_sessions: dict[str, Any] = {}
session_grids: dict[str, list[list[int]]] = {}
session_lock = threading.Lock()

COLOR_MAP = {
    0: "#FFFFFF", 1: "#CCCCCC", 2: "#999999", 3: "#666666",
    4: "#333333", 5: "#000000", 6: "#E53AA3", 7: "#FF7BCC",
    8: "#F93C31", 9: "#1E93FF", 10: "#88D8F1", 11: "#FFDC00",
    12: "#FF851B", 13: "#921231", 14: "#4FCC30", 15: "#A356D6",
}

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
controls, rules, and goals by experimenting.

Key facts:
- Actions 1-5, 7 are simple (no parameters). ACTION6 needs x,y coordinates.
- ACTION0 is RESET — restarts the current level. Use sparingly.
- States: NOT_FINISHED (playing), WIN (all levels done), GAME_OVER (failed).
- Large uniform regions = background/walls. Small shapes = interactive objects.
- Edge bars = health/energy/progress indicators.
- ACTIONs 1-4 often map to directional movement. ACTION6 is usually a click."""

SYSTEM_MSG = (
    "You are an expert puzzle-solving AI agent. Analyse game grids and output "
    "ONLY valid JSON — no markdown, no explanation outside JSON."
)

# ═══════════════════════════════════════════════════════════════════════════
# MODEL REGISTRY — capabilities include image/reasoning/tools support
# ═══════════════════════════════════════════════════════════════════════════

MODEL_REGISTRY: dict[str, dict] = {
    # ── Gemini ────────────────────────────────────────────────────────────
    "gemini-2.5-flash": {
        "provider": "gemini", "api_model": "gemini-2.5-flash",
        "env_key": "GEMINI_API_KEY",
        "price": "$0.15/$0.60 per 1M tok",
        "capabilities": {"image": True, "reasoning": True, "tools": True},
    },
    "gemini-2.5-pro": {
        "provider": "gemini", "api_model": "gemini-2.5-pro",
        "env_key": "GEMINI_API_KEY",
        "price": "$1.25/$10 per 1M tok",
        "capabilities": {"image": True, "reasoning": True, "tools": True},
    },
    "gemini-2.0-flash": {
        "provider": "gemini", "api_model": "gemini-2.0-flash",
        "env_key": "GEMINI_API_KEY",
        "price": "$0.10/$0.40 per 1M tok",
        "capabilities": {"image": True, "reasoning": False, "tools": True},
    },
    "gemini-2.0-flash-lite": {
        "provider": "gemini", "api_model": "gemini-2.0-flash-lite",
        "env_key": "GEMINI_API_KEY",
        "price": "Free tier",
        "capabilities": {"image": True, "reasoning": False, "tools": False},
    },
    # ── Anthropic ─────────────────────────────────────────────────────────
    "claude-sonnet-4-6": {
        "provider": "anthropic", "api_model": "claude-sonnet-4-6",
        "env_key": "ANTHROPIC_API_KEY",
        "price": "$3/$15 per 1M tok",
        "capabilities": {"image": True, "reasoning": True, "tools": True},
    },
    "claude-sonnet-4-5": {
        "provider": "anthropic", "api_model": "claude-sonnet-4-5-20241022",
        "env_key": "ANTHROPIC_API_KEY",
        "price": "$3/$15 per 1M tok",
        "capabilities": {"image": True, "reasoning": True, "tools": True},
    },
    "claude-haiku-4-5": {
        "provider": "anthropic", "api_model": "claude-haiku-4-5-20251001",
        "env_key": "ANTHROPIC_API_KEY",
        "price": "$0.80/$4 per 1M tok",
        "capabilities": {"image": True, "reasoning": False, "tools": True},
    },
    # ── Groq (free tier) ──────────────────────────────────────────────────
    "groq/llama-3.3-70b-versatile": {
        "provider": "groq", "api_model": "llama-3.3-70b-versatile",
        "env_key": "GROQ_API_KEY",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "price": "Free tier",
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    "groq/gemma2-9b-it": {
        "provider": "groq", "api_model": "gemma2-9b-it",
        "env_key": "GROQ_API_KEY",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "price": "Free tier",
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    "groq/mixtral-8x7b-32768": {
        "provider": "groq", "api_model": "mixtral-8x7b-32768",
        "env_key": "GROQ_API_KEY",
        "url": "https://api.groq.com/openai/v1/chat/completions",
        "price": "Free tier",
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    # ── Mistral (free tier) ───────────────────────────────────────────────
    "mistral/mistral-small-latest": {
        "provider": "mistral", "api_model": "mistral-small-latest",
        "env_key": "MISTRAL_API_KEY",
        "url": "https://api.mistral.ai/v1/chat/completions",
        "price": "Free tier",
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    "mistral/open-mistral-nemo": {
        "provider": "mistral", "api_model": "open-mistral-nemo",
        "env_key": "MISTRAL_API_KEY",
        "url": "https://api.mistral.ai/v1/chat/completions",
        "price": "Free tier",
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
    # ── HuggingFace ───────────────────────────────────────────────────────
    "hf/meta-llama-3.3-70b": {
        "provider": "huggingface", "api_model": "meta-llama/Llama-3.3-70B-Instruct",
        "env_key": "HUGGINGFACE_API_KEY",
        "url": "https://api-inference.huggingface.co/v1/chat/completions",
        "price": "Free tier",
        "capabilities": {"image": False, "reasoning": False, "tools": False},
    },
}

# Ollama models discovered at runtime; all support text only by default.
OLLAMA_VRAM = {
    "qwen2.5:32b": "~19GB", "qwen2.5:14b": "~9GB", "qwen3-8b:latest": "~5GB",
    "deepseek-r1:latest": "~5GB", "mistral:7b": "~4.4GB",
    "llama3.1:latest": "~4.9GB", "llama3:latest": "~4.7GB",
    "llava:latest": "~5GB",
}

# Models that support vision via Ollama (llava family)
OLLAMA_VISION_MODELS = {"llava", "llava:latest", "llava:13b", "bakllava"}


# ═══════════════════════════════════════════════════════════════════════════
# GRID HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def get_arcade():
    global arcade_instance
    if arcade_instance is None:
        arcade_instance = arc_agi.Arcade()
    return arcade_instance


def frame_to_grid(frame) -> list[list[int]]:
    return frame.tolist()


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


def compute_change_map(prev_grid, curr_grid):
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


def _compress_change_row(row: str) -> str:
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


def compute_color_histogram(grid: list) -> str:
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


def env_state_dict(env, frame_data=None) -> dict:
    if frame_data is None:
        frame_data = env.observation_space
    if frame_data is None:
        return {"error": "No frame data available"}
    frames = frame_data.frame
    grid = frame_to_grid(frames[-1]) if frames else []
    available = frame_data.available_actions
    action_labels = {aid: ACTION_NAMES.get(aid, f"ACTION{aid}") for aid in available}
    return {
        "grid": grid,
        "state": frame_data.state.value if hasattr(frame_data.state, "value") else str(frame_data.state),
        "levels_completed": frame_data.levels_completed,
        "win_levels": frame_data.win_levels,
        "available_actions": available,
        "action_labels": action_labels,
        "game_id": frame_data.game_id,
    }


# ═══════════════════════════════════════════════════════════════════════════
# PROMPT BUILDING  (config-driven: input sources, tools mode)
# ═══════════════════════════════════════════════════════════════════════════

def _build_prompt(payload: dict, input_settings: dict, tools_mode: str) -> str:
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

    parts.append(f"""{ARC_AGI3_DESCRIPTION}

COLOR PALETTE: 0=White 1=LightGray 2=Gray 3=DarkGray 4=VeryDarkGray 5=Black
               6=Magenta 7=LightMagenta 8=Red 9=Blue 10=LightBlue 11=Yellow
               12=Orange 13=Maroon 14=Green 15=Purple""")

    # ── State header ──────────────────────────────────────────────────────
    action_desc = ", ".join(f"{a}={ACTION_NAMES.get(a, f'ACTION{a}')}" for a in available)
    parts.append(
        f"## STATE\nGame: {game_id} | State: {state} | "
        f"Levels: {levels_completed}/{win_levels}\n"
        f"Available actions: {action_desc}"
    )

    # ── History (always included) ─────────────────────────────────────────
    if history:
        recent = history[-10:]
        lines = []
        for h in recent:
            aname = ACTION_NAMES.get(h.get("action", 0), "?")
            lines.append(f"  Step {h.get('step', '?')}: {aname} -> {h.get('result_state', '?')}")
        parts.append("## HISTORY (last 10)\n" + "\n".join(lines))

    # ── Diff / change map ─────────────────────────────────────────────────
    if input_settings.get("diff") and change_map and change_map.get("change_count", 0) > 0:
        parts.append(
            f"## CHANGES ({change_map['change_count']} cells changed)\n"
            f"{change_map.get('change_map_text', '')}"
        )

    # ── Full grid ─────────────────────────────────────────────────────────
    if input_settings.get("full_grid", True):
        grid_text = "\n".join(f"Row {i}: {compress_row(r)}" for i, r in enumerate(grid))
        parts.append(f"## GRID (RLE, colors 0-15)\n{grid_text}")

    # ── Color histogram ───────────────────────────────────────────────────
    if input_settings.get("color_histogram") or tools_mode == "on":
        histo = compute_color_histogram(grid)
        if histo:
            parts.append(f"## COLOR HISTOGRAM\n{histo}")

    # ── Region map (only with tools=on, or if explicitly requested) ───────
    if tools_mode == "on":
        rmap = compute_region_map(grid)
        if rmap:
            parts.append(f"## REGION MAP\n{rmap}")

    # ── Image note ────────────────────────────────────────────────────────
    if input_settings.get("image"):
        parts.append(
            "## IMAGE\nA screenshot of the current grid is attached. "
            "Use it together with the numeric data above."
        )

    # ── Task block ────────────────────────────────────────────────────────
    tool_extra = ""
    if tools_mode == "on":
        tool_extra = (
            '\n- "analysis": analyse what you see — objects, patterns, spatial relationships, '
            "possible goals, and which areas of the grid are interactive."
        )

    parts.append(f"""## YOUR TASK
1. Identify key objects (character, walls, targets, items).
2. Determine what must happen next to progress.
3. Choose the best action.

Respond with EXACTLY this JSON (nothing else):
{{"observation": "<what you see>", "reasoning": "<your plan>", "action": <number>, "data": {{}}{', "analysis": "<detailed spatial analysis>"' if tools_mode == "on" else ''}}}

Rules:
- "action" must be a plain integer (0-7).
- ACTION6: set "data" to {{"x": <0-63>, "y": <0-63>}}.
- Other actions: set "data" to {{}}.{tool_extra}""")

    return "\n\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# LLM CALLS (with multimodal image support)
# ═══════════════════════════════════════════════════════════════════════════

def _parse_llm_response(content: str, model_name: str) -> dict:
    thinking = ""
    think_match = re.search(r"<think>(.*?)</think>", content, re.DOTALL)
    if think_match:
        thinking = think_match.group(1).strip()
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    try:
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(content[start:end])
            return {"raw": content, "thinking": thinking[:500] if thinking else None,
                    "parsed": parsed, "model": model_name}
    except json.JSONDecodeError:
        pass
    return {"raw": content, "parsed": None, "model": model_name}


def _call_gemini(model_name: str, prompt: str, image_b64: str | None = None) -> str:
    from google import genai
    api_key = os.environ.get("GEMINI_API_KEY", "")
    client = genai.Client(api_key=api_key)

    if image_b64:
        image_bytes = base64.b64decode(image_b64)
        contents = [
            genai.types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
            f"{SYSTEM_MSG}\n\n{prompt}",
        ]
    else:
        contents = f"{SYSTEM_MSG}\n\n{prompt}"

    response = client.models.generate_content(
        model=model_name, contents=contents,
        config=genai.types.GenerateContentConfig(temperature=0.3, max_output_tokens=2048),
    )
    return response.text


def _call_anthropic(model_name: str, prompt: str, image_b64: str | None = None) -> str:
    import httpx
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    content_blocks: list[dict] = []
    if image_b64:
        content_blocks.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": image_b64},
        })
    content_blocks.append({"type": "text", "text": prompt})

    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model_name, "system": SYSTEM_MSG,
            "messages": [{"role": "user", "content": content_blocks}],
            "temperature": 0.3, "max_tokens": 2048,
        },
        timeout=90.0,
    )
    resp.raise_for_status()
    return resp.json()["content"][0]["text"]


def _call_openai_compatible(url: str, api_key: str, model: str, prompt: str,
                             image_b64: str | None = None) -> str:
    import httpx
    if image_b64:
        user_content: list | str = [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
            {"type": "text", "text": prompt},
        ]
    else:
        user_content = prompt

    messages = [
        {"role": "system", "content": SYSTEM_MSG},
        {"role": "user", "content": user_content},
    ]
    resp = httpx.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages, "temperature": 0.3, "max_tokens": 2048},
        timeout=90.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _call_ollama(model_name: str, prompt: str, image_b64: str | None = None) -> str:
    import ollama
    messages = [
        {"role": "system", "content": SYSTEM_MSG},
        {"role": "user", "content": prompt},
    ]
    if image_b64 and model_name.split(":")[0] in OLLAMA_VISION_MODELS:
        messages[-1]["images"] = [image_b64]

    response = ollama.chat(
        model=model_name, messages=messages,
        options={"temperature": 0.3, "num_predict": 2048},
    )
    return response["message"]["content"]


def _route_model_call(model_key: str, prompt: str, image_b64: str | None = None) -> str:
    """Route to the correct provider, passing image if available."""
    info = MODEL_REGISTRY.get(model_key)

    # If not in registry, try ollama
    if info is None:
        return _call_ollama(model_key, prompt, image_b64)

    provider = info["provider"]
    api_model = info["api_model"]

    # Only pass image if model supports it
    img = image_b64 if info.get("capabilities", {}).get("image") else None

    if provider == "gemini":
        return _call_gemini(api_model, prompt, img)
    if provider == "anthropic":
        return _call_anthropic(api_model, prompt, img)
    if provider == "ollama":
        return _call_ollama(api_model, prompt, img)

    # OpenAI-compatible (Groq, Mistral, HuggingFace) — no image for these
    api_key = os.environ.get(info.get("env_key", ""), "")
    url = info.get("url", "")
    return _call_openai_compatible(url, api_key, api_model, prompt, None)


# ═══════════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html", color_map=COLOR_MAP)


@app.route("/api/games")
def list_games():
    arc = get_arcade()
    envs = arc.get_environments()
    return jsonify([
        {"game_id": e.game_id, "title": e.title, "default_fps": e.default_fps}
        for e in envs
    ])


@app.route("/api/start", methods=["POST"])
def start_game():
    data = request.get_json(force=True)
    game_id = data.get("game_id")
    if not game_id:
        return jsonify({"error": "game_id required"}), 400
    bare_id = game_id.split("-")[0]
    arc = get_arcade()
    try:
        env = arc.make(bare_id)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    session_id = env._guid if hasattr(env, "_guid") else str(id(env))
    state = env_state_dict(env)
    with session_lock:
        game_sessions[session_id] = env
        session_grids[session_id] = state.get("grid", [])
    state["session_id"] = session_id
    state["change_map"] = {"changes": [], "change_count": 0, "change_map_text": "(initial)"}
    return jsonify(state)


@app.route("/api/step", methods=["POST"])
def step_game():
    payload = request.get_json(force=True)
    session_id = payload.get("session_id")
    action_id = payload.get("action")
    action_data = payload.get("data", {})
    reasoning = payload.get("reasoning")
    if not session_id or action_id is None:
        return jsonify({"error": "session_id and action required"}), 400

    with session_lock:
        env = game_sessions.get(session_id)
    if env is None:
        return jsonify({"error": "Session not found"}), 404

    try:
        action = GameAction.from_id(int(action_id))
    except ValueError:
        return jsonify({"error": f"Invalid action: {action_id}"}), 400

    with session_lock:
        prev_grid = session_grids.get(session_id, [])

    frame_data = env.step(action, data=action_data or None, reasoning=reasoning)
    if frame_data is None:
        return jsonify({"error": "Step failed"}), 500

    state = env_state_dict(env, frame_data)
    state["session_id"] = session_id
    curr_grid = state.get("grid", [])
    state["change_map"] = compute_change_map(prev_grid, curr_grid)
    with session_lock:
        session_grids[session_id] = curr_grid
    return jsonify(state)


@app.route("/api/reset", methods=["POST"])
def reset_game():
    payload = request.get_json(force=True)
    session_id = payload.get("session_id")
    with session_lock:
        env = game_sessions.get(session_id)
    if env is None:
        return jsonify({"error": "Session not found"}), 404
    frame_data = env.reset()
    state = env_state_dict(env, frame_data)
    state["session_id"] = session_id
    state["change_map"] = {"changes": [], "change_count": 0, "change_map_text": "(reset)"}
    with session_lock:
        session_grids[session_id] = state.get("grid", [])
    return jsonify(state)


@app.route("/api/llm/models")
def llm_models():
    """Return all models with capabilities and availability."""
    models = []

    for key, info in MODEL_REGISTRY.items():
        env_key = info.get("env_key", "")
        available = bool(not env_key or os.environ.get(env_key))
        models.append({
            "name": key,
            "provider": info["provider"],
            "price": info.get("price", "?"),
            "capabilities": info.get("capabilities", {}),
            "available": available,
        })

    # Discover Ollama models
    try:
        import ollama
        ollama_list = ollama.list()
        ollama_names = [m.model for m in ollama_list.models] if hasattr(ollama_list, "models") else []
        for name in ollama_names:
            vram = OLLAMA_VRAM.get(name, "local")
            is_vision = name.split(":")[0] in OLLAMA_VISION_MODELS
            models.append({
                "name": name,
                "provider": "ollama",
                "price": f"Free ({vram})",
                "capabilities": {"image": is_vision, "reasoning": False, "tools": False},
                "available": True,
            })
    except Exception:
        pass

    return jsonify({"models": models})


@app.route("/api/llm/ask", methods=["POST"])
def llm_ask():
    """Ask LLM for next action.

    Body includes:
      - standard game state fields (grid, state, available_actions, etc.)
      - settings.input: {diff, full_grid, image, color_histogram}
      - settings.reasoning_mode: "on" | "off" | "adaptive"
      - settings.tools_mode: "on" | "off" | "adaptive"
      - settings.model: model key
      - image_b64: base64-encoded PNG screenshot (optional)
    """
    payload = request.get_json(force=True)
    settings = payload.get("settings", {})
    model_key = settings.get("model") or payload.get("model", "gemini-2.5-flash")

    input_settings = settings.get("input", {"diff": True, "full_grid": True})
    tools_mode = settings.get("tools_mode", "off")

    # Adaptive tools: enable extra analysis after 10+ steps with no level progress
    if tools_mode == "adaptive":
        history = payload.get("history", [])
        if len(history) >= 10:
            # Check if levels changed in last 10 steps
            recent_levels = [h.get("levels", 0) for h in history[-10:]]
            if len(set(recent_levels)) <= 1:
                tools_mode = "on"
            else:
                tools_mode = "off"
        else:
            tools_mode = "off"

    prompt = _build_prompt(payload, input_settings, tools_mode)

    # Get image if the input setting is on and data was provided
    image_b64 = None
    if input_settings.get("image"):
        image_b64 = payload.get("image_b64")

    try:
        content = _route_model_call(model_key, prompt, image_b64)
        result = _parse_llm_response(content, model_key)
        result["tools_active"] = tools_mode == "on"
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e), "model": model_key}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  ARC-AGI-3 Web Player: http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
