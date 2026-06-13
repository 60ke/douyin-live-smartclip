"""录制记录相关 API Schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from liveclip.domain.enums import RecordSourceType


class RecordResponse(BaseModel):
    """录制记录响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    source_type: RecordSourceType
    file_path: str
    file_size: int | None
    duration_seconds: float | None
    format: str | None
    created_at: datetime
