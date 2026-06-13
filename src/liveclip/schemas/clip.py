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
    title: str
    start_subtitle_index: int
    end_subtitle_index: int
    parts_json: str | None
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
