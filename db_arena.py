# Author: Claude Opus 4.6
# Date: 2026-03-18 00:15
# PURPOSE: Database operations for Arena Auto Research. Manages arena_agents,
#   arena_games, arena_research, arena_comments, arena_program_versions,
#   arena_votes, arena_human_sessions, arena_llm_calls, and arena_library_requests
#   tables. Handles ELO calculations, agent pruning, game storage limits, upset
#   detection, LLM call monitoring/stats, and library request logging. Supports
#   program_version_id and program_file on agents for program tracking.
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
MAX_GAMES_WITH_HISTORY = 500  # FIFO — keep frame history for last N games only


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


def arena_increment_generation(game_id):
    """Increment and return the generation counter for a game."""
    with _db() as conn:
        row = conn.execute(
            "SELECT generation FROM arena_research WHERE game_id = ?", (game_id,)
        ).fetchone()
        if not row:
            arena_get_or_create_research(game_id)
            row = conn.execute(
                "SELECT generation FROM arena_research WHERE game_id = ?", (game_id,)
            ).fetchone()
        new_gen = (row['generation'] or 0) + 1
        conn.execute(
            "UPDATE arena_research SET generation = ?, updated_at = unixepoch('now') WHERE game_id = ?",
            (new_gen, game_id)
        )
        return new_gen


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
                   program_version_id, program_file,
                   CASE WHEN games_played > 0
                        THEN ROUND(wins * 100.0 / games_played, 1)
                        ELSE 0 END as win_pct
            FROM arena_agents
            WHERE game_id = ? AND active = 1
            ORDER BY elo DESC LIMIT ?
        """, (game_id, limit)).fetchall()
        return [dict(r) for r in rows]


def arena_submit_agent(game_id, name, code, generation=0, contributor=None,
                       is_human=0, is_anchor=0, program_version_id=None,
                       program_file=None):
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
                "UPDATE arena_agents SET code = ?, generation = ?, contributor = ?, program_version_id = ?, program_file = ?, active = 1 WHERE id = ?",
                (code, generation, contributor, program_version_id, program_file, existing["id"])
            )
            agent_id = existing["id"]
        else:
            conn.execute(
                """INSERT INTO arena_agents
                   (game_id, name, code, generation, elo, peak_elo, contributor, is_human, is_anchor, program_version_id, program_file)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (game_id, name, code, generation, ELO_START, ELO_START,
                 contributor, is_human, is_anchor, program_version_id, program_file)
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


def arena_get_agent_by_name(game_id, name):
    """Get a single agent by name."""
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM arena_agents WHERE game_id = ? AND name = ?",
            (game_id, name)
        ).fetchone()
        return dict(row) if row else None


def arena_get_agent_games(game_id, agent_id, limit=5):
    """Get an agent's recent games with summary data."""
    with _db() as conn:
        rows = conn.execute("""
            SELECT g.id, g.agent1_id, g.agent2_id, g.winner_id,
                   g.agent1_score, g.agent2_score, g.turns, g.is_upset,
                   g.history, g.created_at,
                   a1.name as agent1_name, a2.name as agent2_name,
                   CASE WHEN g.winner_id IS NULL THEN 'Draw'
                        WHEN g.winner_id = g.agent1_id THEN a1.name
                        ELSE a2.name END as winner_name
            FROM arena_games g
            JOIN arena_agents a1 ON g.agent1_id = a1.id
            JOIN arena_agents a2 ON g.agent2_id = a2.id
            WHERE g.game_id = ? AND (g.agent1_id = ? OR g.agent2_id = ?)
            ORDER BY g.created_at DESC LIMIT ?
        """, (game_id, agent_id, agent_id, limit)).fetchall()
        return [dict(r) for r in rows]


def arena_get_agent_games_for_profile(game_id, agent_id, limit=20):
    """Get an agent's recent games with opponent ELO for profile view.

    Returns games with history (for replay) where available, plus opponent
    ELO fields so the client can partition into 'vs higher' and 'vs lower'.
    """
    with _db() as conn:
        rows = conn.execute("""
            SELECT g.id, g.agent1_id, g.agent2_id, g.winner_id,
                   g.agent1_score, g.agent2_score, g.turns, g.is_upset,
                   g.history, g.created_at,
                   a1.name as agent1_name, a1.elo as agent1_elo,
                   a1.wins as agent1_wins, a1.losses as agent1_losses,
                   a2.name as agent2_name, a2.elo as agent2_elo,
                   a2.wins as agent2_wins, a2.losses as agent2_losses,
                   CASE WHEN g.winner_id IS NULL THEN 'Draw'
                        WHEN g.winner_id = g.agent1_id THEN a1.name
                        ELSE a2.name END as winner_name
            FROM arena_games g
            JOIN arena_agents a1 ON g.agent1_id = a1.id
            JOIN arena_agents a2 ON g.agent2_id = a2.id
            WHERE g.game_id = ? AND (g.agent1_id = ? OR g.agent2_id = ?)
            ORDER BY g.created_at DESC LIMIT ?
        """, (game_id, agent_id, agent_id, limit)).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            try:
                d['history'] = json.loads(d['history']) if d['history'] else []
            except (json.JSONDecodeError, TypeError):
                d['history'] = []
            results.append(d)
        return results


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

        # Skip entirely if this pair already has enough games
        pair_count = _count_pair(conn, agent1_id, agent2_id)
        if pair_count >= MAX_STORED_GAMES_PER_PAIR:
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


def arena_get_recent_games_with_history(game_id, limit=8):
    """Get recent games that still have replay history (not yet stripped)."""
    with _db() as conn:
        rows = conn.execute("""
            SELECT g.id, g.history, g.turns,
                   a1.name as agent1_name, a1.elo as agent1_elo,
                   a1.wins as agent1_wins, a1.losses as agent1_losses,
                   a2.name as agent2_name, a2.elo as agent2_elo,
                   a2.wins as agent2_wins, a2.losses as agent2_losses,
                   CASE WHEN g.winner_id IS NULL THEN 'Draw'
                        WHEN g.winner_id = g.agent1_id THEN a1.name
                        ELSE a2.name END as winner_name
            FROM arena_games g
            JOIN arena_agents a1 ON g.agent1_id = a1.id
            JOIN arena_agents a2 ON g.agent2_id = a2.id
            WHERE g.game_id = ? AND g.history != '[]' AND g.history IS NOT NULL
            ORDER BY g.created_at DESC LIMIT ?
        """, (game_id, limit)).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            try:
                d['history'] = json.loads(d['history']) if d['history'] else []
            except (json.JSONDecodeError, TypeError):
                d['history'] = []
            if d['history']:
                results.append(d)
        return results


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

def arena_get_comments(game_id, limit=100, comment_type=None):
    """Get comments for a game, optionally filtered by comment_type."""
    with _db() as conn:
        if comment_type:
            rows = conn.execute("""
                SELECT * FROM arena_comments
                WHERE game_id = ? AND comment_type = ?
                ORDER BY created_at DESC LIMIT ?
            """, (game_id, comment_type, limit)).fetchall()
        else:
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


def arena_submit_human_result(game_id, opponent_agent_id, delay_ms, winner, turns,
                              history=None):
    """Submit a human vs AI game result. Updates ELO for both.
    Always stores full history — human games are never stripped."""
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
        history=history,
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

def arena_strip_excess_history(game_id=None):
    """FIFO: strip frame history from all but the most recent N games.
    Game records (outcomes) are kept forever — only the heavy history blob is cleared.
    Exceptions (history is NEVER stripped):
      - Upset games (is_upset = 1)
      - Human vs AI games (either agent has is_human = 1)
    """
    with _db() as conn:
        # Collect IDs of all human agents so we can exclude their games
        human_ids = {r[0] for r in conn.execute(
            "SELECT id FROM arena_agents WHERE is_human = 1"
        ).fetchall()}

        if game_id:
            # Find the Nth newest game with history
            row = conn.execute(
                """SELECT id FROM arena_games
                   WHERE game_id = ? AND history != '[]'
                   ORDER BY created_at DESC LIMIT 1 OFFSET ?""",
                (game_id, MAX_GAMES_WITH_HISTORY)
            ).fetchone()
            if row:
                # Get candidate games to strip
                candidates = conn.execute(
                    """SELECT id, agent1_id, agent2_id FROM arena_games
                       WHERE game_id = ? AND id <= ? AND is_upset = 0
                             AND history != '[]'""",
                    (game_id, row['id'])
                ).fetchall()
                strip_ids = [c['id'] for c in candidates
                             if c['agent1_id'] not in human_ids
                             and c['agent2_id'] not in human_ids]
                if strip_ids:
                    conn.execute(
                        f"UPDATE arena_games SET history = '[]' WHERE id IN ({','.join('?' * len(strip_ids))})",
                        strip_ids
                    )
        else:
            row = conn.execute(
                """SELECT id FROM arena_games
                   WHERE history != '[]'
                   ORDER BY created_at DESC LIMIT 1 OFFSET ?""",
                (MAX_GAMES_WITH_HISTORY,)
            ).fetchone()
            if row:
                candidates = conn.execute(
                    """SELECT id, agent1_id, agent2_id FROM arena_games
                       WHERE id <= ? AND is_upset = 0 AND history != '[]'""",
                    (row['id'],)
                ).fetchall()
                strip_ids = [c['id'] for c in candidates
                             if c['agent1_id'] not in human_ids
                             and c['agent2_id'] not in human_ids]
                if strip_ids:
                    conn.execute(
                        f"UPDATE arena_games SET history = '[]' WHERE id IN ({','.join('?' * len(strip_ids))})",
                        strip_ids
                    )


# ═══════════════════════════════════════════════════════════════════════════
# LLM CALL MONITORING
# ═══════════════════════════════════════════════════════════════════════════

# Model cost per 1M tokens (input, output) in USD
_MODEL_COSTS = {
    'claude-haiku-4-5-20251001': (0.80, 4.00),
    'claude-sonnet-4-6': (3.00, 15.00),
    'claude-opus-4-6': (15.00, 75.00),
}


def arena_log_llm_call(game_id, generation, model, status, http_status,
                        input_tokens=0, output_tokens=0, latency_ms=0,
                        error_message=None, auth_type=None):
    """Log an Anthropic API call from arena evolution."""
    input_cost_per_m, output_cost_per_m = _MODEL_COSTS.get(model, (3.0, 15.0))
    cost_usd = (input_tokens * input_cost_per_m + output_tokens * output_cost_per_m) / 1_000_000
    with _db() as conn:
        conn.execute(
            """INSERT INTO arena_llm_calls
               (game_id, generation, model, status, http_status,
                input_tokens, output_tokens, cost_usd, latency_ms,
                error_message, auth_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (game_id, generation, model, status, http_status,
             input_tokens, output_tokens, cost_usd, latency_ms,
             error_message, auth_type)
        )


def arena_log_evolution_session(game_id, generation, model, provider='anthropic',
                                 status='success', api_calls=0, tool_calls=0,
                                 input_tokens=0, output_tokens=0,
                                 cache_read_tokens=0, cache_creation_tokens=0,
                                 cost_usd=0, total_latency_ms=0, rounds=0,
                                 agents_created=0, error_message=None):
    """Log one evolution session (replaces per-call logging)."""
    try:
        with _db() as conn:
            conn.execute(
                """INSERT INTO arena_evolution_sessions
                   (game_id, generation, model, provider, status,
                    api_calls, tool_calls, input_tokens, output_tokens,
                    cache_read_tokens, cache_creation_tokens, cost_usd,
                    total_latency_ms, rounds, agents_created, error_message)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (game_id, generation, model, provider, status,
                 api_calls, tool_calls, input_tokens, output_tokens,
                 cache_read_tokens, cache_creation_tokens, cost_usd,
                 total_latency_ms, rounds, agents_created, error_message)
            )
    except Exception as e:
        log.warning("Failed to log evolution session: %s", e)


def arena_get_llm_monitor_stats():
    """Get aggregated LLM call stats for the monitoring dashboard."""
    now = time.time()
    hour_ago = now - 3600
    day_ago = now - 86400

    with _db() as conn:
        def _counts(since=None):
            where = f"WHERE created_at >= {since}" if since else ""
            row = conn.execute(f"""
                SELECT COUNT(*) as total,
                       SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                       SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as errors,
                       SUM(CASE WHEN status = 'rate_limited' THEN 1 ELSE 0 END) as rate_limited,
                       SUM(CASE WHEN status = 'retry' THEN 1 ELSE 0 END) as retries,
                       SUM(input_tokens) as total_input_tokens,
                       SUM(output_tokens) as total_output_tokens,
                       SUM(cost_usd) as total_cost,
                       AVG(CASE WHEN status = 'success' THEN latency_ms END) as avg_latency
                FROM arena_llm_calls {where}
            """).fetchone()
            return dict(row)

        stats = {
            'last_hour': _counts(hour_ago),
            'last_24h': _counts(day_ago),
            'all_time': _counts(),
        }

        # Per-model breakdown
        model_rows = conn.execute("""
            SELECT model,
                   COUNT(*) as calls,
                   SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                   SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END) as failures,
                   SUM(input_tokens) as input_tokens,
                   SUM(output_tokens) as output_tokens,
                   SUM(cost_usd) as cost,
                   AVG(CASE WHEN status = 'success' THEN latency_ms END) as avg_latency
            FROM arena_llm_calls
            GROUP BY model ORDER BY calls DESC
        """).fetchall()
        stats['by_model'] = [dict(r) for r in model_rows]

        # Auth type breakdown
        auth_rows = conn.execute("""
            SELECT auth_type,
                   COUNT(*) as calls,
                   SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                   SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END) as failures
            FROM arena_llm_calls
            GROUP BY auth_type
        """).fetchall()
        stats['by_auth'] = [dict(r) for r in auth_rows]

        # Hourly cost buckets (last 72 hours) for burn rate + projection
        hourly_rows = conn.execute("""
            SELECT CAST((created_at / 3600) AS INTEGER) * 3600 as hour_ts,
                   SUM(cost_usd) as cost,
                   COUNT(*) as calls,
                   SUM(input_tokens) as input_tokens,
                   SUM(output_tokens) as output_tokens
            FROM arena_llm_calls
            WHERE created_at >= ? AND status = 'success'
            GROUP BY hour_ts ORDER BY hour_ts
        """, (now - 72 * 3600,)).fetchall()
        stats['hourly_costs'] = [dict(r) for r in hourly_rows]

        # Daily cost buckets (all time) for the daily chart
        daily_rows = conn.execute("""
            SELECT CAST((created_at / 86400) AS INTEGER) * 86400 as day_ts,
                   SUM(cost_usd) as cost,
                   COUNT(*) as calls,
                   SUM(input_tokens) as input_tokens,
                   SUM(output_tokens) as output_tokens,
                   SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success
            FROM arena_llm_calls
            GROUP BY day_ts ORDER BY day_ts
        """).fetchall()
        stats['daily_costs'] = [dict(r) for r in daily_rows]

        # First call timestamp (for "running since")
        first_row = conn.execute(
            "SELECT MIN(created_at) as first_call FROM arena_llm_calls"
        ).fetchone()
        stats['first_call_at'] = first_row['first_call'] if first_row else None

        # Recent errors (last 50)
        error_rows = conn.execute("""
            SELECT id, model, status, http_status, error_message, auth_type,
                   latency_ms, created_at
            FROM arena_llm_calls
            WHERE status != 'success'
            ORDER BY created_at DESC LIMIT 50
        """).fetchall()
        stats['recent_errors'] = [dict(r) for r in error_rows]

        # Recent calls (last 100)
        recent_rows = conn.execute("""
            SELECT id, game_id, generation, model, status, http_status,
                   input_tokens, output_tokens, cost_usd, latency_ms,
                   error_message, auth_type, created_at
            FROM arena_llm_calls
            ORDER BY created_at DESC LIMIT 100
        """).fetchall()
        stats['recent_calls'] = [dict(r) for r in recent_rows]

        # Library requests
        lib_rows = conn.execute("""
            SELECT library_name, game_id, COUNT(*) as request_count,
                   MAX(created_at) as last_requested
            FROM arena_library_requests
            GROUP BY library_name, game_id
            ORDER BY request_count DESC
        """).fetchall()
        stats['library_requests'] = [dict(r) for r in lib_rows]

        # ── Evolution sessions (new session-level monitoring) ──
        session_rows = conn.execute("""
            SELECT id, game_id, generation, model, provider, status,
                   api_calls, tool_calls, input_tokens, output_tokens,
                   cache_read_tokens, cache_creation_tokens, cost_usd,
                   total_latency_ms, rounds, agents_created,
                   error_message, created_at
            FROM arena_evolution_sessions
            ORDER BY created_at DESC LIMIT 100
        """).fetchall()
        stats['recent_sessions'] = [dict(r) for r in session_rows]

        # Session aggregates
        sess_agg = conn.execute("""
            SELECT COUNT(*) as total_sessions,
                   SUM(agents_created) as total_agents,
                   SUM(api_calls) as total_api_calls,
                   SUM(tool_calls) as total_tool_calls,
                   SUM(input_tokens) as total_input_tokens,
                   SUM(output_tokens) as total_output_tokens,
                   SUM(cache_read_tokens) as total_cache_read,
                   SUM(cost_usd) as total_cost,
                   AVG(tool_calls) as avg_tool_calls_per_session,
                   AVG(total_latency_ms) as avg_latency_per_session
            FROM arena_evolution_sessions
        """).fetchone()
        stats['session_totals'] = dict(sess_agg) if sess_agg else {}

        # Per-model session breakdown
        sess_model = conn.execute("""
            SELECT model, provider,
                   COUNT(*) as sessions,
                   SUM(agents_created) as agents,
                   SUM(cost_usd) as cost,
                   AVG(tool_calls) as avg_tools,
                   SUM(cache_read_tokens) as cache_read
            FROM arena_evolution_sessions
            GROUP BY model ORDER BY sessions DESC
        """).fetchall()
        stats['sessions_by_model'] = [dict(r) for r in sess_model]

        return stats


def arena_log_library_request(game_id, agent_name, library_name):
    """Log a missing library import attempt. Non-blocking, never raises."""
    try:
        with _db() as conn:
            # Deduplicate: only log once per game_id + library combo per hour
            existing = conn.execute(
                """SELECT 1 FROM arena_library_requests
                   WHERE game_id = ? AND library_name = ?
                   AND created_at > unixepoch('now') - 3600""",
                (game_id, library_name)
            ).fetchone()
            if not existing:
                conn.execute(
                    """INSERT INTO arena_library_requests
                       (game_id, agent_name, library_name)
                       VALUES (?, ?, ?)""",
                    (game_id, agent_name, library_name)
                )
                print(f'[arena] Library request: {library_name} (game={game_id}, agent={agent_name})')
    except Exception:
        pass


def arena_get_library_requests():
    """Get aggregated library requests for the monitor page."""
    try:
        with _db() as conn:
            rows = conn.execute("""
                SELECT library_name, game_id, COUNT(*) as request_count,
                       MAX(created_at) as last_requested
                FROM arena_library_requests
                GROUP BY library_name, game_id
                ORDER BY request_count DESC
            """).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []
