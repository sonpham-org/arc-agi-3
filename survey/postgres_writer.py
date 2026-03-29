# Author: Cascade (Claude Opus 4.6 thinking)
# Date: 2026-03-29 13:25
# PURPOSE: Railway Postgres writer for ARC-AGI-3 instinct survey results.
#   Creates arc3_survey_results table if it doesn't exist, then upserts
#   per-game classification data. Uses psycopg2 with DATABASE_PUBLIC_URL.
#   Dependencies: psycopg2-binary (already in requirements.txt).
# SRP/DRY check: Pass — Postgres I/O only. Classification in classify.py.
"""Write instinct survey results to Railway Postgres."""

from __future__ import annotations

import json
import logging
from datetime import datetime

import psycopg2
import psycopg2.extras

log = logging.getLogger(__name__)

# DDL for the survey results table
_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS arc3_survey_results (
    id SERIAL PRIMARY KEY,
    survey_run_id TEXT NOT NULL,
    game_id TEXT NOT NULL,
    model TEXT NOT NULL,
    session_id TEXT,
    result TEXT,
    steps_taken INTEGER DEFAULT 0,
    levels_completed INTEGER DEFAULT 0,
    total_cost_usd REAL DEFAULT 0,
    action_distribution JSONB,
    first_impression TEXT,
    strategy_phases JSONB,
    change_awareness JSONB,
    hypothesis_count INTEGER DEFAULT 0,
    instinct_class TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(survey_run_id, game_id)
);

CREATE INDEX IF NOT EXISTS idx_survey_game ON arc3_survey_results(game_id);
CREATE INDEX IF NOT EXISTS idx_survey_instinct ON arc3_survey_results(instinct_class);
CREATE INDEX IF NOT EXISTS idx_survey_run ON arc3_survey_results(survey_run_id);
"""

_CREATE_SUMMARY_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS arc3_survey_summaries (
    id SERIAL PRIMARY KEY,
    survey_run_id TEXT NOT NULL UNIQUE,
    total_games INTEGER DEFAULT 0,
    total_steps INTEGER DEFAULT 0,
    total_cost_usd REAL DEFAULT 0,
    instinct_distribution JSONB,
    avg_change_awareness REAL DEFAULT 0,
    games_with_levels INTEGER DEFAULT 0,
    games_with_hypotheses INTEGER DEFAULT 0,
    batch_id TEXT,
    model TEXT,
    config_path TEXT,
    elapsed_seconds REAL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
"""

_UPSERT_RESULT_SQL = """
INSERT INTO arc3_survey_results (
    survey_run_id, game_id, model, session_id, result,
    steps_taken, levels_completed, total_cost_usd,
    action_distribution, first_impression, strategy_phases,
    change_awareness, hypothesis_count, instinct_class
) VALUES (
    %(survey_run_id)s, %(game_id)s, %(model)s, %(session_id)s, %(result)s,
    %(steps_taken)s, %(levels_completed)s, %(total_cost_usd)s,
    %(action_distribution)s, %(first_impression)s, %(strategy_phases)s,
    %(change_awareness)s, %(hypothesis_count)s, %(instinct_class)s
)
ON CONFLICT (survey_run_id, game_id) DO UPDATE SET
    model = EXCLUDED.model,
    session_id = EXCLUDED.session_id,
    result = EXCLUDED.result,
    steps_taken = EXCLUDED.steps_taken,
    levels_completed = EXCLUDED.levels_completed,
    total_cost_usd = EXCLUDED.total_cost_usd,
    action_distribution = EXCLUDED.action_distribution,
    first_impression = EXCLUDED.first_impression,
    strategy_phases = EXCLUDED.strategy_phases,
    change_awareness = EXCLUDED.change_awareness,
    hypothesis_count = EXCLUDED.hypothesis_count,
    instinct_class = EXCLUDED.instinct_class,
    created_at = NOW();
"""

_UPSERT_SUMMARY_SQL = """
INSERT INTO arc3_survey_summaries (
    survey_run_id, total_games, total_steps, total_cost_usd,
    instinct_distribution, avg_change_awareness,
    games_with_levels, games_with_hypotheses,
    batch_id, model, config_path, elapsed_seconds
) VALUES (
    %(survey_run_id)s, %(total_games)s, %(total_steps)s, %(total_cost_usd)s,
    %(instinct_distribution)s, %(avg_change_awareness)s,
    %(games_with_levels)s, %(games_with_hypotheses)s,
    %(batch_id)s, %(model)s, %(config_path)s, %(elapsed_seconds)s
)
ON CONFLICT (survey_run_id) DO UPDATE SET
    total_games = EXCLUDED.total_games,
    total_steps = EXCLUDED.total_steps,
    total_cost_usd = EXCLUDED.total_cost_usd,
    instinct_distribution = EXCLUDED.instinct_distribution,
    avg_change_awareness = EXCLUDED.avg_change_awareness,
    games_with_levels = EXCLUDED.games_with_levels,
    games_with_hypotheses = EXCLUDED.games_with_hypotheses,
    batch_id = EXCLUDED.batch_id,
    model = EXCLUDED.model,
    config_path = EXCLUDED.config_path,
    elapsed_seconds = EXCLUDED.elapsed_seconds,
    created_at = NOW();
"""


def write_survey_results(
    survey_data: dict,
    batch_report: dict,
    pg_url: str,
) -> None:
    """Write survey results to Railway Postgres.

    Args:
        survey_data: Output from report_generator.generate_reports()
        batch_report: The batch_runner report dict (for metadata)
        pg_url: Postgres connection string (DATABASE_PUBLIC_URL)
    """
    games = survey_data.get("games", [])
    summary = survey_data.get("summary", {})

    if not games:
        print("  [postgres] No game results to write.")
        return

    survey_run_id = batch_report.get("batch_id", f"survey-{datetime.now().strftime('%Y%m%d-%H%M%S')}")

    conn = psycopg2.connect(pg_url)
    try:
        with conn.cursor() as cur:
            # Create tables
            cur.execute(_CREATE_TABLE_SQL)
            cur.execute(_CREATE_SUMMARY_TABLE_SQL)
            conn.commit()

            # Write per-game results
            for g in games:
                params = {
                    "survey_run_id": survey_run_id,
                    "game_id": g["game_id"],
                    "model": g["model"],
                    "session_id": g["session_id"],
                    "result": g["result"],
                    "steps_taken": g["steps_taken"],
                    "levels_completed": g["levels_completed"],
                    "total_cost_usd": g["total_cost_usd"],
                    "action_distribution": json.dumps(g["action_distribution"]),
                    "first_impression": (g["first_impression"] or "")[:500],
                    "strategy_phases": json.dumps(g["strategy_phases"]),
                    "change_awareness": json.dumps(g["change_awareness"]),
                    "hypothesis_count": g["hypothesis_count"],
                    "instinct_class": g["instinct_class"],
                }
                cur.execute(_UPSERT_RESULT_SQL, params)

            # Write summary
            summary_params = {
                "survey_run_id": survey_run_id,
                "total_games": summary.get("total_games", 0),
                "total_steps": summary.get("total_steps", 0),
                "total_cost_usd": summary.get("total_cost_usd", 0),
                "instinct_distribution": json.dumps(summary.get("instinct_distribution", {})),
                "avg_change_awareness": summary.get("avg_change_awareness_ratio", 0),
                "games_with_levels": summary.get("games_with_levels", 0),
                "games_with_hypotheses": summary.get("games_with_hypotheses", 0),
                "batch_id": batch_report.get("batch_id", ""),
                "model": batch_report.get("model", ""),
                "config_path": batch_report.get("survey_config", ""),
                "elapsed_seconds": batch_report.get("survey_elapsed_seconds", 0),
            }
            cur.execute(_UPSERT_SUMMARY_SQL, summary_params)
            conn.commit()

        print(f"  [postgres] Wrote {len(games)} game results + summary for run {survey_run_id}")

    except Exception as e:
        conn.rollback()
        raise
    finally:
        conn.close()
