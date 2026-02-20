"""ARC-AGI-3 Autonomous Agent — plays games using free LLM APIs."""

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

import arc_agi
from arcengine import GameAction, GameState

load_dotenv(Path(__file__).parent / ".env")

# ── Color & action labels ──

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

SYSTEM_MSG = "You are an expert puzzle-solving AI agent. You analyze game grids and output ONLY valid JSON. No markdown, no explanation outside JSON. Always respond with a single JSON object."

# ── Available models by provider ──

MODELS = {
    # Groq (OpenAI-compatible, free tier)
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
    # Mistral (OpenAI-compatible, free tier)
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
    # Gemini (via google-genai SDK, free tier)
    "gemini-2.0-flash-lite": {
        "provider": "gemini",
        "api_model": "gemini-2.0-flash-lite",
        "env_key": "GEMINI_API_KEY",
    },
    "gemini-2.0-flash": {
        "provider": "gemini",
        "api_model": "gemini-2.0-flash",
        "env_key": "GEMINI_API_KEY",
    },
    "gemini-2.5-flash": {
        "provider": "gemini",
        "api_model": "gemini-2.5-flash",
        "env_key": "GEMINI_API_KEY",
    },
}

DEFAULT_MODEL = "groq/llama-3.3-70b-versatile"


# ── Prompt building ──

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


def build_prompt(grid, state, available_actions, levels_completed, win_levels, game_id, history):
    grid_text = "\n".join(f"Row {i}: {compress_row(r)}" for i, r in enumerate(grid))
    action_desc = ", ".join(f"{aid}={ACTION_NAMES.get(aid, f'ACTION{aid}')}" for aid in available_actions)

    history_text = ""
    if history:
        recent = history[-10:]
        history_text = "\nRecent moves:\n" + "\n".join(
            f"  Step {h['step']}: {ACTION_NAMES.get(h['action'], 'ACTION' + str(h['action']))} -> state={h['state']}"
            for h in recent
        )

    return f"""You are an expert AI agent playing an ARC-AGI-3 puzzle game.
Your goal is to advance as far as possible through the levels and ideally complete the game.

# ABOUT ARC-AGI-3
{ARC_AGI3_DESCRIPTION}

# COLOR PALETTE
0=White, 1=LightGray, 2=Gray, 3=DarkGray, 4=VeryDarkGray, 5=Black,
6=Magenta, 7=LightMagenta, 8=Red, 9=Blue, 10=LightBlue, 11=Yellow,
12=Orange, 13=Maroon, 14=Green, 15=Purple

# CURRENT GAME STATE
Game: {game_id}
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


def parse_llm_response(content):
    """Parse LLM response, stripping thinking tags and extracting JSON."""
    think_match = re.search(r"<think>(.*?)</think>", content, re.DOTALL)
    if think_match:
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

    try:
        start = content.find("{")
        end = content.rfind("}") + 1
        if start >= 0 and end > start:
            return json.loads(content[start:end])
    except json.JSONDecodeError:
        pass
    return None


# ── LLM API calls ──

def call_openai_compatible(url, api_key, model, prompt):
    """Call an OpenAI-compatible chat completions endpoint (Groq, Mistral)."""
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


def call_gemini(model_name, prompt):
    """Call the Gemini API via google-genai SDK."""
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


def call_model(model_key, prompt):
    """Route to the correct provider and call the model."""
    info = MODELS[model_key]
    provider = info["provider"]
    api_model = info["api_model"]

    if provider == "gemini":
        return call_gemini(api_model, prompt)

    # Groq or Mistral — OpenAI-compatible
    api_key = os.environ.get(info["env_key"])
    if not api_key:
        raise ValueError(f"{info['env_key']} not set in .env")
    return call_openai_compatible(info["url"], api_key, api_model, prompt)


# ── Game playing loop ──

def play_game(arcade, game_id, model_key, max_steps=200):
    """Play a single game autonomously and return the final state."""
    print(f"\n{'='*60}")
    print(f"  PLAYING: {game_id}  |  MODEL: {model_key}")
    print(f"{'='*60}\n")

    env = arcade.make(game_id)
    frame = env.observation_space
    if frame is None:
        print("  [ERROR] Could not start game.")
        return "ERROR"

    history = []
    step_num = 0

    while step_num < max_steps:
        grid = frame.frame[-1].tolist() if frame.frame else []
        state_str = frame.state.value if hasattr(frame.state, 'value') else str(frame.state)
        available = frame.available_actions
        levels_done = frame.levels_completed
        win_levels = frame.win_levels

        # Check terminal states
        if frame.state == GameState.WIN:
            print(f"\n  >>> WIN! Completed all {win_levels} levels in {step_num} steps <<<\n")
            return "WIN"
        if frame.state == GameState.GAME_OVER:
            print(f"\n  >>> GAME OVER at step {step_num} (levels: {levels_done}/{win_levels}) <<<\n")
            return "GAME_OVER"

        # Build prompt and ask LLM
        prompt = build_prompt(grid, state_str, available, levels_done, win_levels, game_id, history)

        try:
            t0 = time.time()
            raw = call_model(model_key, prompt)
            elapsed = time.time() - t0
            parsed = parse_llm_response(raw)
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                print(f"  [Step {step_num+1}] Rate limited — waiting 10s...")
                time.sleep(10)
                try:
                    t0 = time.time()
                    raw = call_model(model_key, prompt)
                    elapsed = time.time() - t0
                    parsed = parse_llm_response(raw)
                except Exception as e2:
                    print(f"  [Step {step_num+1}] LLM error after retry: {e2}")
                    import random
                    fallback = random.choice([a for a in available if a != 0]) if len(available) > 1 else available[0]
                    parsed = {"action": fallback, "data": {}, "observation": "LLM error", "reasoning": "fallback"}
                    elapsed = 0
            else:
                print(f"  [Step {step_num+1}] LLM error: {e}")
                import random
                fallback = random.choice([a for a in available if a != 0]) if len(available) > 1 else available[0]
                parsed = {"action": fallback, "data": {}, "observation": "LLM error", "reasoning": "fallback"}
                elapsed = 0
        except Exception as e:
            print(f"  [Step {step_num+1}] LLM error: {e}")
            import random
            fallback = random.choice([a for a in available if a != 0]) if len(available) > 1 else available[0]
            parsed = {"action": fallback, "data": {}, "observation": "LLM error", "reasoning": "fallback"}
            elapsed = 0

        if parsed is None:
            print(f"  [Step {step_num+1}] Could not parse LLM response, skipping")
            import random
            fallback = random.choice([a for a in available if a != 0]) if len(available) > 1 else available[0]
            parsed = {"action": fallback, "data": {}, "observation": "parse error", "reasoning": "fallback"}

        action_id = parsed.get("action", 1)
        action_data = parsed.get("data", {})
        observation = parsed.get("observation", "")
        reasoning = parsed.get("reasoning", "")

        # Validate action
        if action_id not in available:
            action_id = available[0] if available else 1

        # Execute
        try:
            action = GameAction.from_id(int(action_id))
        except ValueError:
            action = GameAction.ACTION1

        step_num += 1
        action_name = ACTION_NAMES.get(action_id, f"ACTION{action_id}")
        data_str = f" @ ({action_data.get('x','?')},{action_data.get('y','?')})" if action_id == 6 and action_data else ""

        print(f"  Step {step_num:3d} | {action_name}{data_str} | levels: {levels_done}/{win_levels} | {elapsed:.1f}s")
        if observation:
            print(f"           | obs: {observation[:100]}")
        if reasoning:
            print(f"           | why: {reasoning[:100]}")

        frame = env.step(action, data=action_data or None, reasoning=reasoning)
        if frame is None:
            print("  [ERROR] Step returned None")
            break

        history.append({
            "step": step_num,
            "action": action_id,
            "state": frame.state.value if hasattr(frame.state, 'value') else str(frame.state),
        })

    # Timed out
    final_state = frame.state.value if hasattr(frame.state, 'value') else str(frame.state)
    print(f"\n  >>> Reached max steps ({max_steps}). Final state: {final_state} <<<\n")
    return final_state


def main():
    parser = argparse.ArgumentParser(description="ARC-AGI-3 Autonomous Agent")
    parser.add_argument("--game", default="all", help="Game ID to play (ls20, ft09, vc33, or 'all')")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Model to use. Options: {', '.join(MODELS.keys())}")
    parser.add_argument("--max-steps", type=int, default=200, help="Max steps per game (default: 200)")
    parser.add_argument("--list-models", action="store_true", help="List available models and exit")
    args = parser.parse_args()

    if args.list_models:
        print("\nAvailable models:\n")
        for key, info in MODELS.items():
            env_key = info["env_key"]
            has_key = "OK" if os.environ.get(env_key) else "MISSING"
            print(f"  {key:40s}  [{info['provider']:8s}]  {env_key}: {has_key}")
        print()
        return

    if args.model not in MODELS:
        print(f"Unknown model: {args.model}")
        print(f"Available: {', '.join(MODELS.keys())}")
        sys.exit(1)

    # Check API key
    info = MODELS[args.model]
    if not os.environ.get(info["env_key"]):
        print(f"ERROR: {info['env_key']} not set in .env")
        sys.exit(1)

    arcade = arc_agi.Arcade()
    envs = arcade.get_environments()
    available_games = [e.game_id for e in envs]

    def resolve_game_id(query):
        """Match a bare game ID like 'ls20' to the full ID like 'ls20-cb3b57cc'."""
        if query in available_games:
            return query
        for gid in available_games:
            if gid.startswith(query):
                return gid
        return None

    if args.game == "all":
        games_to_play = available_games
    else:
        resolved = resolve_game_id(args.game)
        if resolved is None:
            print(f"Unknown game: {args.game}")
            print(f"Available: {', '.join(available_games)}")
            sys.exit(1)
        games_to_play = [resolved]

    print(f"\n{'#'*60}")
    print(f"  ARC-AGI-3 Autonomous Agent")
    print(f"  Model: {args.model}")
    print(f"  Games: {', '.join(games_to_play)}")
    print(f"  Max steps/game: {args.max_steps}")
    print(f"{'#'*60}")

    results = {}
    for game_id in games_to_play:
        result = play_game(arcade, game_id, args.model, args.max_steps)
        results[game_id] = result

    # Summary
    print(f"\n{'='*60}")
    print("  RESULTS SUMMARY")
    print(f"{'='*60}")
    for gid, res in results.items():
        print(f"  {gid:10s} -> {res}")

    print(f"\n  Scorecard:")
    print(f"  {arcade.get_scorecard()}")
    print()


if __name__ == "__main__":
    main()
