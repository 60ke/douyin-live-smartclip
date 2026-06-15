from __future__ import annotations

from sqlalchemy import BigInteger

from liveclip.db.models import Clip, ClipPlan, Record
from liveclip.domain.models import (
    ClipSegment,
    ClipSegmentConfig,
    PipelineConfig,
    StepResult,
    SubtitleEntry,
)


class TestDbArtifactModels:
    """Tests for DB artifact model columns that protect production data."""

    def test_record_file_size_uses_bigint(self) -> None:
        assert isinstance(Record.__table__.c.file_size.type, BigInteger)

    def test_clip_plan_has_updated_at(self) -> None:
        assert "updated_at" in ClipPlan.__table__.c

    def test_clip_has_updated_at(self) -> None:
        assert "updated_at" in Clip.__table__.c

    def test_clip_has_highlight_columns(self) -> None:
        assert "highlight_enabled" in Clip.__table__.c
        assert "highlight_start_seconds" in Clip.__table__.c
        assert "highlight_end_seconds" in Clip.__table__.c
        assert "highlight_video_path" in Clip.__table__.c


class TestSubtitleEntry:
    """Tests for SubtitleEntry domain model."""

    def test_creation(self) -> None:
        entry = SubtitleEntry(index=1, start=1.0, end=3.5, text="你好")
        assert entry.index == 1
        assert entry.start == 1.0
        assert entry.end == 3.5
        assert entry.text == "你好"

    def test_duration_property(self) -> None:
        entry = SubtitleEntry(index=1, start=1.0, end=3.5, text="你好")
        assert entry.duration == 2.5

    def test_duration_zero(self) -> None:
        entry = SubtitleEntry(index=1, start=5.0, end=5.0, text="瞬间")
        assert entry.duration == 0.0


class TestClipSegment:
    """Tests for ClipSegment domain model."""

    def test_creation(self) -> None:
        seg = ClipSegment(
            title="测试片段",
            start_subtitle_index=1,
            end_subtitle_index=5,
        )
        assert seg.title == "测试片段"
        assert seg.start_subtitle_index == 1
        assert seg.end_subtitle_index == 5
        assert seg.parts == []
        assert seg.score == 0.0
        assert seg.reason == ""

    def test_to_dict(self) -> None:
        seg = ClipSegment(
            title="测试片段",
            start_subtitle_index=1,
            end_subtitle_index=5,
            score=0.8,
            reason="很好",
        )
        d = seg.to_dict()
        assert isinstance(d, dict)
        assert d["title"] == "测试片段"
        assert d["start_subtitle_index"] == 1
        assert d["end_subtitle_index"] == 5
        assert d["score"] == 0.8
        assert d["reason"] == "很好"

    def test_with_parts(self) -> None:
        parts = [{"start_subtitle_index": 1, "end_subtitle_index": 3}]
        seg = ClipSegment(
            title="带parts的片段",
            start_subtitle_index=1,
            end_subtitle_index=5,
            parts=parts,
        )
        assert len(seg.parts) == 1


class TestStepResult:
    """Tests for StepResult domain model."""

    def test_creation_success(self) -> None:
        result = StepResult(success=True, output_path="/tmp/out.mp4")
        assert result.success is True
        assert result.output_path == "/tmp/out.mp4"
        assert result.error_code is None
        assert result.duration_ms == 0

    def test_creation_failure(self) -> None:
        result = StepResult(
            success=False,
            error_code="RECORD_FAILED",
            error_message="录制失败",
        )
        assert result.success is False
        assert result.error_code == "RECORD_FAILED"
        assert result.error_message == "录制失败"

    def test_with_metadata(self) -> None:
        result = StepResult(
            success=True,
            metadata={"key": "value"},
        )
        assert result.metadata == {"key": "value"}


class TestPipelineConfig:
    """Tests for PipelineConfig defaults."""

    def test_defaults(self) -> None:
        config = PipelineConfig()
        assert config.convert_mp4 is True
        assert config.transcribe is True
        assert config.preprocess_subtitle is True
        assert config.plan_clips is True
        assert config.validate_boundary is True
        assert config.validate_boundary_use_llm is False
        assert config.export_clips is True

    def test_custom_values(self) -> None:
        config = PipelineConfig(
            convert_mp4=False,
            transcribe=False,
            export_clips=False,
        )
        assert config.convert_mp4 is False
        assert config.transcribe is False
        assert config.export_clips is False


class TestClipSegmentConfig:
    """Tests for ClipSegmentConfig defaults."""

    def test_defaults(self) -> None:
        config = ClipSegmentConfig()
        assert config.target_segment_seconds == 120.0
        assert config.min_segment_seconds == 90.0
        assert config.max_segment_seconds == 150.0
        assert config.hard_max_segment_seconds == 180.0
        assert config.min_score == 0.5
        assert config.min_export_segment_seconds == 45.0
        assert config.export_high_score_threshold == 0.8

    def test_custom_values(self) -> None:
        config = ClipSegmentConfig(
            target_segment_seconds=60.0,
            min_score=0.7,
            min_export_segment_seconds=30.0,
        )
        assert config.target_segment_seconds == 60.0
        assert config.min_score == 0.7
        assert config.min_export_segment_seconds == 30.0
