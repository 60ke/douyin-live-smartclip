"""导出相关 API Schema — 用于外部同步消费端游标分页拉取切片。"""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime

from pydantic import BaseModel, ConfigDict


def normalize_room_ids(room_ids: list[int] | tuple[int, ...] | None) -> tuple[int, ...]:
    """标准化直播间筛选条件，确保游标和查询使用稳定顺序。"""
    if not room_ids:
        return ()
    normalized = tuple(sorted(set(room_ids)))
    if any(room_id <= 0 for room_id in normalized):
        raise ValueError("room_ids must contain positive integers")
    return normalized


class ExportCursor(BaseModel):
    """不透明游标，包含分页位置和直播间筛选条件。"""

    created_at: datetime
    id: int
    room_ids: tuple[int, ...] = ()

    def encode(self) -> str:
        """将游标编码为 URL 安全的 base64 字符串。"""
        payload = {
            "t": self.created_at.isoformat(),
            "i": self.id,
            "r": list(normalize_room_ids(self.room_ids)),
        }
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).decode()

    @classmethod
    def decode(cls, raw: str) -> ExportCursor:
        """从 base64 字符串解码游标，并兼容不含 room_ids 的旧游标。"""
        try:
            payload = json.loads(base64.urlsafe_b64decode(raw.encode()).decode())
            return cls(
                created_at=datetime.fromisoformat(payload["t"]),
                id=int(payload["i"]),
                room_ids=normalize_room_ids(payload.get("r")),
            )
        except (
            KeyError,
            ValueError,
            OSError,
            TypeError,
            UnicodeDecodeError,
            binascii.Error,
        ) as exc:
            raise ValueError(f"Invalid cursor: {raw}") from exc

    def validate_room_filter(self, room_ids: tuple[int, ...]) -> None:
        """防止将一个筛选条件生成的游标用于另一组直播间。"""
        normalized = normalize_room_ids(room_ids)
        if normalize_room_ids(self.room_ids) != normalized:
            raise ValueError("Cursor room filter does not match current room_ids")


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
    resume_cursor: str | None = None
    count: int
