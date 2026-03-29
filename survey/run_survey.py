# Author: Cascade (Claude Opus 4.6 thinking)
# Date: 2026-03-29 13:10
# PURPOSE: Instinct survey orchestrator for ARC-AGI-3. Runs the existing agent
#   (agent.py) across all available games using batch_runner.py, then invokes
#   report_generator to classify instincts and produce JSON + Markdown reports,
#   and postgres_writer to push results to Railway Postgres.
#   Uses config_survey.yaml (Sonnet 4.6 OAuth, 30 steps, no memory, sequential).
#   Dependencies: batch_runner, agent, db, arc_agi, survey.report_generator,
#   survey.postgres_writer.
# SRP/DRY check: Pass — orchestration only. Classification in classify.py,
#   reporting in report_generator.py, DB writes in postgres_writer.py.
"""ARC-AGI-3 Instinct Survey — run all games, classify behavior, generate reports."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure repo root is on path
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv
load_dotenv(_REPO_ROOT / ".env")

import arc_agi

from agent import load_config, effective_model
from models import MODELS
from batch_runner import run_batch

# Survey defaults
SURVEY_CONFIG = _REPO_ROOT / "config_survey.yaml"
SURVEY_MAX_STEPS = 30
SURVEY_CONCURRENCY = 1  # sequential to avoid OAuth rate limits
SURVEY_TIMEOUT_SECONDS = 600  # 10 minutes per game


def discover_games() -> list[str]:
    """Return sorted, deduplicated list of all available game IDs from arc_agi."""
    arcade = arc_agi.Arcade()
    seen = set()
    games = []
    for e in arcade.get_environments():
        if e.game_id not in seen:
            seen.add(e.game_id)
            games.append(e.game_id)
    return sorted(games)


def run_survey(
    games: list[str] | None = None,
    max_steps: int = SURVEY_MAX_STEPS,
    concurrency: int = SURVEY_CONCURRENCY,
    config_path: Path | None = None,
    skip_report: bool = False,
    skip_postgres: bool = False,
    dry_run: bool = False,
) -> dict:
    """Run the full instinct survey pipeline.

    1. Discover games (or use provided list)
    2. Run batch with survey config (sequential, Sonnet 4.6, 30 steps)
    3. Classify instincts from DB data
    4. Generate JSON + Markdown reports
    5. Write results to Railway Postgres

    Returns the batch report dict augmented with survey classification data.
    """
    # Load survey config
    cfg = load_config(config_path or SURVEY_CONFIG)
    model_key = effective_model(cfg, "executor")

    # Discover games
    if games is None:
        games = discover_games()

    print(f"\n{'#' * 65}")
    print(f"  ARC-AGI-3 INSTINCT SURVEY")
    print(f"  Model       : {model_key}")
    print(f"  Games       : {len(games)}")
    print(f"  Steps/game  : {max_steps}")
    print(f"  Concurrency : {concurrency}")
    print(f"  Config      : {config_path or SURVEY_CONFIG}")
    print(f"{'#' * 65}")
    print(f"\n  Game list: {', '.join(games)}\n")

    if dry_run:
        print("  [dry-run] Would run the above. Exiting.")
        return {"games": games, "model": model_key, "dry_run": True}

    # Validate model + API key
    if model_key not in MODELS:
        print(f"  ERROR: Unknown model '{model_key}'. Check config_survey.yaml.")
        sys.exit(1)
    info = MODELS[model_key]
    env_key = info.get("env_key", "")
    if env_key and not os.environ.get(env_key):
        print(f"  ERROR: {env_key} not set. Check .env or ~/.zshrc.")
        sys.exit(1)

    # Set up timestamped DB for this survey run
    import db as _db_module
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    _db_module.DB_PATH = _db_module._DATA_DIR / f"survey_{ts}.db"
    _db_module._init_db()
    db_path = str(_db_module.DB_PATH)
    print(f"  Survey DB: {db_path}\n")

    # Run batch
    t0 = time.time()
    batch_report = run_batch(
        games=games,
        cfg=cfg,
        concurrency=concurrency,
        max_steps=max_steps,
    )
    elapsed = time.time() - t0

    batch_report["survey_db_path"] = db_path
    batch_report["survey_elapsed_seconds"] = round(elapsed, 1)
    batch_report["survey_config"] = str(config_path or SURVEY_CONFIG)

    print(f"\n  Survey batch complete in {elapsed / 60:.1f} minutes")
    print(f"  DB: {db_path}")

    # Generate reports
    if not skip_report:
        print("\n  Generating instinct classification report...")
        try:
            from survey.report_generator import generate_reports
            survey_results = generate_reports(db_path, batch_report)
            batch_report["survey_results"] = survey_results
        except Exception as e:
            print(f"  [ERROR] Report generation failed: {e}")
            import traceback
            traceback.print_exc()

    # Write to Postgres
    if not skip_postgres:
        pg_url = os.environ.get("DATABASE_PUBLIC_URL")
        if pg_url:
            print("\n  Writing results to Railway Postgres...")
            try:
                from survey.postgres_writer import write_survey_results
                write_survey_results(
                    batch_report.get("survey_results", {}),
                    batch_report,
                    pg_url,
                )
                print("  Postgres write complete.")
            except Exception as e:
                print(f"  [WARNING] Postgres write failed: {e}")
                import traceback
                traceback.print_exc()
        else:
            print("\n  [SKIP] DATABASE_PUBLIC_URL not set — skipping Postgres write.")

    return batch_report


def main():
    parser = argparse.ArgumentParser(
        description="ARC-AGI-3 Instinct Survey — run all games, classify behavior"
    )
    parser.add_argument(
        "--games", default=None,
        help="Comma-separated game IDs (default: all available)"
    )
    parser.add_argument(
        "--max-steps", type=int, default=SURVEY_MAX_STEPS,
        help=f"Max steps per game (default: {SURVEY_MAX_STEPS})"
    )
    parser.add_argument(
        "--concurrency", type=int, default=SURVEY_CONCURRENCY,
        help=f"Concurrent games (default: {SURVEY_CONCURRENCY})"
    )
    parser.add_argument(
        "--config", default=None,
        help="Path to config YAML (default: config_survey.yaml)"
    )
    parser.add_argument(
        "--skip-report", action="store_true",
        help="Skip report generation (just run games)"
    )
    parser.add_argument(
        "--skip-postgres", action="store_true",
        help="Skip Railway Postgres write"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would run without executing"
    )
    parser.add_argument(
        "--report-only", default=None,
        help="Skip running games — generate report from existing DB path"
    )
    args = parser.parse_args()

    # Report-only mode: skip running games, just classify + report from existing DB
    if args.report_only:
        print(f"\n  [report-only] Reading from: {args.report_only}")
        from survey.report_generator import generate_reports
        results = generate_reports(args.report_only, {})
        print(f"\n  Report generated. {len(results.get('games', []))} games classified.")
        return

    game_list = None
    if args.games:
        game_list = [g.strip() for g in args.games.split(",") if g.strip()]

    run_survey(
        games=game_list,
        max_steps=args.max_steps,
        concurrency=args.concurrency,
        config_path=Path(args.config) if args.config else None,
        skip_report=args.skip_report,
        skip_postgres=args.skip_postgres,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
