from __future__ import annotations

from pathlib import Path

from liveclip.domain.models import SubtitleEntry
from liveclip.subtitle.writer import format_srt_entry, rebase_subtitles, write_srt_file


class TestFormatSrtEntry:
    """Tests for format_srt_entry function."""

    def test_basic_format(self) -> None:
        entry = SubtitleEntry(index=1, start=1.0, end=3.5, text="测试")
        result = format_srt_entry(entry)
        assert "1\n" in result
        assert "00:00:01,000 --> 00:00:03,500" in result
        assert "测试" in result

    def test_custom_index(self) -> None:
        entry = SubtitleEntry(index=1, start=1.0, end=3.5, text="测试")
        result = format_srt_entry(entry, index=5)
        assert "5\n" in result

    def test_time_offset(self) -> None:
        entry = SubtitleEntry(index=1, start=10.0, end=15.0, text="偏移")
        result = format_srt_entry(entry, time_offset=-5.0)
        assert "00:00:05,000 --> 00:00:10,000" in result


class TestRebaseSubtitles:
    """Tests for rebase_subtitles function."""

    def test_rebase_offsets(self) -> None:
        subtitles = [
            SubtitleEntry(index=1, start=10.0, end=12.0, text="第一句"),
            SubtitleEntry(index=2, start=13.0, end=15.0, text="第二句"),
        ]
        result = rebase_subtitles(subtitles, time_offset=10.0)
        assert result[0].start == 0.0
        assert result[0].end == 2.0
        assert result[1].start == 3.0
        assert result[1].end == 5.0

    def test_rebase_reindexes(self) -> None:
        subtitles = [
            SubtitleEntry(index=5, start=10.0, end=12.0, text="第一句"),
            SubtitleEntry(index=10, start=13.0, end=15.0, text="第二句"),
        ]
        result = rebase_subtitles(subtitles, time_offset=10.0)
        assert result[0].index == 1
        assert result[1].index == 2

    def test_rebase_zero_offset(self) -> None:
        subtitles = [
            SubtitleEntry(index=1, start=5.0, end=7.0, text="测试"),
        ]
        result = rebase_subtitles(subtitles, time_offset=0.0)
        assert result[0].start == 5.0


class TestWriteSrtFile:
    """Tests for write_srt_file function."""

    def test_write_file(self, tmp_path: Path) -> None:
        subtitles = [
            SubtitleEntry(index=1, start=1.0, end=3.5, text="第一句"),
            SubtitleEntry(index=2, start=4.0, end=6.0, text="第二句"),
        ]
        output_path = tmp_path / "output.srt"
        result = write_srt_file(output_path, subtitles)
        assert result == output_path
        assert output_path.exists()
        content = output_path.read_text(encoding="utf-8")
        assert "第一句" in content
        assert "第二句" in content

    def test_write_with_rebase(self, tmp_path: Path) -> None:
        subtitles = [
            SubtitleEntry(index=1, start=10.0, end=12.0, text="偏移测试"),
        ]
        output_path = tmp_path / "rebased.srt"
        write_srt_file(output_path, subtitles, rebase=True, time_offset=10.0)
        content = output_path.read_text(encoding="utf-8")
        assert "00:00:00,000 --> 00:00:02,000" in content

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        subtitles = [
            SubtitleEntry(index=1, start=1.0, end=2.0, text="测试"),
        ]
        output_path = tmp_path / "sub" / "dir" / "output.srt"
        write_srt_file(output_path, subtitles)
        assert output_path.exists()
