"""
Structured error handling for sonpham-arc3.

Provides context managers and decorators that replace bare
`except Exception as e:` patterns with structured logging.
"""
import logging
import functools
import traceback
from contextlib import contextmanager

log = logging.getLogger(__name__)


class AppError(Exception):
    """Base application error with context."""
    def __init__(self, message, context=None):
        super().__init__(message)
        self.context = context or {}


class DBError(AppError):
    """Database operation error."""
    pass


class LLMError(AppError):
    """LLM provider error."""
    pass


@contextmanager
def handle_db_error(operation: str, **context):
    """Context manager for DB operations with structured logging.
    
    Usage:
        with handle_db_error("save_session", session_id=session_id):
            # db operations here
    """
    try:
        yield
    except Exception as e:
        log.error(
            "DB error in %s: %s",
            operation, str(e),
            extra={"operation": operation, **context},
            exc_info=True
        )
        raise DBError(f"DB operation '{operation}' failed: {e}", context=context) from e


def handle_errors(operation: str, reraise: bool = False, default=None):
    """Decorator for structured error handling.
    
    Usage:
        @handle_errors("get_session", reraise=False, default=None)
        def get_session(session_id):
            ...
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except (AppError, DBError, LLMError):
                raise  # Already structured, re-raise as-is
            except Exception as e:
                log.error(
                    "Error in %s: %s",
                    operation, str(e),
                    exc_info=True
                )
                if reraise:
                    raise
                return default
        return wrapper
    return decorator
