"""导出相关 API Schema — 用于外部同步消费端游标分页拉取切片。"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ExportCursor(BaseModel):
    """不透明游标。

    编码格式为 base64(json({t: ISO8601, i: id, r: [room_id, ...]}))。
    ``r`` 为可选字段，保持对旧版游标的兼容。
    """

    created_at: datetime
    id: int
    room_ids: tuple[int, ...] | None = None

    def encode(self) -> str:
        """将游标编码为 URL 安全的 base64 字符串。"""
        payload: dict[str, object] = {
            "t": self.created_at.isoformat(),
            "i": self.id,
        }
        if self.room_ids is not None:
            payload["r"] = list(self.room_ids)
        return base64.urlsafe_b64encode(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        ).decode()

    @classmethod
    def decode(cls, raw: str) -> ExportCursor:
        """从 base64 字符串解码游标。

        Raises:
            ValueError: 游标格式无效。
        """
        try:
            payload = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
            raw_room_ids = payload.get("r")
            room_ids = None
            if raw_room_ids is not None:
                if not isinstance(raw_room_ids, list):
                    raise TypeError("cursor room_ids must be a list")
                room_ids = tuple(sorted({int(room_id) for room_id in raw_room_ids}))
            return cls(
                created_at=datetime.fromisoformat(payload["t"]),
                id=int(payload["i"]),
                room_ids=room_ids,
            )
        except (
            KeyError,
            ValueError,
            OSError,
            TypeError,
            UnicodeDecodeError,
            binascii.Error,
            json.JSONDecodeError,
        ) as exc:
            raise ValueError(f"Invalid cursor: {raw}") from exc


class ExportRoomItem(BaseModel):
    """可供外部同步客户端选择的直播间。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    url: str
    platform: str
    enabled: bool


class ExportRoomsResponse(BaseModel):
    """直播间列表响应。"""

    items: list[ExportRoomItem]
    count: int


class ExportClipItem(BaseModel):
    """单条导出切片信息。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    playable_video_path: str | None = None
    media_url: str | None = None
    duration_seconds: float | None = None
    room_id: int
    room_name: str
    created_at: datetime


class ExportClipsResponse(BaseModel):
    """导出切片分页响应。"""

    items: list[ExportClipItem]
    next_cursor: str | None = None
    checkpoint_cursor: str | None = None
    count: int
