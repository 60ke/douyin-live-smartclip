from __future__ import annotations

from liveclip.domain.enums import StepName
from liveclip.domain.models import PipelineConfig
from liveclip.pipeline.state_machine import (
    PIPELINE_STEPS,
    get_enabled_steps,
    get_next_step,
    should_run_step,
)


class TestPipelineSteps:
    """Tests for PIPELINE_STEPS order."""

    def test_step_order(self) -> None:
        assert PIPELINE_STEPS == [
            StepName.RECORD_TS,
            StepName.CONVERT_MP4,
            StepName.TRANSCRIBE,
            StepName.PREPROCESS_SUBTITLE,
            StepName.PLAN_CLIPS,
            StepName.VALIDATE_BOUNDARY,
            StepName.EXPORT_CLIPS,
            StepName.FINALIZE,
        ]

    def test_first_step_is_record(self) -> None:
        assert PIPELINE_STEPS[0] == StepName.RECORD_TS

    def test_last_step_is_finalize(self) -> None:
        assert PIPELINE_STEPS[-1] == StepName.FINALIZE


class TestShouldRunStep:
    """Tests for should_run_step function."""

    def test_always_run_steps(self) -> None:
        config = PipelineConfig()
        assert should_run_step(StepName.RECORD_TS, config) is True
        assert should_run_step(StepName.FINALIZE, config) is True

    def test_configurable_step_enabled(self) -> None:
        config = PipelineConfig(convert_mp4=True)
        assert should_run_step(StepName.CONVERT_MP4, config) is True

    def test_configurable_step_disabled(self) -> None:
        config = PipelineConfig(convert_mp4=False)
        assert should_run_step(StepName.CONVERT_MP4, config) is False


class TestGetEnabledSteps:
    """Tests for get_enabled_steps function."""

    def test_all_enabled(self) -> None:
        config = PipelineConfig()
        steps = get_enabled_steps(config)
        assert len(steps) == len(PIPELINE_STEPS)

    def test_some_disabled(self) -> None:
        config = PipelineConfig(
            convert_mp4=False,
            transcribe=False,
        )
        steps = get_enabled_steps(config)
        assert StepName.CONVERT_MP4 not in steps
        assert StepName.TRANSCRIBE not in steps
        assert StepName.RECORD_TS in steps
        assert StepName.FINALIZE in steps


class TestGetNextStep:
    """Tests for get_next_step function."""

    def test_from_none(self) -> None:
        config = PipelineConfig()
        result = get_next_step(None, config)
        assert result == StepName.RECORD_TS

    def test_from_record_ts(self) -> None:
        config = PipelineConfig()
        result = get_next_step(StepName.RECORD_TS, config)
        assert result == StepName.CONVERT_MP4

    def test_from_last_step(self) -> None:
        config = PipelineConfig()
        result = get_next_step(StepName.FINALIZE, config)
        assert result is None

    def test_with_disabled_step(self) -> None:
        config = PipelineConfig(convert_mp4=False)
        result = get_next_step(StepName.RECORD_TS, config)
        assert result == StepName.TRANSCRIBE

    def test_all_disabled_except_mandatory(self) -> None:
        config = PipelineConfig(
            convert_mp4=False,
            transcribe=False,
            preprocess_subtitle=False,
            plan_clips=False,
            validate_boundary=False,
            export_clips=False,
        )
        steps = get_enabled_steps(config)
        assert steps == [StepName.RECORD_TS, StepName.FINALIZE]
