"""产物仓库，Record / Subtitle / ClipPlan / Clip 相关查询。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from liveclip.db.models import Clip, ClipPlan, Record, Subtitle
from liveclip.db.repositories.base import BaseRepository


class RecordRepository(BaseRepository[Record]):
    """录制文件仓库。"""

    def __init__(self) -> None:
        super().__init__(Record)

    async def get_records_by_run(self, session: AsyncSession, run_id: int) -> list[Record]:
        """获取某次运行的所有录制文件。"""
        stmt = select(self.model).where(self.model.run_id == run_id).order_by(self.model.id.asc())
        result = await session.execute(stmt)
        return list(result.scalars().all())


class SubtitleRepository(BaseRepository[Subtitle]):
    """字幕仓库。"""

    def __init__(self) -> None:
        super().__init__(Subtitle)

    async def get_subtitles_by_run(self, session: AsyncSession, run_id: int) -> list[Subtitle]:
        """获取某次运行的所有字幕文件。"""
        stmt = select(self.model).where(self.model.run_id == run_id).order_by(self.model.id.asc())
        result = await session.execute(stmt)
        return list(result.scalars().all())


class ClipPlanRepository(BaseRepository[ClipPlan]):
    """切片方案仓库。"""

    def __init__(self) -> None:
        super().__init__(ClipPlan)

    async def get_clip_plan_by_run(self, session: AsyncSession, run_id: int) -> ClipPlan | None:
        """获取某次运行的切片方案（含 clips 预加载）。"""
        stmt = (
            select(self.model)
            .options(selectinload(self.model.clips))
            .where(self.model.run_id == run_id)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()


class ClipRepository(BaseRepository[Clip]):
    """切片仓库。"""

    def __init__(self) -> None:
        super().__init__(Clip)

    async def get_clips_by_plan(self, session: AsyncSession, plan_id: int) -> list[Clip]:
        """获取某方案下的所有切片。"""
        stmt = select(self.model).where(self.model.plan_id == plan_id).order_by(self.model.id.asc())
        result = await session.execute(stmt)
        return list(result.scalars().all())
