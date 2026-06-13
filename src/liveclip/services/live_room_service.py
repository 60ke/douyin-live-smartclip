"""直播间 CRUD 服务。"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import structlog
from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from liveclip.adapters.douyin.resolver import DouyinResolver
from liveclip.config import load_settings
from liveclip.db.models import Clip, ClipPlan, LiveRoom, Record, Subtitle, Task, TaskRun, TaskStep
from liveclip.db.repositories.live_room_repo import LiveRoomRepository
from liveclip.domain.enums import RunStatus
from liveclip.schemas.live_room import LiveRoomCreate, LiveRoomUpdate

logger = structlog.get_logger(__name__)


class LiveRoomService:
    """直播间业务逻辑层，封装 CRUD 与查询操作。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = LiveRoomRepository()

    async def create(self, data: LiveRoomCreate) -> LiveRoom:
        """创建直播间。"""
        room_name = data.name or self._resolve_room_name(data.url, data.platform) or ""
        room = await self._repo.create(
            self._session,
            url=data.url,
            name=room_name,
            platform=data.platform,
            quality=data.quality,
            max_duration_seconds=data.max_duration_seconds,
            pipeline_config_json=data.pipeline_config_json,
            enabled=data.enabled,
        )
        await self._session.flush()
        logger.info("直播间已创建", room_id=room.id, url=data.url)
        return room

    async def get_by_id(self, room_id: int) -> LiveRoom | None:
        """根据 ID 获取直播间。"""
        return await self._repo.get_by_id(self._session, room_id)

    async def get_by_url(self, url: str) -> LiveRoom | None:
        """根据 URL 获取直播间。"""
        return await self._repo.get_by_url(self._session, url)

    async def get_all(self, offset: int = 0, limit: int = 100) -> tuple[list[LiveRoom], int]:
        """获取直播间列表及总数。"""
        items = await self._repo.get_all(self._session, offset=offset, limit=limit)
        count_stmt = select(func.count()).select_from(LiveRoom)
        result = await self._session.execute(count_stmt)
        total = result.scalar_one()
        return items, total

    async def get_enabled(self) -> list[LiveRoom]:
        """获取所有已启用的直播间。"""
        return await self._repo.get_enabled_rooms(self._session)

    async def update(self, room_id: int, data: LiveRoomUpdate) -> LiveRoom | None:
        """更新直播间信息。"""
        update_fields = data.model_dump(exclude_unset=True)
        if "name" in update_fields and not str(update_fields.get("name") or "").strip():
            existing = await self._repo.get_by_id(self._session, room_id)
            if existing is not None:
                resolved_name = self._resolve_room_name(existing.url, existing.platform)
                if resolved_name:
                    update_fields["name"] = resolved_name
        if not update_fields:
            return await self._repo.get_by_id(self._session, room_id)
        try:
            room = await self._repo.update(self._session, room_id, **update_fields)
        except ValueError:
            return None
        await self._session.flush()
        logger.info("直播间已更新", room_id=room_id, fields=list(update_fields.keys()))
        return room

    async def delete(self, room_id: int) -> bool:
        """删除直播间及其关联的所有数据。

        处理三个层面：
        1. 取消所有正在运行/等待执行的任务
        2. 删除数据库中的所有关联记录（任务、运行、切片、字幕、录制）
        3. 删除磁盘上的所有产物文件和锁文件
        """
        room = await self._repo.get_by_id(self._session, room_id)
        if room is None:
            return False

        # 1. 取消正在运行/等待中的 run
        await self._cancel_runs_for_room(room_id)

        # 2. 收集要删除的文件路径和锁（在删 DB 记录之前）
        file_paths, run_ids = await self._collect_room_file_paths(room_id)
        lock_dir = self._resolve_lock_dir()

        # 3. 删除数据库记录
        await self._delete_room_children(room_id)
        await self._session.execute(delete(LiveRoom).where(LiveRoom.id == room_id))
        await self._session.flush()

        # 4. 清理磁盘文件（DB 已删，即使文件清理失败也不回滚）
        await self._cleanup_files(file_paths)
        await self._cleanup_locks(run_ids, lock_dir)
        await self._cleanup_room_dir(room_id)

        logger.info("直播间已删除", room_id=room_id, url=room.url)
        return True

    async def _cancel_runs_for_room(self, room_id: int) -> None:
        """取消直播间下所有 PENDING/RUNNING 状态的运行。"""
        task_ids = await self._ids(select(Task.id).where(Task.room_id == room_id))
        if not task_ids:
            return

        result = await self._session.execute(
            update(TaskRun)
            .where(
                TaskRun.task_id.in_(task_ids),
                TaskRun.run_status.in_([RunStatus.PENDING, RunStatus.RUNNING]),
            )
            .values(run_status=RunStatus.CANCELED)
        )
        cancelled = result.rowcount
        if cancelled:
            logger.info(
                "room_delete_cancelled_runs",
                room_id=room_id,
                cancelled_count=cancelled,
            )
        await self._session.flush()

    async def _collect_room_file_paths(
        self, room_id: int
    ) -> tuple[list[str], list[int]]:
        """收集直播间关联的所有产物文件路径和 run_id 列表。"""
        paths: list[str] = []
        task_ids = await self._ids(select(Task.id).where(Task.room_id == room_id))
        if not task_ids:
            return paths, []

        run_ids = await self._ids(
            select(TaskRun.id).where(TaskRun.task_id.in_(task_ids))
        )
        if not run_ids:
            return paths, []

        # 录制文件
        result = await self._session.execute(
            select(Record.file_path).where(Record.run_id.in_(run_ids))
        )
        for (fp,) in result.all():
            if fp:
                paths.append(fp)

        # 字幕文件
        result = await self._session.execute(
            select(Subtitle.file_path).where(Subtitle.run_id.in_(run_ids))
        )
        for (fp,) in result.all():
            if fp:
                paths.append(fp)

        # 切片输出文件
        plan_ids = await self._ids(
            select(ClipPlan.id).where(ClipPlan.run_id.in_(run_ids))
        )
        if plan_ids:
            result = await self._session.execute(
                select(Clip.output_path).where(Clip.plan_id.in_(plan_ids))
            )
            for (fp,) in result.all():
                if fp:
                    paths.append(fp)

            result = await self._session.execute(
                select(Clip.subtitle_output_path).where(Clip.plan_id.in_(plan_ids))
            )
            for (fp,) in result.all():
                if fp:
                    paths.append(fp)

        return paths, run_ids

    @staticmethod
    def _resolve_lock_dir() -> Path:
        """获取锁文件目录。"""
        settings = load_settings()
        return settings.storage.base_dir / ".locks"

    @staticmethod
    async def _cleanup_files(paths: list[str]) -> None:
        """删除文件列表中的所有文件（忽略不存在的文件）。"""
        for fp in paths:
            try:
                p = Path(fp).resolve()
                if p.is_file():
                    p.unlink()
                    logger.debug("room_delete_file_removed", path=str(p))
            except OSError as exc:
                logger.warning(
                    "room_delete_file_cleanup_failed",
                    path=fp,
                    error=str(exc),
                )

    @staticmethod
    async def _cleanup_locks(run_ids: list[int], lock_dir: Path) -> None:
        """清理所有 run 的锁文件。"""
        for run_id in run_ids:
            lock_path = lock_dir / f"run_{run_id}.lock"
            try:
                if lock_path.exists():
                    lock_path.unlink()
                    logger.debug("room_delete_lock_removed", path=str(lock_path))
            except OSError as exc:
                logger.warning(
                    "room_delete_lock_cleanup_failed",
                    path=str(lock_path),
                    error=str(exc),
                )

    @staticmethod
    async def _cleanup_room_dir(room_id: int) -> None:
        """删除房间目录树（包括所有录制、转码、字幕、切片产物文件）。"""
        settings = load_settings()
        base_dir = settings.storage.base_dir.resolve()
        room_dir = base_dir / f"room_{room_id}"

        if room_dir.exists():
            try:
                shutil.rmtree(str(room_dir))
                logger.info("room_dir_removed", path=str(room_dir))
            except OSError as exc:
                logger.warning(
                    "room_dir_cleanup_failed",
                    path=str(room_dir),
                    error=str(exc),
                )

    async def _delete_room_children(self, room_id: int) -> None:
        """删除直播间关联任务、运行和流水线产物记录。"""
        task_ids = await self._ids(select(Task.id).where(Task.room_id == room_id))
        if not task_ids:
            return

        run_ids = await self._ids(select(TaskRun.id).where(TaskRun.task_id.in_(task_ids)))
        if run_ids:
            plan_ids = await self._ids(select(ClipPlan.id).where(ClipPlan.run_id.in_(run_ids)))
            if plan_ids:
                await self._session.execute(delete(Clip).where(Clip.plan_id.in_(plan_ids)))
            await self._session.execute(delete(ClipPlan).where(ClipPlan.run_id.in_(run_ids)))
            await self._session.execute(delete(Subtitle).where(Subtitle.run_id.in_(run_ids)))
            await self._session.execute(delete(Record).where(Record.run_id.in_(run_ids)))
            await self._session.execute(delete(TaskStep).where(TaskStep.run_id.in_(run_ids)))
            await self._session.execute(delete(TaskRun).where(TaskRun.task_id.in_(task_ids)))

        await self._session.execute(delete(Task).where(Task.id.in_(task_ids)))
        await self._session.flush()

    async def _ids(self, stmt: Select[tuple[int]]) -> list[int]:
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    @staticmethod
    def _resolve_room_name(url: str, platform: str = "douyin") -> str | None:
        if not url or platform != "douyin":
            return None
        try:
            settings = load_settings()
            cookie = os.environ.get(settings.douyin.cookie_env)
            room_info = DouyinResolver().resolve_room_info(url, cookie)
        except Exception as exc:
            logger.warning("直播间名称解析失败", url=url, error=str(exc))
            return None
        return room_info.anchor_name.strip() or None
