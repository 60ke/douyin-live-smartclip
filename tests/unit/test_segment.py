from __future__ import annotations

from liveclip.domain.models import ClipSegment, SubtitleEntry
from liveclip.subtitle.segment import (
    dedupe_segments,
    slice_subtitles,
    split_long_segment,
    subtitles_to_payload,
    subtitles_to_text,
)


class TestSliceSubtitles:
    """Tests for slice_subtitles function."""

    def test_slice_range(self, sample_subtitles: list[SubtitleEntry]) -> None:
        result = slice_subtitles(sample_subtitles, 2, 5)
        assert len(result) == 4
        assert result[0].index == 2
        assert result[-1].index == 5

    def test_slice_single(self, sample_subtitles: list[SubtitleEntry]) -> None:
        result = slice_subtitles(sample_subtitles, 3, 3)
        assert len(result) == 1
        assert result[0].index == 3

    def test_slice_out_of_range(self, sample_subtitles: list[SubtitleEntry]) -> None:
        result = slice_subtitles(sample_subtitles, 100, 200)
        assert len(result) == 0


class TestSubtitlesToText:
    """Tests for subtitles_to_text function."""

    def test_join_texts(self, sample_subtitles: list[SubtitleEntry]) -> None:
        result = subtitles_to_text(sample_subtitles[:3])
        assert "大家好" in result
        assert "AI绘图" in result

    def test_empty_list(self) -> None:
        assert subtitles_to_text([]) == ""


class TestSubtitlesToPayload:
    """Tests for subtitles_to_payload function."""

    def test_payload_structure(self, sample_subtitles: list[SubtitleEntry]) -> None:
        result = subtitles_to_payload(sample_subtitles[:2])
        assert len(result) == 2
        assert "index" in result[0]
        assert "start" in result[0]
        assert "end" in result[0]
        assert "text" in result[0]

    def test_empty_list(self) -> None:
        assert subtitles_to_payload([]) == []


class TestSplitLongSegment:
    """Tests for split_long_segment function."""

    def test_short_segment_not_split(self, sample_subtitles: list[SubtitleEntry]) -> None:
        seg = ClipSegment(
            title="短片段",
            start_subtitle_index=1,
            end_subtitle_index=3,
        )
        result = split_long_segment(seg, sample_subtitles, max_seconds=180.0)
        assert len(result) == 1

    def test_invalid_indices(self) -> None:
        seg = ClipSegment(
            title="无效",
            start_subtitle_index=999,
            end_subtitle_index=999,
        )
        subtitles = [SubtitleEntry(index=1, start=0.0, end=1.0, text="测试")]
        result = split_long_segment(seg, subtitles, max_seconds=180.0)
        assert len(result) == 1


class TestDedupeSegments:
    """Tests for dedupe_segments function."""

    def test_no_duplicates(self, sample_subtitles: list[SubtitleEntry]) -> None:
        seg1 = ClipSegment(
            title="片段1",
            start_subtitle_index=1,
            end_subtitle_index=3,
            score=0.8,
        )
        seg2 = ClipSegment(
            title="片段2",
            start_subtitle_index=5,
            end_subtitle_index=8,
            score=0.7,
        )
        result = dedupe_segments([seg1, seg2], sample_subtitles)
        assert len(result) == 2

    def test_overlapping_keeps_higher_score(self, sample_subtitles: list[SubtitleEntry]) -> None:
        seg1 = ClipSegment(
            title="高分",
            start_subtitle_index=1,
            end_subtitle_index=5,
            score=0.9,
        )
        seg2 = ClipSegment(
            title="低分",
            start_subtitle_index=2,
            end_subtitle_index=6,
            score=0.5,
        )
        result = dedupe_segments([seg1, seg2], sample_subtitles)
        assert len(result) == 1
        assert result[0].title == "高分"

    def test_contained_segment_uses_shorter_duration_as_base(self) -> None:
        subtitles = [
            SubtitleEntry(index=1, start=0.0, end=50.0, text="长段开始。"),
            SubtitleEntry(index=2, start=50.0, end=100.0, text="长段中间。"),
            SubtitleEntry(index=3, start=100.0, end=200.0, text="长段结束。"),
        ]
        long_segment = ClipSegment(
            title="长段",
            start_subtitle_index=1,
            end_subtitle_index=3,
            score=0.9,
        )
        contained_segment = ClipSegment(
            title="被包含短段",
            start_subtitle_index=1,
            end_subtitle_index=2,
            score=0.8,
        )

        result = dedupe_segments([long_segment, contained_segment], subtitles)

        assert [segment.title for segment in result] == ["长段"]

    def test_single_segment(self, sample_subtitles: list[SubtitleEntry]) -> None:
        seg = ClipSegment(
            title="唯一",
            start_subtitle_index=1,
            end_subtitle_index=3,
            score=0.8,
        )
        result = dedupe_segments([seg], sample_subtitles)
        assert len(result) == 1

    def test_empty_list(self, sample_subtitles: list[SubtitleEntry]) -> None:
        result = dedupe_segments([], sample_subtitles)
        assert result == []
