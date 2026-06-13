from __future__ import annotations

import pytest

from liveclip.utils.timecode import format_duration, format_timecode, parse_timecode


class TestFormatTimecode:
    """Tests for format_timecode function."""

    def test_zero(self) -> None:
        assert format_timecode(0.0) == "00:00:00,000"

    def test_simple_seconds(self) -> None:
        assert format_timecode(5.0) == "00:00:05,000"

    def test_with_milliseconds(self) -> None:
        assert format_timecode(1.5) == "00:00:01,500"

    def test_minutes_and_seconds(self) -> None:
        assert format_timecode(125.0) == "00:02:05,000"

    def test_hours(self) -> None:
        assert format_timecode(3661.5) == "01:01:01,500"

    def test_negative_clamped_to_zero(self) -> None:
        assert format_timecode(-5.0) == "00:00:00,000"

    def test_custom_separator(self) -> None:
        assert format_timecode(1.5, sep=".") == "00:00:01.500"

    def test_srt_style_default(self) -> None:
        result = format_timecode(3723.456)
        assert result == "01:02:03,456"


class TestParseTimecode:
    """Tests for parse_timecode function."""

    def test_comma_separator(self) -> None:
        # 01:23:45 = 1*3600 + 23*60 + 45 = 5025
        assert parse_timecode("01:23:45,678") == pytest.approx(5025.678)

    def test_dot_separator(self) -> None:
        assert parse_timecode("01:23:45.678") == pytest.approx(5025.678)

    def test_no_milliseconds(self) -> None:
        assert parse_timecode("00:05:30") == pytest.approx(330.0)

    def test_zero(self) -> None:
        assert parse_timecode("00:00:00,000") == 0.0

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid timecode"):
            parse_timecode("invalid")

    def test_invalid_minutes_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid timecode"):
            parse_timecode("00:60:00,000")

    def test_invalid_seconds_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid timecode"):
            parse_timecode("00:00:60,000")

    def test_roundtrip(self) -> None:
        original = 5025.678
        formatted = format_timecode(original)
        parsed = parse_timecode(formatted)
        assert parsed == pytest.approx(original, abs=0.001)


class TestFormatDuration:
    """Tests for format_duration function."""

    def test_seconds_only(self) -> None:
        assert format_duration(45.0) == "45s"

    def test_minutes_and_seconds(self) -> None:
        assert format_duration(125.0) == "2m 5s"

    def test_hours_minutes_seconds(self) -> None:
        assert format_duration(3725.0) == "1h 2m 5s"

    def test_zero(self) -> None:
        assert format_duration(0.0) == "0s"

    def test_negative_clamped(self) -> None:
        assert format_duration(-10.0) == "0s"

    def test_exact_hour(self) -> None:
        # format_duration omits 0s when higher units present
        assert format_duration(3600.0) == "1h"

    def test_exact_minute(self) -> None:
        assert format_duration(60.0) == "1m"
