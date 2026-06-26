"""运行与步骤相关 API Schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from liveclip.domain.enums import ResourceStatus, RunStatus, StepName, StepStatus, TriggerType


class RunCreate(BaseModel):
    """创建运行请求。"""

    task_id: int
    trigger_type: TriggerType = TriggerType.API


class RunResponse(BaseModel):
    """运行响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    task_id: int
    run_status: RunStatus
    trigger_type: TriggerType
    started_at: datetime | None
    finished_at: datetime | None
    error_code: str | None
    error_message: str | None
    heartbeat_at: datetime | None
    resource_status: ResourceStatus = ResourceStatus.AVAILABLE
    resource_deleted_at: datetime | None = None
    resource_cleanup_error: str | None = None
    pipeline_config_snapshot_json: str | None = None
    created_at: datetime


class RunListResponse(BaseModel):
    """运行列表响应。"""

    items: list[RunResponse]
    total: int


class StepResponse(BaseModel):
    """步骤响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    step_name: StepName
    step_status: StepStatus
    started_at: datetime | None
    finished_at: datetime | None
    input_path: str | None
    output_path: str | None
    error_code: str | None
    error_message: str | None
    duration_ms: int | None
    metadata_json: str | None
    created_at: datetime


class RunDetailResponse(RunResponse):
    """运行详情响应（含步骤列表）。"""

    steps: list[StepResponse]
