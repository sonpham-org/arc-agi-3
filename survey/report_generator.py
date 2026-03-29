# Author: Cascade (Claude Opus 4.6 thinking)
# Date: 2026-03-29 13:20
# PURPOSE: Report generator for ARC-AGI-3 instinct survey. Reads a survey SQLite
#   DB (timestamped, created by run_survey.py), classifies each game session using
#   survey.classify, and produces two deliverables:
#     1. docs/reports/instinct-survey.json — full per-game data array
#     2. docs/reports/instinct-survey.md — human-readable summary with rankings
#   Dependencies: survey.classify, sqlite3, json, pathlib.
# SRP/DRY check: Pass — report generation only. Classification in classify.py.
"""Report generator for ARC-AGI-3 instinct survey."""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path

from survey.classify import classify_game

_REPO_ROOT = Path(__file__).resolve().parent.parent
_REPORTS_DIR = _REPO_ROOT / "docs" / "reports"


def _read_db(db_path: str) -> tuple[list[dict], dict[str, list[dict]], dict[str, list[dict]]]:
    """Read sessions, actions, and llm_calls from a survey DB.

    Returns:
        (sessions, actions_by_session, calls_by_session)
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    sessions = [dict(r) for r in conn.execute(
        "SELECT * FROM sessions ORDER BY game_id"
    ).fetchall()]

    actions_by_session: dict[str, list[dict]] = {}
    for row in conn.execute("SELECT * FROM session_actions ORDER BY session_id, step_num"):
        d = dict(row)
        sid = d["session_id"]
        actions_by_session.setdefault(sid, []).append(d)

    calls_by_session: dict[str, list[dict]] = {}
    for row in conn.execute("SELECT * FROM llm_calls ORDER BY session_id, timestamp"):
        d = dict(row)
        sid = d["session_id"]
        calls_by_session.setdefault(sid, []).append(d)

    conn.close()
    return sessions, actions_by_session, calls_by_session


def generate_reports(db_path: str, batch_report: dict) -> dict:
    """Generate instinct survey reports from a survey DB.

    Args:
        db_path: Path to the survey SQLite DB
        batch_report: The batch_runner report dict (for metadata)

    Returns:
        Dict with 'games' (list of per-game results) and 'summary' (aggregate stats)
    """
    sessions, actions_by_session, calls_by_session = _read_db(db_path)

    if not sessions:
        print("  [report] No sessions found in DB.")
        return {"games": [], "summary": {}}

    # Classify each game
    game_results = []
    for session in sessions:
        sid = session["id"]
        actions = actions_by_session.get(sid, [])
        calls = calls_by_session.get(sid, [])
        result = classify_game(session, actions, calls)
        game_results.append(result)

    # Sort by levels_completed (desc), then by hypothesis_count (desc)
    game_results.sort(
        key=lambda g: (g["levels_completed"], g["hypothesis_count"]),
        reverse=True,
    )

    # Aggregate stats
    instinct_dist = Counter(g["instinct_class"] for g in game_results)
    total_games = len(game_results)
    total_steps = sum(g["steps_taken"] for g in game_results)
    total_cost = sum(g["total_cost_usd"] for g in game_results)
    avg_change_awareness = (
        sum(g["change_awareness"]["ratio"] for g in game_results) / total_games
        if total_games > 0 else 0
    )

    summary = {
        "total_games": total_games,
        "total_steps": total_steps,
        "total_cost_usd": round(total_cost, 4),
        "instinct_distribution": dict(instinct_dist.most_common()),
        "avg_change_awareness_ratio": round(avg_change_awareness, 3),
        "games_with_levels": sum(1 for g in game_results if g["levels_completed"] > 0),
        "games_with_hypotheses": sum(1 for g in game_results if g["hypothesis_count"] >= 2),
        "timestamp": datetime.utcnow().isoformat(),
        "db_path": db_path,
    }

    survey_data = {
        "summary": summary,
        "games": game_results,
    }

    # Write JSON report
    _REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = _REPORTS_DIR / "instinct-survey.json"
    json_path.write_text(json.dumps(survey_data, indent=2))
    print(f"  [report] JSON written: {json_path}")

    # Write Markdown report
    md_path = _REPORTS_DIR / "instinct-survey.md"
    md_path.write_text(_render_markdown(survey_data))
    print(f"  [report] Markdown written: {md_path}")

    return survey_data


def _render_markdown(data: dict) -> str:
    """Render a human-readable Markdown summary from survey data."""
    s = data["summary"]
    games = data["games"]
    lines = []

    lines.append("# ARC-AGI-3 Instinct Survey Results")
    lines.append("")
    lines.append(f"**Generated:** {s['timestamp']}")
    lines.append(f"**Total games:** {s['total_games']}")
    lines.append(f"**Total steps:** {s['total_steps']}")
    lines.append(f"**Total cost (est.):** ${s['total_cost_usd']:.4f}")
    lines.append(f"**Games with levels completed:** {s['games_with_levels']}")
    lines.append(f"**Games showing hypothesis behavior:** {s['games_with_hypotheses']}")
    lines.append(f"**Avg change awareness ratio:** {s['avg_change_awareness_ratio']:.3f}")
    lines.append("")

    # Instinct distribution
    lines.append("---")
    lines.append("")
    lines.append("## Instinct Distribution")
    lines.append("")
    lines.append("| Category | Count | % |")
    lines.append("|----------|------:|--:|")
    for cat, count in sorted(s["instinct_distribution"].items(),
                             key=lambda x: -x[1]):
        pct = count / s["total_games"] * 100 if s["total_games"] > 0 else 0
        lines.append(f"| `{cat}` | {count} | {pct:.0f}% |")
    lines.append("")

    # Games ranked by levels completed
    lines.append("---")
    lines.append("")
    lines.append("## Game Rankings (by levels completed)")
    lines.append("")
    lines.append("| Rank | Game | Levels | Steps | Instinct | Hypotheses | Change Awareness |")
    lines.append("|-----:|------|-------:|------:|----------|----------:|-----------------:|")
    for i, g in enumerate(games, 1):
        lines.append(
            f"| {i} | `{g['game_id']}` | {g['levels_completed']} | {g['steps_taken']} | "
            f"`{g['instinct_class']}` | {g['hypothesis_count']} | "
            f"{g['change_awareness']['ratio']:.2f} |"
        )
    lines.append("")

    # Most promising games
    promising = [g for g in games if g["hypothesis_count"] >= 2 or g["levels_completed"] > 0]
    if promising:
        lines.append("---")
        lines.append("")
        lines.append("## Most Promising Games")
        lines.append("")
        for g in promising[:10]:
            lines.append(f"### `{g['game_id']}` — {g['instinct_class']}")
            lines.append(f"- **Levels:** {g['levels_completed']} | "
                         f"**Steps:** {g['steps_taken']} | "
                         f"**Hypotheses:** {g['hypothesis_count']}")
            lines.append(f"- **First impression:** {g['first_impression'][:200]}")
            lines.append(f"- **Action distribution:** {g['action_distribution']}")
            if g["strategy_phases"]:
                lines.append(f"- **Strategy phases:**")
                for p in g["strategy_phases"]:
                    lines.append(f"  - Steps {p['steps']}: {p['label']} — {p['summary']}")
            lines.append("")

    # Worst games (frozen or completely lost)
    worst = [g for g in games if g["instinct_class"] in ("frozen", "random_clicker")
             and g["levels_completed"] == 0]
    if worst:
        lines.append("---")
        lines.append("")
        lines.append("## Worst Games (frozen / random)")
        lines.append("")
        for g in worst[:10]:
            lines.append(f"- **`{g['game_id']}`** — {g['instinct_class']} | "
                         f"Steps: {g['steps_taken']} | "
                         f"Top actions: {_top_actions_str(g['action_distribution'])}")
        lines.append("")

    # Common failure patterns
    lines.append("---")
    lines.append("")
    lines.append("## Common Failure Patterns")
    lines.append("")

    # Aggregate action distributions across all games
    all_actions = Counter()
    for g in games:
        for act, cnt in g["action_distribution"].items():
            all_actions[act] += cnt
    total_all = sum(all_actions.values())
    lines.append("### Global Action Distribution")
    lines.append("")
    lines.append("| Action | Count | % |")
    lines.append("|--------|------:|--:|")
    for act, cnt in all_actions.most_common():
        pct = cnt / total_all * 100 if total_all > 0 else 0
        lines.append(f"| `{act}` | {cnt} | {pct:.0f}% |")
    lines.append("")

    # Observations
    lines.append("### Observations")
    lines.append("")
    frozen_count = s["instinct_distribution"].get("frozen", 0)
    clicker_count = s["instinct_distribution"].get("random_clicker", 0)
    if frozen_count > 0:
        lines.append(f"- **{frozen_count}** games show frozen behavior "
                     f"(agent repeats same action >90% of the time)")
    if clicker_count > 0:
        lines.append(f"- **{clicker_count}** games show random clicking "
                     f"(no clear strategy or hypothesis)")
    if s["avg_change_awareness_ratio"] < 0.2:
        lines.append(f"- Low average change awareness ({s['avg_change_awareness_ratio']:.2f}) — "
                     f"agent often ignores grid changes after actions")
    if s["games_with_hypotheses"] > 0:
        lines.append(f"- **{s['games_with_hypotheses']}** games show hypothesis-forming behavior — "
                     f"the agent's training data gives it some scientific instinct")
    lines.append("")

    return "\n".join(lines)


def _top_actions_str(action_dist: dict, top_n: int = 3) -> str:
    """Format top N actions as a compact string."""
    sorted_actions = sorted(action_dist.items(), key=lambda x: -x[1])
    return ", ".join(f"{a}={c}" for a, c in sorted_actions[:top_n])
