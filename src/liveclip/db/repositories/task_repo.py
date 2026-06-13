"""Task 仓库，任务相关查询。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.db.models import Task
from liveclip.db.repositories.base import BaseRepository


class TaskRepository(BaseRepository[Task]):
    """任务仓库。"""

    def __init__(self) -> None:
        super().__init__(Task)

    async def get_by_room_id(self, session: AsyncSession, room_id: int) -> list[Task]:
        """根据直播间 ID 获取关联任务列表。"""
        stmt = select(self.model).where(self.model.room_id == room_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_enabled_tasks(self, session: AsyncSession) -> list[Task]:
        """获取所有已启用的任务。"""
        stmt = select(self.model).where(self.model.enabled.is_(True))
        result = await session.execute(stmt)
        return list(result.scalars().all())
