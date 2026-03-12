"""Social service layer — Comments, voting, and leaderboard.

Validation and orchestration for social features.
Pure business logic — no Flask request/response objects.
"""

import logging
import time

log = logging.getLogger(__name__)


def validate_comment_body(body: str) -> tuple[bool, str]:
    """Validate comment body. Returns (is_valid, error_msg)."""
    if not body:
        return False, "comment body required"
    body = body.strip()
    if not body:
        return False, "comment cannot be empty"
    if len(body) > 5000:
        return False, "comment too long (max 5000 chars)"
    return True, ""


def validate_vote_direction(vote: int) -> tuple[bool, str]:
    """Validate vote direction (1=upvote, -1=downvote). Returns (is_valid, error_msg)."""
    if vote not in (1, -1, 0):  # 0 = remove vote
        return False, "vote must be 1 (upvote), -1 (downvote), or 0 (remove)"
    return True, ""


def validate_comment_id(comment_id) -> tuple[bool, str]:
    """Validate comment_id is an integer. Returns (is_valid, error_msg)."""
    if comment_id is None:
        return False, "comment_id required"
    try:
        int(comment_id)
        return True, ""
    except (ValueError, TypeError):
        return False, "comment_id must be an integer"


def validate_game_id(game_id: str) -> tuple[bool, str]:
    """Validate game_id is present. Returns (is_valid, error_msg)."""
    if not game_id:
        return False, "game_id required"
    return True, ""


# ═══════════════════════════════════════════════════════════════════════════
# COMMENTS — get_comments(), post_comment(), vote_comment()
# ═══════════════════════════════════════════════════════════════════════════

def get_comments(game_id: str, voter_id: str = "", get_db_fn=None) -> tuple[list, int]:
    """Get comments for a game, including voter's votes on each.
    
    Returns:
        (comments_list, status_code)
    """
    is_valid, error_msg = validate_game_id(game_id)
    if not is_valid:
        return {"error": error_msg}, 400
    
    if not get_db_fn:
        return {"error": "Service not initialized"}, 500
    
    try:
        conn = get_db_fn()
        rows = conn.execute(
            "SELECT * FROM comments WHERE location=? ORDER BY created_at DESC LIMIT 200",
            (game_id,),
        ).fetchall()
        
        # Get voter's votes if provided
        my_votes = {}
        if voter_id and rows:
            cids = [r["id"] for r in rows]
            ph = ",".join("?" * len(cids))
            vote_rows = conn.execute(
                f"SELECT comment_id, vote FROM comment_votes WHERE voter_id=? AND comment_id IN ({ph})",
                [voter_id] + cids,
            ).fetchall()
            my_votes = {r["comment_id"]: r["vote"] for r in vote_rows}
        
        conn.close()
        
        return [
            {**dict(r), "my_vote": my_votes.get(r["id"], 0)} for r in rows
        ], 200
    except Exception as e:
        log.error(f"get_comments error: {e}")
        return {"error": str(e)}, 500


def post_comment(data: dict, get_db_fn=None) -> tuple[dict, int]:
    """Post a new comment.
    
    Returns:
        (comment_dict, status_code)
    """
    game_id = (data.get("game_id") or "").strip()
    body = (data.get("body") or "").strip()
    author_id = (data.get("author_id") or "").strip()
    author_name = (data.get("author_name") or "").strip()
    
    is_valid, error_msg = validate_game_id(game_id)
    if not is_valid:
        return {"error": error_msg}, 400
    
    is_valid, error_msg = validate_comment_body(body)
    if not is_valid:
        return {"error": error_msg}, 400
    
    if not author_id:
        return {"error": "author_id required"}, 400
    
    if not author_name:
        author_name = f"anon-{author_id[:6]}"
    
    if not get_db_fn:
        return {"error": "Service not initialized"}, 500
    
    try:
        conn = get_db_fn()
        cur = conn.execute(
            "INSERT INTO comments (location, user_id, author_name, body, created_at) VALUES (?,?,?,?,?)",
            (game_id, author_id, author_name, body, time.time()),
        )
        cid = cur.lastrowid
        conn.commit()
        row = conn.execute("SELECT * FROM comments WHERE id=?", (cid,)).fetchone()
        conn.close()
        return {**dict(row), "my_vote": 0}, 201
    except Exception as e:
        log.error(f"post_comment error: {e}")
        return {"error": str(e)}, 500


def vote_comment(comment_id: int, voter_id: str, vote: int, get_db_fn=None) -> tuple[dict, int]:
    """Vote on a comment (upvote, downvote, or remove vote).
    
    Returns:
        (response_dict, status_code)
    """
    is_valid, error_msg = validate_comment_id(comment_id)
    if not is_valid:
        return {"error": error_msg}, 400
    
    voter_id = (voter_id or "").strip()
    if not voter_id:
        return {"error": "voter_id required"}, 400
    
    is_valid, error_msg = validate_vote_direction(vote)
    if not is_valid:
        return {"error": error_msg}, 400
    
    if not get_db_fn:
        return {"error": "Service not initialized"}, 500
    
    try:
        conn = get_db_fn()
        
        # Get existing vote
        existing = conn.execute(
            "SELECT vote FROM comment_votes WHERE comment_id=? AND voter_id=?",
            (comment_id, voter_id),
        ).fetchone()
        old_vote = existing["vote"] if existing else 0
        
        # If same vote, return OK
        if old_vote == vote:
            conn.close()
            return {"ok": True}, 200
        
        # Remove old vote effect
        if old_vote == 1:
            conn.execute("UPDATE comments SET upvotes = upvotes - 1 WHERE id=?", (comment_id,))
        elif old_vote == -1:
            conn.execute("UPDATE comments SET downvotes = downvotes - 1 WHERE id=?", (comment_id,))
        
        # Apply new vote
        if vote == 0:
            conn.execute("DELETE FROM comment_votes WHERE comment_id=? AND voter_id=?", (comment_id, voter_id))
        else:
            conn.execute(
                "INSERT OR REPLACE INTO comment_votes (comment_id, voter_id, vote) VALUES (?,?,?)",
                (comment_id, voter_id, vote),
            )
            if vote == 1:
                conn.execute("UPDATE comments SET upvotes = upvotes + 1 WHERE id=?", (comment_id,))
            else:
                conn.execute("UPDATE comments SET downvotes = downvotes + 1 WHERE id=?", (comment_id,))
        
        conn.commit()
        row = conn.execute("SELECT upvotes, downvotes FROM comments WHERE id=?", (comment_id,)).fetchone()
        conn.close()
        
        return {"ok": True, "upvotes": row["upvotes"], "downvotes": row["downvotes"]}, 200
    except Exception as e:
        log.error(f"vote_comment error: {e}")
        return {"error": str(e)}, 500


# ═══════════════════════════════════════════════════════════════════════════
# LEADERBOARD — get_leaderboard(), leaderboard_detail()
# ═══════════════════════════════════════════════════════════════════════════

def get_leaderboard(get_db_fn=None) -> tuple[dict, int]:
    """Get best AI and human sessions per game for leaderboard display.
    
    Returns:
        (leaderboard_dict, status_code)
    """
    if not get_db_fn:
        return {"leaderboard": [], "error": "Service not initialized"}, 500
    
    try:
        conn = get_db_fn()
        
        # Best AI session per game
        ai_rows = conn.execute("""
            SELECT * FROM (
                SELECT s.id, s.game_id, s.result, s.steps, s.levels, s.model,
                       s.created_at, s.duration_seconds,
                       ROW_NUMBER() OVER (
                           PARTITION BY SUBSTR(s.game_id, 1, INSTR(s.game_id || '-', '-') - 1)
                           ORDER BY s.levels DESC, s.steps ASC
                       ) AS rn
                FROM sessions s
                WHERE COALESCE(s.player_type, 'agent') = 'agent' AND s.steps > 0
            ) WHERE rn = 1
        """).fetchall()
        
        # Best human session per game
        human_rows = conn.execute("""
            SELECT * FROM (
                SELECT s.id, s.game_id, s.result, s.steps, s.levels,
                       s.created_at, s.duration_seconds,
                       COALESCE(u.display_name, SUBSTR(u.email, 1, INSTR(u.email, '@') - 1)) AS author,
                       ROW_NUMBER() OVER (
                           PARTITION BY SUBSTR(s.game_id, 1, INSTR(s.game_id || '-', '-') - 1)
                           ORDER BY s.levels DESC, s.duration_seconds ASC, s.steps ASC
                       ) AS rn
                FROM sessions s
                LEFT JOIN users u ON s.user_id = u.id
                WHERE s.player_type = 'human' AND s.steps > 0
            ) WHERE rn = 1
        """).fetchall()
        
        conn.close()
        
        ai_best = {dict(r)["game_id"].split("-")[0]: dict(r) for r in ai_rows}
        human_best = {dict(r)["game_id"].split("-")[0]: dict(r) for r in human_rows}
        all_games = sorted(set(list(ai_best.keys()) + list(human_best.keys())))
        rows = [{"game_id": gid, "ai": ai_best.get(gid), "human": human_best.get(gid)} for gid in all_games]
        
        return {"leaderboard": rows}, 200
    except Exception as e:
        log.error(f"get_leaderboard error: {e}")
        return {"leaderboard": [], "error": str(e)}, 500


def get_leaderboard_detail(game_id: str, get_db_fn=None) -> tuple[dict, int]:
    """Get top AI and human attempts for a specific game.
    
    Returns:
        (leaderboard_detail_dict, status_code)
    """
    is_valid, error_msg = validate_game_id(game_id)
    if not is_valid:
        return {"error": error_msg}, 400
    
    if not get_db_fn:
        return {"error": "Service not initialized"}, 500
    
    try:
        conn = get_db_fn()
        
        ai_rows = conn.execute("""
            SELECT s.id, s.game_id, s.result, s.steps, s.levels, s.model,
                   s.created_at, s.duration_seconds
            FROM sessions s
            WHERE COALESCE(s.player_type, 'agent') = 'agent'
              AND s.steps > 0 AND s.game_id LIKE ? || '%'
            ORDER BY s.levels DESC, s.steps ASC
            LIMIT 20
        """, (game_id,)).fetchall()
        
        human_rows = conn.execute("""
            SELECT s.id, s.game_id, s.result, s.steps, s.levels,
                   s.created_at, s.duration_seconds,
                   COALESCE(u.display_name, SUBSTR(u.email, 1, INSTR(u.email, '@') - 1)) AS author
            FROM sessions s
            LEFT JOIN users u ON s.user_id = u.id
            WHERE s.player_type = 'human'
              AND s.steps > 0 AND s.game_id LIKE ? || '%'
            ORDER BY s.levels DESC, s.duration_seconds ASC, s.steps ASC
            LIMIT 20
        """, (game_id,)).fetchall()
        
        conn.close()
        
        return {
            "game_id": game_id,
            "ai": [dict(r) for r in ai_rows],
            "human": [dict(r) for r in human_rows],
        }, 200
    except Exception as e:
        log.error(f"get_leaderboard_detail error: {e}")
        return {
            "game_id": game_id,
            "ai": [],
            "human": [],
            "error": str(e),
        }, 500


# ═══════════════════════════════════════════════════════════════════════════
# CONTRIBUTORS — get_contributors()
# ═══════════════════════════════════════════════════════════════════════════

def get_contributors(get_db_fn=None) -> tuple[dict, int]:
    """Get top contributors: commenters, human players, and AI contributors.
    
    Returns:
        (contributors_dict, status_code)
    """
    if not get_db_fn:
        return {"error": "Service not initialized"}, 500
    
    try:
        conn = get_db_fn()
        
        # Top commenters
        commenters = conn.execute("""
            SELECT user_id, author_name, COUNT(*) as comment_count,
                   SUM(upvotes) as total_upvotes
            FROM comments GROUP BY user_id
            ORDER BY comment_count DESC LIMIT 20
        """).fetchall()
        
        # Top human players
        human_players = conn.execute("""
            SELECT COALESCE(user_id, 'anon') as uid,
                   COUNT(*) as session_count,
                   SUM(duration_seconds) as total_time,
                   SUM(steps) as total_steps,
                   COUNT(DISTINCT SUBSTR(game_id, 1, INSTR(game_id || '-', '-') - 1)) as games_played
            FROM sessions
            WHERE player_type = 'human' AND steps > 5
            GROUP BY uid ORDER BY session_count DESC LIMIT 20
        """).fetchall()
        
        # Top AI contributors
        ai_contributors = conn.execute("""
            SELECT COALESCE(user_id, 'anon') as uid, model,
                   COUNT(*) as session_count,
                   SUM(steps) as total_steps,
                   COUNT(DISTINCT SUBSTR(game_id, 1, INSTR(game_id || '-', '-') - 1)) as games_played
            FROM sessions
            WHERE COALESCE(player_type, 'agent') = 'agent' AND steps > 5
            GROUP BY uid ORDER BY session_count DESC LIMIT 20
        """).fetchall()
        
        conn.close()
        
        return {
            "commenters": [dict(r) for r in commenters],
            "human_players": [dict(r) for r in human_players],
            "ai_contributors": [dict(r) for r in ai_contributors],
        }, 200
    except Exception as e:
        log.error(f"get_contributors error: {e}")
        return {"error": str(e)}, 500
