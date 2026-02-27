"""Tests for _extract_json and _parse_llm_response from server.py."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from server import _extract_json, _parse_llm_response


# ── _extract_json ─────────────────────────────────────────────────────────

class TestExtractJson:

    def test_valid_single_action(self):
        text = '{"action": 1, "observation": "wall ahead", "reasoning": "go right"}'
        result = _extract_json(text)
        assert result is not None
        assert result["action"] == 1

    def test_valid_plan(self):
        text = '{"plan": [{"action": 1}, {"action": 2}], "observation": "start"}'
        result = _extract_json(text)
        assert result is not None
        assert len(result["plan"]) == 2

    def test_json_in_markdown(self):
        text = """Here is my response:
```json
{"action": 3, "observation": "door", "reasoning": "open it"}
```
"""
        result = _extract_json(text)
        assert result is not None
        assert result["action"] == 3

    def test_json_in_prose(self):
        text = 'I think the best move is {"action": 5, "reasoning": "jump"} and that should work.'
        result = _extract_json(text)
        assert result is not None
        assert result["action"] == 5

    def test_c_style_comments_before_json(self):
        text = """// This is a comment
{"action": 2, "reasoning": "move left"}"""
        result = _extract_json(text)
        assert result is not None
        assert result["action"] == 2

    def test_c_style_comments_on_multiple_lines(self):
        text = """// comment 1
// comment 2
{"action": 4, "data": {}}"""
        result = _extract_json(text)
        assert result is not None
        assert result["action"] == 4

    def test_escaped_quotes_in_values(self):
        text = r'{"action": 1, "reasoning": "he said \"hello\""}'
        result = _extract_json(text)
        assert result is not None
        assert result["action"] == 1

    def test_nested_braces_in_strings(self):
        text = '{"action": 2, "observation": "grid looks like {{}}", "data": {}}'
        result = _extract_json(text)
        assert result is not None
        assert result["action"] == 2

    def test_multiple_json_objects_picks_first_with_action(self):
        text = '{"irrelevant": true} {"action": 7, "reasoning": "yes"}'
        result = _extract_json(text)
        assert result is not None
        assert result["action"] == 7

    def test_missing_action_and_plan_returns_none(self):
        text = '{"observation": "something", "reasoning": "nothing"}'
        result = _extract_json(text)
        assert result is None

    def test_empty_input(self):
        assert _extract_json("") is None

    def test_whitespace_only(self):
        assert _extract_json("   \n\t  ") is None

    def test_malformed_json_unbalanced_braces(self):
        text = '{"action": 1, "reasoning": "oops"'
        assert _extract_json(text) is None

    def test_malformed_json_trailing_comma(self):
        text = '{"action": 1, "reasoning": "oops",}'
        assert _extract_json(text) is None

    def test_both_action_and_plan_present(self):
        text = '{"action": 1, "plan": [{"action": 2}], "reasoning": "both"}'
        result = _extract_json(text)
        assert result is not None
        # Should accept — has both keys
        assert "action" in result or "plan" in result

    def test_action_zero(self):
        text = '{"action": 0, "reasoning": "idle"}'
        result = _extract_json(text)
        assert result is not None
        assert result["action"] == 0

    def test_action_with_data_object(self):
        text = '{"action": 6, "data": {"x": 10, "y": 20}, "reasoning": "click"}'
        result = _extract_json(text)
        assert result is not None
        assert result["data"]["x"] == 10

    def test_plan_with_data(self):
        text = '{"plan": [{"action": 1, "data": {}}, {"action": 6, "data": {"x": 5, "y": 5}}]}'
        result = _extract_json(text)
        assert result is not None
        assert result["plan"][1]["data"]["x"] == 5

    def test_no_json_at_all(self):
        text = "I don't know what to do. Let me think about it."
        assert _extract_json(text) is None

    def test_json_inside_array_still_found(self):
        text = '[{"action": 1}]'
        # _extract_json scans for { so it finds the inner object even inside an array
        result = _extract_json(text)
        assert result is not None
        assert result["action"] == 1


# ── _parse_llm_response ──────────────────────────────────────────────────

class TestParseLlmResponse:

    def test_basic_parse(self):
        content = '{"action": 3, "reasoning": "go up"}'
        result = _parse_llm_response(content, "test-model")
        assert result["parsed"] is not None
        assert result["parsed"]["action"] == 3
        assert result["model"] == "test-model"
        assert result["thinking"] is None

    def test_thinking_block_stripped(self):
        content = '<think>Let me analyze...</think>{"action": 2, "reasoning": "left"}'
        result = _parse_llm_response(content, "test-model")
        assert result["parsed"]["action"] == 2
        assert result["thinking"] == "Let me analyze..."

    def test_json_only_in_thinking_block(self):
        content = '<think>{"action": 5, "reasoning": "jump"}</think>No JSON here.'
        result = _parse_llm_response(content, "test-model")
        assert result["parsed"] is not None
        assert result["parsed"]["action"] == 5

    def test_no_json_anywhere(self):
        content = "<think>just thinking</think>No answer."
        result = _parse_llm_response(content, "test-model")
        assert result["parsed"] is None

    def test_empty_content(self):
        result = _parse_llm_response("", "test-model")
        assert result["parsed"] is None

    def test_non_string_content_dict(self):
        result = _parse_llm_response({"action": 1}, "test-model")
        assert result["parsed"] is not None
        assert result["parsed"]["action"] == 1

    def test_non_string_content_none(self):
        result = _parse_llm_response(None, "test-model")
        assert result["parsed"] is None

    def test_thinking_truncated_to_500(self):
        long_think = "x" * 1000
        content = f'<think>{long_think}</think>{{"action": 1}}'
        result = _parse_llm_response(content, "m")
        assert len(result["thinking"]) == 500
