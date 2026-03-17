# Author: Claude Opus 4.6
# Date: 2026-03-15 00:00
# PURPOSE: Shared validation functions for the service layer. Centralizes
#   game_id, session_id, action_id, and comment validation to eliminate
#   duplication across game_service.py and social_service.py.
# SRP/DRY check: Pass — single source of truth for input validation
"""Shared validators for the service layer."""


def validate_game_id(game_id: str) -> tuple[bool, str]:
    """Validate game_id is present. Returns (is_valid, error_msg)."""
    if not game_id:
        return False, "game_id required"
    return True, ""


def validate_session_id(session_id: str) -> tuple[bool, str]:
    """Validate session_id is present. Returns (is_valid, error_msg)."""
    if not session_id:
        return False, "session_id required"
    return True, ""


def validate_action_id(action_id) -> tuple[bool, str]:
    """Validate action_id is a valid integer. Returns (is_valid, error_msg)."""
    if action_id is None:
        return False, "action required"
    try:
        int(action_id)
        return True, ""
    except (ValueError, TypeError):
        return False, f"Invalid action: {action_id}"


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
    """Validate vote direction (1=upvote, -1=downvote, 0=remove). Returns (is_valid, error_msg)."""
    if vote not in (1, -1, 0):
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
