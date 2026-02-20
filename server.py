"""ARC-AGI-3 Web Player + Local LLM Reasoning Server."""

import json
import logging
import os
import re
import sys
import threading
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request

import arc_agi
from arcengine import GameAction, GameState

# Load .env from project root
load_dotenv(Path(__file__).parent / ".env")

app = Flask(__name__, template_folder="templates", static_folder="static")
app.logger.setLevel(logging.INFO)

# Global state: one Arcade instance, multiple game sessions
arcade_instance: Optional[arc_agi.Arcade] = None
game_sessions: dict[str, Any] = {}  # session_id -> env wrapper
session_lock = threading.Lock()

# Color palette matching ARC-AGI-3
COLOR_MAP = {
    0: "#FFFFFF", 1: "#CCCCCC", 2: "#999999", 3: "#666666",
    4: "#333333", 5: "#000000", 6: "#E53AA3", 7: "#FF7BCC",
    8: "#F93C31", 9: "#1E93FF", 10: "#88D8F1", 11: "#FFDC00",
    12: "#FF851B", 13: "#921231", 14: "#4FCC30", 15: "#A356D6",
}

ACTION_NAMES = {
    0: "RESET", 1: "ACTION1", 2: "ACTION2", 3: "ACTION3",
    4: "ACTION4", 5: "ACTION5", 6: "ACTION6", 7: "ACTION7",
}

# ── Generic ARC-AGI-3 description (no game-specific spoilers) ──

ARC_AGI3_DESCRIPTION = """## What is ARC-AGI-3?
ARC-AGI-3 is an interactive reasoning benchmark. Each game is a 64x64 pixel grid with 16 colors (0-15).
There are NO instructions provided. You must discover the controls, rules, and goals by experimenting.

### Key facts:
- Games are turn-based. Each turn you pick one action from the available actions list.
- Actions 1-5 and 7 are "simple" actions (no parameters). They might map to directions, toggles, etc.
- Action 6 is a "complex" action requiring x,y coordinates (0-63). It's typically a click/tap on the grid.
- Action 0 is RESET (restarts the current level — use sparingly).
- Games have multiple levels. Completing all levels = WIN.
- The game state is NOT_FINISHED (playing), WIN (all levels done), or GAME_OVER (failed).
- You can lose by running out of lives, energy, or moves depending on the game.

### How to discover the game:
1. OBSERVE the grid carefully. Look for distinct colored regions, patterns, small objects, borders, bars.
2. EXPERIMENT by trying different actions and observing what changes in the grid.
3. TRACK changes — compare the grid before and after each action to understand what each action does.
4. IDENTIFY your character/cursor (if any) — look for a small distinct shape that moves when you act.
5. IDENTIFY goals — look for target indicators, matching patterns, or areas you need to reach.
6. IDENTIFY obstacles — walls, barriers, energy bars, timers.
7. BUILD a mental model of the rules, then act strategically.

### Tips for grid analysis:
- Large uniform regions are likely background or walls.
- Small distinct colored shapes are likely interactive objects (player, items, buttons).
- Bars or gradients near edges may be health/energy/progress indicators.
- If only ACTION6 (click) is available, the game is click-based — try clicking on distinct objects.
- If ACTIONs 1-4 are available, they likely map to directional movement (up/down/left/right).
- Pay attention to what changes between turns to understand cause and effect."""


def get_arcade():
    global arcade_instance
    if arcade_instance is None:
        arcade_instance = arc_agi.Arcade()
    return arcade_instance


def frame_to_grid(frame) -> list[list[int]]:
    """Convert a numpy frame to a plain list of lists."""
    return frame.tolist()


def env_state_dict(env, frame_data=None) -> dict:
    """Build a JSON-serializable state dict from an environment."""
    if frame_data is None:
        frame_data = env.observation_space

    if frame_data is None:
        return {"error": "No frame data available"}

    # Get last frame only (for display)
    frames = frame_data.frame
    grid = frame_to_grid(frames[-1]) if frames else []

    available = frame_data.available_actions
    action_labels = {}
    for aid in available:
        action_labels[aid] = ACTION_NAMES.get(aid, f"ACTION{aid}")

    return {
        "grid": grid,
        "state": frame_data.state.value if hasattr(frame_data.state, 'value') else str(frame_data.state),
        "levels_completed": frame_data.levels_completed,
        "win_levels": frame_data.win_levels,
        "available_actions": available,
        "action_labels": action_labels,
        "game_id": frame_data.game_id,
    }


# ------- Routes -------

@app.route("/")
def index():
    return render_template("index.html", color_map=COLOR_MAP)


@app.route("/api/games")
def list_games():
    """List all available games."""
    arc = get_arcade()
    envs = arc.get_environments()
    games = []
    for e in envs:
        games.append({
            "game_id": e.game_id,
            "title": e.title,
            "default_fps": e.default_fps,
        })
    return jsonify(games)


@app.route("/api/start", methods=["POST"])
def start_game():
    """Start a new game session. Body: {"game_id": "ls20"}"""
    data = request.get_json(force=True)
    game_id = data.get("game_id")
    if not game_id:
        return jsonify({"error": "game_id required"}), 400

    # Strip version suffix for make() - it expects bare game_id like "ls20"
    bare_id = game_id.split("-")[0]

    arc = get_arcade()
    try:
        env = arc.make(bare_id)
    except Exception as e:
        return jsonify({"error": str(e)}), 400

    session_id = env._guid if hasattr(env, '_guid') else str(id(env))
    with session_lock:
        game_sessions[session_id] = env

    state = env_state_dict(env)
    state["session_id"] = session_id
    return jsonify(state)


@app.route("/api/step", methods=["POST"])
def step_game():
    """Take an action. Body: {"session_id": "...", "action": 1, "data": {}, "reasoning": {}}"""
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
        return jsonify({"error": f"Invalid action id: {action_id}"}), 400

    frame_data = env.step(action, data=action_data or None, reasoning=reasoning)
    if frame_data is None:
        return jsonify({"error": "Step failed"}), 500

    state = env_state_dict(env, frame_data)
    state["session_id"] = session_id
    return jsonify(state)


@app.route("/api/reset", methods=["POST"])
def reset_game():
    """Reset a game session. Body: {"session_id": "..."}"""
    payload = request.get_json(force=True)
    session_id = payload.get("session_id")

    with session_lock:
        env = game_sessions.get(session_id)

    if env is None:
        return jsonify({"error": "Session not found"}), 404

    frame_data = env.reset()
    state = env_state_dict(env, frame_data)
    state["session_id"] = session_id
    return jsonify(state)


# ── Model registry with pricing ──

GEMINI_MODELS = {
    "gemini-2.5-flash": {"price_in": 0.15, "price_out": 0.60, "provider": "gemini"},
    "gemini-2.5-pro": {"price_in": 1.25, "price_out": 10.00, "provider": "gemini"},
    "gemini-2.0-flash": {"price_in": 0.10, "price_out": 0.40, "provider": "gemini"},
    "gemini-2.0-flash-lite": {"price_in": 0.0, "price_out": 0.0, "provider": "gemini"},
}

GROQ_MODELS = {
    "groq/llama-3.3-70b-versatile": {"price_in": 0.0, "price_out": 0.0, "provider": "groq", "api_model": "llama-3.3-70b-versatile"},
    "groq/gemma2-9b-it": {"price_in": 0.0, "price_out": 0.0, "provider": "groq", "api_model": "gemma2-9b-it"},
    "groq/mixtral-8x7b-32768": {"price_in": 0.0, "price_out": 0.0, "provider": "groq", "api_model": "mixtral-8x7b-32768"},
}

MISTRAL_MODELS = {
    "mistral/mistral-small-latest": {"price_in": 0.0, "price_out": 0.0, "provider": "mistral", "api_model": "mistral-small-latest"},
    "mistral/open-mistral-nemo": {"price_in": 0.0, "price_out": 0.0, "provider": "mistral", "api_model": "open-mistral-nemo"},
}

# Ollama models are free (local), but we estimate VRAM usage
OLLAMA_PRICE_INFO = {
    "qwen2.5:32b": "~19GB VRAM",
    "qwen2.5:14b": "~9GB VRAM",
    "qwen3-8b:latest": "~5GB VRAM",
    "qwen3-8b-16k:latest": "~5GB VRAM",
    "deepseek-r1:latest": "~5GB VRAM",
    "mistral:7b": "~4.4GB VRAM",
    "llama3.1:latest": "~4.9GB VRAM",
    "llama3:latest": "~4.7GB VRAM",
    "tinyllama:1.1b": "~0.6GB VRAM",
}


def _build_prompt(payload):
    """Build the LLM prompt from the game state payload."""
    grid = payload.get("grid", [])
    state = payload.get("state", "")
    available = payload.get("available_actions", [])
    levels_completed = payload.get("levels_completed", 0)
    win_levels = payload.get("win_levels", 0)
    history = payload.get("history", [])

    def compress_row(row):
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

    grid_text = "\n".join(f"Row {i}: {compress_row(r)}" for i, r in enumerate(grid))
    action_desc = ", ".join(f"{aid}={ACTION_NAMES.get(aid, f'ACTION{aid}')}" for aid in available)

    history_text = ""
    if history:
        recent = history[-10:]
        history_text = "\nRecent moves:\n" + "\n".join(
            f"  Step {h['step']}: {ACTION_NAMES.get(h['action'], 'ACTION' + str(h['action']))} -> state={h['result_state']}"
            for h in recent
        )

    game_id_raw = payload.get('game_id', 'unknown')

    return f"""You are an expert AI agent playing an ARC-AGI-3 puzzle game.
Your goal is to advance as far as possible through the levels and ideally complete the game.

# ABOUT ARC-AGI-3
{ARC_AGI3_DESCRIPTION}

# COLOR PALETTE
0=White, 1=LightGray, 2=Gray, 3=DarkGray, 4=VeryDarkGray, 5=Black,
6=Magenta, 7=LightMagenta, 8=Red, 9=Blue, 10=LightBlue, 11=Yellow,
12=Orange, 13=Maroon, 14=Green, 15=Purple

# CURRENT GAME STATE
Game: {game_id_raw}
State: {state}
Levels completed: {levels_completed}/{win_levels}
Available actions: {action_desc}
{history_text}

# CURRENT GRID (run-length encoded rows, color indices 0-15)
{grid_text}

# YOUR TASK
Based on the game rules above and the current grid state:
1. Identify key objects on the grid (your character, walls, targets, interactive elements)
2. Determine what needs to happen next to make progress
3. Choose the best action

Respond ONLY with this JSON (no other text):
{{"observation": "what key objects you see and where", "reasoning": "your plan and why this specific action helps", "action": <action_id_number>, "data": {{}}}}

IMPORTANT: "action" must be a NUMBER (e.g. 1, 2, 3, 4 for directional, or 6 for click).
For ACTION6 include coordinates: "data": {{"x": <0-63>, "y": <0-63>}}
For other actions: "data": {{}}"""


SYSTEM_MSG = "You are an expert puzzle-solving AI agent. You analyze game grids and output ONLY valid JSON. No markdown, no explanation outside JSON. Always respond with a single JSON object."


def _parse_llm_response(content, model_name):
    """Parse LLM response, stripping thinking tags and extracting JSON."""
    thinking = ""
    think_match = re.search(r"<think>(.*?)</think>", content, re.DOTALL)
    if think_match:
        thinking = think_match.group(1).strip()
        content_clean = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    else:
        content_clean = content

    try:
        start = content_clean.find("{")
        end = content_clean.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(content_clean[start:end])
            return {
                "raw": content_clean,
                "thinking": thinking[:500] if thinking else None,
                "parsed": parsed,
                "model": model_name,
            }
    except json.JSONDecodeError:
        pass

    return {"raw": content, "parsed": None, "model": model_name}


def _call_ollama(model_name, prompt):
    """Call a local Ollama model."""
    import ollama
    response = ollama.chat(
        model=model_name,
        messages=[
            {"role": "system", "content": SYSTEM_MSG},
            {"role": "user", "content": prompt},
        ],
        options={"temperature": 0.3, "num_predict": 2048},
    )
    return response["message"]["content"]


def _call_openai_compatible(url, api_key, model, prompt):
    """Call an OpenAI-compatible chat completions endpoint (Groq, Mistral)."""
    import httpx
    resp = httpx.post(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_MSG},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 2048,
        },
        timeout=60.0,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _call_groq(model_name, prompt):
    """Call Groq API."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY not set in .env")
    info = GROQ_MODELS.get(model_name, {})
    api_model = info.get("api_model", model_name.replace("groq/", ""))
    return _call_openai_compatible("https://api.groq.com/openai/v1/chat/completions", api_key, api_model, prompt)


def _call_mistral(model_name, prompt):
    """Call Mistral API."""
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        raise ValueError("MISTRAL_API_KEY not set in .env")
    info = MISTRAL_MODELS.get(model_name, {})
    api_model = info.get("api_model", model_name.replace("mistral/", ""))
    return _call_openai_compatible("https://api.mistral.ai/v1/chat/completions", api_key, api_model, prompt)


def _call_gemini(model_name, prompt):
    """Call the Gemini API."""
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY not set in .env")

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model_name,
        contents=f"{SYSTEM_MSG}\n\n{prompt}",
        config=genai.types.GenerateContentConfig(
            temperature=0.3,
            max_output_tokens=2048,
        ),
    )
    return response.text


@app.route("/api/llm/ask", methods=["POST"])
def llm_ask():
    """Ask LLM for reasoning about next move.

    Body: {"grid": [...], "state": "...", "available_actions": [...],
           "levels_completed": 0, "win_levels": 5, "game_id": "...",
           "history": [...], "model": "gemini-2.5-flash"}
    """
    payload = request.get_json(force=True)
    model_name = payload.get("model", "qwen2.5:32b")

    prompt = _build_prompt(payload)

    try:
        # Route to the right provider
        if model_name in GROQ_MODELS or model_name.startswith("groq/"):
            content = _call_groq(model_name, prompt)
        elif model_name in MISTRAL_MODELS or model_name.startswith("mistral/"):
            content = _call_mistral(model_name, prompt)
        elif model_name in GEMINI_MODELS or model_name.startswith("gemini-"):
            content = _call_gemini(model_name, prompt)
        else:
            content = _call_ollama(model_name, prompt)

        return jsonify(_parse_llm_response(content, model_name))

    except Exception as e:
        return jsonify({"error": str(e), "model": model_name}), 500


@app.route("/api/llm/models")
def llm_models():
    """List available models from all providers with pricing."""
    models = []

    # Gemini models (if API key available)
    if os.environ.get("GEMINI_API_KEY"):
        for name, info in GEMINI_MODELS.items():
            price_label = f"${info['price_in']}/{info['price_out']} per 1M tok" if info['price_in'] > 0 else "Free tier"
            models.append({
                "name": name,
                "provider": "gemini",
                "price": price_label,
                "price_in": info["price_in"],
                "price_out": info["price_out"],
            })

    # Groq models (free tier)
    if os.environ.get("GROQ_API_KEY"):
        for name, info in GROQ_MODELS.items():
            models.append({
                "name": name,
                "provider": "groq",
                "price": "Free tier",
                "price_in": 0,
                "price_out": 0,
            })

    # Mistral models (free tier)
    if os.environ.get("MISTRAL_API_KEY"):
        for name, info in MISTRAL_MODELS.items():
            models.append({
                "name": name,
                "provider": "mistral",
                "price": "Free tier",
                "price_in": 0,
                "price_out": 0,
            })

    # Ollama models (local, free)
    try:
        import ollama
        ollama_list = ollama.list()
        ollama_names = [m.model for m in ollama_list.models] if hasattr(ollama_list, 'models') else []
        for name in ollama_names:
            vram = OLLAMA_PRICE_INFO.get(name, "local")
            models.append({
                "name": name,
                "provider": "ollama",
                "price": f"Free ({vram})",
                "price_in": 0,
                "price_out": 0,
            })
    except Exception:
        pass

    return jsonify({"models": models})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n  ARC-AGI-3 Web Player: http://localhost:{port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
