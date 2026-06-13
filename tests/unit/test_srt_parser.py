from __future__ import annotations

from pathlib import Path

from liveclip.domain.models import SubtitleEntry
from liveclip.subtitle.parser import parse_srt_file, parse_srt_string


class TestParseSrtString:
    """Tests for parse_srt_string function."""

    def test_valid_srt(self, sample_srt_content: str) -> None:
        result = parse_srt_string(sample_srt_content)
        assert len(result) == 10
        assert isinstance(result[0], SubtitleEntry)
        assert result[0].index == 1
        assert result[0].start == 1.0
        assert result[0].end == 3.5
        assert result[0].text == "大家好，欢迎来到直播间"

    def test_last_entry(self, sample_srt_content: str) -> None:
        result = parse_srt_string(sample_srt_content)
        assert result[-1].index == 10
        assert result[-1].start == 40.3
        assert result[-1].end == 45.8

    def test_empty_input(self) -> None:
        result = parse_srt_string("")
        assert result == []

    def test_whitespace_input(self) -> None:
        result = parse_srt_string("   \n\n  ")
        assert result == []

    def test_dot_separator(self) -> None:
        content = "1\n00:00:01.000 --> 00:00:03.500\n测试文本\n"
        result = parse_srt_string(content)
        assert len(result) == 1
        assert result[0].start == 1.0
        assert result[0].end == 3.5

    def test_multiline_text(self) -> None:
        content = "1\n00:00:01,000 --> 00:00:03,500\n第一行\n第二行\n"
        result = parse_srt_string(content)
        assert len(result) == 1
        assert "第一行" in result[0].text
        assert "第二行" in result[0].text


class TestParseSrtFile:
    """Tests for parse_srt_file function."""

    def test_parse_file(self, tmp_path: Path) -> None:
        srt_content = "1\n00:00:01,000 --> 00:00:03,500\n测试字幕\n"
        srt_file = tmp_path / "test.srt"
        srt_file.write_text(srt_content, encoding="utf-8")

        result = parse_srt_file(srt_file)
        assert len(result) == 1
        assert result[0].text == "测试字幕"

    def test_parse_fixture(self, fixtures_dir: Path) -> None:
        srt_path = fixtures_dir / "sample.srt"
        if srt_path.exists():
            result = parse_srt_file(srt_path)
            assert len(result) == 10
