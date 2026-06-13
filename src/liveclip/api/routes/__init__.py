"""路由模块导出。"""

from __future__ import annotations

from liveclip.api.routes.clips import router as clips_router
from liveclip.api.routes.hotwords import router as hotwords_router
from liveclip.api.routes.live_rooms import router as live_rooms_router
from liveclip.api.routes.media import router as media_router
from liveclip.api.routes.prompts import router as prompts_router
from liveclip.api.routes.recordings import router as recordings_router
from liveclip.api.routes.runs import router as runs_router
from liveclip.api.routes.tasks import router as tasks_router

__all__ = [
    "clips_router",
    "hotwords_router",
    "live_rooms_router",
    "media_router",
    "prompts_router",
    "recordings_router",
    "runs_router",
    "tasks_router",
]
