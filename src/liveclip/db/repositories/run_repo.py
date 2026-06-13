"""TaskRun 仓库，任务运行相关查询。"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.db.models import TaskRun, TaskStep
from liveclip.db.repositories.base import BaseRepository
from liveclip.domain.enums import RunStatus, StepStatus


class TaskRunRepository(BaseRepository[TaskRun]):
    """任务运行仓库。"""

    def __init__(self) -> None:
        super().__init__(TaskRun)

    async def pick_next_pending_run(self, session: AsyncSession) -> TaskRun | None:
        """获取下一个待执行的 PENDING 运行。

        仅当不存在 RUNNING 状态的运行时才返回（max_concurrent_runs=1）。
        """
        running_stmt = select(self.model).where(self.model.run_status == RunStatus.RUNNING)
        running_result = await session.execute(running_stmt)
        if running_result.scalar_one_or_none() is not None:
            return None

        pending_stmt = (
            select(self.model)
            .where(self.model.run_status == RunStatus.PENDING)
            .order_by(self.model.created_at.asc())
            .limit(1)
        )
        result = await session.execute(pending_stmt)
        return result.scalar_one_or_none()

    async def update_heartbeat(self, session: AsyncSession, run_id: int) -> None:
        """更新运行心跳时间。"""
        instance = await session.get(self.model, run_id)
        if instance is not None:
            instance.heartbeat_at = datetime.now()
            await session.flush()

    async def get_stale_runs(self, session: AsyncSession, timeout_seconds: int) -> list[TaskRun]:
        """获取心跳超时的运行列表。"""
        cutoff = datetime.now() - timedelta(seconds=timeout_seconds)
        stmt = select(self.model).where(
            self.model.run_status == RunStatus.RUNNING,
            self.model.heartbeat_at.is_not(None),
            self.model.heartbeat_at < cutoff,
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_steps_by_run(self, session: AsyncSession, run_id: int) -> list[TaskStep]:
        """获取某次运行的所有步骤。"""
        stmt = select(TaskStep).where(TaskStep.run_id == run_id).order_by(TaskStep.id.asc())
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_active_step(self, session: AsyncSession, run_id: int) -> TaskStep | None:
        """获取某次运行中当前正在执行的步骤。"""
        stmt = select(TaskStep).where(
            TaskStep.run_id == run_id,
            TaskStep.step_status == StepStatus.RUNNING,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()
