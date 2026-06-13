"""Prompt 配置相关 API Schema。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PromptProfileCreate(BaseModel):
    """创建 Prompt 配置请求。"""

    name: str
    step_name: str
    template_text: str
    description: str = ""
    is_active: bool = True


class PromptProfileUpdate(BaseModel):
    """更新 Prompt 配置请求。"""

    template_text: str | None = None
    description: str | None = None
    is_active: bool | None = None


class PromptProfileResponse(BaseModel):
    """Prompt 配置响应。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    step_name: str
    template_text: str
    description: str
    is_active: bool
    created_at: datetime
    updated_at: datetime
