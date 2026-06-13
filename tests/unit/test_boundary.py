from __future__ import annotations

from pathlib import Path
from typing import Any

from liveclip.domain.models import (
    ClipSegment,
    ClipSegmentConfig,
    LLMCallConfig,
    PipelineConfig,
    RecordConfig,
    SubtitleEntry,
)
from liveclip.pipeline.context import PipelineContext
from liveclip.pipeline.steps.validate_boundary import (
    ValidateBoundaryStep,
    _filter_short_segments_with_report,
    trim_overlaps_to_previous_complete_end,
)
from liveclip.storage.paths import RunPaths
from liveclip.subtitle.boundary import (
    filter_short_segments,
    snap_segment_boundaries,
    snap_to_complete_subtitle,
)


class TestSnapToCompleteSubtitle:
    """Tests for snap_to_complete_subtitle function."""

    def test_snap_forward(self, sample_subtitles: list[SubtitleEntry]) -> None:
        time_seconds = 1.0
        snapped_time, sub_index = snap_to_complete_subtitle(
            sample_subtitles, time_seconds, direction="forward"
        )
        assert isinstance(snapped_time, float)
        assert sub_index >= 1

    def test_snap_backward(self, sample_subtitles: list[SubtitleEntry]) -> None:
        time_seconds = 10.0
        snapped_time, sub_index = snap_to_complete_subtitle(
            sample_subtitles, time_seconds, direction="backward"
        )
        assert isinstance(snapped_time, float)

    def test_empty_subtitles(self) -> None:
        snapped_time, sub_index = snap_to_complete_subtitle([], 5.0)
        assert snapped_time == 5.0
        assert sub_index == 0


class TestSnapSegmentBoundaries:
    """Tests for snap_segment_boundaries function."""

    def test_snap_adjusts_boundaries(self, sample_subtitles: list[SubtitleEntry]) -> None:
        segment = ClipSegment(
            title="测试",
            start_subtitle_index=2,
            end_subtitle_index=7,
        )
        result = snap_segment_boundaries(segment, sample_subtitles)
        assert isinstance(result, ClipSegment)

    def test_empty_subtitles(self) -> None:
        segment = ClipSegment(
            title="测试",
            start_subtitle_index=1,
            end_subtitle_index=3,
        )
        result = snap_segment_boundaries(segment, [])
        assert result.start_subtitle_index == 1
        assert result.end_subtitle_index == 3

    def test_trims_obvious_leading_half_sentence(self) -> None:
        subtitles = [
            SubtitleEntry(index=1, start=0.0, end=1.8, text="多的情况下，你的成本比较高，"),
            SubtitleEntry(index=2, start=1.8, end=5.0, text="我们来看这个功能怎么解决问题。"),
            SubtitleEntry(index=3, start=5.0, end=12.0, text="这里演示完整流程。"),
        ]
        segment = ClipSegment(title="测试", start_subtitle_index=1, end_subtitle_index=3)

        result = snap_segment_boundaries(segment, subtitles)

        assert result.start_subtitle_index == 2
        assert result.validation["auto_start_policy"] == "trim_start_fragment_to_natural_subtitle"
        assert result.validation["first_sentence"] == "我们来看这个功能怎么解决问题。"

    def test_keeps_natural_incomplete_opening(self) -> None:
        subtitles = [
            SubtitleEntry(index=1, start=0.0, end=1.8, text="我们先看一下这个功能，"),
            SubtitleEntry(index=2, start=1.8, end=5.0, text="它可以直接生成效果图。"),
            SubtitleEntry(index=3, start=5.0, end=12.0, text="这里演示完整流程。"),
        ]
        segment = ClipSegment(title="测试", start_subtitle_index=1, end_subtitle_index=3)

        result = snap_segment_boundaries(segment, subtitles)

        assert result.start_subtitle_index == 1


class TestFilterShortSegments:
    """Tests for filter_short_segments function."""

    def test_removes_short_low_score_segments(self, sample_subtitles: list[SubtitleEntry]) -> None:
        short_seg = ClipSegment(
            title="低分短片",
            start_subtitle_index=1,
            end_subtitle_index=1,
            score=0.7,
        )
        result = filter_short_segments([short_seg], sample_subtitles, min_seconds=45.0)
        assert len(result) == 0

    def test_keeps_long_segments(self, sample_subtitles: list[SubtitleEntry]) -> None:
        long_seg = ClipSegment(
            title="足够长",
            start_subtitle_index=1,
            end_subtitle_index=7,
            score=0.9,
        )
        result = filter_short_segments([long_seg], sample_subtitles, min_seconds=20.0)
        assert len(result) == 1

    def test_short_high_score_kept(self, sample_subtitles: list[SubtitleEntry]) -> None:
        short_seg = ClipSegment(
            title="短片高分",
            start_subtitle_index=1,
            end_subtitle_index=2,
            score=0.9,
        )
        result = filter_short_segments(
            [short_seg],
            sample_subtitles,
            min_seconds=45.0,
            high_score_threshold=0.8,
        )
        assert len(result) == 1

    def test_empty_subtitles(self) -> None:
        seg = ClipSegment(
            title="测试",
            start_subtitle_index=1,
            end_subtitle_index=3,
        )
        result = filter_short_segments([seg], [])
        assert len(result) == 1

    def test_filter_report_includes_drop_reason(self) -> None:
        subtitles = [
            SubtitleEntry(index=1, start=0.0, end=10.0, text="短片段开始。"),
            SubtitleEntry(index=2, start=10.0, end=20.0, text="短片段结束。"),
            SubtitleEntry(index=3, start=20.0, end=80.0, text="长片段结束。"),
        ]
        segments = [
            ClipSegment(
                title="低分短片段", start_subtitle_index=1, end_subtitle_index=2, score=0.7
            ),
            ClipSegment(
                title="高分短片段", start_subtitle_index=1, end_subtitle_index=2, score=0.9
            ),
            ClipSegment(title="长片段", start_subtitle_index=1, end_subtitle_index=3, score=0.9),
        ]

        kept, filtered = _filter_short_segments_with_report(
            segments,
            subtitles,
            min_seconds=45.0,
            high_score_threshold=0.8,
        )

        assert [seg.title for seg in kept] == ["高分短片段", "长片段"]
        assert filtered == [
            {
                "index": 1,
                "title": "低分短片段",
                "start_subtitle_index": 1,
                "end_subtitle_index": 2,
                "duration_seconds": 20.0,
                "score": 0.7,
                "reason": "duration_below_min_seconds_and_score_low",
            }
        ]


def test_trim_overlaps_to_previous_complete_end() -> None:
    subtitles = [
        SubtitleEntry(index=1, start=0.0, end=20.0, text="当前主题开始。"),
        SubtitleEntry(index=2, start=20.0, end=40.0, text="当前主题完整结束。"),
        SubtitleEntry(index=3, start=40.0, end=50.0, text="接下来我们看第二个功能。"),
        SubtitleEntry(index=4, start=50.0, end=80.0, text="第二个主题结束。"),
    ]
    segments = [
        ClipSegment(title="前一个", start_subtitle_index=1, end_subtitle_index=3, score=0.9),
        ClipSegment(title="后一个", start_subtitle_index=3, end_subtitle_index=4, score=0.9),
    ]

    result = trim_overlaps_to_previous_complete_end(segments, subtitles)

    assert result[0].end_subtitle_index == 2


class _FakeBoundaryLLM:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def chat(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        return (
            '{"passed": false, "action": "adjust_end", '
            '"target_end_subtitle_index": 2, "reason": "回退到完整结尾"}'
        )


def _boundary_ctx(tmp_path: Path) -> PipelineContext:
    return PipelineContext(
        task_id=1,
        room_id=1,
        run_id=1,
        paths=RunPaths(base_dir=tmp_path, room_id=1, run_id=1),
        pipeline_config=PipelineConfig(validate_boundary_use_llm=True),
        clip_segment_config=ClipSegmentConfig(),
        llm_call_config=LLMCallConfig(),
        record_config=RecordConfig(),
    )


def test_llm_boundary_validates_each_non_part_segment_like_old_project(tmp_path: Path) -> None:
    subtitles = [
        SubtitleEntry(index=1, start=0.0, end=10.0, text="开头。"),
        SubtitleEntry(index=2, start=10.0, end=20.0, text="完整结束。"),
        SubtitleEntry(index=3, start=20.0, end=30.0, text="下一段开头。"),
        SubtitleEntry(index=4, start=30.0, end=40.0, text="拼接段。"),
    ]
    segments = [
        ClipSegment(title="普通段一", start_subtitle_index=1, end_subtitle_index=3),
        ClipSegment(
            title="拼接段",
            start_subtitle_index=1,
            end_subtitle_index=4,
            parts=[
                {"start_subtitle_index": 1, "end_subtitle_index": 2},
                {"start_subtitle_index": 4, "end_subtitle_index": 4},
            ],
        ),
        ClipSegment(title="普通段二", start_subtitle_index=2, end_subtitle_index=3),
    ]
    fake_llm = _FakeBoundaryLLM()
    step = ValidateBoundaryStep(llm_client=fake_llm)  # type: ignore[arg-type]

    result = step._llm_validate(_boundary_ctx(tmp_path), segments, subtitles)

    assert len(fake_llm.calls) == 2
    assert all(call["max_tokens"] == 700 for call in fake_llm.calls)
    assert all(call["timeout_seconds"] == 60 for call in fake_llm.calls)
    assert result[0].end_subtitle_index == 2
    assert result[1].validation["validator"] == "parts_code_boundary_snap"
    assert result[2].end_subtitle_index == 2
