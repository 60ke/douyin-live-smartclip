"""liveclip API Schema 模块。"""

from __future__ import annotations

from liveclip.schemas.clip import ClipPlanResponse, ClipResponse
from liveclip.schemas.hotword import (
    HotwordDictCreate,
    HotwordDictResponse,
    HotwordDictUpdate,
)
from liveclip.schemas.live_room import (
    LiveRoomCreate,
    LiveRoomListResponse,
    LiveRoomResponse,
    LiveRoomUpdate,
)
from liveclip.schemas.prompt import (
    PromptProfileCreate,
    PromptProfileResponse,
    PromptProfileUpdate,
)
from liveclip.schemas.record import RecordResponse
from liveclip.schemas.run import (
    RunCreate,
    RunDetailResponse,
    RunListResponse,
    RunResponse,
    StepResponse,
)
from liveclip.schemas.subtitle import SubtitleResponse
from liveclip.schemas.task import (
    TaskCreate,
    TaskListResponse,
    TaskResponse,
    TaskUpdate,
)

__all__ = [
    "ClipPlanResponse",
    "ClipResponse",
    "HotwordDictCreate",
    "HotwordDictResponse",
    "HotwordDictUpdate",
    "LiveRoomCreate",
    "LiveRoomListResponse",
    "LiveRoomResponse",
    "LiveRoomUpdate",
    "PromptProfileCreate",
    "PromptProfileResponse",
    "PromptProfileUpdate",
    "RecordResponse",
    "RunCreate",
    "RunDetailResponse",
    "RunListResponse",
    "RunResponse",
    "StepResponse",
    "SubtitleResponse",
    "TaskCreate",
    "TaskListResponse",
    "TaskResponse",
    "TaskUpdate",
]
