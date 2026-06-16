"""liveclip 领域模型定义。"""

from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 配置模型
# ---------------------------------------------------------------------------


class RecordConfig(BaseModel):
    """录制配置。"""

    max_duration_seconds: int = 0
    quality: str = "origin"


class PipelineConfig(BaseModel):
    """流水线步骤开关配置。"""

    convert_mp4: bool = True
    convert_mp4_reencode_h264: bool = False
    transcribe: bool = True
    preprocess_subtitle: bool = True
    plan_clips: bool = True
    clip_plan_mode: str = "legacy"
    clip_plan_subtitle_source: str = "raw"
    validate_boundary: bool = True
    validate_boundary_use_llm: bool = False
    export_clips: bool = True
    hard_subtitle: dict[str, object] | bool | None = None
    cover: dict[str, object] | bool | None = None
    highlight_intro: dict[str, object] | bool | None = None


class ClipSegmentConfig(BaseModel):
    """切片分段参数配置。"""

    target_segment_seconds: float = 120.0
    min_segment_seconds: float = 90.0
    max_segment_seconds: float = 150.0
    hard_max_segment_seconds: float = 180.0
    min_score: float = 0.5
    min_export_segment_seconds: float = 45.0
    export_high_score_threshold: float = 0.8


class LLMCallConfig(BaseModel):
    """大模型调用配置。"""

    temperature: float = 0.2
    max_tokens: int = 1200
    timeout_seconds: int = 90
    max_retries: int = 4


# ---------------------------------------------------------------------------
# 字幕模型
# ---------------------------------------------------------------------------


class SubtitleEntry(BaseModel):
    """单条字幕条目。"""

    index: int
    start: float
    end: float
    text: str

    @property
    def duration(self) -> float:
        """字幕持续时间（秒）。"""
        return self.end - self.start


# ---------------------------------------------------------------------------
# 切片方案模型
# ---------------------------------------------------------------------------


class ClipSegment(BaseModel):
    """单个切片段。"""

    title: str
    start_subtitle_index: int
    end_subtitle_index: int
    parts: list[dict[str, object]] = Field(default_factory=list)
    score: float = 0.0
    reason: str = ""
    structure_score: float = 0.0
    structure_reason: str = ""
    hook: str = ""
    validation: dict[str, object] = Field(default_factory=dict)
    output: str | None = None
    subtitle_output: str | None = None

    def to_dict(self) -> dict[str, object]:
        """转换为可序列化字典。"""
        return self.model_dump()


class ClipPlanResult(BaseModel):
    """切片方案结果。"""

    segments: list[ClipSegment] = Field(default_factory=list)
    subtitle_source: str = "raw"
    index_space: str = "raw"
    planner_mode: str = "legacy"


# ---------------------------------------------------------------------------
# 步骤结果模型
# ---------------------------------------------------------------------------


class StepResult(BaseModel):
    """单个流水线步骤的执行结果。"""

    success: bool
    output_path: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    duration_ms: int = 0
    metadata: dict[str, object] = Field(default_factory=dict)
