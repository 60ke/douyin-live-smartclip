"""录制视频与字幕产物查询路由。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.api.deps import get_db_session
from liveclip.db.models import LiveRoom, Record, Subtitle, Task, TaskRun
from liveclip.observability import get_logger
from liveclip.schemas.record import RecordResponse
from liveclip.schemas.recording import RecordingResponse
from liveclip.schemas.subtitle import SubtitleResponse
from liveclip.utils.timezone import as_china_aware

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/recordings", tags=["recordings"])


@router.get("/room/{room_id}", response_model=list[RecordingResponse])
async def list_room_recordings(
    room_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> list[RecordingResponse]:
    """获取某个直播间已生成的 MP4 视频录制文件。"""
    stmt = (
        select(Record, TaskRun, Task, LiveRoom)
        .join(TaskRun, TaskRun.id == Record.run_id)
        .join(Task, Task.id == TaskRun.task_id)
        .join(LiveRoom, LiveRoom.id == Task.room_id)
        .where(Task.room_id == room_id, Record.format == "mp4")
        .order_by(Record.created_at.desc(), Record.id.desc())
    )
    result = await session.execute(stmt)
    rows = result.all()

    if not rows:
        await session.commit()
        return []

    run_ids = [record.run_id for record, _, _, _ in rows]
    subtitles = await _preferred_subtitles_by_run(session, run_ids)

    recordings: list[RecordingResponse] = []
    for record, run, task, room in rows:
        try:
            recordings.append(
                RecordingResponse(
                    id=record.id,
                    run_id=record.run_id,
                    task_id=task.id,
                    room_id=room.id,
                    room_name=room.name,
                    room_url=room.url,
                    run_status=str(run.run_status),
                    error_message=run.error_message,
                    file_path=record.file_path,
                    file_size=record.file_size or 0,
                    duration_seconds=record.duration_seconds or 0.0,
                    format=record.format or "mp4",
                    subtitle_file_path=subtitles.get(record.run_id),
                    live_started_at=as_china_aware(run.started_at),
                    live_finished_at=as_china_aware(run.finished_at),
                    created_at=as_china_aware(record.created_at),
                )
            )
        except Exception:
            logger.warning(
                "recording_response_build_failed",
                record_id=record.id,
                run_id=record.run_id,
                exc_info=True,
            )
    await session.commit()
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
    response = [RecordResponse.model_validate(record) for record in records]
    await session.commit()
    return response


@router.get("/run/{run_id}/subtitles", response_model=list[SubtitleResponse])
async def list_run_subtitles(
    run_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> list[SubtitleResponse]:
    """获取某次运行生成的字幕文件。"""
    result = await session.execute(
        select(Subtitle).where(Subtitle.run_id == run_id).order_by(Subtitle.id.asc())
    )
    subtitles = list(result.scalars().all())
    original_subtitles = _original_subtitles(subtitles)
    response = [SubtitleResponse.model_validate(subtitle) for subtitle in original_subtitles]
    await session.commit()
    return response


async def _preferred_subtitles_by_run(
    session: AsyncSession,
    run_ids: list[int],
) -> dict[int, str]:
    if not run_ids:
        return {}

    result = await session.execute(
        select(Subtitle)
        .where(Subtitle.run_id.in_(run_ids))
        .order_by(Subtitle.run_id.asc(), Subtitle.id.asc())
    )
    by_run: dict[int, list[Subtitle]] = {}
    for subtitle in result.scalars().all():
        by_run.setdefault(subtitle.run_id, []).append(subtitle)
    return {
        run_id: preferred.file_path
        for run_id, subtitles in by_run.items()
        if (preferred := _prefer_original_subtitle(subtitles)) is not None
    }


def _prefer_original_subtitle(subtitles: list[Subtitle]) -> Subtitle | None:
    if not subtitles:
        return None
    for subtitle in subtitles:
        if not subtitle.file_path.endswith("run_combine.srt"):
            return subtitle
    return subtitles[-1]


def _original_subtitles(subtitles: list[Subtitle]) -> list[Subtitle]:
    originals = [
        subtitle
        for subtitle in subtitles
        if not subtitle.file_path.endswith("run_combine.srt")
    ]
    return originals or subtitles[-1:]
