"""切片与切片方案相关 API Schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

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
    created_at: datetime
