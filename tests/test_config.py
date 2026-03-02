"""Tests for load_config and _deep_merge from agent.py."""
import sys, os
from pathlib import Path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent import load_config, _deep_merge, _DEFAULT_CONFIG


class TestDeepMerge:

    def test_partial_override(self):
        base = {"a": 1, "b": 2, "c": 3}
        override = {"b": 20}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 20, "c": 3}

    def test_nested_dict_merge(self):
        base = {"outer": {"a": 1, "b": 2}}
        override = {"outer": {"b": 99}}
        result = _deep_merge(base, override)
        assert result["outer"]["a"] == 1
        assert result["outer"]["b"] == 99

    def test_new_key_added(self):
        base = {"a": 1}
        override = {"b": 2}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 2}

    def test_non_dict_override_replaces(self):
        base = {"a": {"nested": True}}
        override = {"a": "flat"}
        result = _deep_merge(base, override)
        assert result["a"] == "flat"

    def test_empty_override(self):
        base = {"a": 1}
        result = _deep_merge(base, {})
        assert result == {"a": 1}


class TestLoadConfig:

    def test_loads_real_config(self):
        cfg = load_config()
        # Should have all top-level keys from _DEFAULT_CONFIG
        for key in _DEFAULT_CONFIG:
            assert key in cfg

    def test_missing_file_uses_defaults(self):
        cfg = load_config(Path("/nonexistent/config.yaml"))
        assert cfg == _DEFAULT_CONFIG

    def test_expected_keys_present(self):
        cfg = load_config()
        assert "context" in cfg
        assert "reasoning" in cfg
        assert "memory" in cfg
        assert "full_grid" in cfg["context"]
        assert "executor_model" in cfg["reasoning"]
