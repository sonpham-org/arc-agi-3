"""Deprecated functions — backward compatibility stubs for removed tables."""
import logging

log = logging.getLogger(__name__)


def _log_turn(session_id: str, turn_num: int, scaffolding_type: str, **kwargs):
    """Deprecated: session_turns table removed. No-op for backward compat."""
    pass


def _get_session_turns(session_id: str) -> list[dict]:
    """Deprecated: session_turns table removed. Returns empty list."""
    return []
