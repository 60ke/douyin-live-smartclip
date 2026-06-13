from __future__ import annotations

from pathlib import Path
from typing import Any

from liveclip.adapters.douyin.live_status import DouyinLiveStatus
from liveclip.adapters.douyin.resolver import DouyinRoomInfo
from liveclip.domain.enums import StepName
from liveclip.domain.models import (
    ClipSegmentConfig,
    LLMCallConfig,
    PipelineConfig,
    RecordConfig,
    StepResult,
)
from liveclip.pipeline.context import PipelineContext
from liveclip.pipeline.steps import (
    ConvertMp4Step,
    ExportClipsStep,
    FinalizeStep,
    PlanClipsStep,
    PreprocessSubtitleStep,
    RecordTsStep,
    TranscribeStep,
    ValidateBoundaryStep,
)
from liveclip.storage.paths import RunPaths


class FakeResolver:
    def resolve_room_info(self, url: str, cookie: str | None = None) -> DouyinRoomInfo:
        return DouyinRoomInfo(
            room_id="room-1",
            web_rid="926637114034",
            sec_user_id="sec",
            anchor_name="测试主播",
        )


class FakeLiveChecker:
    def check_live(
        self,
        room_info: DouyinRoomInfo,
        cookie: str | None = None,
    ) -> DouyinLiveStatus:
        return DouyinLiveStatus(
            is_live=True,
            anchor_name=room_info.anchor_name,
            title="测试直播",
            stream_url=None,
        )


class FakeStreamFetcher:
    def get_stream_url(
        self,
        room_info: DouyinRoomInfo,
        quality: str = "origin",
        cookie: str | None = None,
    ) -> str:
        return "https://example.com/live.flv"


class FakeRecorder:
    def record(
        self,
        stream_url: str,
        output_path: Path,
        max_duration: int | None = None,
        headers: str | None = None,
        http_proxy: str | None = None,
        cancel_check: object | None = None,
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"fake-ts")
        return output_path


class FakeConverter:
    def convert_ts_to_mp4(
        self,
        input_path: Path,
        output_path: Path,
        reencode_h264: bool = False,
        cancel_check: object | None = None,
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(input_path.read_bytes() + b"-mp4")
        return output_path


class FakeTranscriber:
    def transcribe(
        self,
        video_path: Path,
        output_srt_path: Path,
        hotwords: list[str] | None = None,
        cancel_check: object | None = None,
    ) -> Path:
        output_srt_path.parent.mkdir(parents=True, exist_ok=True)
        output_srt_path.write_text(
            "1\n"
            "00:00:00,000 --> 00:00:03,000\n"
            "这是完整开头。\n\n"
            "2\n"
            "00:00:04,000 --> 00:00:08,000\n"
            "这是完整结尾。\n\n",
            encoding="utf-8",
        )
        return output_srt_path


class FakeHotwords:
    def load_hotwords(self) -> list[str]:
        return ["测试"]


class FakeLLM:
    def chat(self, **kwargs: Any) -> str:
        return (
            '{"segments":[{"title":"完整片段","start_subtitle_index":1,'
            '"end_subtitle_index":2,"score":0.9,"structure_score":0.9,'
            '"reason":"测试完整链路"}]}'
        )


class FakeClipper:
    def clip_segment(
        self,
        input_path: Path,
        output_path: Path,
        start_seconds: float,
        duration_seconds: float,
        cancel_check: object | None = None,
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"clip")
        return output_path

    def clip_parts(
        self,
        input_path: Path,
        output_path: Path,
        parts: list[tuple[float, float]],
        cancel_check: object | None = None,
    ) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"clip-parts")
        return output_path


def _record_result(ctx: PipelineContext, step_name: StepName, result: StepResult) -> None:
    assert result.success
    ctx.set_step_result(str(step_name), result)


def test_offline_pipeline_runs_record_to_export(tmp_path: Path) -> None:
    paths = RunPaths(base_dir=tmp_path, room_id=1, run_id=10)
    paths.ensure_all_dirs()
    ctx = PipelineContext(
        run_id=10,
        room_id=1,
        task_id=100,
        paths=paths,
        pipeline_config=PipelineConfig(),
        clip_segment_config=ClipSegmentConfig(min_segment_seconds=1.0),
        llm_call_config=LLMCallConfig(),
        record_config=RecordConfig(max_duration_seconds=5, quality="origin"),
    )
    ctx.metadata["room_url"] = "https://live.douyin.com/926637114034"

    _record_result(
        ctx,
        StepName.RECORD_TS,
        RecordTsStep(
            resolver=FakeResolver(),
            live_checker=FakeLiveChecker(),
            stream_fetcher=FakeStreamFetcher(),
            recorder=FakeRecorder(),
        ).execute(ctx),
    )
    _record_result(ctx, StepName.CONVERT_MP4, ConvertMp4Step(FakeConverter()).execute(ctx))
    _record_result(
        ctx,
        StepName.TRANSCRIBE,
        TranscribeStep(transcriber=FakeTranscriber(), hotword_manager=FakeHotwords()).execute(ctx),
    )
    _record_result(ctx, StepName.PREPROCESS_SUBTITLE, PreprocessSubtitleStep().execute(ctx))
    _record_result(ctx, StepName.PLAN_CLIPS, PlanClipsStep(llm_client=FakeLLM()).execute(ctx))
    _record_result(ctx, StepName.VALIDATE_BOUNDARY, ValidateBoundaryStep().execute(ctx))
    _record_result(ctx, StepName.EXPORT_CLIPS, ExportClipsStep(clipper=FakeClipper()).execute(ctx))
    _record_result(ctx, StepName.FINALIZE, FinalizeStep().execute(ctx))

    assert paths.raw_ts_path.exists()
    assert paths.mp4_path.exists()
    assert paths.srt_path.exists()
    assert paths.normalized_plan_path.exists()
    assert paths.validated_plan_path.exists()
    assert (paths.clips_dir / "export_summary.json").exists()
    assert paths.summary_path.exists()
