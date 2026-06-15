from __future__ import annotations

from liveclip.domain.enums import (
    ClipPlanStatus,
    ClipStatus,
    LiveStatus,
    RecordSourceType,
    RunStatus,
    StepName,
    StepStatus,
    TaskType,
    TriggerType,
)


class TestTaskType:
    """Tests for TaskType enum."""

    def test_values_are_strings(self) -> None:
        for member in TaskType:
            assert isinstance(member.value, str)

    def test_specific_values(self) -> None:
        assert TaskType.ONCE == "ONCE"
        assert TaskType.CRON == "CRON"


class TestRunStatus:
    """Tests for RunStatus enum."""

    def test_values_are_strings(self) -> None:
        for member in RunStatus:
            assert isinstance(member.value, str)

    def test_specific_values(self) -> None:
        assert RunStatus.PENDING == "PENDING"
        assert RunStatus.RUNNING == "RUNNING"
        assert RunStatus.WAITING == "WAITING"
        assert RunStatus.SUCCEEDED == "SUCCEEDED"
        assert RunStatus.FAILED == "FAILED"
        assert RunStatus.CANCELED == "CANCELED"


class TestStepStatus:
    """Tests for StepStatus enum."""

    def test_values_are_strings(self) -> None:
        for member in StepStatus:
            assert isinstance(member.value, str)

    def test_specific_values(self) -> None:
        assert StepStatus.SKIPPED == "SKIPPED"


class TestStepName:
    """Tests for StepName enum."""

    def test_values_are_strings(self) -> None:
        for member in StepName:
            assert isinstance(member.value, str)

    def test_specific_values(self) -> None:
        assert StepName.RECORD_TS == "RECORD_TS"
        assert StepName.FINALIZE == "FINALIZE"


class TestTriggerType:
    """Tests for TriggerType enum."""

    def test_values_are_strings(self) -> None:
        for member in TriggerType:
            assert isinstance(member.value, str)

    def test_specific_values(self) -> None:
        assert TriggerType.API == "API"
        assert TriggerType.DEBUG_FROM_FILE == "DEBUG_FROM_FILE"


class TestLiveStatus:
    """Tests for LiveStatus enum."""

    def test_values_are_strings(self) -> None:
        for member in LiveStatus:
            assert isinstance(member.value, str)

    def test_specific_values(self) -> None:
        assert LiveStatus.LIVE == "LIVE"
        assert LiveStatus.NOT_LIVE == "NOT_LIVE"


class TestRecordSourceType:
    """Tests for RecordSourceType enum."""

    def test_values_are_strings(self) -> None:
        for member in RecordSourceType:
            assert isinstance(member.value, str)

    def test_specific_values(self) -> None:
        assert RecordSourceType.DOUYIN_RECORD == "DOUYIN_RECORD"
        assert RecordSourceType.LOCAL_FILE == "LOCAL_FILE"


class TestClipPlanStatus:
    """Tests for ClipPlanStatus enum."""

    def test_values_are_strings(self) -> None:
        for member in ClipPlanStatus:
            assert isinstance(member.value, str)

    def test_specific_values(self) -> None:
        assert ClipPlanStatus.PENDING == "PENDING"
        assert ClipPlanStatus.PROCESSING == "PROCESSING"
        assert ClipPlanStatus.COMPLETED == "COMPLETED"
        assert ClipPlanStatus.FAILED == "FAILED"


class TestClipStatus:
    """Tests for ClipStatus enum."""

    def test_values_are_strings(self) -> None:
        for member in ClipStatus:
            assert isinstance(member.value, str)

    def test_specific_values(self) -> None:
        assert ClipStatus.PENDING == "PENDING"
        assert ClipStatus.EXPORTING == "EXPORTING"
        assert ClipStatus.COMPLETED == "COMPLETED"
        assert ClipStatus.FAILED == "FAILED"
