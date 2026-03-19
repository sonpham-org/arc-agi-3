# Author: Claude Opus 4.6
# Date: 2026-03-18 23:55
# PURPOSE: Database operations for Arena Auto Research. Supports PostgreSQL
#   (primary, via DATABASE_URL env var) with SQLite fallback (when DATABASE_URL unset).
#   PostgreSQL eliminates write-lock contention from heartbeat tournament thread.
#   Manages arena_agents, arena_games, arena_research, arena_comments,
#   arena_program_versions, arena_votes, arena_human_sessions,
#   arena_evolution_sessions, arena_evolution_cycles, and arena_library_requests
#   tables. Handles ELO calculations, agent pruning, game storage limits, upset
#   detection, evolution session monitoring/stats, evolution cycle logging (full LLM
#   conversation), game frequency monitoring, and library request logging.
#   Supports program_version_id, program_file, and evolution_cycle_id on agents.
#   arena_clear_all_agents() wipes agents+games.
#   Monitor stats now read from arena_evolution_sessions (not legacy arena_llm_calls).
#   arena_get_all_pair_counts() — bulk pair count query (replaces O(n^2) individual calls).
# SRP/DRY check: Pass — arena-specific DB ops only, follows db_sessions/db_auth pattern
"""Arena Auto Research database operations.

Dual-mode: PostgreSQL (if DATABASE_URL set) or SQLite (fallback).
All SQL uses ? placeholders — the _PGConn wrapper converts to %s for psycopg2.
"""

import json
import logging
import os
import random
import time
from contextlib import contextmanager

log = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# DUAL-MODE CONNECTION LAYER
# ═══════════════════════════════════════════════════════════════════════════

_USE_PG = bool(os.environ.get('DATABASE_URL'))
_pg_pool = None
_pg_schema_initialized = False
_pg_init_lock = __import__('threading').Lock()


class _PGConn:
    """Wraps psycopg2 connection to match sqlite3.Row API.

    - Converts ? placeholders to %s for psycopg2.
    - Returns rows as dicts (via RealDictCursor) that support both d['col'] and d[index].
    - Provides .rowcount on the cursor returned by execute().
    """

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        from psycopg2.extras import RealDictCursor
        cur = self._conn.cursor(cursor_factory=RealDictCursor)
        sql = sql.replace('?', '%s')
        cur.execute(sql, params or ())
        return cur

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()


def _init_pg_schema(conn):
    """Create all 11 arena tables in PostgreSQL if they don't exist."""
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS arena_research (
            id SERIAL PRIMARY KEY,
            game_id TEXT UNIQUE NOT NULL,
            program_md TEXT DEFAULT '',
            program_version INTEGER DEFAULT 0,
            generation INTEGER DEFAULT 0,
            status TEXT DEFAULT 'stopped',
            created_at DOUBLE PRECISION DEFAULT EXTRACT(EPOCH FROM NOW()),
            updated_at DOUBLE PRECISION DEFAULT EXTRACT(EPOCH FROM NOW())
        );

        CREATE TABLE IF NOT EXISTS arena_agents (
            id SERIAL PRIMARY KEY,
            game_id TEXT NOT NULL,
            name TEXT NOT NULL,
            code TEXT NOT NULL,
            generation INTEGER DEFAULT 0,
            elo DOUBLE PRECISION DEFAULT 1000.0,
            peak_elo DOUBLE PRECISION DEFAULT 1000.0,
            games_played INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            draws INTEGER DEFAULT 0,
            contributor TEXT,
            is_human INTEGER DEFAULT 0,
            is_anchor INTEGER DEFAULT 0,
            active INTEGER DEFAULT 1,
            program_version_id INTEGER,
            program_file TEXT,
            evolution_cycle_id INTEGER,
            created_at DOUBLE PRECISION DEFAULT EXTRACT(EPOCH FROM NOW())
        );
        CREATE INDEX IF NOT EXISTS idx_aa_game_elo ON arena_agents(game_id, elo DESC);
        CREATE INDEX IF NOT EXISTS idx_aa_game_active ON arena_agents(game_id, active);

        CREATE TABLE IF NOT EXISTS arena_games (
            id SERIAL PRIMARY KEY,
            game_id TEXT NOT NULL,
            agent1_id INTEGER REFERENCES arena_agents(id),
            agent2_id INTEGER REFERENCES arena_agents(id),
            winner_id INTEGER,
            agent1_score INTEGER DEFAULT 0,
            agent2_score INTEGER DEFAULT 0,
            turns INTEGER DEFAULT 0,
            history TEXT,
            is_upset INTEGER DEFAULT 0,
            created_at DOUBLE PRECISION DEFAULT EXTRACT(EPOCH FROM NOW())
        );
        CREATE INDEX IF NOT EXISTS idx_ag_game ON arena_games(game_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_ag_agents ON arena_games(agent1_id, agent2_id);
        CREATE INDEX IF NOT EXISTS idx_ag_history ON arena_games(game_id, created_at DESC) WHERE history IS NOT NULL AND history != '[]';

        CREATE TABLE IF NOT EXISTS arena_evolution_cycles (
            id SERIAL PRIMARY KEY,
            game_id TEXT NOT NULL,
            generation INTEGER DEFAULT 0,
            worker_label TEXT DEFAULT '',
            agents_created INTEGER DEFAULT 0,
            agents_passed INTEGER DEFAULT 0,
            conversation TEXT,
            started_at DOUBLE PRECISION,
            finished_at DOUBLE PRECISION,
            created_at DOUBLE PRECISION DEFAULT EXTRACT(EPOCH FROM NOW())
        );

        CREATE TABLE IF NOT EXISTS arena_comments (
            id SERIAL PRIMARY KEY,
            game_id TEXT NOT NULL,
            user_id TEXT,
            username TEXT,
            content TEXT NOT NULL,
            comment_type TEXT DEFAULT 'strategy',
            parent_id INTEGER,
            upvotes INTEGER DEFAULT 0,
            downvotes INTEGER DEFAULT 0,
            created_at DOUBLE PRECISION DEFAULT EXTRACT(EPOCH FROM NOW())
        );
        CREATE INDEX IF NOT EXISTS idx_ac_game ON arena_comments(game_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS arena_program_versions (
            id SERIAL PRIMARY KEY,
            game_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            content TEXT NOT NULL,
            author TEXT,
            change_summary TEXT,
            votes_for INTEGER DEFAULT 0,
            votes_against INTEGER DEFAULT 0,
            vote_deadline DOUBLE PRECISION,
            applied INTEGER DEFAULT 0,
            auto_evolved INTEGER DEFAULT 0,
            trigger_reason TEXT,
            conversation_log TEXT,
            created_at DOUBLE PRECISION DEFAULT EXTRACT(EPOCH FROM NOW())
        );
        CREATE INDEX IF NOT EXISTS idx_apv_game ON arena_program_versions(game_id, version DESC);

        CREATE TABLE IF NOT EXISTS arena_votes (
            id SERIAL PRIMARY KEY,
            game_id TEXT NOT NULL,
            version_id INTEGER REFERENCES arena_program_versions(id),
            user_id TEXT NOT NULL,
            vote INTEGER NOT NULL,
            created_at DOUBLE PRECISION DEFAULT EXTRACT(EPOCH FROM NOW()),
            UNIQUE(version_id, user_id)
        );

        CREATE TABLE IF NOT EXISTS arena_human_sessions (
            id SERIAL PRIMARY KEY,
            game_id TEXT NOT NULL,
            human_agent_id INTEGER REFERENCES arena_agents(id),
            opponent_id INTEGER REFERENCES arena_agents(id),
            delay_ms INTEGER,
            winner TEXT,
            turns INTEGER DEFAULT 0,
            created_at DOUBLE PRECISION DEFAULT EXTRACT(EPOCH FROM NOW())
        );

        CREATE TABLE IF NOT EXISTS arena_evolution_sessions (
            id SERIAL PRIMARY KEY,
            game_id TEXT NOT NULL,
            generation INTEGER DEFAULT 0,
            model TEXT,
            provider TEXT DEFAULT 'anthropic',
            status TEXT DEFAULT 'success',
            api_calls INTEGER DEFAULT 0,
            tool_calls INTEGER DEFAULT 0,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cache_read_tokens INTEGER DEFAULT 0,
            cache_creation_tokens INTEGER DEFAULT 0,
            cost_usd DOUBLE PRECISION DEFAULT 0,
            total_latency_ms DOUBLE PRECISION DEFAULT 0,
            rounds INTEGER DEFAULT 0,
            agents_created INTEGER DEFAULT 0,
            error_message TEXT,
            created_at DOUBLE PRECISION DEFAULT EXTRACT(EPOCH FROM NOW())
        );
        CREATE INDEX IF NOT EXISTS idx_aes_game ON arena_evolution_sessions(game_id);
        CREATE INDEX IF NOT EXISTS idx_aes_time ON arena_evolution_sessions(created_at DESC);

        CREATE TABLE IF NOT EXISTS arena_llm_calls (
            id SERIAL PRIMARY KEY,
            game_id TEXT NOT NULL,
            generation INTEGER DEFAULT 0,
            model TEXT,
            status TEXT,
            http_status INTEGER,
            input_tokens INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            cost_usd DOUBLE PRECISION DEFAULT 0,
            latency_ms DOUBLE PRECISION DEFAULT 0,
            error_message TEXT,
            auth_type TEXT,
            created_at DOUBLE PRECISION DEFAULT EXTRACT(EPOCH FROM NOW())
        );

        CREATE TABLE IF NOT EXISTS arena_library_requests (
            id SERIAL PRIMARY KEY,
            game_id TEXT NOT NULL,
            agent_name TEXT,
            library_name TEXT NOT NULL,
            created_at DOUBLE PRECISION DEFAULT EXTRACT(EPOCH FROM NOW())
        );
    """)
    conn.commit()


@contextmanager
def _arena_db():
    """Arena DB context manager. PostgreSQL if DATABASE_URL set, else SQLite fallback."""
    global _pg_pool, _pg_schema_initialized
    if _USE_PG:
        import psycopg2
        from psycopg2.pool import ThreadedConnectionPool
        with _pg_init_lock:
            if _pg_pool is None:
                _pg_pool = ThreadedConnectionPool(2, 20, os.environ['DATABASE_URL'])
            if not _pg_schema_initialized:
                schema_conn = _pg_pool.getconn()
                try:
                    _init_pg_schema(schema_conn)
                    _pg_schema_initialized = True
                finally:
                    _pg_pool.putconn(schema_conn)
        conn = _pg_pool.getconn()
        conn.autocommit = False
        try:
            yield _PGConn(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            _pg_pool.putconn(conn)
    else:
        from db import _db
        with _db() as conn:
            yield conn


# Alias for backward compatibility — arena_heartbeat.py imports _db from db_arena
_db = _arena_db


def _insert_returning_id(conn, sql, params):
    """Insert and return the new row's ID. Handles PG RETURNING vs SQLite last_insert_rowid."""
    if _USE_PG:
        cur = conn.execute(sql + ' RETURNING id', params)
        return cur.fetchone()['id']
    else:
        conn.execute(sql, params)
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _apv_has_evo_cols(conn):
    """Check if arena_program_versions has auto_evolved/trigger_reason/conversation_log columns.

    PostgreSQL always has them (schema created with all columns).
    SQLite may not if migration hasn't run.
    """
    if _USE_PG:
        return True
    cols = {r[1] for r in conn.execute("PRAGMA table_info(arena_program_versions)").fetchall()}
    return 'auto_evolved' in cols


# Constants
ELO_K = 32
ELO_K_PROVISIONAL = 64  # Higher K for first 20 games
ELO_START = 1000.0
PROVISIONAL_GAMES = 20
MAX_STORED_GAMES_PER_PAIR = 10
MAX_ACTIVE_AGENTS_PER_GAME = 500
ELO_GAP_SKIP = 400
UPSET_ELO_GAP = 200
MAX_UPSET_RECORDS = 500
MAX_GAMES_WITH_HISTORY = 500  # FIFO — keep frame history for last N games only


# ═══════════════════════════════════════════════════════════════════════════
# RESEARCH STATE
# ═══════════════════════════════════════════════════════════════════════════

def arena_get_or_create_research(game_id):
    """Get or create research state for a game. Returns dict."""
    with _arena_db() as conn:
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
    with _arena_db() as conn:
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
            "UPDATE arena_research SET generation = ?, updated_at = ? WHERE game_id = ?",
            (new_gen, time.time(), game_id)
        )
        return new_gen


def arena_get_research_stats(game_id):
    """Get summary stats for a game's research."""
    with _arena_db() as conn:
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
    with _arena_db() as conn:
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
    with _arena_db() as conn:
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
                    return f"Agent pool full ({MAX_ACTIVE_AGENTS_PER_GAME} active). No weak agents (ELO < 1000) to prune."

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
            agent_id = _insert_returning_id(conn,
                """INSERT INTO arena_agents
                   (game_id, name, code, generation, elo, peak_elo, contributor, is_human, is_anchor, program_version_id, program_file)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (game_id, name, code, generation, ELO_START, ELO_START,
                 contributor, is_human, is_anchor, program_version_id, program_file)
            )

        row = conn.execute("SELECT * FROM arena_agents WHERE id = ?", (agent_id,)).fetchone()
        return dict(row)


def arena_get_agent(game_id, agent_id):
    """Get a single agent by ID."""
    with _arena_db() as conn:
        row = conn.execute(
            "SELECT * FROM arena_agents WHERE id = ? AND game_id = ?",
            (agent_id, game_id)
        ).fetchone()
        return dict(row) if row else None


def arena_get_agent_by_name(game_id, name):
    """Get a single agent by name."""
    with _arena_db() as conn:
        row = conn.execute(
            "SELECT * FROM arena_agents WHERE game_id = ? AND name = ?",
            (game_id, name)
        ).fetchone()
        return dict(row) if row else None


def arena_get_agent_games(game_id, agent_id, limit=5):
    """Get an agent's recent games with summary data."""
    with _arena_db() as conn:
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
    with _arena_db() as conn:
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
    with _arena_db() as conn:
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
    with _arena_db() as conn:
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

        # Decide whether to store history (pair cap applies to history blob only, NOT to game record)
        pair_count = _count_pair(conn, agent1_id, agent2_id)
        history_json = "[]"
        if history and pair_count < MAX_STORED_GAMES_PER_PAIR:
            history_json = json.dumps(history)
        elif history and is_upset:
            upset_count = conn.execute(
                "SELECT COUNT(*) as cnt FROM arena_games WHERE game_id = ? AND is_upset = 1",
                (game_id,)
            ).fetchone()["cnt"]
            if upset_count < MAX_UPSET_RECORDS:
                history_json = json.dumps(history)

        game_row_id = _insert_returning_id(conn,
            """INSERT INTO arena_games
               (game_id, agent1_id, agent2_id, winner_id,
                agent1_score, agent2_score, turns, history, is_upset)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (game_id, agent1_id, agent2_id, winner_id,
             scores[0], scores[1], turns, history_json, is_upset)
        )

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
    with _arena_db() as conn:
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
    with _arena_db() as conn:
        return _count_pair(conn, agent1_id, agent2_id)


def _count_pair(conn, id1, id2):
    row = conn.execute(
        """SELECT COUNT(*) as cnt FROM arena_games
           WHERE (agent1_id=? AND agent2_id=?) OR (agent1_id=? AND agent2_id=?)""",
        (id1, id2, id2, id1)
    ).fetchone()
    return row["cnt"] if row else 0


def arena_get_all_pair_counts(game_id, agent_ids):
    """Bulk-fetch pair game counts for a set of agents. Returns dict of (id1, id2) -> count.
    Single query replaces O(n^2) individual arena_count_pair_games calls."""
    if not agent_ids:
        return {}
    with _arena_db() as conn:
        placeholders = ','.join('?' * len(agent_ids))
        rows = conn.execute(f"""
            SELECT
                CASE WHEN agent1_id < agent2_id THEN agent1_id ELSE agent2_id END as lo,
                CASE WHEN agent1_id < agent2_id THEN agent2_id ELSE agent1_id END as hi,
                COUNT(*) as cnt
            FROM arena_games
            WHERE game_id = ?
              AND agent1_id IN ({placeholders})
              AND agent2_id IN ({placeholders})
            GROUP BY lo, hi
        """, [game_id] + list(agent_ids) + list(agent_ids)).fetchall()
        result = {}
        for r in rows:
            result[(r['lo'], r['hi'])] = r['cnt']
            result[(r['hi'], r['lo'])] = r['cnt']
        return result


def arena_get_recent_games(game_id, limit=50):
    """Get recent games for a game type."""
    with _arena_db() as conn:
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
    with _arena_db() as conn:
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
    with _arena_db() as conn:
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
    with _arena_db() as conn:
        if comment_type:
            rows = conn.execute("""
                SELECT * FROM (
                    SELECT * FROM arena_comments
                    WHERE game_id = ? AND comment_type = ?
                    ORDER BY created_at DESC LIMIT ?
                ) AS sub ORDER BY created_at ASC
            """, (game_id, comment_type, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT * FROM (
                    SELECT * FROM arena_comments
                    WHERE game_id = ?
                    ORDER BY created_at DESC LIMIT ?
                ) AS sub ORDER BY created_at ASC
            """, (game_id, limit)).fetchall()
        return [dict(r) for r in rows]


def arena_post_comment(game_id, user_id, username, content,
                       comment_type="strategy", parent_id=None):
    """Post a strategy comment."""
    with _arena_db() as conn:
        cid = _insert_returning_id(conn,
            """INSERT INTO arena_comments
               (game_id, user_id, username, content, comment_type, parent_id)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (game_id, user_id, username, content, comment_type, parent_id)
        )
        row = conn.execute("SELECT * FROM arena_comments WHERE id = ?", (cid,)).fetchone()
        return dict(row)


def arena_vote_comment(comment_id, user_id, vote):
    """Upvote (+1) or downvote (-1) a comment. Returns updated comment."""
    with _arena_db() as conn:
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

def arena_get_program_version(version_id):
    """Get a single program version by ID, including conversation log. Returns dict or None."""
    with _arena_db() as conn:
        has_evo = _apv_has_evo_cols(conn)
        if has_evo:
            evo_cols = "auto_evolved, trigger_reason, conversation_log,"
        else:
            evo_cols = "0 as auto_evolved, NULL as trigger_reason, NULL as conversation_log,"
        row = conn.execute(
            f"SELECT id, game_id, version, content, author, change_summary, "
            f"{evo_cols} created_at "
            f"FROM arena_program_versions WHERE id = ?",
            (version_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get('conversation_log'):
            try:
                d['conversation_log'] = json.loads(d['conversation_log'])
            except (json.JSONDecodeError, TypeError):
                d['conversation_log'] = []
        return d


def arena_count_agents_since_program(game_id):
    """Count agents created under the current applied program version.

    Returns (count, version_id, version_created_at) or (0, None, None) if no version.
    """
    with _arena_db() as conn:
        # Find current applied version
        ver = conn.execute(
            """SELECT id, created_at FROM arena_program_versions
               WHERE game_id = ? AND applied = 1
               ORDER BY version DESC LIMIT 1""",
            (game_id,)
        ).fetchone()
        if not ver:
            return 0, None, None
        cnt = conn.execute(
            "SELECT COUNT(*) as c FROM arena_agents WHERE game_id = ? AND program_version_id = ?",
            (game_id, ver['id'])
        ).fetchone()['c']
        return cnt, ver['id'], ver['created_at']


def arena_auto_evolve_program(game_id, content, change_summary,
                               conversation_log=None, trigger_reason=None):
    """Create and auto-apply a new program.md version from AI evolution.

    Returns the new version dict.
    """
    conv_json = None
    if conversation_log:
        conv_json = json.dumps(conversation_log, default=str)
        if len(conv_json) > 200_000:
            conv_json = conv_json[:200_000]

    with _arena_db() as conn:
        has_evo = _apv_has_evo_cols(conn)
        research = conn.execute(
            "SELECT program_version FROM arena_research WHERE game_id = ?", (game_id,)
        ).fetchone()
        current_version = research["program_version"] if research else 0
        new_version = current_version + 1

        if has_evo:
            vid = _insert_returning_id(conn,
                """INSERT INTO arena_program_versions
                   (game_id, version, content, author, change_summary,
                    applied, auto_evolved, conversation_log, trigger_reason)
                   VALUES (?, ?, ?, ?, ?, 1, 1, ?, ?)""",
                (game_id, new_version, content, 'AI Evolution', change_summary,
                 conv_json, trigger_reason)
            )
        else:
            vid = _insert_returning_id(conn,
                """INSERT INTO arena_program_versions
                   (game_id, version, content, author, change_summary, applied)
                   VALUES (?, ?, ?, ?, ?, 1)""",
                (game_id, new_version, content, 'AI Evolution', change_summary)
            )

        # Auto-apply: update arena_research with new content
        conn.execute(
            "UPDATE arena_research SET program_md = ?, program_version = ?, updated_at = ? WHERE game_id = ?",
            (content, new_version, time.time(), game_id)
        )

        evo_select = "auto_evolved, trigger_reason," if has_evo else "0 as auto_evolved, NULL as trigger_reason,"
        row = conn.execute(
            f"SELECT id, game_id, version, author, change_summary, {evo_select} "
            f"applied, created_at FROM arena_program_versions WHERE id = ?",
            (vid,)
        ).fetchone()
        return dict(row)


def arena_get_program_versions(game_id):
    """Get all program versions for a game (without conversation_log for size)."""
    with _arena_db() as conn:
        has_evo = _apv_has_evo_cols(conn)
        evo_select = "auto_evolved, trigger_reason," if has_evo else "0 as auto_evolved, NULL as trigger_reason,"
        rows = conn.execute(
            f"""SELECT id, game_id, version, author, change_summary, votes_for, votes_against,
                      applied, {evo_select} created_at
               FROM arena_program_versions
               WHERE game_id = ?
               ORDER BY version DESC""",
            (game_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def arena_get_program(game_id):
    """Get current program.md and version history."""
    with _arena_db() as conn:
        research = conn.execute(
            "SELECT program_md, program_version FROM arena_research WHERE game_id = ?",
            (game_id,)
        ).fetchone()
        # Check which columns exist (migration may not have run yet)
        has_evo_cols = _apv_has_evo_cols(conn)
        evo_select = "auto_evolved, trigger_reason," if has_evo_cols else "0 as auto_evolved, NULL as trigger_reason,"
        versions = conn.execute(
            f"""SELECT id, version, author, change_summary, votes_for, votes_against,
                      vote_deadline, applied, {evo_select} created_at
               FROM arena_program_versions WHERE game_id = ? ORDER BY version DESC LIMIT 50""",
            (game_id,)
        ).fetchall()
        # Check for active proposal (vote_deadline in the future)
        now = time.time()
        active_proposal = conn.execute(
            f"""SELECT id, version, author, change_summary, votes_for, votes_against,
                      vote_deadline, applied, {evo_select} created_at
               FROM arena_program_versions
               WHERE game_id = ? AND vote_deadline > ? AND applied = 0
               ORDER BY id DESC LIMIT 1""",
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
    with _arena_db() as conn:
        research = conn.execute(
            "SELECT program_version FROM arena_research WHERE game_id = ?", (game_id,)
        ).fetchone()
        current_version = research["program_version"] if research else 0
        new_version = current_version + 1
        deadline = time.time() + vote_seconds

        pid = _insert_returning_id(conn,
            """INSERT INTO arena_program_versions
               (game_id, version, content, author, change_summary, vote_deadline)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (game_id, new_version, content, author, change_summary, deadline)
        )
        row = conn.execute("SELECT * FROM arena_program_versions WHERE id = ?", (pid,)).fetchone()
        return dict(row)


def arena_vote_program(version_id, user_id, vote):
    """Vote on a program.md proposal. vote: +1 or -1."""
    with _arena_db() as conn:
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
    with _arena_db() as conn:
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
    with _arena_db() as conn:
        row = conn.execute(
            "SELECT * FROM arena_agents WHERE game_id = ? AND name = ?",
            (game_id, name)
        ).fetchone()
        if row:
            return dict(row)
        aid = _insert_returning_id(conn,
            """INSERT INTO arena_agents
               (game_id, name, code, generation, elo, peak_elo, contributor, is_human)
               VALUES (?, ?, 'human', 0, ?, ?, 'human', 1)""",
            (game_id, name, ELO_START, ELO_START)
        )
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
    with _arena_db() as conn:
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
    with _arena_db() as conn:
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
    with _arena_db() as conn:
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
        with _arena_db() as conn:
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


# ═══════════════════════════════════════════════════════════════════════════
# EVOLUTION CYCLES (full LLM conversation log per evolution)
# ═══════════════════════════════════════════════════════════════════════════

MAX_EVOLUTION_LOG_CHARS = 100_000  # cap conversation JSON at ~100KB


def arena_save_evolution_cycle(game_id, generation, conversation_log,
                               worker_label='', agents_created=0,
                               started_at=None, finished_at=None):
    """Save one evolution cycle with its full conversation log. Returns cycle id."""
    try:
        conv_json = json.dumps(conversation_log, default=str)
        if len(conv_json) > MAX_EVOLUTION_LOG_CHARS:
            conv_json = conv_json[:MAX_EVOLUTION_LOG_CHARS]
        with _arena_db() as conn:
            cycle_id = _insert_returning_id(conn,
                """INSERT INTO arena_evolution_cycles
                   (game_id, generation, worker_label, agents_created,
                    conversation, started_at, finished_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (game_id, generation, worker_label, agents_created,
                 conv_json, started_at, finished_at)
            )
            return cycle_id
    except Exception as e:
        log.warning("Failed to save evolution cycle: %s", e)
        return None


def arena_link_agent_to_cycle(agent_id, cycle_id):
    """Set evolution_cycle_id on an agent."""
    try:
        with _arena_db() as conn:
            conn.execute(
                "UPDATE arena_agents SET evolution_cycle_id = ? WHERE id = ?",
                (cycle_id, agent_id)
            )
    except Exception as e:
        log.warning("Failed to link agent %s to cycle %s: %s", agent_id, cycle_id, e)


def arena_get_evolution_cycle(cycle_id):
    """Get a single evolution cycle by ID."""
    with _arena_db() as conn:
        row = conn.execute(
            "SELECT * FROM arena_evolution_cycles WHERE id = ?", (cycle_id,)
        ).fetchone()
        if not row:
            return None
        d = dict(row)
        if d.get('conversation'):
            try:
                d['conversation'] = json.loads(d['conversation'])
            except (json.JSONDecodeError, TypeError):
                d['conversation'] = []
        return d


# ═══════════════════════════════════════════════════════════════════════════
# AGENT PROFILE (aggregated data for the tabbed agent view)
# ═══════════════════════════════════════════════════════════════════════════

def arena_get_agent_profile(game_id, agent_id):
    """Get agent profile data: agent info, code, program summary. Lightweight by default.

    Heavy fields (evolution_log, game histories) are omitted — load via separate endpoints.
    """
    with _arena_db() as conn:
        # Agent basic info + code
        agent_row = conn.execute(
            "SELECT * FROM arena_agents WHERE id = ? AND game_id = ?",
            (agent_id, game_id)
        ).fetchone()
        if not agent_row:
            return None
        agent = dict(agent_row)

        # Program version details (if agent has one) — content only, no conversation log
        program_version = None
        if agent.get('program_version_id'):
            pv_row = conn.execute(
                "SELECT id, game_id, version, content, author, change_summary, created_at "
                "FROM arena_program_versions WHERE id = ?",
                (agent['program_version_id'],)
            ).fetchone()
            if pv_row:
                program_version = dict(pv_row)

        # Evolution meta only (no conversation log — that's the heavy part)
        evolution_meta = None
        has_evolution_log = False
        if agent.get('evolution_cycle_id'):
            cycle_row = conn.execute(
                "SELECT id, generation, worker_label, agents_created, started_at, finished_at "
                "FROM arena_evolution_cycles WHERE id = ?",
                (agent['evolution_cycle_id'],)
            ).fetchone()
            if cycle_row:
                evolution_meta = dict(cycle_row)
                has_evolution_log = True

        # Recent games — metadata only, no history blobs
        game_rows = conn.execute("""
            SELECT g.id, g.game_id, g.agent1_id, g.agent2_id, g.winner_id,
                   g.agent1_score, g.agent2_score, g.turns, g.is_upset, g.created_at,
                   a1.name as agent1_name, a1.elo as agent1_elo,
                   a2.name as agent2_name, a2.elo as agent2_elo
            FROM arena_games g
            JOIN arena_agents a1 ON g.agent1_id = a1.id
            JOIN arena_agents a2 ON g.agent2_id = a2.id
            WHERE g.game_id = ? AND (g.agent1_id = ? OR g.agent2_id = ?)
            ORDER BY g.created_at DESC LIMIT 20
        """, (game_id, agent_id, agent_id)).fetchall()
        games = [dict(row) for row in game_rows]

        agent_info = {
            'id': agent['id'],
            'game_id': agent['game_id'],
            'name': agent['name'],
            'elo': agent['elo'],
            'peak_elo': agent.get('peak_elo', agent['elo']),
            'games_played': agent['games_played'],
            'wins': agent['wins'],
            'losses': agent['losses'],
            'draws': agent['draws'],
            'generation': agent.get('generation', 0),
            'contributor': agent.get('contributor'),
            'is_human': agent.get('is_human', 0),
            'is_anchor': agent.get('is_anchor', 0),
            'created_at': agent.get('created_at'),
        }

        return {
            'agent': agent_info,
            'code': agent.get('code', ''),
            'program_file': agent.get('program_file', ''),
            'program_version': program_version,
            'evolution_meta': evolution_meta,
            'has_evolution_log': has_evolution_log,
            'games': games,
        }


def arena_get_agent_evolution_log(game_id, agent_id):
    """Get the full evolution conversation log for an agent. Heavy — only call on demand."""
    with _arena_db() as conn:
        agent_row = conn.execute(
            "SELECT evolution_cycle_id FROM arena_agents WHERE id = ? AND game_id = ?",
            (agent_id, game_id)
        ).fetchone()
        if not agent_row or not agent_row['evolution_cycle_id']:
            return None
        cycle_row = conn.execute(
            "SELECT * FROM arena_evolution_cycles WHERE id = ?",
            (agent_row['evolution_cycle_id'],)
        ).fetchone()
        if not cycle_row:
            return None
        cycle = dict(cycle_row)
        try:
            evolution_log = json.loads(cycle.get('conversation', '[]'))
        except (json.JSONDecodeError, TypeError):
            evolution_log = []
        return {'evolution_log': evolution_log}


def arena_get_llm_monitor_stats():
    """Get aggregated evolution session stats for the monitoring dashboard.

    All data sourced from arena_evolution_sessions (session-level tracking).
    Legacy arena_llm_calls table is no longer written to.
    """
    now = time.time()
    hour_ago = now - 3600
    day_ago = now - 86400

    with _arena_db() as conn:
        # ── Time-bucketed summaries ──
        def _session_counts(since=None):
            where = f"WHERE created_at >= {since}" if since else ""
            row = conn.execute(f"""
                SELECT COUNT(*) as total_sessions,
                       SUM(agents_created) as agents_created,
                       SUM(api_calls) as total_calls,
                       SUM(tool_calls) as total_tool_calls,
                       SUM(input_tokens) as total_input_tokens,
                       SUM(output_tokens) as total_output_tokens,
                       SUM(cache_read_tokens) as total_cache_read,
                       SUM(cache_creation_tokens) as total_cache_creation,
                       SUM(cost_usd) as total_cost,
                       SUM(total_latency_ms) as total_latency,
                       AVG(total_latency_ms) as avg_latency,
                       SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                       SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as errors,
                       SUM(CASE WHEN status = 'no_agent' THEN 1 ELSE 0 END) as no_agent
                FROM arena_evolution_sessions {where}
            """).fetchone()
            return dict(row)

        stats = {
            'last_hour': _session_counts(hour_ago),
            'last_24h': _session_counts(day_ago),
            'all_time': _session_counts(),
        }

        # ── Per-model breakdown ──
        model_rows = conn.execute("""
            SELECT model, provider,
                   COUNT(*) as sessions,
                   SUM(agents_created) as agents,
                   SUM(api_calls) as total_calls,
                   SUM(tool_calls) as total_tool_calls,
                   SUM(input_tokens) as input_tokens,
                   SUM(output_tokens) as output_tokens,
                   SUM(cache_read_tokens) as cache_read,
                   SUM(cache_creation_tokens) as cache_creation,
                   SUM(cost_usd) as cost,
                   AVG(total_latency_ms) as avg_latency,
                   SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                   SUM(CASE WHEN status != 'success' THEN 1 ELSE 0 END) as failures
            FROM arena_evolution_sessions
            GROUP BY model ORDER BY sessions DESC
        """).fetchall()
        stats['by_model'] = [dict(r) for r in model_rows]

        # ── Per-game breakdown ──
        game_rows = conn.execute("""
            SELECT game_id,
                   COUNT(*) as sessions,
                   SUM(agents_created) as agents,
                   SUM(api_calls) as total_calls,
                   SUM(cost_usd) as cost,
                   AVG(total_latency_ms) as avg_latency,
                   MAX(generation) as latest_gen,
                   SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as success,
                   SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) as errors
            FROM arena_evolution_sessions
            GROUP BY game_id ORDER BY sessions DESC
        """).fetchall()
        stats['by_game'] = [dict(r) for r in game_rows]

        # ── Hourly cost buckets (last 72h) ──
        hourly_rows = conn.execute("""
            SELECT CAST((created_at / 3600) AS INTEGER) * 3600 as hour_ts,
                   SUM(cost_usd) as cost,
                   COUNT(*) as sessions,
                   SUM(api_calls) as calls,
                   SUM(agents_created) as agents
            FROM arena_evolution_sessions
            WHERE created_at >= ?
            GROUP BY hour_ts ORDER BY hour_ts
        """, (now - 72 * 3600,)).fetchall()
        stats['hourly_costs'] = [dict(r) for r in hourly_rows]

        # ── Daily cost buckets (all time) ──
        daily_rows = conn.execute("""
            SELECT CAST((created_at / 86400) AS INTEGER) * 86400 as day_ts,
                   SUM(cost_usd) as cost,
                   COUNT(*) as sessions,
                   SUM(api_calls) as calls,
                   SUM(agents_created) as agents,
                   SUM(input_tokens) as input_tokens,
                   SUM(output_tokens) as output_tokens
            FROM arena_evolution_sessions
            GROUP BY day_ts ORDER BY day_ts
        """).fetchall()
        stats['daily_costs'] = [dict(r) for r in daily_rows]

        # ── First session timestamp ──
        first_row = conn.execute(
            "SELECT MIN(created_at) as first_call FROM arena_evolution_sessions"
        ).fetchone()
        stats['first_call_at'] = first_row['first_call'] if first_row else None

        # ── Recent sessions (last 100) ──
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

        # ── Recent errors (sessions with status != 'success') ──
        error_rows = conn.execute("""
            SELECT id, game_id, generation, model, provider, status,
                   error_message, total_latency_ms, cost_usd, created_at
            FROM arena_evolution_sessions
            WHERE status = 'error'
            ORDER BY created_at DESC LIMIT 50
        """).fetchall()
        stats['recent_errors'] = [dict(r) for r in error_rows]

        # ── Library requests ──
        lib_rows = conn.execute("""
            SELECT library_name, game_id, COUNT(*) as request_count,
                   MAX(created_at) as last_requested
            FROM arena_library_requests
            GROUP BY library_name, game_id
            ORDER BY request_count DESC
        """).fetchall()
        stats['library_requests'] = [dict(r) for r in lib_rows]

        # ── Game frequency (tournament matches from arena_games) ──
        def _game_counts(since=None):
            where = f"WHERE created_at >= {since}" if since else ""
            row = conn.execute(f"""
                SELECT COUNT(*) as total_games,
                       SUM(CASE WHEN winner_id IS NOT NULL THEN 1 ELSE 0 END) as decisive,
                       SUM(CASE WHEN winner_id IS NULL THEN 1 ELSE 0 END) as draws,
                       AVG(turns) as avg_turns
                FROM arena_games {where}
            """).fetchone()
            return dict(row)

        stats['game_freq'] = {
            'last_hour': _game_counts(hour_ago),
            'last_24h': _game_counts(day_ago),
            'all_time': _game_counts(),
        }

        # Per-game breakdown of match frequency
        game_freq_rows = conn.execute("""
            SELECT game_id,
                   COUNT(*) as total_games,
                   SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) as last_hour,
                   SUM(CASE WHEN created_at >= ? THEN 1 ELSE 0 END) as last_24h,
                   AVG(turns) as avg_turns,
                   MAX(created_at) as last_game_at
            FROM arena_games
            GROUP BY game_id ORDER BY total_games DESC
        """, (hour_ago, day_ago)).fetchall()
        stats['game_freq']['by_game'] = [dict(r) for r in game_freq_rows]

        # Hourly game counts (last 72h) — for the frequency chart
        hourly_game_rows = conn.execute("""
            SELECT CAST((created_at / 3600) AS INTEGER) * 3600 as hour_ts,
                   COUNT(*) as games,
                   COUNT(DISTINCT game_id) as active_games
            FROM arena_games
            WHERE created_at >= ?
            GROUP BY hour_ts ORDER BY hour_ts
        """, (now - 72 * 3600,)).fetchall()
        stats['game_freq']['hourly'] = [dict(r) for r in hourly_game_rows]

        # Gap detection: time since last game overall
        last_game_row = conn.execute(
            "SELECT MAX(created_at) as last_game FROM arena_games"
        ).fetchone()
        stats['game_freq']['last_game_at'] = last_game_row['last_game'] if last_game_row else None

        return stats


def arena_log_library_request(game_id, agent_name, library_name):
    """Log a missing library import attempt. Non-blocking, never raises."""
    try:
        with _arena_db() as conn:
            # Deduplicate: only log once per game_id + library combo per hour
            cutoff = time.time() - 3600
            existing = conn.execute(
                """SELECT 1 FROM arena_library_requests
                   WHERE game_id = ? AND library_name = ?
                   AND created_at > ?""",
                (game_id, library_name, cutoff)
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
        with _arena_db() as conn:
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


def arena_clear_all_agents(game_id=None):
    """Clear all arena agents and their games. If game_id given, only that game.

    Deletes from arena_games first (FK references arena_agents), then arena_agents.
    Does NOT touch arena_program_versions (those are the spec history, keep them).
    Returns counts of deleted rows.
    """
    with _arena_db() as conn:
        # Get agent IDs first for targeted game deletion
        if game_id:
            agent_ids = [r["id"] for r in conn.execute(
                "SELECT id FROM arena_agents WHERE game_id = ?", (game_id,)
            ).fetchall()]
            if agent_ids:
                placeholders = ",".join("?" * len(agent_ids))
                games_del = conn.execute(
                    f"DELETE FROM arena_games WHERE agent1_id IN ({placeholders}) OR agent2_id IN ({placeholders})",
                    agent_ids + agent_ids
                ).rowcount
            else:
                games_del = 0
            agents_del = conn.execute("DELETE FROM arena_agents WHERE game_id = ?", (game_id,)).rowcount
        else:
            games_del = conn.execute("DELETE FROM arena_games").rowcount
            agents_del = conn.execute("DELETE FROM arena_agents").rowcount

    return {"agents_deleted": agents_del, "games_deleted": games_del}
