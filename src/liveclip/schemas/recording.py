"""录制视频列表响应 Schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class RecordingResponse(BaseModel):
    """面向前端的录制视频条目。"""

    id: int
    run_id: int
    task_id: int
    room_id: int
    room_name: str
    room_url: str
    run_status: str
    error_message: str | None
    file_path: str
    file_size: int
    duration_seconds: float
    format: str
    subtitle_file_path: str | None = None
    live_started_at: datetime | None = None
    live_finished_at: datetime | None = None
    created_at: datetime
    resource_status: str = "AVAILABLE"
    resource_deleted_at: datetime | None = None
    resource_cleanup_error: str | None = None
