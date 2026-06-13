"""任务相关 API Schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from liveclip.domain.enums import TaskType


class TaskCreate(BaseModel):
    """创建任务请求。"""

    room_id: int
    task_type: TaskType
    cron_expression: str | None = None
    pipeline_config_json: str | None = None
    enabled: bool = True


class TaskUpdate(BaseModel):
    """更新任务请求。"""

    cron_expression: str | None = None
    pipeline_config_json: str | None = None
    enabled: bool | None = None


class TaskResponse(BaseModel):
    """任务响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    room_id: int
    task_type: TaskType
    cron_expression: str | None
    pipeline_config_json: str | None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class TaskListResponse(BaseModel):
    """任务列表响应。"""

    items: list[TaskResponse]
    total: int
