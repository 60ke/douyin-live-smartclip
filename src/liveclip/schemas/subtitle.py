"""字幕相关 API Schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class SubtitleResponse(BaseModel):
    """字幕响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    file_path: str
    language: str | None
    word_count: int | None
    created_at: datetime
