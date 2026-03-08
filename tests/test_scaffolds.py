"""Test all game scaffolds end-to-end with a real LLM (Groq or Gemini).

Runs each game for a few steps to verify:
  1. Game initialises without errors (arcade.make works)
  2. Observation space returns valid grid + available actions
  3. LLM receives the prompt and returns parseable JSON
  4. env.step() executes the action without crashing
  5. State transitions work (grid updates, levels track, terminal states)

Usage:
    python test_scaffolds.py                          # test all games, auto-pick provider
    python test_scaffolds.py --model gemini-2.5-flash  # use specific model
    python test_scaffolds.py --games fd01,pt01         # test specific games
    python test_scaffolds.py --steps 3                 # steps per game (default: 5)
    python test_scaffolds.py --dry-run                 # no LLM calls, just random actions
"""

import argparse
import json
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

import arc_agi
from arcengine import GameAction, GameState

from agent import (
    MODELS, call_model_with_retry, load_config, _parse_json,
    build_context_block, build_action_prompt, ACTION_NAMES, _fallback_action,
)

# ── Defaults ──────────────────────────────────────────────────────────────

PREFERRED_MODELS = [
    "groq/llama-3.3-70b-versatile",   # free
    "gemini-2.5-flash",                # ~free
    "mistral/mistral-small-latest",    # free
]

def pick_model() -> str | None:
    """Auto-select the first available cheap model."""
    for model_key in PREFERRED_MODELS:
        info = MODELS.get(model_key)
        if not info:
            continue
        env_key = info.get("env_key", "")
        if not env_key or os.environ.get(env_key):
            return model_key
    return None


# ── Single-game test ──────────────────────────────────────────────────────

def test_game(arcade, game_id: str, model_key: str | None, cfg: dict,
              max_steps: int = 5, dry_run: bool = False) -> dict:
    """Run a single game for a few steps. Returns result dict."""
    result = {
        "game_id": game_id,
        "status": "UNKNOWN",
        "steps_taken": 0,
        "errors": [],
        "warnings": [],
        "final_state": None,
        "levels": None,
        "elapsed": 0.0,
    }
    t0 = time.time()

    # 1. Initialise game
    try:
        env = arcade.make(game_id)
    except Exception as e:
        result["status"] = "FAIL"
        result["errors"].append(f"arcade.make failed: {e}")
        result["elapsed"] = round(time.time() - t0, 2)
        return result

    # 2. Get initial observation
    try:
        frame = env.observation_space
        if frame is None:
            result["status"] = "FAIL"
            result["errors"].append("observation_space is None")
            result["elapsed"] = round(time.time() - t0, 2)
            return result
    except Exception as e:
        result["status"] = "FAIL"
        result["errors"].append(f"observation_space error: {e}")
        result["elapsed"] = round(time.time() - t0, 2)
        return result

    # Validate initial frame
    try:
        grid = frame.frame[-1].tolist() if frame.frame else []
        if not grid:
            result["warnings"].append("Initial grid is empty")
        available = frame.available_actions
        if not available:
            result["errors"].append("No available actions at start")
            result["status"] = "FAIL"
            result["elapsed"] = round(time.time() - t0, 2)
            return result
        state = frame.state
        levels = frame.levels_completed
        win_levels = frame.win_levels
    except Exception as e:
        result["status"] = "FAIL"
        result["errors"].append(f"Frame field access error: {e}")
        result["elapsed"] = round(time.time() - t0, 2)
        return result

    # 3. Step loop
    prev_grid = None
    history = []
    llm_ok_count = 0
    parse_fail_count = 0

    for step_num in range(1, max_steps + 1):
        grid = frame.frame[-1].tolist() if frame.frame else []
        state_str = frame.state.value if hasattr(frame.state, "value") else str(frame.state)
        available = frame.available_actions
        levels_done = frame.levels_completed
        win_levels = frame.win_levels

        # Check terminal
        if frame.state == GameState.WIN:
            result["final_state"] = "WIN"
            result["steps_taken"] = step_num - 1
            break
        if frame.state == GameState.GAME_OVER:
            result["final_state"] = "GAME_OVER"
            result["steps_taken"] = step_num - 1
            break

        # Pick action
        action_id = None
        action_data = {}

        if dry_run or model_key is None:
            # Random action, no LLM
            action_id = _fallback_action(available)
        else:
            # Build prompt and call LLM
            try:
                context_block = build_context_block(
                    grid, state_str, available, levels_done, win_levels,
                    game_id, history, cfg, prev_grid, "",
                )
                prompt = build_action_prompt(context_block)

                raw = call_model_with_retry(model_key, prompt, cfg, role="executor")
                parsed = _parse_json(raw) if raw else None

                if parsed is None:
                    parse_fail_count += 1
                    action_id = _fallback_action(available)
                    if raw:
                        result["warnings"].append(
                            f"Step {step_num}: LLM returned unparseable response: {raw[:120]}"
                        )
                else:
                    llm_ok_count += 1
                    action_id = parsed.get("action", 1)
                    action_data = parsed.get("data") or {}
            except Exception as e:
                result["warnings"].append(f"Step {step_num}: LLM call error: {e}")
                action_id = _fallback_action(available)

        # Validate action
        if action_id not in available:
            action_id = available[0] if available else 1

        # Execute step
        try:
            action = GameAction.from_id(int(action_id))
        except (ValueError, KeyError):
            action = GameAction.ACTION1
            action_id = 1

        try:
            prev_grid = grid
            frame = env.step(action, data=action_data or None)
            if frame is None:
                result["errors"].append(f"Step {step_num}: env.step returned None")
                result["steps_taken"] = step_num
                result["status"] = "FAIL"
                result["elapsed"] = round(time.time() - t0, 2)
                return result
        except Exception as e:
            result["errors"].append(f"Step {step_num}: env.step crashed: {e}")
            result["steps_taken"] = step_num
            result["status"] = "FAIL"
            result["elapsed"] = round(time.time() - t0, 2)
            return result

        # Record history for context building
        new_state = frame.state.value if hasattr(frame.state, "value") else "?"
        history.append({
            "step": step_num,
            "action": action_id,
            "data": action_data,
            "state": new_state,
            "levels": frame.levels_completed,
            "observation": "",
        })

        result["steps_taken"] = step_num

    # Final state
    if result["final_state"] is None:
        result["final_state"] = frame.state.value if hasattr(frame.state, "value") else str(frame.state)
    result["levels"] = f"{frame.levels_completed}/{frame.win_levels}"
    result["elapsed"] = round(time.time() - t0, 2)

    # Determine pass/fail
    if result["errors"]:
        result["status"] = "FAIL"
    elif parse_fail_count > 0 and llm_ok_count == 0:
        result["status"] = "WARN"
        result["warnings"].append("All LLM responses failed to parse")
    else:
        result["status"] = "PASS"
        if not dry_run and model_key:
            result["llm_parsed"] = f"{llm_ok_count}/{llm_ok_count + parse_fail_count}"

    return result


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Test game scaffolds end-to-end")
    parser.add_argument("--model", type=str, default=None,
                        help="LLM model key (default: auto-pick cheapest available)")
    parser.add_argument("--games", type=str, default="all",
                        help="Comma-separated game IDs or 'all' (default: all)")
    parser.add_argument("--steps", type=int, default=5,
                        help="Max steps per game (default: 5)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Skip LLM calls, use random actions (test scaffold only)")
    args = parser.parse_args()

    # Load config
    cfg = load_config()
    cfg["reasoning"]["temperature"] = 0.3
    cfg["reasoning"]["max_tokens"] = 2048
    cfg["memory"]["reflect_after_game"] = False
    cfg["memory"]["condense_every"] = 0
    cfg["context"]["memory_injection"] = False

    # Pick model
    model_key = args.model
    if not args.dry_run:
        if model_key is None:
            model_key = pick_model()
        if model_key is None:
            print("  No LLM provider available. Use --dry-run or set an API key.")
            sys.exit(1)
        if model_key not in MODELS:
            print(f"  Unknown model: {model_key}")
            sys.exit(1)
        # Verify env key
        info = MODELS[model_key]
        env_key = info.get("env_key", "")
        if env_key and not os.environ.get(env_key):
            print(f"  {env_key} not set for model {model_key}")
            sys.exit(1)

    # Discover games
    arcade = arc_agi.Arcade()
    all_games = sorted([e.game_id for e in arcade.get_environments()])

    if args.games == "all":
        games = all_games
    else:
        games = []
        for g in args.games.split(","):
            g = g.strip()
            if g in all_games:
                games.append(g)
            else:
                matches = [gid for gid in all_games if gid.startswith(g)]
                if matches:
                    games.extend(matches)
                else:
                    print(f"  Unknown game: {g}  (available: {', '.join(all_games)})")
                    sys.exit(1)

    # Header
    mode_str = "DRY-RUN (no LLM)" if args.dry_run else f"LLM: {model_key}"
    print(f"\n{'=' * 65}")
    print(f"  SCAFFOLD TEST — {len(games)} game(s), {args.steps} steps each")
    print(f"  Mode: {mode_str}")
    print(f"  Games: {', '.join(games)}")
    print(f"{'=' * 65}\n")

    # Run tests
    results = []
    passed = 0
    failed = 0
    warned = 0

    for game_id in games:
        print(f"  {game_id:<8s} ...", end=" ", flush=True)
        try:
            r = test_game(arcade, game_id, model_key, cfg, args.steps, args.dry_run)
        except Exception as e:
            r = {
                "game_id": game_id, "status": "FAIL",
                "errors": [f"Unhandled: {traceback.format_exc()}"],
                "steps_taken": 0, "elapsed": 0,
                "warnings": [], "final_state": None, "levels": None,
            }
        results.append(r)

        status = r["status"]
        steps = r["steps_taken"]
        elapsed = r.get("elapsed", 0)
        levels = r.get("levels", "?")
        llm_info = f"  llm={r['llm_parsed']}" if r.get("llm_parsed") else ""
        state_info = f"  state={r['final_state']}" if r.get("final_state") else ""

        if status == "PASS":
            print(f"PASS  ({steps} steps, {elapsed}s, lvl {levels}{llm_info}{state_info})")
            passed += 1
        elif status == "WARN":
            print(f"WARN  ({steps} steps, {elapsed}s)")
            for w in r["warnings"][:2]:
                print(f"           {w[:100]}")
            warned += 1
        else:
            print(f"FAIL")
            for e in r["errors"][:3]:
                print(f"           {e[:120]}")
            failed += 1

    # Summary
    print(f"\n{'─' * 65}")
    print(f"  Results: {passed} passed, {failed} failed, {warned} warned  ({len(games)} total)")
    print(f"{'─' * 65}\n")

    # Write detailed results
    report_path = Path(__file__).parent / "data" / "scaffold_test_results.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"  Detailed results: {report_path}\n")

    if failed > 0:
        print("  FAILURES:")
        for r in results:
            if r["status"] == "FAIL":
                print(f"    {r['game_id']}: {'; '.join(r['errors'][:2])}")
        print()
        sys.exit(1)


if __name__ == "__main__":
    main()
