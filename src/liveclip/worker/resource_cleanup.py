"""Periodic cleanup of old run resource directories."""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.db.models import Task, TaskRun
from liveclip.db.session import get_session_context
from liveclip.domain.enums import ResourceStatus, RunStatus
from liveclip.utils.timezone import china_now

logger = structlog.get_logger(__name__)

_TERMINAL_RUN_STATUSES = (
    str(RunStatus.SUCCEEDED),
    str(RunStatus.FAILED),
    str(RunStatus.CANCELED),
)


@dataclass(frozen=True)
class CleanupCandidate:
    run_id: int
    room_id: int


class ResourceCleanupService:
    """Delete expired run directories while keeping database history."""

    def __init__(
        self,
        *,
        base_dir: Path,
        retention_hours: int,
        dry_run: bool = False,
    ) -> None:
        self._base_dir = base_dir
        self._retention_hours = retention_hours
        self._dry_run = dry_run

    async def cleanup_once(self) -> int:
        """Clean eligible runs once and return the number of marked runs."""
        session = get_session_context()
        try:
            candidates = await self._load_candidates(session)
            cleaned = 0
            for candidate in candidates:
                if await self._cleanup_candidate(session, candidate):
                    cleaned += 1
            await session.commit()
            if candidates:
                logger.info(
                    "resource_cleanup_done",
                    candidates=len(candidates),
                    cleaned=cleaned,
                    dry_run=self._dry_run,
                )
            return cleaned
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def _load_candidates(self, session: AsyncSession) -> list[CleanupCandidate]:
        cutoff = china_now() - timedelta(hours=self._retention_hours)
        result = await session.execute(
            select(TaskRun.id, Task.room_id)
            .join(Task, Task.id == TaskRun.task_id)
            .where(
                TaskRun.run_status.in_(_TERMINAL_RUN_STATUSES),
                TaskRun.finished_at.is_not(None),
                TaskRun.finished_at <= cutoff,
                TaskRun.resource_status != str(ResourceStatus.CLEANED),
            )
            .order_by(TaskRun.finished_at.asc(), TaskRun.id.asc())
        )
        return [
            CleanupCandidate(run_id=run_id, room_id=room_id)
            for run_id, room_id in result.all()
        ]

    async def _cleanup_candidate(
        self,
        session: AsyncSession,
        candidate: CleanupCandidate,
    ) -> bool:
        run = await session.get(TaskRun, candidate.run_id)
        if run is None:
            return False

        try:
            target = resolve_run_resource_dir(
                self._base_dir,
                room_id=candidate.room_id,
                run_id=candidate.run_id,
            )
            logger.info(
                "resource_cleanup_candidate",
                run_id=candidate.run_id,
                room_id=candidate.room_id,
                path=str(target),
                dry_run=self._dry_run,
            )
            if not self._dry_run and target.exists():
                await asyncio.to_thread(shutil.rmtree, target)
            if not self._dry_run:
                run.resource_status = str(ResourceStatus.CLEANED)
                run.resource_deleted_at = china_now()
                run.resource_cleanup_error = None
            return True
        except Exception as exc:
            run.resource_status = str(ResourceStatus.CLEANUP_FAILED)
            run.resource_cleanup_error = str(exc)[:2048]
            logger.warning(
                "resource_cleanup_failed",
                run_id=candidate.run_id,
                room_id=candidate.room_id,
                error=str(exc),
                exc_info=True,
            )
            return False


class ResourceCleanupRunner:
    """Periodic cleanup loop used by the embedded API worker."""

    def __init__(
        self,
        *,
        service: ResourceCleanupService,
        interval_seconds: int,
    ) -> None:
        self._service = service
        self._interval_seconds = interval_seconds
        self._shutdown = False

    async def run(self) -> None:
        logger.info(
            "resource_cleanup_started",
            interval_seconds=self._interval_seconds,
        )
        while not self._shutdown:
            try:
                await self._service.cleanup_once()
            except Exception as exc:
                logger.error("resource_cleanup_loop_error", error=str(exc), exc_info=True)
            await asyncio.sleep(self._interval_seconds)
        logger.info("resource_cleanup_stopped")

    def shutdown(self) -> None:
        self._shutdown = True


def resolve_run_resource_dir(base_dir: Path, *, room_id: int, run_id: int) -> Path:
    """Resolve and validate the only directory a cleanup run may delete."""
    base = base_dir.resolve()
    target = (base / f"room_{room_id}" / f"run_{run_id}").resolve()
    if not target.is_relative_to(base):
        raise ValueError(f"cleanup path escapes storage base: {target}")
    if target.parent.name != f"room_{room_id}" or target.name != f"run_{run_id}":
        raise ValueError(f"unexpected cleanup path: {target}")
    return target
