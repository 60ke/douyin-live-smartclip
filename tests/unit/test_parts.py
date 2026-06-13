from __future__ import annotations

from liveclip.domain.models import ClipSegment, SubtitleEntry
from liveclip.subtitle.parts import normalize_segment_parts, segment_duration_seconds


def test_normalize_segment_parts_sorts_and_limits_parts() -> None:
    subtitles = [
        SubtitleEntry(index=1, start=0.0, end=10.0, text="一。"),
        SubtitleEntry(index=2, start=10.0, end=20.0, text="二。"),
        SubtitleEntry(index=3, start=20.0, end=30.0, text="三。"),
        SubtitleEntry(index=4, start=30.0, end=40.0, text="四。"),
        SubtitleEntry(index=5, start=40.0, end=50.0, text="五。"),
    ]
    segment = ClipSegment(
        title="多段",
        start_subtitle_index=1,
        end_subtitle_index=5,
        parts=[
            {"start_subtitle_index": 1, "end_subtitle_index": 1},
            {"start_subtitle_index": 2, "end_subtitle_index": 2},
            {"start_subtitle_index": 3, "end_subtitle_index": 3},
            {"start_subtitle_index": 4, "end_subtitle_index": 4},
            {"start_subtitle_index": 5, "end_subtitle_index": 5},
        ],
    )

    normalized = normalize_segment_parts(segment, subtitles)

    assert len(normalized.parts) == 4
    assert normalized.start_subtitle_index == 1
    assert normalized.end_subtitle_index == 4
    assert normalized.parts[0]["start"] == 0.0
    assert normalized.parts[-1]["end"] == 40.0


def test_segment_duration_uses_parts_sum() -> None:
    subtitles = [
        SubtitleEntry(index=1, start=0.0, end=10.0, text="一。"),
        SubtitleEntry(index=2, start=10.0, end=20.0, text="二。"),
        SubtitleEntry(index=3, start=20.0, end=30.0, text="三。"),
    ]
    segment = normalize_segment_parts(
        ClipSegment(
            title="跳剪",
            start_subtitle_index=1,
            end_subtitle_index=3,
            parts=[
                {"start_subtitle_index": 1, "end_subtitle_index": 1},
                {"start_subtitle_index": 3, "end_subtitle_index": 3},
            ],
        ),
        subtitles,
    )

    assert segment_duration_seconds(segment, subtitles) == 20.0
