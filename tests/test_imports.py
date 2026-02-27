"""Tests that core modules import without errors."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_import_db():
    import db  # noqa: F401


def test_import_server():
    import server  # noqa: F401


def test_import_agent():
    import agent  # noqa: F401


def test_import_batch_runner():
    import batch_runner  # noqa: F401
