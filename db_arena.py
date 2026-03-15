# Author: Claude Opus 4.6
# Date: 2026-03-15 22:00
# PURPOSE: Database operations for Arena Auto Research. Manages arena_agents,
#   arena_games, arena_research, arena_comments, arena_program_versions,
#   arena_votes, and arena_human_sessions tables. Handles ELO calculations,
#   agent pruning, game storage limits, and upset detection.
# SRP/DRY check: Pass — arena-specific DB ops only, follows db_sessions/db_auth pattern
"""Arena Auto Research database operations."""

import json
import logging
import random
import time

from db import _db, _get_db

log = logging.getLogger(__name__)

# Constants
ELO_K = 32
ELO_K_PROVISIONAL = 64  # Higher K for first 20 games
ELO_START = 1000.0
PROVISIONAL_GAMES = 20
MAX_STORED_GAMES_PER_PAIR = 10
MAX_ACTIVE_AGENTS_PER_GAME = 200
ELO_GAP_SKIP = 400
UPSET_ELO_GAP = 200
MAX_UPSET_RECORDS = 500
HISTORY_TTL_SECONDS = 48 * 3600  # 48 hours
GAME_RECORD_TTL_SECONDS = 90 * 24 * 3600  # 90 days


# ═══════════════════════════════════════════════════════════════════════════
# RESEARCH STATE
# ═══════════════════════════════════════════════════════════════════════════

def arena_get_or_create_research(game_id):
    """Get or create research state for a game. Returns dict."""
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM arena_research WHERE game_id = ?", (game_id,)
        ).fetchone()
        if row:
            return dict(row)
        conn.execute(
            "INSERT INTO arena_research (game_id, program_md, status) VALUES (?, '', 'stopped')",
            (game_id,)
        )
        row = conn.execute(
            "SELECT * FROM arena_research WHERE game_id = ?", (game_id,)
        ).fetchone()
        return dict(row)


def arena_get_research_stats(game_id):
    """Get summary stats for a game's research."""
    with _db() as conn:
        research = conn.execute(
            "SELECT * FROM arena_research WHERE game_id = ?", (game_id,)
        ).fetchone()
        agent_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM arena_agents WHERE game_id = ? AND active = 1",
            (game_id,)
        ).fetchone()["cnt"]
        game_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM arena_games WHERE game_id = ?",
            (game_id,)
        ).fetchone()["cnt"]
        best = conn.execute(
            "SELECT name, elo FROM arena_agents WHERE game_id = ? AND active = 1 ORDER BY elo DESC LIMIT 1",
            (game_id,)
        ).fetchone()
        return {
            "game_id": game_id,
            "generation": research["generation"] if research else 0,
            "status": research["status"] if research else "stopped",
            "agent_count": agent_count,
            "game_count": game_count,
            "best_agent": best["name"] if best else None,
            "best_elo": round(best["elo"], 1) if best else None,
        }


# ═══════════════════════════════════════════════════════════════════════════
# AGENTS
# ═══════════════════════════════════════════════════════════════════════════

def arena_get_leaderboard(game_id, limit=100):
    """Get ELO-sorted leaderboard for a game."""
    with _db() as conn:
        rows = conn.execute("""
            SELECT id, game_id, name, generation, elo, peak_elo,
                   games_played, wins, losses, draws, contributor,
                   is_human, is_anchor, active, created_at,
                   CASE WHEN games_played > 0
                        THEN ROUND(wins * 100.0 / games_played, 1)
                        ELSE 0 END as win_pct
            FROM arena_agents
            WHERE game_id = ? AND active = 1
            ORDER BY elo DESC LIMIT ?
        """, (game_id, limit)).fetchall()
        return [dict(r) for r in rows]


def arena_submit_agent(game_id, name, code, generation=0, contributor=None,
                       is_human=0, is_anchor=0):
    """Submit a new agent or update existing. Returns agent dict or error string."""
    with _db() as conn:
        # Check active agent cap (skip for human pseudo-agents)
        if not is_human:
            active_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM arena_agents WHERE game_id = ? AND active = 1",
                (game_id,)
            ).fetchone()["cnt"]
            if active_count >= MAX_ACTIVE_AGENTS_PER_GAME:
                # Try to prune weak agents first
                pruned = _prune_weak(conn, game_id, 1)
                if pruned == 0:
                    return "Agent pool full (200 active). No weak agents (ELO < 1000) to prune."

        existing = conn.execute(
            "SELECT id FROM arena_agents WHERE game_id = ? AND name = ?",
            (game_id, name)
        ).fetchone()
        if existing:
            conn.execute(
                "UPDATE arena_agents SET code = ?, generation = ?, contributor = ?, active = 1 WHERE id = ?",
                (code, generation, contributor, existing["id"])
            )
            agent_id = existing["id"]
        else:
            conn.execute(
                """INSERT INTO arena_agents
                   (game_id, name, code, generation, elo, peak_elo, contributor, is_human, is_anchor)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (game_id, name, code, generation, ELO_START, ELO_START,
                 contributor, is_human, is_anchor)
            )
            agent_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        row = conn.execute("SELECT * FROM arena_agents WHERE id = ?", (agent_id,)).fetchone()
        return dict(row)


def arena_get_agent(game_id, agent_id):
    """Get a single agent by ID."""
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM arena_agents WHERE id = ? AND game_id = ?",
            (agent_id, game_id)
        ).fetchone()
        return dict(row) if row else None


def arena_prune_weak_agents(game_id, count=10):
    """Randomly deactivate agents with ELO < 1000. Returns number pruned."""
    with _db() as conn:
        return _prune_weak(conn, game_id, count)


def _prune_weak(conn, game_id, count):
    """Internal prune — operates on an existing connection."""
    weak = conn.execute(
        """SELECT id FROM arena_agents
           WHERE game_id = ? AND active = 1 AND elo < 1000
                 AND is_anchor = 0 AND is_human = 0
                 AND games_played >= ?""",
        (game_id, PROVISIONAL_GAMES)
    ).fetchall()
    if not weak:
        return 0
    weak_ids = [r["id"] for r in weak]
    to_prune = random.sample(weak_ids, min(count, len(weak_ids)))
    for aid in to_prune:
        conn.execute("UPDATE arena_agents SET active = 0 WHERE id = ?", (aid,))
    return len(to_prune)


# ═══════════════════════════════════════════════════════════════════════════
# GAMES & ELO
# ═══════════════════════════════════════════════════════════════════════════

def arena_record_game(game_id, agent1_id, agent2_id, winner_id,
                      scores, turns, history=None):
    """Record a game and update ELO. Enforces storage limits.

    Returns: dict with game_id and elo updates, or None if skipped.
    """
    with _db() as conn:
        a1 = conn.execute("SELECT * FROM arena_agents WHERE id = ?", (agent1_id,)).fetchone()
        a2 = conn.execute("SELECT * FROM arena_agents WHERE id = ?", (agent2_id,)).fetchone()
        if not a1 or not a2:
            return None

        elo_gap = abs(a1["elo"] - a2["elo"])

        # Determine ELO result
        if winner_id == agent1_id:
            elo_result = 1.0
        elif winner_id == agent2_id:
            elo_result = 0.0
        else:
            elo_result = 0.5

        # Detect upset
        is_upset = 0
        if winner_id and elo_gap > UPSET_ELO_GAP:
            winner_elo = a1["elo"] if winner_id == agent1_id else a2["elo"]
            loser_elo = a2["elo"] if winner_id == agent1_id else a1["elo"]
            if winner_elo < loser_elo:
                is_upset = 1

        # Decide whether to store history
        pair_count = _count_pair(conn, agent1_id, agent2_id)
        history_json = "[]"
        if history and pair_count < MAX_STORED_GAMES_PER_PAIR:
            history_json = json.dumps(history)
        elif history and is_upset:
            # Always store upset history (up to cap)
            upset_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM arena_games WHERE game_id = ? AND is_upset = 1",
                (game_id,)
            ).fetchone()["cnt"]
            if upset_count < MAX_UPSET_RECORDS:
                history_json = json.dumps(history)

        conn.execute(
            """INSERT INTO arena_games
               (game_id, agent1_id, agent2_id, winner_id,
                agent1_score, agent2_score, turns, history, is_upset)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (game_id, agent1_id, agent2_id, winner_id,
             scores[0], scores[1], turns, history_json, is_upset)
        )
        game_row_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Update agent stats
        for aid in [agent1_id, agent2_id]:
            conn.execute(
                "UPDATE arena_agents SET games_played = games_played + 1 WHERE id = ?",
                (aid,)
            )
        if winner_id is None:
            conn.execute(
                "UPDATE arena_agents SET draws = draws + 1 WHERE id IN (?, ?)",
                (agent1_id, agent2_id)
            )
        else:
            loser_id = agent2_id if winner_id == agent1_id else agent1_id
            conn.execute("UPDATE arena_agents SET wins = wins + 1 WHERE id = ?", (winner_id,))
            conn.execute("UPDATE arena_agents SET losses = losses + 1 WHERE id = ?", (loser_id,))

        # ELO update
        new_elos = _update_elo(conn, agent1_id, agent2_id, elo_result)

        return {
            "game_id": game_row_id,
            "is_upset": is_upset,
            "elo_updates": new_elos,
        }


def arena_update_elo(agent1_id, agent2_id, result):
    """Standalone ELO update (used by external callers)."""
    with _db() as conn:
        return _update_elo(conn, agent1_id, agent2_id, result)


def _update_elo(conn, agent1_id, agent2_id, result):
    """Update ELO ratings. result: 1.0=a1 wins, 0.0=a2 wins, 0.5=draw."""
    a1 = conn.execute("SELECT elo, games_played FROM arena_agents WHERE id = ?", (agent1_id,)).fetchone()
    a2 = conn.execute("SELECT elo, games_played FROM arena_agents WHERE id = ?", (agent2_id,)).fetchone()
    if not a1 or not a2:
        return {}

    k1 = ELO_K_PROVISIONAL if a1["games_played"] < PROVISIONAL_GAMES else ELO_K
    k2 = ELO_K_PROVISIONAL if a2["games_played"] < PROVISIONAL_GAMES else ELO_K

    e1 = 1.0 / (1.0 + 10 ** ((a2["elo"] - a1["elo"]) / 400))
    e2 = 1.0 - e1

    new1 = a1["elo"] + k1 * (result - e1)
    new2 = a2["elo"] + k2 * ((1.0 - result) - e2)

    conn.execute(
        "UPDATE arena_agents SET elo = ?, peak_elo = MAX(peak_elo, ?) WHERE id = ?",
        (new1, new1, agent1_id)
    )
    conn.execute(
        "UPDATE arena_agents SET elo = ?, peak_elo = MAX(peak_elo, ?) WHERE id = ?",
        (new2, new2, agent2_id)
    )
    return {agent1_id: round(new1, 1), agent2_id: round(new2, 1)}


def arena_count_pair_games(agent1_id, agent2_id):
    """Count stored games between two agents."""
    with _db() as conn:
        return _count_pair(conn, agent1_id, agent2_id)


def _count_pair(conn, id1, id2):
    row = conn.execute(
        """SELECT COUNT(*) as cnt FROM arena_games
           WHERE (agent1_id=? AND agent2_id=?) OR (agent1_id=? AND agent2_id=?)""",
        (id1, id2, id2, id1)
    ).fetchone()
    return row["cnt"] if row else 0


def arena_get_recent_games(game_id, limit=50):
    """Get recent games for a game type."""
    with _db() as conn:
        rows = conn.execute("""
            SELECT g.id, g.agent1_id, g.agent2_id, g.winner_id,
                   g.agent1_score, g.agent2_score, g.turns, g.is_upset, g.created_at,
                   a1.name as agent1_name, a1.elo as agent1_elo,
                   a2.name as agent2_name, a2.elo as agent2_elo,
                   CASE WHEN g.winner_id IS NULL THEN 'Draw'
                        WHEN g.winner_id = g.agent1_id THEN a1.name
                        ELSE a2.name END as winner_name
            FROM arena_games g
            JOIN arena_agents a1 ON g.agent1_id = a1.id
            JOIN arena_agents a2 ON g.agent2_id = a2.id
            WHERE g.game_id = ?
            ORDER BY g.created_at DESC LIMIT ?
        """, (game_id, limit)).fetchall()
        return [dict(r) for r in rows]


def arena_get_game(game_id, match_id):
    """Get a single game with full history."""
    with _db() as conn:
        row = conn.execute("""
            SELECT g.*, a1.name as agent1_name, a2.name as agent2_name,
                   a1.elo as agent1_elo, a2.elo as agent2_elo,
                   CASE WHEN g.winner_id IS NULL THEN 'Draw'
                        WHEN g.winner_id = g.agent1_id THEN a1.name
                        ELSE a2.name END as winner_name
            FROM arena_games g
            JOIN arena_agents a1 ON g.agent1_id = a1.id
            JOIN arena_agents a2 ON g.agent2_id = a2.id
            WHERE g.id = ? AND g.game_id = ?
        """, (match_id, game_id)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["history"] = json.loads(d["history"]) if d["history"] else []
        return d


# ═══════════════════════════════════════════════════════════════════════════
# COMMENTS
# ═══════════════════════════════════════════════════════════════════════════

def arena_get_comments(game_id, limit=100):
    """Get strategy comments for a game."""
    with _db() as conn:
        rows = conn.execute("""
            SELECT * FROM arena_comments
            WHERE game_id = ?
            ORDER BY created_at DESC LIMIT ?
        """, (game_id, limit)).fetchall()
        return [dict(r) for r in rows]


def arena_post_comment(game_id, user_id, username, content,
                       comment_type="strategy", parent_id=None):
    """Post a strategy comment."""
    with _db() as conn:
        conn.execute(
            """INSERT INTO arena_comments
               (game_id, user_id, username, content, comment_type, parent_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (game_id, user_id, username, content, comment_type, parent_id)
        )
        cid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        row = conn.execute("SELECT * FROM arena_comments WHERE id = ?", (cid,)).fetchone()
        return dict(row)


def arena_vote_comment(comment_id, user_id, vote):
    """Upvote (+1) or downvote (-1) a comment. Returns updated comment."""
    with _db() as conn:
        # Check existing vote
        existing = conn.execute(
            "SELECT vote FROM arena_votes WHERE version_id = ? AND user_id = ?",
            (comment_id, user_id)
        ).fetchone()
        if existing:
            # Reverse old vote
            old = existing["vote"]
            if old == vote:
                return None  # Already voted same way
            col = "upvotes" if old > 0 else "downvotes"
            conn.execute(f"UPDATE arena_comments SET {col} = {col} - 1 WHERE id = ?", (comment_id,))
            conn.execute(
                "UPDATE arena_votes SET vote = ? WHERE version_id = ? AND user_id = ?",
                (vote, comment_id, user_id)
            )
        else:
            conn.execute(
                "INSERT INTO arena_votes (game_id, version_id, user_id, vote) VALUES ('', ?, ?, ?)",
                (comment_id, user_id, vote)
            )
        col = "upvotes" if vote > 0 else "downvotes"
        conn.execute(f"UPDATE arena_comments SET {col} = {col} + 1 WHERE id = ?", (comment_id,))
        row = conn.execute("SELECT * FROM arena_comments WHERE id = ?", (comment_id,)).fetchone()
        return dict(row) if row else None


# ═══════════════════════════════════════════════════════════════════════════
# PROGRAM.MD VERSIONING & VOTING
# ═══════════════════════════════════════════════════════════════════════════

def arena_get_program(game_id):
    """Get current program.md and version history."""
    with _db() as conn:
        research = conn.execute(
            "SELECT program_md, program_version FROM arena_research WHERE game_id = ?",
            (game_id,)
        ).fetchone()
        versions = conn.execute(
            "SELECT id, version, author, change_summary, votes_for, votes_against, vote_deadline, applied, created_at FROM arena_program_versions WHERE game_id = ? ORDER BY version DESC LIMIT 20",
            (game_id,)
        ).fetchall()
        # Check for active proposal (vote_deadline in the future)
        now = time.time()
        active_proposal = conn.execute(
            "SELECT * FROM arena_program_versions WHERE game_id = ? AND vote_deadline > ? AND applied = 0 ORDER BY id DESC LIMIT 1",
            (game_id, now)
        ).fetchone()
        return {
            "content": research["program_md"] if research else "",
            "version": research["program_version"] if research else 0,
            "versions": [dict(v) for v in versions],
            "active_proposal": dict(active_proposal) if active_proposal else None,
        }


def arena_propose_program(game_id, content, author, change_summary, vote_seconds=10):
    """Propose a program.md change. Starts a vote with deadline."""
    with _db() as conn:
        research = conn.execute(
            "SELECT program_version FROM arena_research WHERE game_id = ?", (game_id,)
        ).fetchone()
        current_version = research["program_version"] if research else 0
        new_version = current_version + 1
        deadline = time.time() + vote_seconds

        conn.execute(
            """INSERT INTO arena_program_versions
               (game_id, version, content, author, change_summary, vote_deadline)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (game_id, new_version, content, author, change_summary, deadline)
        )
        pid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        row = conn.execute("SELECT * FROM arena_program_versions WHERE id = ?", (pid,)).fetchone()
        return dict(row)


def arena_vote_program(version_id, user_id, vote):
    """Vote on a program.md proposal. vote: +1 or -1."""
    with _db() as conn:
        # Check deadline
        prop = conn.execute(
            "SELECT * FROM arena_program_versions WHERE id = ?", (version_id,)
        ).fetchone()
        if not prop:
            return {"error": "Proposal not found"}
        if prop["applied"]:
            return {"error": "Already applied"}
        if time.time() > prop["vote_deadline"]:
            return {"error": "Voting period ended"}

        try:
            conn.execute(
                "INSERT INTO arena_votes (game_id, version_id, user_id, vote) VALUES (?, ?, ?, ?)",
                (prop["game_id"], version_id, user_id, vote)
            )
        except Exception:
            return {"error": "Already voted"}

        col = "votes_for" if vote > 0 else "votes_against"
        conn.execute(
            f"UPDATE arena_program_versions SET {col} = {col} + 1 WHERE id = ?",
            (version_id,)
        )
        row = conn.execute("SELECT * FROM arena_program_versions WHERE id = ?", (version_id,)).fetchone()
        return dict(row)


def arena_apply_program_vote(version_id):
    """Apply a program.md proposal if votes_for > votes_against."""
    with _db() as conn:
        prop = conn.execute(
            "SELECT * FROM arena_program_versions WHERE id = ?", (version_id,)
        ).fetchone()
        if not prop or prop["applied"]:
            return False
        if prop["votes_for"] > prop["votes_against"]:
            conn.execute(
                "UPDATE arena_research SET program_md = ?, program_version = ?, updated_at = ? WHERE game_id = ?",
                (prop["content"], prop["version"], time.time(), prop["game_id"])
            )
            conn.execute(
                "UPDATE arena_program_versions SET applied = 1 WHERE id = ?", (version_id,)
            )
            return True
        # Rejected
        conn.execute("UPDATE arena_program_versions SET applied = -1 WHERE id = ?", (version_id,))
        return False


# ═══════════════════════════════════════════════════════════════════════════
# HUMAN PLAY
# ═══════════════════════════════════════════════════════════════════════════

def arena_get_or_create_human_agent(game_id, delay_ms):
    """Get or create the human-{delay}ms pseudo-agent for a game."""
    delay_label = f"{delay_ms}ms" if delay_ms > 0 else "inf"
    name = f"human-{delay_label}"
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM arena_agents WHERE game_id = ? AND name = ?",
            (game_id, name)
        ).fetchone()
        if row:
            return dict(row)
        conn.execute(
            """INSERT INTO arena_agents
               (game_id, name, code, generation, elo, peak_elo, contributor, is_human)
               VALUES (?, ?, 'human', 0, ?, ?, 'human', 1)""",
            (game_id, name, ELO_START, ELO_START)
        )
        aid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        row = conn.execute("SELECT * FROM arena_agents WHERE id = ?", (aid,)).fetchone()
        return dict(row)


def arena_submit_human_result(game_id, opponent_agent_id, delay_ms, winner, turns):
    """Submit a human vs AI game result. Updates ELO for both."""
    human_agent = arena_get_or_create_human_agent(game_id, delay_ms)
    human_id = human_agent["id"]

    if winner == "human":
        winner_id = human_id
    elif winner == "ai":
        winner_id = opponent_agent_id
    else:
        winner_id = None

    result = arena_record_game(
        game_id=game_id,
        agent1_id=human_id,
        agent2_id=opponent_agent_id,
        winner_id=winner_id,
        scores=(1 if winner == "human" else 0, 1 if winner == "ai" else 0),
        turns=turns,
    )

    # Also log to human sessions table
    with _db() as conn:
        conn.execute(
            """INSERT INTO arena_human_sessions
               (game_id, human_agent_id, opponent_id, delay_ms, winner, turns)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (game_id, human_id, opponent_agent_id, delay_ms, winner, turns)
        )

    return result


# ═══════════════════════════════════════════════════════════════════════════
# CLEANUP / MAINTENANCE
# ═══════════════════════════════════════════════════════════════════════════

def arena_strip_old_history(game_id=None):
    """Strip history JSON from games older than 48h (keep upsets)."""
    cutoff = time.time() - HISTORY_TTL_SECONDS
    with _db() as conn:
        if game_id:
            conn.execute(
                """UPDATE arena_games SET history = '[]'
                   WHERE game_id = ? AND created_at < ? AND is_upset = 0
                         AND history != '[]'""",
                (game_id, cutoff)
            )
        else:
            conn.execute(
                """UPDATE arena_games SET history = '[]'
                   WHERE created_at < ? AND is_upset = 0 AND history != '[]'""",
                (cutoff,)
            )


def arena_delete_old_games(game_id=None):
    """Delete game records older than 90 days."""
    cutoff = time.time() - GAME_RECORD_TTL_SECONDS
    with _db() as conn:
        if game_id:
            conn.execute(
                "DELETE FROM arena_games WHERE game_id = ? AND created_at < ?",
                (game_id, cutoff)
            )
        else:
            conn.execute(
                "DELETE FROM arena_games WHERE created_at < ?", (cutoff,)
            )
