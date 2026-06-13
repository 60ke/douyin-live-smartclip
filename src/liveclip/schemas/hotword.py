"""热词词典相关 API Schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class HotwordDictCreate(BaseModel):
    """创建热词词典请求。"""

    name: str
    words: list[str]
    is_active: bool = True


class HotwordDictUpdate(BaseModel):
    """更新热词词典请求。"""

    words: list[str] | None = None
    is_active: bool | None = None


class HotwordDictResponse(BaseModel):
    """热词词典响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    words_json: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
