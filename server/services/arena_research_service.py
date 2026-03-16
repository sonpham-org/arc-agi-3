# Author: Claude Opus 4.6
# Date: 2026-03-16 01:30
# PURPOSE: Service layer for Arena Auto Research. Validates inputs, orchestrates
#   DB calls from db_arena.py, enforces rate limits and submission gates.
#   Pure business logic — no Flask request/response objects.
# SRP/DRY check: Pass — validation/orchestration only, DB ops in db_arena.py
"""Arena Auto Research service — validation and orchestration."""

import logging
import re
import time

from db_arena import (
    arena_get_or_create_research,
    arena_get_leaderboard,
    arena_submit_agent,
    arena_get_agent,
    arena_record_game,
    arena_get_recent_games,
    arena_get_game,
    arena_prune_weak_agents,
    arena_get_comments,
    arena_post_comment,
    arena_vote_comment,
    arena_get_program,
    arena_propose_program,
    arena_vote_program,
    arena_apply_program_vote,
    arena_submit_human_result,
    arena_get_or_create_human_agent,
    arena_get_research_stats,
    arena_strip_excess_history,
    MAX_ACTIVE_AGENTS_PER_GAME,
    ELO_GAP_SKIP,
)

log = logging.getLogger(__name__)

# Valid Arena game IDs (must match ARENA_GAMES in arena.js)
# Only snake enabled for now — re-enable others when ready
ARENA_GAME_IDS = {
    "snake",
    "chess960",
    "othello",
}
_ALL_ARENA_GAME_IDS = {
    "snake", "tron", "connect4", "chess960",
    "othello", "go9", "gomoku", "artillery", "poker",
}

# Rate limits (in-memory, resets on server restart)
_submission_counts = {}  # {(user_id, game_id, date_str): count}
DAILY_SUBMISSION_LIMIT = 10
DAILY_GLOBAL_LIMIT = 500


# ═══════════════════════════════════════════════════════════════════════════
# VALIDATION
# ═══════════════════════════════════════════════════════════════════════════

def validate_game_id(game_id):
    """Returns (is_valid, error_msg)."""
    if not game_id or game_id not in ARENA_GAME_IDS:
        return False, f"Invalid game_id. Must be one of: {', '.join(sorted(ARENA_GAME_IDS))}"
    return True, ""


def validate_agent_name(name):
    """Returns (is_valid, error_msg)."""
    if not name:
        return False, "Agent name required"
    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]{0,63}$', name):
        return False, "Name must be 1-64 chars: letters, digits, underscores; start with letter/underscore"
    return True, ""


def validate_agent_code(code):
    """Returns (is_valid, error_msg)."""
    if not code:
        return False, "Agent code required"
    if len(code) > 50000:
        return False, "Code too large (max 50KB)"
    if "getMove" not in code and "get_move" not in code:
        return False, "Code must contain a getMove or get_move function"
    # Basic safety: block dangerous patterns
    dangerous = ["fetch(", "XMLHttpRequest", "require(", "import(", "eval(", "Function("]
    for d in dangerous:
        if d in code:
            return False, f"Forbidden pattern: {d}"
    return True, ""


def validate_comment(content):
    """Returns (is_valid, error_msg)."""
    if not content or not content.strip():
        return False, "Comment cannot be empty"
    if len(content) > 5000:
        return False, "Comment too long (max 5000 chars)"
    return True, ""


def check_submission_rate(user_id, game_id):
    """Check if user is within daily submission limit. Returns (allowed, error_msg)."""
    today = time.strftime("%Y-%m-%d")
    key = (user_id, game_id, today)
    count = _submission_counts.get(key, 0)
    if count >= DAILY_SUBMISSION_LIMIT:
        return False, f"Daily submission limit reached ({DAILY_SUBMISSION_LIMIT}/day)"
    return True, ""


def record_submission(user_id, game_id):
    """Record a submission for rate limiting."""
    today = time.strftime("%Y-%m-%d")
    key = (user_id, game_id, today)
    _submission_counts[key] = _submission_counts.get(key, 0) + 1


# ═══════════════════════════════════════════════════════════════════════════
# ORCHESTRATION
# ═══════════════════════════════════════════════════════════════════════════

def get_research_overview(game_id):
    """Get full research overview for a game: stats + leaderboard + program."""
    ok, err = validate_game_id(game_id)
    if not ok:
        return {"error": err}
    arena_get_or_create_research(game_id)
    stats = arena_get_research_stats(game_id)
    leaderboard = arena_get_leaderboard(game_id, limit=200)
    program = arena_get_program(game_id)
    return {
        **stats,
        "leaderboard": leaderboard,
        "program": program,
    }


def submit_agent(game_id, name, code, contributor=None):
    """Validate and submit an agent. Returns agent dict or error."""
    ok, err = validate_game_id(game_id)
    if not ok:
        return {"error": err}
    ok, err = validate_agent_name(name)
    if not ok:
        return {"error": err}
    ok, err = validate_agent_code(code)
    if not ok:
        return {"error": err}
    if contributor:
        ok, err = check_submission_rate(contributor, game_id)
        if not ok:
            return {"error": err}

    arena_get_or_create_research(game_id)
    result = arena_submit_agent(game_id, name, code, contributor=contributor)
    if isinstance(result, str):
        return {"error": result}

    if contributor:
        record_submission(contributor, game_id)
    return result


def submit_game_result(game_id, agent1_id, agent2_id, winner_id,
                       scores, turns, history=None):
    """Validate and record a game result."""
    ok, err = validate_game_id(game_id)
    if not ok:
        return {"error": err}
    return arena_record_game(game_id, agent1_id, agent2_id, winner_id,
                             scores, turns, history)


def should_skip_match(agent1_id, agent2_id, game_id):
    """Check if a match should be skipped due to ELO gap."""
    a1 = arena_get_agent(game_id, agent1_id)
    a2 = arena_get_agent(game_id, agent2_id)
    if not a1 or not a2:
        return True
    gap = abs(a1["elo"] - a2["elo"])
    if gap > ELO_GAP_SKIP:
        # Allow if either agent is provisional (< 20 games)
        if a1["games_played"] < 20 or a2["games_played"] < 20:
            return False
        return True
    return False


def submit_human_play(game_id, opponent_agent_id, delay_ms, winner, turns):
    """Validate and submit a human play result."""
    ok, err = validate_game_id(game_id)
    if not ok:
        return {"error": err}
    if winner not in ("human", "ai", "draw"):
        return {"error": "winner must be 'human', 'ai', or 'draw'"}
    if delay_ms not in (0, 250, 500, 1000, 2000):
        return {"error": "delay_ms must be 0 (infinite), 250, 500, 1000, or 2000"}
    return arena_submit_human_result(game_id, opponent_agent_id, delay_ms, winner, turns)


def run_cleanup(game_id=None):
    """Run maintenance: strip excess history (FIFO), prune agents. Game records kept forever."""
    arena_strip_excess_history(game_id)
    if game_id:
        stats = arena_get_research_stats(game_id)
        if stats["agent_count"] > MAX_ACTIVE_AGENTS_PER_GAME:
            excess = stats["agent_count"] - MAX_ACTIVE_AGENTS_PER_GAME
            arena_prune_weak_agents(game_id, excess)
