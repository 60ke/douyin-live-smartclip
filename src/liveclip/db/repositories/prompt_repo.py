"""PromptProfile 仓库，Prompt 模板相关查询。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.db.models import PromptProfile
from liveclip.db.repositories.base import BaseRepository


class PromptProfileRepository(BaseRepository[PromptProfile]):
    """Prompt 模板仓库。"""

    def __init__(self) -> None:
        super().__init__(PromptProfile)

    async def get_active_by_step(
        self, session: AsyncSession, step_name: str
    ) -> PromptProfile | None:
        """根据步骤名称获取激活的 Prompt 模板。"""
        stmt = select(self.model).where(
            self.model.step_name == step_name,
            self.model.is_active.is_(True),
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_name(self, session: AsyncSession, name: str) -> PromptProfile | None:
        """根据名称获取 Prompt 模板。"""
        stmt = select(self.model).where(self.model.name == name)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
