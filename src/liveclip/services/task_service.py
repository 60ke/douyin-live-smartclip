"""任务 CRUD 与运行创建服务。"""

from __future__ import annotations

import json

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.db.models import Task, TaskRun, TaskStep
from liveclip.db.repositories.task_repo import TaskRepository
from liveclip.domain.enums import RunStatus, StepStatus, TriggerType
from liveclip.domain.models import PipelineConfig
from liveclip.pipeline.state_machine import get_enabled_steps
from liveclip.schemas.task import TaskCreate, TaskUpdate
from liveclip.utils.timezone import china_now

logger = structlog.get_logger(__name__)


class TaskService:
    """任务 CRUD 与运行创建服务。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = TaskRepository()

    async def create(self, data: TaskCreate) -> Task:
        """创建任务。"""
        task = Task(
            room_id=data.room_id,
            task_type=str(data.task_type),
            cron_expression=data.cron_expression,
            pipeline_config_json=data.pipeline_config_json,
            enabled=data.enabled,
        )
        self._session.add(task)
        await self._session.flush()
        await self._session.refresh(task)
        logger.info("任务已创建", task_id=task.id, room_id=task.room_id)
        return task

    async def get_by_id(self, task_id: int) -> Task | None:
        """根据 ID 获取任务。"""
        return await self._repo.get_by_id(self._session, task_id)

    async def get_by_room(self, room_id: int) -> list[Task]:
        """获取直播间下所有任务。"""
        return await self._repo.get_by_room_id(self._session, room_id)

    async def get_all(self, offset: int = 0, limit: int = 100) -> tuple[list[Task], int]:
        """获取任务列表及总数。"""
        items = await self._repo.get_all(self._session, offset=offset, limit=limit)
        count_stmt = select(func.count()).select_from(Task)
        result = await self._session.execute(count_stmt)
        total = result.scalar_one()
        return items, total

    async def update(self, task_id: int, data: TaskUpdate) -> Task | None:
        """更新任务。"""
        task = await self._repo.get_by_id(self._session, task_id)
        if not task:
            return None
        updates = data.model_dump(exclude_unset=True)
        for key, value in updates.items():
            setattr(task, key, value)
        task.updated_at = china_now()
        await self._session.flush()
        await self._session.refresh(task)
        logger.info("任务已更新", task_id=task.id)
        return task

    async def delete(self, task_id: int) -> bool:
        """删除任务。"""
        result = await self._repo.delete(self._session, task_id)
        if result:
            logger.info("任务已删除", task_id=task_id)
        return result

    async def create_run(self, task_id: int, trigger_type: TriggerType) -> TaskRun:
        """创建运行，并根据流水线配置生成 PENDING 步骤。"""
        task = await self._repo.get_by_id(self._session, task_id)
        if not task:
            raise ValueError(f"Task id={task_id} 不存在")

        pipeline_config = self._parse_pipeline_config(task.pipeline_config_json)

        run = TaskRun(
            task_id=task_id,
            run_status=str(RunStatus.PENDING),
            trigger_type=str(trigger_type),
        )
        self._session.add(run)
        await self._session.flush()
        await self._session.refresh(run)

        enabled_steps = get_enabled_steps(pipeline_config)
        for step_name in enabled_steps:
            step = TaskStep(
                run_id=run.id,
                step_name=str(step_name),
                step_status=str(StepStatus.PENDING),
            )
            self._session.add(step)

        await self._session.flush()
        logger.info(
            "运行已创建",
            run_id=run.id,
            task_id=task_id,
            steps=[str(s) for s in enabled_steps],
        )
        return run

    async def get_runs(self, task_id: int) -> list[TaskRun]:
        """获取任务的所有运行。"""
        stmt = select(TaskRun).where(TaskRun.task_id == task_id).order_by(TaskRun.id.asc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def _parse_pipeline_config(config_json: str | None) -> PipelineConfig:
        """解析流水线配置 JSON。"""
        if config_json:
            try:
                data = json.loads(config_json)
                return PipelineConfig(**data)
            except (json.JSONDecodeError, TypeError):
                logger.warning("流水线配置解析失败", config_json=config_json)
        return PipelineConfig()
