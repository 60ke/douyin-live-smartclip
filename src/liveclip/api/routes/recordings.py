"""录制视频与字幕产物查询路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.api.deps import get_db_session
from liveclip.db.models import Record, Subtitle, Task, TaskRun
from liveclip.observability import get_logger
from liveclip.schemas.record import RecordResponse
from liveclip.schemas.recording import RecordingResponse
from liveclip.schemas.subtitle import SubtitleResponse

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/recordings", tags=["recordings"])


@router.get("/room/{room_id}", response_model=list[RecordingResponse])
async def list_room_recordings(
    room_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> list[RecordingResponse]:
    """获取某个直播间已生成的 MP4 视频录制文件。"""
    stmt = (
        select(Record, TaskRun, Task)
        .join(TaskRun, TaskRun.id == Record.run_id)
        .join(Task, Task.id == TaskRun.task_id)
        .where(Task.room_id == room_id, Record.format == "mp4")
        .order_by(Record.created_at.desc(), Record.id.desc())
    )
    result = await session.execute(stmt)
    rows = result.all()

    if not rows:
        await session.commit()
        return []

    run_ids = [record.run_id for record, _, _ in rows]
    subtitles = await _latest_subtitles_by_run(session, run_ids)
    await session.commit()

    recordings: list[RecordingResponse] = []
    for record, run, _ in rows:
        try:
            recordings.append(
                RecordingResponse(
                    id=record.id,
                    run_id=record.run_id,
                    task_id=run.task_id,
                    run_status=str(run.run_status),
                    error_message=run.error_message,
                    file_path=record.file_path,
                    file_size=record.file_size or 0,
                    duration_seconds=record.duration_seconds or 0.0,
                    format=record.format or "mp4",
                    subtitle_file_path=subtitles.get(record.run_id),
                    created_at=record.created_at,
                )
            )
        except Exception:
            logger.warning(
                "recording_response_build_failed",
                record_id=record.id,
                run_id=record.run_id,
                exc_info=True,
            )
    return recordings


@router.get("/run/{run_id}", response_model=list[RecordResponse])
async def list_run_records(
    run_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> list[RecordResponse]:
    """获取某次运行生成的视频录制文件。"""
    result = await session.execute(
        select(Record).where(Record.run_id == run_id).order_by(Record.created_at.desc())
    )
    records = list(result.scalars().all())
    await session.commit()
    return [RecordResponse.model_validate(record) for record in records]


@router.get("/run/{run_id}/subtitles", response_model=list[SubtitleResponse])
async def list_run_subtitles(
    run_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> list[SubtitleResponse]:
    """获取某次运行生成的字幕文件。"""
    result = await session.execute(
        select(Subtitle).where(Subtitle.run_id == run_id).order_by(Subtitle.created_at.desc())
    )
    subtitles = list(result.scalars().all())
    await session.commit()
    return [SubtitleResponse.model_validate(subtitle) for subtitle in subtitles]


async def _latest_subtitles_by_run(
    session: AsyncSession,
    run_ids: list[int],
) -> dict[int, str]:
    if not run_ids:
        return {}

    latest_stmt = (
        select(Subtitle.run_id, func.max(Subtitle.id).label("subtitle_id"))
        .where(Subtitle.run_id.in_(run_ids))
        .group_by(Subtitle.run_id)
        .subquery()
    )
    result = await session.execute(
        select(Subtitle)
        .join(latest_stmt, Subtitle.id == latest_stmt.c.subtitle_id)
        .order_by(Subtitle.id.desc())
    )
    return {subtitle.run_id: subtitle.file_path for subtitle in result.scalars().all()}

