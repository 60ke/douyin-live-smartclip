"""切片与切片方案相关 API Schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from liveclip.domain.enums import ClipPlanStatus, ClipStatus


class ClipResponse(BaseModel):
    """单个切片响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    plan_id: int
    source_record_id: int | None = None
    title: str
    start_subtitle_index: int
    end_subtitle_index: int
    parts_json: str | None
    start_seconds: float | None = None
    end_seconds: float | None = None
    duration_seconds: float | None = None
    score: float
    structure_score: float
    reason: str
    structure_reason: str
    status: ClipStatus
    output_path: str | None
    subtitle_output_path: str | None
    cover_title: str | None = None
    cover_source_image_path: str | None = None
    cover_image_path: str | None = None
    cover_intro_video_path: str | None = None
    highlight_enabled: bool = False
    highlight_start_seconds: float | None = None
    highlight_end_seconds: float | None = None
    highlight_reason: str | None = None
    highlight_confidence: float | None = None
    highlight_video_path: str | None = None
    final_video_path: str | None = None
    playable_video_path: str | None = None
    created_at: datetime


class ClipPlanResponse(BaseModel):
    """切片方案响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    llm_profile_id: int | None
    status: ClipPlanStatus
    raw_llm_response_path: str | None
    normalized_plan_path: str | None
    validated_plan_path: str | None
    segment_count: int
    resource_status: str = "AVAILABLE"
    resource_deleted_at: datetime | None = None
    resource_cleanup_error: str | None = None
    created_at: datetime
    clips: list[ClipResponse]


class RecordingClipResponse(BaseModel):
    """面向产品界面的录制视频切片映射响应。"""

    id: int
    plan_id: int
    run_id: int
    source_record_id: int
    source_video_path: str
    source_subtitle_path: str | None = None
    room_id: int
    room_name: str
    room_url: str
    task_id: int
    run_status: str
    resource_status: str = "AVAILABLE"
    resource_deleted_at: datetime | None = None
    resource_cleanup_error: str | None = None
    live_started_at: datetime | None = None
    live_finished_at: datetime | None = None
    clip_live_started_at: datetime | None = None
    clip_live_finished_at: datetime | None = None
    title: str
    start_subtitle_index: int
    end_subtitle_index: int
    start_seconds: float | None = None
    end_seconds: float | None = None
    duration_seconds: float | None = None
    parts_json: str | None = None
    score: float
    structure_score: float
    reason: str
    structure_reason: str
    status: ClipStatus
    output_path: str | None
    subtitle_output_path: str | None
    cover_title: str | None = None
    cover_source_image_path: str | None = None
    cover_image_path: str | None = None
    cover_intro_video_path: str | None = None
    highlight_enabled: bool = False
    highlight_start_seconds: float | None = None
    highlight_end_seconds: float | None = None
    highlight_reason: str | None = None
    highlight_confidence: float | None = None
    highlight_video_path: str | None = None
    final_video_path: str | None = None
    playable_video_path: str | None = None
    subtitle_mode: str = "external"
    created_at: datetime


class ClipCoverUpdateRequest(BaseModel):
    """Request body for editing and rendering a clip cover."""

    title: str = Field(..., min_length=1, max_length=80)
    source_image_path: str | None = Field(default=None, max_length=1024)
    cover_duration_seconds: float = Field(default=1.0, gt=0, le=5)
    highlight_enabled: bool = False
    highlight_start_seconds: float | None = Field(default=None, ge=0)
    highlight_end_seconds: float | None = Field(default=None, gt=0)
