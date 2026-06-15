from __future__ import annotations

from pathlib import Path

from liveclip.domain.enums import StepName
from liveclip.domain.models import (
    ClipSegmentConfig,
    LLMCallConfig,
    PipelineConfig,
    RecordConfig,
    StepResult,
)
from liveclip.pipeline.context import PipelineContext
from liveclip.pipeline.steps.preprocess_subtitle import PreprocessSubtitleStep
from liveclip.storage.paths import RunPaths


def test_preprocess_writes_combined_srt_without_overwriting_raw(tmp_path: Path) -> None:
    paths = RunPaths(base_dir=tmp_path, room_id=1, run_id=7)
    paths.ensure_all_dirs()
    raw_content = (
        "1\n00:00:00,000 --> 00:00:01,000\n你好，\n\n"
        "2\n00:00:01,100 --> 00:00:02,000\n欢迎来到直播间。\n"
    )
    paths.srt_path.write_text(raw_content, encoding="utf-8")
    ctx = PipelineContext(
        task_id=1,
        room_id=1,
        run_id=7,
        paths=paths,
        pipeline_config=PipelineConfig(),
        clip_segment_config=ClipSegmentConfig(),
        llm_call_config=LLMCallConfig(),
        record_config=RecordConfig(),
    )
    ctx.set_step_result(
        str(StepName.TRANSCRIBE),
        StepResult(success=True, output_path=str(paths.srt_path)),
    )

    result = PreprocessSubtitleStep().execute(ctx)

    assert result.output_path == str(paths.combined_srt_path)
    assert paths.srt_path.read_text(encoding="utf-8") == raw_content
    assert paths.combined_srt_path.exists()
