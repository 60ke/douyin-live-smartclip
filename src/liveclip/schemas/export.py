"""导出相关 API Schema — 用于外部同步消费端游标分页拉取切片。"""

from __future__ import annotations

import base64
import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ExportCursor(BaseModel):
    """不透明游标，编码格式为 base64(json({t: ISO8601, i: id}))。"""

    created_at: datetime
    id: int

    def encode(self) -> str:
        """将游标编码为 URL 安全的 base64 字符串。"""
        payload = {"t": self.created_at.isoformat(), "i": self.id}
        return base64.urlsafe_b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()

    @classmethod
    def decode(cls, raw: str) -> ExportCursor:
        """从 base64 字符串解码游标。

        Raises:
            ValueError: 游标格式无效。
        """
        try:
            payload = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
            return cls(created_at=datetime.fromisoformat(payload["t"]), id=payload["i"])
        except (KeyError, ValueError, OSError) as exc:
            raise ValueError(f"Invalid cursor: {raw}") from exc


class ExportClipItem(BaseModel):
    """单条导出切片信息。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    playable_video_path: str | None = None
    media_url: str | None = None
    duration_seconds: float | None = None
    room_name: str
    created_at: datetime


class ExportClipsResponse(BaseModel):
    """导出切片分页响应。"""

    items: list[ExportClipItem]
    next_cursor: str | None = None
    count: int
