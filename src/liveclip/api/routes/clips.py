"""切片查询路由。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.api.deps import get_clip_service, get_db_session
from liveclip.config import load_settings
from liveclip.db.models import Clip, ClipPlan, LiveRoom, Record, Subtitle, Task, TaskRun
from liveclip.domain.enums import ClipStatus
from liveclip.observability import get_logger
from liveclip.schemas.clip import ClipPlanResponse, ClipResponse, RecordingClipResponse
from liveclip.services import ClipService

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/clips", tags=["clips"])


@router.get("/run/{run_id}", response_model=list[ClipPlanResponse])
async def get_clips_by_run(
    run_id: int,
    session: AsyncSession = Depends(get_db_session),
    service: ClipService = Depends(get_clip_service),
) -> list[ClipPlanResponse]:
    """根据运行 ID 获取切片方案列表。

    若数据库中无记录，尝试从磁盘 export_summary.json 回填。
    """
    plans = await service.get_plans_by_run(run_id)
    if not plans:
        plans = await _backfill_clips_from_disk(session, run_id)
    await session.commit()
    return [ClipPlanResponse.model_validate(p) for p in plans]


@router.get("/plan/{plan_id}", response_model=list[ClipResponse])
async def get_clips_by_plan(
    plan_id: int,
    session: AsyncSession = Depends(get_db_session),
    service: ClipService = Depends(get_clip_service),
) -> list[ClipResponse]:
    """根据方案 ID 获取切片列表。"""
    clips = await service.get_clips_by_plan(plan_id)
    await session.commit()
    if not clips:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该方案无切片")
    return [ClipResponse.model_validate(c) for c in clips]


@router.get("/recording/{record_id}", response_model=list[RecordingClipResponse])
async def get_clips_by_recording(
    record_id: int,
    session: AsyncSession = Depends(get_db_session),
) -> list[RecordingClipResponse]:
    """获取某个录制视频对应的产品化切片列表。"""
    context_result = await session.execute(
        select(Record, TaskRun, Task, LiveRoom)
        .join(TaskRun, TaskRun.id == Record.run_id)
        .join(Task, Task.id == TaskRun.task_id)
        .join(LiveRoom, LiveRoom.id == Task.room_id)
        .where(Record.id == record_id)
    )
    context = context_result.first()
    if context is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="录制视频不存在")

    record, run, task, room = context
    plans = await _ensure_plans(session, run.id)
    plan_ids = [plan.id for plan in plans]
    if not plan_ids:
        await session.commit()
        return []

    subtitle_path = await _preferred_subtitle_path(session, run.id)
    result = await session.execute(
        select(Clip)
        .where(Clip.plan_id.in_(plan_ids))
        .order_by(Clip.start_seconds.asc(), Clip.id.asc())
    )
    clips = list(result.scalars().all())

    changed = False
    for clip in clips:
        if clip.source_record_id is None:
            clip.source_record_id = record.id
            changed = True
    await session.commit()

    if changed:
        logger.info("recording_clips_source_record_backfilled", record_id=record.id, run_id=run.id)

    return [
        _build_recording_clip_response(
            clip=clip,
            record=record,
            run=run,
            task=task,
            room=room,
            subtitle_path=subtitle_path,
        )
        for clip in clips
    ]


async def _backfill_clips_from_disk(
    session: AsyncSession, run_id: int
) -> list[ClipPlan]:
    """从磁盘 export_summary.json 回填 ClipPlan/Clip 记录到数据库。"""
    from sqlalchemy.orm import selectinload

    # 查找 room_id
    result = await session.execute(
        select(Task.room_id)
        .join(TaskRun, TaskRun.task_id == Task.id)
        .where(TaskRun.id == run_id)
    )
    row = result.first()
    if row is None:
        return []

    room_id = row[0]
    settings = load_settings()
    summary_path = (
        Path(settings.storage.base_dir)
        / f"room_{room_id}"
        / f"run_{run_id}"
        / "clips"
        / "export_summary.json"
    )

    if not summary_path.exists():
        return []

    try:
        summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("backfill_summary_read_failed", run_id=run_id, error=str(exc))
        return []

    # 从 plan JSON 中加载评分数据
    plan_dir = summary_path.parent.parent / "plans"
    plan_scores = _load_plan_scores(plan_dir)

    clip_plan = ClipPlan(
        run_id=run_id,
        status="COMPLETED",
        segment_count=summary_data.get("total", 0),
    )
    session.add(clip_plan)
    await session.flush()
    source_record = await _get_source_record(session, run_id)

    for idx, clip_data in enumerate(summary_data.get("clips", [])):
        scores = plan_scores.get(idx, {})
        parts = clip_data.get("parts") or []
        session.add(
            Clip(
                plan_id=clip_plan.id,
                source_record_id=source_record.id if source_record else None,
                title=clip_data.get("title", "未命名"),
                start_subtitle_index=_metadata_int(scores, "start_subtitle_index") or 0,
                end_subtitle_index=_metadata_int(scores, "end_subtitle_index") or 0,
                parts_json=json.dumps(parts, ensure_ascii=False) if parts else None,
                start_seconds=_metadata_float(clip_data, "start_time"),
                end_seconds=_metadata_float(clip_data, "end_time"),
                duration_seconds=_metadata_float(clip_data, "duration_seconds"),
                score=_metadata_float(scores, "score") or 0.0,
                structure_score=_metadata_float(scores, "structure_score") or 0.0,
                reason=str(scores.get("reason") or ""),
                structure_reason=str(scores.get("structure_reason") or ""),
                status="COMPLETED",
                output_path=clip_data.get("clip_path"),
                subtitle_output_path=clip_data.get("subtitle_path"),
            )
        )

    await session.flush()
    await session.refresh(clip_plan)

    # 重新查询以加载 clips 关联
    result2 = await session.execute(
        select(ClipPlan)
        .options(selectinload(ClipPlan.clips))
        .where(ClipPlan.id == clip_plan.id)
    )
    fresh_plan = result2.scalar_one()

    logger.info(
        "clips_backfilled_from_disk",
        run_id=run_id,
        plan_id=clip_plan.id,
        clip_count=summary_data.get("total", 0),
    )
    return [fresh_plan]


async def _ensure_plans(session: AsyncSession, run_id: int) -> list[ClipPlan]:
    from sqlalchemy.orm import selectinload

    result = await session.execute(
        select(ClipPlan)
        .options(selectinload(ClipPlan.clips))
        .where(ClipPlan.run_id == run_id)
        .order_by(ClipPlan.id.desc())
    )
    plans = list(result.scalars().all())
    if plans:
        return plans
    return await _backfill_clips_from_disk(session, run_id)


async def _get_source_record(session: AsyncSession, run_id: int) -> Record | None:
    result = await session.execute(
        select(Record).where(Record.run_id == run_id).order_by(Record.id.desc())
    )
    records = list(result.scalars().all())
    for record in records:
        if record.format == "mp4":
            return record
    return records[0] if records else None


async def _preferred_subtitle_path(session: AsyncSession, run_id: int) -> str | None:
    result = await session.execute(
        select(Subtitle)
        .where(Subtitle.run_id == run_id)
        .order_by(Subtitle.id.asc())
    )
    subtitles = list(result.scalars().all())
    subtitle = _prefer_original_subtitle(subtitles)
    return subtitle.file_path if subtitle else None


def _prefer_original_subtitle(subtitles: list[Subtitle]) -> Subtitle | None:
    if not subtitles:
        return None
    for subtitle in subtitles:
        if not subtitle.file_path.endswith("run_combine.srt"):
            return subtitle
    return subtitles[-1]


def _build_recording_clip_response(
    *,
    clip: Clip,
    record: Record,
    run: TaskRun,
    task: Task,
    room: LiveRoom,
    subtitle_path: str | None,
) -> RecordingClipResponse:
    return RecordingClipResponse(
        id=clip.id,
        plan_id=clip.plan_id,
        run_id=run.id,
        source_record_id=record.id,
        source_video_path=record.file_path,
        source_subtitle_path=subtitle_path,
        room_id=room.id,
        room_name=room.name,
        room_url=room.url,
        task_id=task.id,
        run_status=str(run.run_status),
        live_started_at=run.started_at,
        live_finished_at=run.finished_at,
        clip_live_started_at=_offset_datetime(run.started_at, clip.start_seconds),
        clip_live_finished_at=_offset_datetime(run.started_at, clip.end_seconds),
        title=clip.title,
        start_subtitle_index=clip.start_subtitle_index,
        end_subtitle_index=clip.end_subtitle_index,
        start_seconds=clip.start_seconds,
        end_seconds=clip.end_seconds,
        duration_seconds=clip.duration_seconds,
        parts_json=clip.parts_json,
        score=clip.score,
        structure_score=clip.structure_score,
        reason=clip.reason,
        structure_reason=clip.structure_reason,
        status=ClipStatus(clip.status),
        output_path=clip.output_path,
        subtitle_output_path=clip.subtitle_output_path,
        created_at=clip.created_at,
    )


def _offset_datetime(value: datetime | None, seconds: float | None) -> datetime | None:
    if value is None or seconds is None:
        return None
    return value + timedelta(seconds=seconds)


def _load_plan_scores(plan_dir: Path) -> dict[int, dict[str, object]]:
    """从 plan_dir 下的 validated_plan.json 或 normalized_plan.json 加载评分数据。

    返回以 segment 索引为 key 的评分字典。
    """
    for name in ("validated_plan.json", "normalized_plan.json"):
        plan_path = plan_dir / name
        if not plan_path.exists():
            continue
        try:
            data = json.loads(plan_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        scores: dict[int, dict[str, object]] = {}
        for idx, seg in enumerate(data.get("segments", data.get("clips", []))):
            scores[idx] = {
                "score": seg.get("score", 0.0),
                "structure_score": seg.get("structure_score", 0.0),
                "reason": seg.get("reason", ""),
                "structure_reason": seg.get("structure_reason", ""),
                "start_subtitle_index": seg.get("start_subtitle_index", 0),
                "end_subtitle_index": seg.get("end_subtitle_index", 0),
            }
        return scores
    return {}


def _metadata_float(metadata: dict[str, object] | None, key: str) -> float | None:
    if not metadata:
        return None
    value = metadata.get(key)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def _metadata_int(metadata: dict[str, object] | None, key: str) -> int | None:
    if not metadata:
        return None
    value = metadata.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None
