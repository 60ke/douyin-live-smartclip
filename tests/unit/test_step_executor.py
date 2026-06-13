from __future__ import annotations

from pathlib import Path

from pytest import MonkeyPatch

from liveclip.config.settings import AppSettings, LLMConfig, StorageConfig
from liveclip.domain.enums import StepName
from liveclip.domain.models import (
    ClipSegmentConfig,
    LLMCallConfig,
    PipelineConfig,
    RecordConfig,
)
from liveclip.pipeline.context import PipelineContext
from liveclip.pipeline.steps.plan_clips import PlanClipsStep
from liveclip.pipeline.steps.validate_boundary import ValidateBoundaryStep
from liveclip.storage.paths import RunPaths
from liveclip.worker.step_executor import StepExecutor


def _ctx(tmp_path: Path) -> PipelineContext:
    return PipelineContext(
        task_id=1,
        room_id=1,
        run_id=1,
        paths=RunPaths(base_dir=tmp_path, room_id=1, run_id=1),
        pipeline_config=PipelineConfig(),
        clip_segment_config=ClipSegmentConfig(),
        llm_call_config=LLMCallConfig(),
        record_config=RecordConfig(),
    )


def test_worker_llm_steps_use_configured_model_not_prompt_profile(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    settings = AppSettings(
        storage=StorageConfig(base_dir=tmp_path),
        llm=LLMConfig(
            model="deepseek-ai/DeepSeek-V4-Flash",
            default_profile_name="default",
            base_url="https://api.siliconflow.cn/v1/chat/completions",
        ),
    )
    executor = StepExecutor(settings)
    ctx = _ctx(tmp_path)

    plan_step = executor._create_step_instance(StepName.PLAN_CLIPS, ctx)
    boundary_step = executor._create_step_instance(StepName.VALIDATE_BOUNDARY, ctx)

    assert isinstance(plan_step, PlanClipsStep)
    assert isinstance(boundary_step, ValidateBoundaryStep)
    assert plan_step._llm_client._model == "deepseek-ai/DeepSeek-V4-Flash"
    assert boundary_step._llm_client._model == "deepseek-ai/DeepSeek-V4-Flash"


def test_worker_llm_steps_prefer_legacy_model_env(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_API", "test-key")
    monkeypatch.setenv("LLM_MODEL", "deepseek-ai/DeepSeek-V4-Flash")
    settings = AppSettings(
        storage=StorageConfig(base_dir=tmp_path),
        llm=LLMConfig(
            model="deepseek-v4-flash",
            default_profile_name="default",
        ),
    )
    executor = StepExecutor(settings)
    ctx = _ctx(tmp_path)

    plan_step = executor._create_step_instance(StepName.PLAN_CLIPS, ctx)

    assert isinstance(plan_step, PlanClipsStep)
    assert plan_step._llm_client._model == "deepseek-ai/DeepSeek-V4-Flash"
