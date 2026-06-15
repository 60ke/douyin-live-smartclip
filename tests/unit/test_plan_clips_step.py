from __future__ import annotations

import json
from pathlib import Path

from pytest import MonkeyPatch

from liveclip.domain.models import (
    ClipSegment,
    ClipSegmentConfig,
    LLMCallConfig,
    PipelineConfig,
    RecordConfig,
    SubtitleEntry,
)
from liveclip.pipeline.context import PipelineContext
from liveclip.pipeline.steps.plan_clips import (
    PlanClipsStep,
    _extract_items,
    parse_llm_response,
    postprocess_segments,
    subtitle_payload,
    subtitles_from_sentences,
)
from liveclip.storage.paths import RunPaths


def _ctx(tmp_path: Path, clip_config: ClipSegmentConfig) -> PipelineContext:
    return PipelineContext(
        run_id=1,
        room_id=1,
        task_id=1,
        paths=RunPaths(base_dir=tmp_path, room_id=1, run_id=1),
        pipeline_config=PipelineConfig(),
        clip_segment_config=clip_config,
        llm_call_config=LLMCallConfig(),
        record_config=RecordConfig(),
    )


def _ctx_with_pipeline(
    tmp_path: Path,
    clip_config: ClipSegmentConfig,
    pipeline_config: PipelineConfig,
) -> PipelineContext:
    return PipelineContext(
        run_id=1,
        room_id=1,
        task_id=1,
        paths=RunPaths(base_dir=tmp_path, room_id=1, run_id=1),
        pipeline_config=pipeline_config,
        clip_segment_config=clip_config,
        llm_call_config=LLMCallConfig(),
        record_config=RecordConfig(),
    )


def test_parse_llm_response_skips_rejected_and_bad_structure() -> None:
    raw = json.dumps(
        {
            "segments": [
                {
                    "keep": False,
                    "title": "不要",
                    "start_subtitle_index": 1,
                    "end_subtitle_index": 2,
                    "score": 0.95,
                },
                {
                    "title": "结构太差",
                    "start_subtitle_index": 1,
                    "end_subtitle_index": 2,
                    "score": 0.95,
                    "structure_score": 0.3,
                },
                {
                    "topic": "可用片段",
                    "start_subtitle_index": 3,
                    "end_subtitle_index": 8,
                    "score": 0.9,
                    "structure_score": 0.5,
                },
            ]
        },
        ensure_ascii=False,
    )

    segments = parse_llm_response(raw)

    assert len(segments) == 1
    assert segments[0].title == "可用片段"
    assert segments[0].score == 0.55


def test_parse_llm_response_accepts_legacy_aliases_and_time_fallback() -> None:
    subtitles = [
        SubtitleEntry(index=10, start=1.0, end=3.0, text="第一段。"),
        SubtitleEntry(index=11, start=5.0, end=8.0, text="第二段。"),
        SubtitleEntry(index=12, start=10.0, end=14.0, text="第三段。"),
    ]
    raw = json.dumps(
        {
            "clips": [
                {
                    "title": "别名 parts",
                    "ranges": [{"start_index": 10, "end_index": 11}],
                    "score": 0.8,
                    "structure_score": 0.9,
                },
                {
                    "title": "时间兜底",
                    "start_time": "00:00:10.000",
                    "end_time": "00:00:14.000",
                    "score": 0.8,
                },
            ]
        },
        ensure_ascii=False,
    )

    segments = parse_llm_response(raw, subtitles)

    assert segments[0].start_subtitle_index == 10
    assert segments[0].end_subtitle_index == 11
    assert segments[0].parts[0]["start"] == 1.0
    assert segments[0].score == 0.865
    assert segments[1].start_subtitle_index == 12
    assert segments[1].end_subtitle_index == 12


def test_parse_llm_response_accepts_single_segment_object() -> None:
    raw = json.dumps(
        {
            "title": "单对象片段",
            "start_subtitle_index": 1,
            "end_subtitle_index": 5,
            "score": 0.8,
        },
        ensure_ascii=False,
    )

    segments = parse_llm_response(raw)

    assert len(segments) == 1
    assert segments[0].title == "单对象片段"
    assert segments[0].start_subtitle_index == 1
    assert segments[0].end_subtitle_index == 5


def test_parse_llm_response_defaults_missing_score_like_old_smartclip() -> None:
    raw = json.dumps(
        {
            "segments": [
                {
                    "title": "缺少分数但可保留",
                    "start_subtitle_index": 1,
                    "end_subtitle_index": 2,
                }
            ]
        },
        ensure_ascii=False,
    )

    segment = parse_llm_response(raw)[0]

    assert segment.score == 0.7


class _BadRefineLLM:
    def chat(self, **kwargs: object) -> str:
        return json.dumps({"keep": False, "reason": "不适合成片"}, ensure_ascii=False)


class _CaptureLLM:
    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def chat(self, **kwargs: object) -> str:
        self.calls.append(kwargs)
        return self.response


def test_refine_candidate_parse_failure_drops_candidate(tmp_path: Path) -> None:
    subtitles = [
        SubtitleEntry(index=1, start=0.0, end=10.0, text="开头。"),
        SubtitleEntry(index=2, start=10.0, end=20.0, text="结尾。"),
    ]
    ctx = _ctx(tmp_path, ClipSegmentConfig())
    step = PlanClipsStep(llm_client=_BadRefineLLM())  # type: ignore[arg-type]

    segments, raw = step._refine_candidate(
        ctx,
        {
            "topic": "无效候选",
            "start_subtitle_index": 1,
            "end_subtitle_index": 2,
        },
        subtitles,
    )

    assert segments == []
    assert "不适合成片" in raw


def test_refine_candidate_uses_large_token_window(tmp_path: Path) -> None:
    subtitles = [
        SubtitleEntry(index=1, start=0.0, end=10.0, text="开头。"),
        SubtitleEntry(index=2, start=10.0, end=20.0, text="结尾。"),
    ]
    ctx = _ctx(tmp_path, ClipSegmentConfig())
    llm = _CaptureLLM(
        json.dumps(
            {
                "segments": [
                    {
                        "title": "可切片段",
                        "start_subtitle_index": 1,
                        "end_subtitle_index": 2,
                    }
                ]
            },
            ensure_ascii=False,
        )
    )
    step = PlanClipsStep(llm_client=llm)  # type: ignore[arg-type]

    segments, _ = step._refine_candidate(
        ctx,
        {"topic": "候选", "start_subtitle_index": 1, "end_subtitle_index": 2},
        subtitles,
    )

    assert len(segments) == 1
    assert llm.calls[0]["max_tokens"] == 4_000
    assert llm.calls[0]["timeout_seconds"] == 75


def test_full_prompt_uses_large_token_window(tmp_path: Path) -> None:
    subtitles = [SubtitleEntry(index=1, start=0.0, end=10.0, text="开头。")]
    sentences = [{"start_subtitle_index": 1, "end_subtitle_index": 1, "text": "开头。"}]
    ctx = _ctx(tmp_path, ClipSegmentConfig())
    llm = _CaptureLLM('{"segments": []}')
    step = PlanClipsStep(llm_client=llm)  # type: ignore[arg-type]

    response = step._call_full_prompt(ctx, subtitles, sentences)

    assert response == '{"segments": []}'
    assert llm.calls[0]["max_tokens"] == 8_000
    assert llm.calls[0]["timeout_seconds"] == 180


def test_full_prompt_uses_planner_duration_config(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        ClipSegmentConfig(
            min_segment_seconds=15.0,
            target_segment_seconds=60.0,
            max_segment_seconds=90.0,
            hard_max_segment_seconds=120.0,
            min_export_segment_seconds=15.0,
        ),
    )
    ctx.record_config = RecordConfig(max_duration_seconds=300)

    prompt = PlanClipsStep()._render_full_prompt(ctx)

    assert "目标时长：15 秒 ～ 60 秒" in prompt
    assert "硬性上限：120 秒" in prompt
    assert "总时长不超过 300 秒" in prompt


def test_extract_items_recovers_complete_candidates_from_truncated_response() -> None:
    raw = (
        '{"candidates": ['
        '{"topic": "完整候选", "start_subtitle_index": 1, "end_subtitle_index": 10},'
        '{"topic": "被截断候选", "start_subtitle_index": 11, "drop_notes": "未闭合'
    )

    items = _extract_items(raw, ("clips", "candidates", "segments"))

    assert items == [{"topic": "完整候选", "start_subtitle_index": 1, "end_subtitle_index": 10}]


def test_parse_llm_response_preserves_validation_metadata() -> None:
    raw = json.dumps(
        {
            "segments": [
                {
                    "title": "带校验信息",
                    "start_subtitle_index": 1,
                    "end_subtitle_index": 2,
                    "score": 0.9,
                    "structure_score": 0.9,
                    "duration_status": "normal",
                    "content_type": "feature_demo",
                    "first_sentence": "开头",
                    "last_sentence": "结尾",
                    "end_boundary_quality": "strong",
                    "trim_attempts": "无需调整",
                }
            ]
        },
        ensure_ascii=False,
    )

    segment = parse_llm_response(raw)[0]

    assert segment.validation["duration_status"] == "normal"
    assert segment.validation["content_type"] == "feature_demo"
    assert segment.validation["trim_note"] == "无需调整"


def test_postprocess_segments_keeps_short_segments_until_boundary_filter(tmp_path: Path) -> None:
    subtitles = [
        SubtitleEntry(index=1, start=0.0, end=30.0, text="短片段。"),
        SubtitleEntry(index=2, start=30.0, end=60.0, text="还是短。"),
        SubtitleEntry(index=3, start=60.0, end=100.0, text="长片段开始。"),
        SubtitleEntry(index=4, start=100.0, end=150.0, text="长片段结束。"),
    ]
    segments = [
        ClipSegment(
            title="短",
            start_subtitle_index=1,
            end_subtitle_index=2,
            score=0.7,
        ),
        ClipSegment(
            title="长",
            start_subtitle_index=3,
            end_subtitle_index=4,
            score=0.85,
        ),
    ]
    ctx = _ctx_with_pipeline(
        tmp_path,
        ClipSegmentConfig(
            min_segment_seconds=90.0,
            target_segment_seconds=120.0,
            max_segment_seconds=150.0,
            hard_max_segment_seconds=180.0,
            min_score=0.5,
        ),
        PipelineConfig(clip_plan_mode="full"),
    )

    result = postprocess_segments(segments, subtitles, ctx)

    assert [segment.title for segment in result] == ["短", "长"]


def test_postprocess_segments_dedupes_before_score_filter_like_old_project(tmp_path: Path) -> None:
    subtitles = [
        SubtitleEntry(index=1, start=0.0, end=60.0, text="开头。"),
        SubtitleEntry(index=2, start=60.0, end=120.0, text="结尾。"),
    ]
    high_score = ClipSegment(
        title="高分重叠",
        start_subtitle_index=1,
        end_subtitle_index=2,
        score=0.9,
    )
    low_score = ClipSegment(
        title="低分重叠",
        start_subtitle_index=1,
        end_subtitle_index=2,
        score=0.4,
    )
    ctx = _ctx(tmp_path, ClipSegmentConfig(min_score=0.5))

    result = postprocess_segments([low_score, high_score], subtitles, ctx)

    assert [segment.title for segment in result] == ["高分重叠"]


def test_postprocess_segments_legacy_uses_old_short_clip_threshold(tmp_path: Path) -> None:
    subtitles = [
        SubtitleEntry(index=1, start=0.0, end=30.0, text="短片段。"),
        SubtitleEntry(index=2, start=30.0, end=58.0, text="高分短片段。"),
    ]
    segment = ClipSegment(
        title="旧逻辑高分短片",
        start_subtitle_index=1,
        end_subtitle_index=2,
        score=0.85,
    )
    ctx = _ctx(
        tmp_path,
        ClipSegmentConfig(
            min_segment_seconds=90.0,
            target_segment_seconds=120.0,
            max_segment_seconds=150.0,
            hard_max_segment_seconds=180.0,
            min_score=0.5,
        ),
    )

    result = postprocess_segments([segment], subtitles, ctx)

    assert [item.title for item in result] == ["旧逻辑高分短片"]


def test_postprocess_segments_legacy_does_not_split_under_full_window(tmp_path: Path) -> None:
    subtitles = [
        SubtitleEntry(index=1, start=0.0, end=110.0, text="第一部分。"),
        SubtitleEntry(index=2, start=110.0, end=220.0, text="第二部分。"),
    ]
    segment = ClipSegment(
        title="旧逻辑完整长片",
        start_subtitle_index=1,
        end_subtitle_index=2,
        score=0.85,
    )
    ctx = _ctx(
        tmp_path,
        ClipSegmentConfig(
            min_segment_seconds=90.0,
            target_segment_seconds=120.0,
            max_segment_seconds=150.0,
            hard_max_segment_seconds=180.0,
            min_score=0.5,
        ),
    )

    result = postprocess_segments([segment], subtitles, ctx)

    assert len(result) == 1
    assert result[0].title == "旧逻辑完整长片"
    assert result[0].start_subtitle_index == 1
    assert result[0].end_subtitle_index == 2


def test_postprocess_segments_uses_parts_duration(tmp_path: Path) -> None:
    subtitles = [
        SubtitleEntry(index=1, start=0.0, end=50.0, text="第一段。"),
        SubtitleEntry(index=2, start=50.0, end=500.0, text="中间噪音。"),
        SubtitleEntry(index=3, start=500.0, end=560.0, text="第二段。"),
    ]
    segment = ClipSegment(
        title="跳剪",
        start_subtitle_index=1,
        end_subtitle_index=3,
        parts=[
            {"start_subtitle_index": 1, "end_subtitle_index": 1},
            {"start_subtitle_index": 3, "end_subtitle_index": 3},
        ],
        score=0.85,
    )
    ctx = _ctx(
        tmp_path,
        ClipSegmentConfig(
            min_segment_seconds=90.0,
            target_segment_seconds=120.0,
            max_segment_seconds=150.0,
            hard_max_segment_seconds=180.0,
            min_score=0.5,
        ),
    )

    result = postprocess_segments([segment], subtitles, ctx)

    assert len(result) == 1
    assert result[0].parts[0]["start"] == 0.0
    assert result[0].parts[1]["start"] == 500.0


def test_subtitles_from_sentences_builds_typed_entries() -> None:
    result = subtitles_from_sentences([{"index": "1", "start": "0.5", "end": 2, "text": "你好。"}])

    assert result == [SubtitleEntry(index=1, start=0.5, end=2.0, text="你好。")]


def test_subtitle_payload_matches_old_smartclip_fields() -> None:
    payload = subtitle_payload(SubtitleEntry(index=7, start=1.23, end=4.56, text="内容。"))

    assert payload == {
        "index": 7,
        "start_time": "00:00:01.230",
        "end_time": "00:00:04.560",
        "text": "内容。",
    }


def test_dump_llm_creates_dump_dir_from_environment(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    dump_dir = tmp_path / "missing" / "dump"
    monkeypatch.setenv("LIVECLIP_LLM_DUMP_DIR", str(dump_dir))
    ctx = _ctx(tmp_path, ClipSegmentConfig())

    PlanClipsStep()._dump_llm(ctx, "structure_system", "system", "{}")

    assert (dump_dir / "001_structure_system_system.txt").read_text() == "system"
    assert (dump_dir / "001_structure_system_user.json").read_text() == "{}"
