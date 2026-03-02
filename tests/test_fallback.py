"""Tests for _fallback_action from agent.py."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent import _fallback_action


class TestFallbackAction:

    def test_filters_out_action_zero(self):
        # Run many times to check action 0 is never chosen when alternatives exist
        for _ in range(50):
            result = _fallback_action([0, 1, 2, 3])
            assert result != 0

    def test_returns_from_available(self):
        result = _fallback_action([1, 2, 3])
        assert result in [1, 2, 3]

    def test_empty_list_returns_1(self):
        assert _fallback_action([]) == 1

    def test_only_zero_available(self):
        assert _fallback_action([0]) == 0

    def test_single_nonzero_action(self):
        assert _fallback_action([5]) == 5

    def test_all_actions(self):
        for _ in range(50):
            result = _fallback_action([0, 1, 2, 3, 4, 5, 6, 7])
            assert result in [1, 2, 3, 4, 5, 6, 7]
