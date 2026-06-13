"""HotwordDict 仓库，热词词典相关查询。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.db.models import HotwordDict
from liveclip.db.repositories.base import BaseRepository


class HotwordDictRepository(BaseRepository[HotwordDict]):
    """热词词典仓库。"""

    def __init__(self) -> None:
        super().__init__(HotwordDict)

    async def get_active_by_name(self, session: AsyncSession, name: str) -> HotwordDict | None:
        """根据名称获取激活的热词词典。"""
        stmt = select(self.model).where(
            self.model.name == name,
            self.model.is_active.is_(True),
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_all_active(self, session: AsyncSession) -> list[HotwordDict]:
        """获取所有激活的热词词典。"""
        stmt = select(self.model).where(self.model.is_active.is_(True))
        result = await session.execute(stmt)
        return list(result.scalars().all())
