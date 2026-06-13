"""LiveRoom 仓库，直播间相关查询。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.db.models import LiveRoom
from liveclip.db.repositories.base import BaseRepository


class LiveRoomRepository(BaseRepository[LiveRoom]):
    """直播间仓库。"""

    def __init__(self) -> None:
        super().__init__(LiveRoom)

    async def get_by_url(self, session: AsyncSession, url: str) -> LiveRoom | None:
        """根据直播 URL 查询直播间。"""
        stmt = select(self.model).where(self.model.url == url)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_enabled_rooms(self, session: AsyncSession) -> list[LiveRoom]:
        """获取所有已启用的直播间。"""
        stmt = select(self.model).where(self.model.enabled.is_(True))
        result = await session.execute(stmt)
        return list(result.scalars().all())
