from __future__ import annotations

from liveclip.domain.enums import StepName
from liveclip.domain.models import (
    ClipSegment,
    ClipSegmentConfig,
    LLMCallConfig,
    PipelineConfig,
    RecordConfig,
    StepResult,
    SubtitleEntry,
)
from liveclip.pipeline.context import PipelineContext
from liveclip.pipeline.steps.export_clips import ExportClipsStep
from liveclip.storage.paths import RunPaths


def test_export_clips_step_clamps_max_workers() -> None:
    step = ExportClipsStep(max_workers=0)

    assert step._max_workers == 1


def test_resolve_parts_from_subtitle_indices() -> None:
    subtitles = [
        SubtitleEntry(index=1, start=0.0, end=3.0, text="开头。"),
        SubtitleEntry(index=2, start=3.0, end=5.5, text="中间。"),
        SubtitleEntry(index=3, start=10.0, end=12.0, text="结尾。"),
    ]
    segment = ClipSegment(
        title="拼接片段",
        start_subtitle_index=1,
        end_subtitle_index=3,
        parts=[
            {"start_subtitle_index": 1, "end_subtitle_index": 2},
            {"start_subtitle_index": 3, "end_subtitle_index": 3},
        ],
    )

    assert ExportClipsStep._resolve_parts(segment, subtitles) == [(0.0, 5.5), (10.0, 2.0)]


def test_resolve_parts_accepts_seconds_fallback() -> None:
    segment = ClipSegment(
        title="秒级拼接片段",
        start_subtitle_index=1,
        end_subtitle_index=1,
        parts=[{"start": 2.5, "end": 8.0}],
    )

    assert ExportClipsStep._resolve_parts(segment, []) == [(2.5, 5.5)]


def test_load_timing_subtitles_prefers_preprocessed_index_space(tmp_path) -> None:
    raw_srt = tmp_path / "source.srt"
    raw_srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nraw one\n\n2\n00:00:01,000 --> 00:00:02,000\nraw two\n",
        encoding="utf-8",
    )
    processed_srt = tmp_path / "processed.srt"
    processed_srt.write_text(
        "1\n00:10:00,000 --> 00:11:00,000\nprocessed merged\n",
        encoding="utf-8",
    )
    paths = RunPaths(base_dir=tmp_path, room_id=1, run_id=1)
    ctx = PipelineContext(
        task_id=1,
        room_id=1,
        run_id=1,
        paths=paths,
        pipeline_config=PipelineConfig(),
        clip_segment_config=ClipSegmentConfig(),
        llm_call_config=LLMCallConfig(),
        record_config=RecordConfig(),
    )
    ctx.set_step_result(
        str(StepName.PREPROCESS_SUBTITLE),
        StepResult(success=True, output_path=str(processed_srt)),
    )
    ctx.set_step_result(
        str(StepName.TRANSCRIBE), StepResult(success=True, output_path=str(raw_srt))
    )

    subtitles = ExportClipsStep._load_timing_subtitles(
        ctx, tmp_path / "source.mp4", index_space="processed"
    )

    assert len(subtitles) == 1
    assert subtitles[0].start == 600.0
    assert subtitles[0].text == "processed merged"


def test_load_timing_subtitles_uses_raw_index_space_when_plan_is_raw(tmp_path) -> None:
    raw_srt = tmp_path / "source.srt"
    raw_srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nraw one\n\n2\n00:00:01,000 --> 00:00:02,000\nraw two\n",
        encoding="utf-8",
    )
    processed_srt = tmp_path / "processed.srt"
    processed_srt.write_text(
        "1\n00:10:00,000 --> 00:11:00,000\nprocessed merged\n",
        encoding="utf-8",
    )
    paths = RunPaths(base_dir=tmp_path, room_id=1, run_id=1)
    ctx = PipelineContext(
        task_id=1,
        room_id=1,
        run_id=1,
        paths=paths,
        pipeline_config=PipelineConfig(),
        clip_segment_config=ClipSegmentConfig(),
        llm_call_config=LLMCallConfig(),
        record_config=RecordConfig(),
    )
    ctx.set_step_result(
        str(StepName.PREPROCESS_SUBTITLE),
        StepResult(success=True, output_path=str(processed_srt)),
    )
    ctx.set_step_result(
        str(StepName.TRANSCRIBE), StepResult(success=True, output_path=str(raw_srt))
    )

    subtitles = ExportClipsStep._load_timing_subtitles(
        ctx, tmp_path / "source.mp4", index_space="raw"
    )

    assert [sub.text for sub in subtitles] == ["raw one", "raw two"]


def test_load_export_subtitles_prefers_raw_transcription(tmp_path) -> None:
    raw_srt = tmp_path / "source.srt"
    raw_srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\nraw one\n\n2\n00:00:01,000 --> 00:00:02,000\nraw two\n",
        encoding="utf-8",
    )
    processed_srt = tmp_path / "processed.srt"
    processed_srt.write_text(
        "1\n00:00:00,000 --> 00:00:02,000\nprocessed merged\n",
        encoding="utf-8",
    )
    paths = RunPaths(base_dir=tmp_path, room_id=1, run_id=1)
    ctx = PipelineContext(
        task_id=1,
        room_id=1,
        run_id=1,
        paths=paths,
        pipeline_config=PipelineConfig(),
        clip_segment_config=ClipSegmentConfig(),
        llm_call_config=LLMCallConfig(),
        record_config=RecordConfig(),
    )
    ctx.set_step_result(
        str(StepName.PREPROCESS_SUBTITLE),
        StepResult(success=True, output_path=str(processed_srt)),
    )
    ctx.set_step_result(
        str(StepName.TRANSCRIBE), StepResult(success=True, output_path=str(raw_srt))
    )

    subtitles = ExportClipsStep._load_export_subtitles(ctx, tmp_path / "source.mp4")

    assert [sub.text for sub in subtitles] == ["raw one", "raw two"]


def test_slice_subtitles_by_time_clamps_to_clip_range() -> None:
    subtitles = [
        SubtitleEntry(index=1, start=0.0, end=2.0, text="before"),
        SubtitleEntry(index=2, start=2.0, end=4.0, text="inside"),
        SubtitleEntry(index=3, start=4.0, end=6.0, text="after"),
    ]

    sliced = ExportClipsStep._slice_subtitles_by_time(subtitles, 1.0, 5.0)

    assert [(sub.start, sub.end, sub.text) for sub in sliced] == [
        (1.0, 2.0, "before"),
        (2.0, 4.0, "inside"),
        (4.0, 5.0, "after"),
    ]


def test_slice_part_subtitles_rebases_each_part_to_concat_timeline() -> None:
    subtitles = [
        SubtitleEntry(index=1, start=0.0, end=2.0, text="one"),
        SubtitleEntry(index=2, start=10.0, end=12.0, text="two"),
    ]

    sliced = ExportClipsStep._slice_part_subtitles(subtitles, [(0.0, 2.0), (10.0, 2.0)])

    assert [(sub.index, sub.start, sub.end, sub.text) for sub in sliced] == [
        (1, 0.0, 2.0, "one"),
        (2, 2.0, 4.0, "two"),
    ]


def test_prepare_clips_dir_removes_stale_media(tmp_path) -> None:
    for name in ["old.mp4", "old.srt", "old.mp4.part", "old_concat.txt"]:
        (tmp_path / name).write_text("stale", encoding="utf-8")
    summary = tmp_path / "export_summary.json"
    summary.write_text("{}", encoding="utf-8")

    ExportClipsStep._prepare_clips_dir(tmp_path)

    assert not (tmp_path / "old.mp4").exists()
    assert not (tmp_path / "old.srt").exists()
    assert not (tmp_path / "old.mp4.part").exists()
    assert not (tmp_path / "old_concat.txt").exists()
    assert summary.exists()
