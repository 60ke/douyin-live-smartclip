"""Worker 主运行器，负责轮询、调度与执行流水线。"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from liveclip.db.models import Task, TaskRun
from liveclip.db.session import get_session_context, init_db
from liveclip.domain.enums import RunStatus, TaskType, TriggerType
from liveclip.domain.models import (
    LLMCallConfig,
    PipelineConfig,
    RecordConfig,
)
from liveclip.exceptions import LIVE_ROOM_NOT_LIVE, RUN_HEARTBEAT_TIMEOUT
from liveclip.pipeline.context import PipelineContext
from liveclip.pipeline.state_machine import get_enabled_steps
from liveclip.schemas.run import RunCreate
from liveclip.services.run_service import RunService
from liveclip.storage.paths import RunPaths
from liveclip.utils.timezone import china_now
from liveclip.worker.locker import RunLocker
from liveclip.worker.step_executor import StepExecutor

if TYPE_CHECKING:
    from liveclip.config.settings import AppSettings

logger = structlog.get_logger(__name__)


class WorkerRunner:
    """Worker 主运行器。

    在独立进程中运行（不在 FastAPI 事件循环中），轮询数据库
    获取待执行运行，获取锁后依次执行流水线步骤。

    Args:
        settings: 应用配置。
    """

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings
        self._locker = RunLocker(lock_dir=settings.storage.base_dir / ".locks")
        self._executor = StepExecutor(settings)
        self._shutdown_flag: bool = False

    async def run(self) -> None:
        """主循环：轮询待执行运行并执行流水线。

        流程：
        1. 初始化数据库连接
        2. 循环：
           a. 清理陈旧锁
           b. 处理心跳超时的陈旧运行
           c. 获取下一个 PENDING 运行
           d. 获取分布式锁
           e. 构建上下文并执行流水线
           f. 释放锁
        3. 每次迭代间休眠 poll_interval_seconds
        """
        init_db(self._settings.database.url)
        logger.info(
            "worker_started",
            poll_interval=self._settings.worker.poll_interval_seconds,
        )

        while not self._shutdown_flag:
            try:
                # 清理陈旧锁
                self._locker.cleanup_stale()

                # 处理陈旧运行
                await self._handle_stale_runs()

                # 根据已启用任务生成到期运行
                await self._schedule_due_tasks()

                # 获取下一个待执行运行
                run = await self._pick_next_and_lock()
                if run is not None:
                    ctx = await self._build_context(run)
                    try:
                        await self._execute_run(run, ctx)
                    finally:
                        self._locker.release(run.id)
                        logger.debug("lock_released_after_run", run_id=run.id)

            except Exception as exc:
                logger.error("worker_loop_error", error=str(exc))

            # 休眠
            await asyncio.sleep(self._settings.worker.poll_interval_seconds)

        logger.info("worker_shutdown_complete")

    async def run_once(self) -> bool:
        """执行一次 worker 轮询并在处理完一个运行后退出。

        Returns:
            True 表示处理了一个运行，False 表示没有待处理运行。
        """
        init_db(self._settings.database.url)
        self._locker.cleanup_stale()
        await self._handle_stale_runs()
        await self._schedule_due_tasks()

        run = await self._pick_next_and_lock()
        if run is None:
            logger.info("worker_once_no_pending_run")
            return False

        try:
            ctx = await self._build_context(run)
            await self._execute_run(run, ctx)
            return True
        finally:
            self._locker.release(run.id)
            logger.debug("lock_released_after_run_once", run_id=run.id)

    async def run_by_id(self, run_id: int) -> bool:
        """执行指定的 PENDING 运行。

        Returns:
            True 表示找到了指定运行并完成执行，False 表示运行不存在或不可执行。
        """
        init_db(self._settings.database.url)
        self._locker.cleanup_stale()
        await self._handle_stale_runs()
        await self._schedule_due_tasks()

        session = get_session_context()
        try:
            run = await session.get(TaskRun, run_id)
            if run is None:
                logger.warning("worker_run_not_found", run_id=run_id)
                return False
            if run.run_status != str(RunStatus.PENDING):
                logger.warning(
                    "worker_run_not_pending",
                    run_id=run_id,
                    status=run.run_status,
                )
                return False
            if not self._locker.acquire(run.id):
                logger.warning("lock_acquire_failed", run_id=run.id)
                return False
            logger.info("run_picked", run_id=run.id, task_id=run.task_id)
        finally:
            await session.close()

        try:
            ctx = await self._build_context(run)
            await self._execute_run(run, ctx)
            return True
        finally:
            self._locker.release(run.id)
            logger.debug("lock_released_after_run_by_id", run_id=run.id)

    async def _pick_next_and_lock(self) -> TaskRun | None:
        """获取下一个 PENDING 运行并尝试获取锁。

        Returns:
            成功获取锁的 TaskRun，或 None。
        """
        session = get_session_context()
        try:
            run_service = RunService(session)
            run = await run_service.pick_next_pending()
            if run is None:
                return None

            if not self._locker.acquire(run.id):
                logger.debug("lock_acquire_failed", run_id=run.id)
                return None

            await session.commit()
            logger.info("run_picked", run_id=run.id, task_id=run.task_id)
            return run
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def _execute_run(self, run: TaskRun, ctx: PipelineContext) -> None:
        """执行完整的流水线运行。

        流程：
        1. 标记运行为 RUNNING
        2. 按顺序执行每个已启用的步骤
        3. 每步执行前检查取消信号
        4. 步骤失败则标记运行为 FAILED 并停止
        5. 全部成功则标记运行为 SUCCEEDED

        Args:
            run: 任务运行记录。
            ctx: 流水线执行上下文。
        """
        session = get_session_context()
        try:
            run_service = RunService(session)

            # 1. 标记运行为 RUNNING
            await run_service.mark_running(run.id)
            await run_service.update_heartbeat(run.id)
            await session.commit()

            logger.info("run_started", run_id=run.id)

            # 2. 获取步骤列表
            _, steps = await run_service.get_detail(run.id)
            step_map = {step.step_name: step for step in steps}

            # 3. 依次执行步骤
            pipeline_config = ctx.pipeline_config
            enabled_steps = get_enabled_steps(pipeline_config)

            for index, step_name in enumerate(enabled_steps):
                if self._shutdown_flag:
                    logger.info("worker_shutting_down_cancel_run", run_id=run.id)
                    ctx.request_cancel()

                if ctx.is_cancelled():
                    await run_service.mark_canceled(run.id)
                    await session.commit()
                    logger.info("run_cancelled", run_id=run.id)
                    return

                step_record = step_map.get(str(step_name))
                if step_record is None:
                    logger.warning(
                        "step_record_not_found",
                        step_name=str(step_name),
                        run_id=run.id,
                    )
                    continue

                result = await self._executor.execute_step(step_record, ctx, run_service)

                # 更新上下文
                ctx.set_step_result(str(step_name), result)

                if not result.success:
                    if result.error_code == LIVE_ROOM_NOT_LIVE and self._is_loop_context(ctx):
                        for skipped_step_name in enabled_steps[index + 1 :]:
                            skipped_step = step_map.get(str(skipped_step_name))
                            if skipped_step is not None:
                                await run_service.mark_step_skipped(
                                    skipped_step.id,
                                    error_code=LIVE_ROOM_NOT_LIVE,
                                    error_message="直播间暂未开播，本次检测不执行后续步骤",
                                )
                        await run_service.mark_waiting(
                            run.id,
                            error_code=LIVE_ROOM_NOT_LIVE,
                            error_message="直播间暂未开播，循环录制将继续自动检测",
                        )
                        await session.commit()
                        logger.info(
                            "run_waiting_for_live",
                            run_id=run.id,
                            step_name=str(step_name),
                        )
                        return

                    # 步骤失败，标记运行为 FAILED
                    await run_service.mark_failed(
                        run.id,
                        error_code=result.error_code or "UNKNOWN",
                        error_message=result.error_message or "步骤执行失败",
                    )
                    await session.commit()
                    logger.warning(
                        "run_failed_at_step",
                        run_id=run.id,
                        step_name=str(step_name),
                        error_code=result.error_code,
                    )
                    return

            # 4. 全部步骤成功
            await run_service.mark_succeeded(run.id)
            await session.commit()
            logger.info("run_succeeded", run_id=run.id)

        except Exception as exc:
            try:
                error_code = getattr(exc, "error_code", "UNKNOWN")
                error_message = str(exc)
                run_service = RunService(session)
                await run_service.mark_failed(run.id, error_code, error_message)
                await session.commit()
            except Exception as commit_exc:
                logger.error(
                    "mark_failed_commit_error",
                    run_id=run.id,
                    error=str(commit_exc),
                )
            logger.error(
                "run_execution_error",
                run_id=run.id,
                error=str(exc),
            )
        finally:
            await session.close()

    async def _handle_stale_runs(self) -> None:
        """查找心跳超时的运行并标记为 FAILED。"""
        session = get_session_context()
        try:
            run_service = RunService(session)
            timeout = self._settings.worker.running_timeout_seconds
            stale_runs = await run_service.get_stale_runs(timeout)

            for run in stale_runs:
                logger.warning(
                    "stale_run_detected",
                    run_id=run.id,
                    heartbeat_at=str(run.heartbeat_at),
                )
                await run_service.mark_failed(
                    run.id,
                    error_code=str(RUN_HEARTBEAT_TIMEOUT),
                    error_message=f"心跳超时（{timeout}秒无更新）",
                )
                self._locker.release(run.id)

            if stale_runs:
                await session.commit()
                logger.info("stale_runs_handled", count=len(stale_runs))
        except Exception as exc:
            logger.error("handle_stale_runs_error", error=str(exc))
            await session.rollback()
        finally:
            await session.close()

    async def _schedule_due_tasks(self) -> None:
        """为到期的循环/预约任务创建 PENDING 运行。"""
        session = get_session_context()
        try:
            run_service = RunService(session)
            tasks = await self._load_enabled_tasks(session)
            created_count = 0
            for task in tasks:
                config = self._parse_scheduler_config(task.pipeline_config_json)
                if await self._has_active_run(session, task.id):
                    continue

                if self._is_loop_task(task, config):
                    if await self._loop_task_due(session, task, config):
                        await run_service.create(
                            RunCreate(task_id=task.id, trigger_type=TriggerType.CRON)
                        )
                        created_count += 1
                    continue

                if self._is_scheduled_task(task, config):
                    if await self._scheduled_task_due(session, task, config):
                        await run_service.create(
                            RunCreate(task_id=task.id, trigger_type=TriggerType.CRON)
                        )
                        created_count += 1

            if created_count:
                await session.commit()
                logger.info("scheduled_runs_created", count=created_count)
            else:
                await session.rollback()
        except Exception as exc:
            logger.error("schedule_due_tasks_error", error=str(exc))
            await session.rollback()
        finally:
            await session.close()

    async def _load_enabled_tasks(self, session: AsyncSession) -> list[Task]:
        stmt = select(Task).where(Task.enabled.is_(True)).order_by(Task.created_at.asc())
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def _has_active_run(self, session: AsyncSession, task_id: int) -> bool:
        stmt = select(TaskRun).where(
            TaskRun.task_id == task_id,
            TaskRun.run_status.in_([str(RunStatus.PENDING), str(RunStatus.RUNNING)]),
        )
        result = await session.execute(stmt.limit(1))
        return result.scalar_one_or_none() is not None

    async def _latest_run(self, session: AsyncSession, task_id: int) -> TaskRun | None:
        stmt = (
            select(TaskRun)
            .where(TaskRun.task_id == task_id)
            .order_by(TaskRun.created_at.desc())
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def _loop_task_due(
        self,
        session: AsyncSession,
        task: Task,
        config: dict[str, object],
    ) -> bool:
        latest_run = await self._latest_run(session, task.id)
        if latest_run is None:
            return True
        interval_seconds = self._get_check_interval_seconds(task, config)
        last_checked_at = latest_run.finished_at or latest_run.created_at
        return china_now() - last_checked_at >= timedelta(seconds=interval_seconds)

    async def _scheduled_task_due(
        self,
        session: AsyncSession,
        task: Task,
        config: dict[str, object],
    ) -> bool:
        latest_run = await self._latest_run(session, task.id)
        if latest_run is not None:
            return False
        scheduled_at = self._parse_datetime(config.get("scheduled_start_at"))
        return scheduled_at is not None and scheduled_at <= china_now()

    @staticmethod
    def _is_loop_task(task: Task, config: dict[str, object]) -> bool:
        return task.task_type == str(TaskType.CRON) or config.get("task_mode") == "LOOP"

    @staticmethod
    def _is_scheduled_task(task: Task, config: dict[str, object]) -> bool:
        return task.task_type == str(TaskType.ONCE) and config.get("task_mode") == "SCHEDULE"

    @staticmethod
    def _parse_scheduler_config(config_json: str | None) -> dict[str, object]:
        if not config_json:
            return {}
        try:
            data = json.loads(config_json)
        except (json.JSONDecodeError, TypeError):
            logger.warning("scheduler_config_parse_failed", config_json=config_json)
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _get_check_interval_seconds(task: Task, config: dict[str, object]) -> int:
        value: object = config.get("check_interval_seconds")
        if value is None and task.cron_expression:
            value = WorkerRunner._parse_seconds_cron(task.cron_expression)
        if isinstance(value, str | int | float):
            try:
                seconds = int(value)
            except ValueError:
                seconds = 60
        else:
            seconds = 60
        return max(seconds, 10)

    @staticmethod
    def _parse_seconds_cron(expression: str) -> int | None:
        first_field = expression.split()[0] if expression else ""
        if first_field.startswith("*/"):
            try:
                return int(first_field[2:])
            except ValueError:
                return None
        return None

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        if not value:
            return None
        if isinstance(value, datetime):
            parsed = value
        else:
            try:
                parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            except ValueError:
                return None
        if parsed.tzinfo is not None:
            return parsed.astimezone().replace(tzinfo=None)
        return parsed

    async def _build_context(self, run: TaskRun) -> PipelineContext:
        """根据 TaskRun 构建流水线执行上下文。

        使用独立会话加载 TaskRun 及其关联的 Task 和 LiveRoom，
        从中读取配置构建完整的 PipelineContext。

        Args:
            run: 任务运行记录（仅使用 run.id 和 run.task_id）。

        Returns:
            流水线执行上下文。
        """
        session = get_session_context()
        try:
            # 重新加载 run 及关联对象
            stmt = (
                select(TaskRun)
                .where(TaskRun.id == run.id)
                .options(
                    selectinload(TaskRun.task).selectinload(Task.room),
                )
            )
            result = await session.execute(stmt)
            loaded_run = result.scalar_one()
            task = loaded_run.task
            room = task.room

            pipeline_config = self._parse_pipeline_config(task.pipeline_config_json)
            room_pipeline_config = self._parse_pipeline_config(room.pipeline_config_json)

            # 合并配置：task 级别覆盖 room 级别
            merged_config = self._merge_pipeline_config(room_pipeline_config, pipeline_config)

            record_config = RecordConfig(
                max_duration_seconds=room.max_duration_seconds,
                quality=room.quality,
            )

            paths = RunPaths(
                base_dir=self._settings.storage.base_dir,
                room_id=room.id,
                run_id=run.id,
                room_name=room.name,
                recording_started_at=run.started_at or china_now(),
            )

            ctx = PipelineContext(
                run_id=run.id,
                room_id=room.id,
                task_id=task.id,
                paths=paths,
                pipeline_config=merged_config,
                clip_segment_config=self._settings.clip_segment,
                llm_call_config=LLMCallConfig(),
                record_config=record_config,
            )

            # 注入直播间元数据
            ctx.metadata["room_url"] = room.url
            ctx.metadata["room_name"] = room.name
            ctx.metadata["task_type"] = task.task_type
            ctx.metadata["task_mode"] = self._parse_scheduler_config(
                task.pipeline_config_json
            ).get("task_mode")
            douyin_cookie = os.environ.get(self._settings.douyin.cookie_env)
            if douyin_cookie:
                ctx.metadata["cookie"] = douyin_cookie

            return ctx
        finally:
            await session.close()

    @staticmethod
    def _parse_pipeline_config(config_json: str | None) -> PipelineConfig:
        """解析流水线配置 JSON。"""
        if config_json:
            try:
                data = json.loads(config_json)
                return PipelineConfig(**data)
            except (json.JSONDecodeError, TypeError):
                logger.warning("pipeline_config_parse_failed", config_json=config_json)
        return PipelineConfig()

    @staticmethod
    def _is_loop_context(ctx: PipelineContext) -> bool:
        return (
            ctx.metadata.get("task_type") == str(TaskType.CRON)
            or ctx.metadata.get("task_mode") == "LOOP"
        )

    @staticmethod
    def _merge_pipeline_config(base: PipelineConfig, override: PipelineConfig) -> PipelineConfig:
        """合并两层流水线配置，override 中的非默认值覆盖 base。

        Args:
            base: 基础配置（room 级别）。
            override: 覆盖配置（task 级别）。

        Returns:
            合并后的配置。
        """
        base_data = base.model_dump()
        override_data = override.model_dump()
        for key, value in override_data.items():
            if value is not None:
                base_data[key] = value
        return PipelineConfig(**base_data)

    def shutdown(self) -> None:
        """设置优雅关闭标志。"""
        self._shutdown_flag = True
        logger.info("worker_shutdown_requested")
