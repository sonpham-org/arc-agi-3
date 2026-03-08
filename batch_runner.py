"""ARC-AGI-3 Batch Runner — run multiple games concurrently via ThreadPoolExecutor."""

import argparse
import json
import os
import secrets
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

import arc_agi

from agent import (
    MODELS, DEFAULT_MODEL, call_model_with_retry,
    load_config, effective_model, play_game,
)
from db import (
    _get_db, _db_insert_session, _db_insert_step, _db_update_session,
    _compress_grid, _turso_import_session, _turso_sync_session,
    _get_session_calls, _get_session_turns, _export_session_to_file,
)

ROOT = Path(__file__).parent

# ═══════════════════════════════════════════════════════════════════════════
# PER-PROVIDER RATE LIMITING
# ═══════════════════════════════════════════════════════════════════════════

# Max concurrent LLM calls per provider
PROVIDER_CONCURRENCY = {
    "groq": 2,
    "gemini": 4,
    "anthropic": 4,
    "mistral": 2,
    "huggingface": 2,
    "cloudflare": 4,
    "ollama": 8,
    "copilot": 4,
}

_provider_semaphores: dict[str, threading.Semaphore] = {}


def _get_provider_semaphore(provider: str) -> threading.Semaphore:
    if provider not in _provider_semaphores:
        limit = PROVIDER_CONCURRENCY.get(provider, 4)
        _provider_semaphores[provider] = threading.Semaphore(limit)
    return _provider_semaphores[provider]


def _install_rate_limiting(model_key: str):
    """Monkey-patch call_model (the lowest-level LLM call) to add per-provider semaphore.

    This rate-limits both call_model_with_metadata and call_model_with_retry since
    they both delegate to call_model internally.
    """
    import agent
    original = agent.call_model

    if getattr(original, '_rate_limited', False):
        return  # already patched

    real_fn = getattr(original, '__wrapped__', original)

    def rate_limited_call(mk, prompt, cfg, role="executor", **kwargs):
        info = MODELS.get(mk)
        provider = info["provider"] if info else "unknown"
        sem = _get_provider_semaphore(provider)
        sem.acquire()
        try:
            return real_fn(mk, prompt, cfg, role, **kwargs)
        finally:
            sem.release()

    rate_limited_call._rate_limited = True
    rate_limited_call.__wrapped__ = real_fn
    agent.call_model = rate_limited_call


# ═══════════════════════════════════════════════════════════════════════════
# BATCH STATE TRACKER
# ═══════════════════════════════════════════════════════════════════════════

class BatchState:
    """Thread-safe progress tracker for a batch run."""

    def __init__(self, batch_id: str, total_games: int):
        self.batch_id = batch_id
        self.total = total_games
        self.completed = 0
        self.wins = 0
        self.failures = 0
        self.errors = 0
        self.running: dict[str, float] = {}  # game_id -> start_time
        self._lock = threading.Lock()

    def start_game(self, game_id: str):
        with self._lock:
            self.running[game_id] = time.time()

    def finish_game(self, game_id: str, result: str):
        with self._lock:
            self.running.pop(game_id, None)
            self.completed += 1
            if result == "WIN":
                self.wins += 1
            elif result in ("GAME_OVER", "TIMEOUT", "NOT_FINISHED"):
                self.failures += 1
            elif result == "ERROR":
                self.errors += 1
            else:
                self.failures += 1

    def summary(self) -> dict:
        with self._lock:
            return {
                "total": self.total,
                "completed": self.completed,
                "wins": self.wins,
                "failures": self.failures,
                "errors": self.errors,
                "running": list(self.running.keys()),
            }


# ═══════════════════════════════════════════════════════════════════════════
# STEP CALLBACK — persists each step to DB
# ═══════════════════════════════════════════════════════════════════════════

def make_step_callback():
    """Create a step callback that writes each step to the sessions DB."""

    def step_callback(session_id, step_num, action, data, grid, llm_response, state, levels):
        _db_insert_step(
            session_id=session_id,
            step_num=step_num,
            action=action,
            data=data or {},
            grid=grid,
            change_map=None,
            llm_response=llm_response,
        )
        _db_update_session(session_id, steps=step_num, levels=levels, result=state)

    return step_callback


# ═══════════════════════════════════════════════════════════════════════════
# SINGLE GAME RUNNER
# ═══════════════════════════════════════════════════════════════════════════

def run_single_game(arcade, game_id: str, cfg: dict, max_steps: int,
                    batch_state: BatchState, batch_id: str,
                    repeat_idx: int = 0) -> dict:
    """Run one game with DB persistence. Returns result dict."""
    # Generate unique session ID
    session_id = f"batch-{batch_id[:8]}-{game_id}-{repeat_idx}-{secrets.token_hex(4)}"
    model_key = effective_model(cfg, "executor")

    # Insert session record
    _db_insert_session(session_id, game_id, "batch")
    _db_update_session(session_id, model=model_key)

    # Insert batch_games record
    try:
        conn = _get_db()
        conn.execute(
            "INSERT OR REPLACE INTO batch_games (batch_id, game_id, session_id, status, started_at) "
            "VALUES (?, ?, ?, 'running', ?)",
            (batch_id, f"{game_id}_{repeat_idx}" if repeat_idx > 0 else game_id,
             session_id, time.time()),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

    batch_state.start_game(game_id if repeat_idx == 0 else f"{game_id}_{repeat_idx}")
    game_key = game_id if repeat_idx == 0 else f"{game_id}_{repeat_idx}"

    t0 = time.time()
    result = "ERROR"
    error_msg = None
    steps = 0
    levels = 0

    # Select game loop based on scaffolding mode
    from scaffoldings import SCAFFOLDING_REGISTRY
    scfg = cfg.get("scaffolding", {})
    mode = scfg.get("mode", "")
    game_fn = SCAFFOLDING_REGISTRY.get(mode, play_game)

    try:
        result = game_fn(
            arcade, game_id, cfg, max_steps,
            session_id=session_id,
            step_callback=make_step_callback(),
        )
        # Read final step count from DB
        try:
            conn = _get_db()
            row = conn.execute(
                "SELECT steps, levels FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if row:
                steps = row["steps"]
                levels = row["levels"]
            conn.close()
        except Exception:
            pass
    except Exception as e:
        import traceback
        traceback.print_exc()
        error_msg = str(e)
        result = "ERROR"

    elapsed = time.time() - t0
    batch_state.finish_game(game_key, result)

    # Update batch_games record
    try:
        conn = _get_db()
        conn.execute(
            "UPDATE batch_games SET status='finished', result=?, steps=?, levels=?, "
            "finished_at=?, error=? WHERE batch_id=? AND game_id=?",
            (result, steps, levels, time.time(), error_msg, batch_id, game_key),
        )
        # Update batch_runs aggregates
        s = batch_state.summary()
        conn.execute(
            "UPDATE batch_runs SET completed_games=?, wins=?, failures=? WHERE id=?",
            (s["completed"], s["wins"], s["failures"], batch_id),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

    # Export session to per-session file for durability
    try:
        _export_session_to_file(session_id)
    except Exception:
        pass

    return {
        "game_id": game_id,
        "repeat_idx": repeat_idx,
        "session_id": session_id,
        "result": result,
        "steps": steps,
        "levels": levels,
        "elapsed": round(elapsed, 1),
        "error": error_msg,
    }


# ═══════════════════════════════════════════════════════════════════════════
# PROGRESS PRINTER
# ═══════════════════════════════════════════════════════════════════════════

def progress_printer(batch_state: BatchState, stop_event: threading.Event):
    """Background thread that prints live progress every 5s."""
    while not stop_event.is_set():
        stop_event.wait(5.0)
        if stop_event.is_set():
            break
        s = batch_state.summary()
        running_str = ", ".join(s["running"][:4])
        if len(s["running"]) > 4:
            running_str += f" +{len(s['running']) - 4} more"
        print(
            f"  [progress] {s['completed']}/{s['total']} done | "
            f"W:{s['wins']} F:{s['failures']} E:{s['errors']} | "
            f"running: {running_str or 'none'}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# BATCH ORCHESTRATOR
# ═══════════════════════════════════════════════════════════════════════════

def get_completed_games(batch_id: str, model_key: str) -> set[str]:
    """Query DB for games already completed in a prior run with same model."""
    done = set()
    try:
        conn = _get_db()
        rows = conn.execute(
            "SELECT bg.game_id FROM batch_games bg "
            "JOIN sessions s ON bg.session_id = s.id "
            "WHERE bg.batch_id = ? AND bg.status = 'finished' "
            "AND bg.result IN ('WIN', 'GAME_OVER', 'NOT_FINISHED') "
            "AND s.model = ?",
            (batch_id, model_key),
        ).fetchall()
        done = {r["game_id"] for r in rows}
        conn.close()
    except Exception:
        pass
    return done


def run_batch(
    games: list[str],
    cfg: dict,
    concurrency: int = 4,
    max_steps: int = 200,
    repeat: int = 1,
    resume_batch_id: str | None = None,
    upload_turso: bool = False,
) -> dict:
    """Run a batch of games concurrently. Returns results dict."""
    batch_id = resume_batch_id or f"batch-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(4)}"
    model_key = effective_model(cfg, "executor")

    # Build game list with repeats
    game_tasks = []
    for game_id in games:
        for r in range(repeat):
            game_tasks.append((game_id, r))

    # Resume: skip already completed
    if resume_batch_id:
        completed = get_completed_games(batch_id, model_key)
        original_count = len(game_tasks)
        game_tasks = [
            (gid, r) for gid, r in game_tasks
            if (gid if r == 0 else f"{gid}_{r}") not in completed
        ]
        print(f"  [resume] Skipping {original_count - len(game_tasks)} already completed games")

    total = len(game_tasks)
    if total == 0:
        print("  No games to run.")
        return {"batch_id": batch_id, "results": [], "skipped": True}

    # Install rate limiting
    _install_rate_limiting(model_key)

    # Create batch_runs record
    try:
        conn = _get_db()
        conn.execute(
            "INSERT OR IGNORE INTO batch_runs (id, created_at, config_json, status, total_games) "
            "VALUES (?, ?, ?, 'running', ?)",
            (batch_id, time.time(), json.dumps({"model": model_key, "concurrency": concurrency}), total),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

    batch_state = BatchState(batch_id, total)

    # Create shared Arcade instance
    arcade = arc_agi.Arcade()

    print(f"\n{'#' * 65}")
    print(f"  BATCH RUN: {batch_id}")
    print(f"  Model    : {model_key}")
    print(f"  Games    : {len(games)} x {repeat} repeat(s) = {total} total")
    print(f"  Workers  : {concurrency}")
    print(f"  Max steps: {max_steps}")
    print(f"{'#' * 65}\n")

    # Start progress printer
    stop_event = threading.Event()
    printer = threading.Thread(target=progress_printer, args=(batch_state, stop_event), daemon=True)
    printer.start()

    results = []
    try:
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {}
            for game_id, repeat_idx in game_tasks:
                fut = executor.submit(
                    run_single_game, arcade, game_id, cfg, max_steps,
                    batch_state, batch_id, repeat_idx,
                )
                futures[fut] = (game_id, repeat_idx)

            for fut in as_completed(futures):
                game_id, repeat_idx = futures[fut]
                try:
                    result = fut.result()
                    results.append(result)
                    tag = f"{result['result']:12s}"
                    print(f"  [done] {game_id} r{repeat_idx} -> {tag} ({result['steps']} steps, {result['elapsed']}s)")
                except Exception as e:
                    print(f"  [error] {game_id} r{repeat_idx}: {e}")
                    results.append({
                        "game_id": game_id, "repeat_idx": repeat_idx,
                        "result": "ERROR", "error": str(e),
                    })
    finally:
        stop_event.set()
        printer.join(timeout=2)

    # Finalize batch record
    try:
        s = batch_state.summary()
        conn = _get_db()
        conn.execute(
            "UPDATE batch_runs SET status='finished', completed_games=?, wins=?, failures=?, finished_at=? WHERE id=?",
            (s["completed"], s["wins"], s["failures"], time.time(), batch_id),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

    # Upload to Turso if requested
    if upload_turso:
        _upload_batch_to_turso(results)

    # Print summary
    s = batch_state.summary()
    print(f"\n{'=' * 65}")
    print(f"  BATCH COMPLETE: {batch_id}")
    print(f"  Total: {s['total']} | Wins: {s['wins']} | Failures: {s['failures']} | Errors: {s['errors']}")
    win_rate = (s['wins'] / s['completed'] * 100) if s['completed'] > 0 else 0
    print(f"  Win rate: {win_rate:.1f}%")
    print(f"{'=' * 65}\n")

    # Write JSON report
    report = {
        "batch_id": batch_id,
        "model": model_key,
        "timestamp": datetime.now().isoformat(),
        "summary": s,
        "win_rate": round(win_rate, 1),
        "results": results,
    }
    report_path = ROOT / "data" / f"batch_{batch_id}.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2))
    print(f"  Report saved: {report_path}")

    return report


def _upload_batch_to_turso(results: list[dict]):
    """Upload sessions with >5 steps to Turso (incremental sync)."""
    uploaded = 0
    for r in results:
        if r.get("steps", 0) < 5 or not r.get("session_id"):
            continue
        try:
            sync_result = _turso_sync_session(r["session_id"])
            if sync_result["ok"]:
                uploaded += 1
                detail = f"{sync_result['steps']}s/{sync_result['turns']}t/{sync_result['calls']}c"
                print(f"  [turso] synced {r['session_id'][:16]}… ({detail})")
        except Exception as e:
            print(f"  [turso] upload failed for {r['session_id']}: {e}")

    if uploaded:
        print(f"  [turso] Synced {uploaded} sessions")


# ═══════════════════════════════════════════════════════════════════════════
# OBSERVABILITY SERVER (auto-started with --obs)
# ═══════════════════════════════════════════════════════════════════════════

_obs_port = None


def _start_obs_server():
    """Start the standalone obs server on a random available port."""
    global _obs_port
    try:
        from obs_server import start_obs_server
        _obs_port = start_obs_server()
        print(f"\n  Observatory dashboard: http://localhost:{_obs_port}/obs\n")
    except Exception as e:
        print(f"  [obs] Failed to start dashboard server: {e}")


def _obs_keepalive(seconds: int = 60):
    """Keep the process alive so the dashboard remains accessible after the run."""
    if _obs_port is None:
        return
    print(f"\n  Run complete. Dashboard still live for {seconds}s — Ctrl+C to exit early.")
    try:
        time.sleep(seconds)
    except KeyboardInterrupt:
        pass
    print("  Observatory shutting down.")


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="ARC-AGI-3 Batch Runner")
    parser.add_argument("--games", default="all",
                        help="Comma-separated game IDs, or 'all' (default: all)")
    parser.add_argument("--concurrency", type=int, default=4,
                        help="Number of concurrent games (default: 4)")
    parser.add_argument("--model", default=None,
                        help="Override executor model")
    parser.add_argument("--max-steps", type=int, default=200,
                        help="Max steps per game (default: 200)")
    parser.add_argument("--repeat", type=int, default=1,
                        help="Run each game N times (default: 1)")
    parser.add_argument("--resume", default=None,
                        help="Resume a previous batch by ID")
    parser.add_argument("--upload-turso", action="store_true",
                        help="Upload completed sessions to Turso")
    parser.add_argument("--upload-session", default=None,
                        help="Upload a single session to Turso by ID (no batch run)")
    parser.add_argument("--planner-model", default=None,
                        help="Override planner/orchestrator model (e.g. gemini-3.1-pro)")
    parser.add_argument("--scaffolding", default=None,
                        help="Override scaffolding mode (e.g. agent_spawn, three_system)")
    parser.add_argument("--config", default=None,
                        help="Path to config.yaml")
    parser.add_argument("--obs", action="store_true",
                        help="Enable observability dashboard (writes to .agent_obs/)")
    args = parser.parse_args()

    # ── Standalone session upload ────────────────────────────────────────
    if args.upload_session:
        sid = args.upload_session
        conn = _get_db()
        sess_row = conn.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
        if not sess_row:
            # Try prefix match
            rows = conn.execute(
                "SELECT id, game_id, steps, result FROM sessions WHERE id LIKE ? ORDER BY created_at DESC LIMIT 5",
                (f"%{sid}%",),
            ).fetchall()
            conn.close()
            if rows:
                print(f"Session '{sid}' not found. Did you mean:")
                for r in rows:
                    print(f"  {r['id']}  ({r['game_id']}, {r['steps']} steps, {r['result']})")
            else:
                print(f"Session '{sid}' not found in local DB.")
            sys.exit(1)
        conn.close()
        print(f"Syncing session {sid} ({sess_row['steps']} steps, {sess_row['result']})...")
        sync_result = _turso_sync_session(sid)
        if sync_result["ok"]:
            detail = f"{sync_result['steps']} steps, {sync_result['turns']} turns, {sync_result['calls']} calls"
            print(f"Done! Synced {detail}. View at: https://arc3.sonpham.net/share/{sid}")
        else:
            print("Upload failed. Check TURSO_DATABASE_URL and TURSO_AUTH_TOKEN env vars.")
        sys.exit(0)

    cfg = load_config(Path(args.config) if args.config else None)
    if args.model:
        cfg["reasoning"]["executor_model"] = args.model
    if args.planner_model:
        cfg["reasoning"]["planner_model"] = args.planner_model
    if args.scaffolding:
        cfg.setdefault("scaffolding", {})["mode"] = args.scaffolding
    # Each batch run gets its own timestamped DB file (must be set before obs server)
    import db as _db_module
    from datetime import datetime
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    _db_module.DB_PATH = _db_module._DATA_DIR / f"sessions_{ts}.db"
    _db_module._init_db()
    print(f"  DB: {_db_module.DB_PATH}")

    if args.obs:
        cfg["observability"] = True
        _start_obs_server()

    # Validate model
    exec_model = cfg["reasoning"]["executor_model"]
    if exec_model not in MODELS:
        print(f"Unknown model: {exec_model}")
        print(f"Available: {', '.join(sorted(MODELS.keys()))}")
        sys.exit(1)

    info = MODELS[exec_model]
    if info.get("env_key") and not os.environ.get(info["env_key"]):
        print(f"ERROR: {info['env_key']} not set in .env")
        sys.exit(1)

    # Validate planner model if specified
    planner_model = cfg["reasoning"].get("planner_model")
    if planner_model and planner_model != exec_model:
        if planner_model not in MODELS:
            print(f"Unknown planner model: {planner_model}")
            print(f"Available: {', '.join(sorted(MODELS.keys()))}")
            sys.exit(1)
        p_info = MODELS[planner_model]
        if p_info.get("env_key") and not os.environ.get(p_info["env_key"]):
            print(f"ERROR: {p_info['env_key']} not set in .env (for planner model)")
            sys.exit(1)

    # Resolve game list
    arcade = arc_agi.Arcade()
    available_games = [e.game_id for e in arcade.get_environments()]

    if args.games == "all":
        games = available_games
    else:
        games = []
        for g in args.games.split(","):
            g = g.strip()
            # Support prefix matching
            matched = [gid for gid in available_games if gid.startswith(g)]
            if matched:
                games.extend(matched)
            else:
                print(f"Warning: unknown game '{g}', skipping")

    if not games:
        print(f"No games found. Available: {', '.join(available_games)}")
        sys.exit(1)

    run_batch(
        games=games,
        cfg=cfg,
        concurrency=args.concurrency,
        max_steps=args.max_steps,
        repeat=args.repeat,
        resume_batch_id=args.resume,
        upload_turso=args.upload_turso,
    )

    if args.obs:
        _obs_keepalive(60)


if __name__ == "__main__":
    main()
