from __future__ import annotations

from liveclip.utils.json import clamp_score, extract_json_object


class TestExtractJsonObject:
    """Tests for extract_json_object function."""

    def test_clean_json(self) -> None:
        text = '{"key": "value", "count": 42}'
        result = extract_json_object(text)
        assert result is not None
        assert result["key"] == "value"
        assert result["count"] == 42

    def test_markdown_code_fences(self) -> None:
        text = '```json\n{"key": "value"}\n```'
        result = extract_json_object(text)
        assert result is not None
        assert result["key"] == "value"

    def test_code_fences_without_language(self) -> None:
        text = '```\n{"key": "value"}\n```'
        result = extract_json_object(text)
        assert result is not None
        assert result["key"] == "value"

    def test_surrounding_text(self) -> None:
        text = 'Here is the result: {"key": "value"} and more text'
        result = extract_json_object(text)
        assert result is not None
        assert result["key"] == "value"

    def test_no_json_returns_none(self) -> None:
        text = "no json here"
        result = extract_json_object(text)
        assert result is None

    def test_nested_json(self) -> None:
        text = '{"outer": {"inner": "value"}}'
        result = extract_json_object(text)
        assert result is not None
        assert result["outer"]["inner"] == "value"

    def test_invalid_json_in_text(self) -> None:
        # extract_json_object finds first { and tries to parse;
        # if depth tracking fails it continues to next {
        text = 'no braces here {"valid": true}'
        result = extract_json_object(text)
        assert result is not None
        assert result["valid"] is True

    def test_array_not_returned(self) -> None:
        text = "[1, 2, 3]"
        result = extract_json_object(text)
        assert result is None


class TestClampScore:
    """Tests for clamp_score function."""

    def test_within_range(self) -> None:
        assert clamp_score(0.5) == 0.5

    def test_below_min(self) -> None:
        assert clamp_score(-0.5) == 0.0

    def test_above_max(self) -> None:
        assert clamp_score(1.5) == 1.0

    def test_at_min(self) -> None:
        assert clamp_score(0.0) == 0.0

    def test_at_max(self) -> None:
        assert clamp_score(1.0) == 1.0

    def test_custom_range(self) -> None:
        assert clamp_score(5.0, min_val=0.0, max_val=10.0) == 5.0
        assert clamp_score(-1.0, min_val=0.0, max_val=10.0) == 0.0
        assert clamp_score(15.0, min_val=0.0, max_val=10.0) == 10.0
