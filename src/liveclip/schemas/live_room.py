"""直播间相关 API Schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class LiveRoomCreate(BaseModel):
    """创建直播间请求。"""

    url: str
    name: str = ""
    platform: str = "douyin"
    quality: str = "origin"
    max_duration_seconds: int = 3600
    pipeline_config_json: str | None = None
    enabled: bool = True


class LiveRoomUpdate(BaseModel):
    """更新直播间请求。"""

    name: str | None = None
    quality: str | None = None
    max_duration_seconds: int | None = None
    pipeline_config_json: str | None = None
    enabled: bool | None = None


class LiveRoomResponse(BaseModel):
    """直播间响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    url: str
    name: str
    platform: str
    quality: str
    max_duration_seconds: int
    pipeline_config_json: str | None
    enabled: bool
    created_at: datetime
    updated_at: datetime


class LiveRoomListResponse(BaseModel):
    """直播间列表响应。"""

    items: list[LiveRoomResponse]
    total: int
