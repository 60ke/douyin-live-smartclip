"""切片查询路由。"""

from __future__ import annotations

import asyncio
import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.api.deps import get_clip_service, get_db_session
from liveclip.config import load_settings
from liveclip.db.models import Clip, ClipPlan, LiveRoom, Record, Subtitle, Task, TaskRun
from liveclip.domain.enums import ClipStatus
from liveclip.exceptions import LLMError
from liveclip.observability import get_logger
from liveclip.schemas.clip import (
    ClipCoverUpdateRequest,
    ClipPlanResponse,
    ClipResponse,
    RecordingClipResponse,
)
from liveclip.services import ClipCoverRenderer, ClipService, HighlightIntroSelector
from liveclip.utils.timezone import as_china_aware

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
    response = [ClipPlanResponse.model_validate(p) for p in plans]
    await session.commit()
    return response


@router.get("/plan/{plan_id}", response_model=list[ClipResponse])
async def get_clips_by_plan(
    plan_id: int,
    session: AsyncSession = Depends(get_db_session),
    service: ClipService = Depends(get_clip_service),
) -> list[ClipResponse]:
    """根据方案 ID 获取切片列表。"""
    clips = await service.get_clips_by_plan(plan_id)
    if not clips:
        await session.commit()
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该方案无切片")
    response = [ClipResponse.model_validate(c) for c in clips]
    await session.commit()
    return response


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
    if changed:
        await session.flush()

    if changed:
        logger.info("recording_clips_source_record_backfilled", record_id=record.id, run_id=run.id)

    response = []
    for clip in clips:
        item = await _build_recording_clip_response(
            clip=clip,
            record=record,
            run=run,
            task=task,
            room=room,
            subtitle_path=subtitle_path,
        )
        response.append(item)
    await session.commit()
    return response


@router.put("/{clip_id}/cover", response_model=ClipResponse)
async def update_clip_cover(
    clip_id: int,
    payload: ClipCoverUpdateRequest,
    session: AsyncSession = Depends(get_db_session),
) -> ClipResponse:
    """编辑切片封面并生成封面首帧视频与最终视频。"""
    clip = await session.get(Clip, clip_id)
    if clip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="切片不存在")
    if not clip.output_path:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="切片暂无视频文件")

    settings = load_settings()
    base_dir = settings.storage.base_dir.resolve()
    renderer = ClipCoverRenderer(
        ffmpeg_binary=settings.ffmpeg.ffmpeg_binary,
        ffprobe_binary=settings.ffmpeg.ffprobe_binary,
    )
    llm_highlight_reason: str | None = None
    llm_highlight_confidence: float | None = None
    highlight_enabled = payload.highlight_enabled
    highlight_start_seconds = payload.highlight_start_seconds
    highlight_end_seconds = payload.highlight_end_seconds
    try:
        video_path = _resolve_clip_video_path(clip, base_dir=base_dir)
        source_image_path = (
            _resolve_existing_path(payload.source_image_path, base_dir=base_dir)
            if payload.source_image_path
            else None
        )
        if (
            highlight_enabled
            and highlight_start_seconds is None
            and highlight_end_seconds is None
        ):
            spec = renderer.probe_video(video_path)
            subtitle_path = _resolve_optional_existing_path(
                clip.subtitle_output_path,
                base_dir=base_dir,
            )
            decision = HighlightIntroSelector().select(
                title=payload.title or clip.title,
                duration_seconds=spec.duration_seconds,
                subtitle_path=subtitle_path,
                reason=clip.reason,
                structure_reason=clip.structure_reason,
            )
            if not decision.enabled:
                highlight_enabled = False
            highlight_start_seconds = decision.start_seconds
            highlight_end_seconds = decision.end_seconds
            llm_highlight_reason = decision.reason
            llm_highlight_confidence = decision.confidence
        result = renderer.render(
            clip_id=clip.id,
            video_path=video_path,
            output_dir=video_path.parent / "covers",
            title=payload.title,
            source_image_path=source_image_path,
            cover_duration_seconds=payload.cover_duration_seconds,
            highlight_enabled=highlight_enabled,
            highlight_start_seconds=highlight_start_seconds,
            highlight_end_seconds=highlight_end_seconds,
        )
    except LLMError as exc:
        logger.warning("clip_highlight_llm_failed", clip_id=clip.id, error=str(exc), exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"高能片头 LLM 判断失败: {exc.message}",
        ) from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "")[:800]
        logger.warning(
            "clip_cover_ffmpeg_failed",
            clip_id=clip.id,
            returncode=exc.returncode,
            stderr=stderr,
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"FFmpeg 封面生成失败 (rc={exc.returncode}): {stderr}",
        ) from exc
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.warning("clip_cover_render_failed", clip_id=clip.id, error=str(exc), exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="封面生成失败") from exc

    clip.cover_title = payload.title
    clip.cover_source_image_path = str(source_image_path) if source_image_path else None
    clip.cover_image_path = str(result.cover_image_path)
    clip.cover_intro_video_path = str(result.cover_intro_video_path)
    clip.highlight_enabled = result.highlight_enabled
    clip.highlight_start_seconds = result.highlight_start_seconds
    clip.highlight_end_seconds = result.highlight_end_seconds
    clip.highlight_reason = llm_highlight_reason or result.highlight_reason
    clip.highlight_confidence = llm_highlight_confidence or result.highlight_confidence
    clip.highlight_video_path = str(result.highlight_video_path) if result.highlight_video_path else None
    clip.final_video_path = str(result.final_video_path)
    await session.flush()
    await session.refresh(clip)
    response = ClipResponse.model_validate(clip)
    await session.commit()
    return response


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
                cover_title=clip_data.get("cover_title"),
                cover_source_image_path=clip_data.get("cover_source_image_path"),
                cover_image_path=clip_data.get("cover_image_path"),
                cover_intro_video_path=clip_data.get("cover_intro_video_path"),
                highlight_enabled=bool(clip_data.get("highlight_enabled", False)),
                highlight_start_seconds=_metadata_float(clip_data, "highlight_start_seconds"),
                highlight_end_seconds=_metadata_float(clip_data, "highlight_end_seconds"),
                highlight_reason=clip_data.get("highlight_reason"),
                highlight_confidence=_metadata_float(clip_data, "highlight_confidence"),
                highlight_video_path=clip_data.get("highlight_video_path"),
                final_video_path=clip_data.get("final_video_path"),
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


def _resolve_existing_path(path: str | None, *, base_dir: Path) -> Path:
    if not path:
        raise FileNotFoundError("文件路径为空")
    file_path = Path(path).expanduser()
    candidates = (
        [file_path]
        if file_path.is_absolute()
        else _relative_path_candidates(file_path, base_dir)
    )
    checked: list[str] = []
    for candidate in candidates:
        resolved = candidate.resolve()
        checked.append(str(resolved))
        if resolved.exists():
            if not resolved.is_file():
                raise FileNotFoundError(f"路径不是文件: {path}")
            return resolved
    raise FileNotFoundError(f"文件不存在: {path}; checked={checked}")


def _relative_path_candidates(path: Path, base_dir: Path) -> list[Path]:
    candidates = [base_dir / path]
    parts = path.parts
    if parts and parts[0] == base_dir.name:
        candidates.append(base_dir.parent / path)
    candidates.append(Path.cwd() / path)

    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(candidate)
    return unique


def _resolve_optional_existing_path(path: str | None, *, base_dir: Path) -> Path | None:
    if not path:
        return None
    try:
        return _resolve_existing_path(path, base_dir=base_dir)
    except FileNotFoundError:
        return None


def _resolve_clip_video_path(clip: Clip, *, base_dir: Path) -> Path:
    checked: list[str] = []
    for path in (clip.output_path, clip.final_video_path):
        if not path or path in checked:
            continue
        checked.append(path)
        try:
            return _resolve_existing_path(path, base_dir=base_dir)
        except FileNotFoundError:
            continue
    raise FileNotFoundError(f"切片视频文件不存在: {checked}")


async def _build_recording_clip_response(
    *,
    clip: Clip,
    record: Record,
    run: TaskRun,
    task: Task,
    room: LiveRoom,
    subtitle_path: str | None,
) -> RecordingClipResponse:
    start_seconds, end_seconds = await _resolve_clip_times(clip, run, room)
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
        live_started_at=as_china_aware(run.started_at),
        live_finished_at=as_china_aware(run.finished_at),
        clip_live_started_at=as_china_aware(_offset_datetime(run.started_at, start_seconds)),
        clip_live_finished_at=as_china_aware(_offset_datetime(run.started_at, end_seconds)),
        title=clip.title,
        start_subtitle_index=clip.start_subtitle_index,
        end_subtitle_index=clip.end_subtitle_index,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        duration_seconds=clip.duration_seconds if clip.duration_seconds is not None else (end_seconds - start_seconds if start_seconds is not None and end_seconds is not None else None),
        parts_json=clip.parts_json,
        score=clip.score,
        structure_score=clip.structure_score,
        reason=clip.reason,
        structure_reason=clip.structure_reason,
        status=ClipStatus(clip.status),
        output_path=clip.output_path,
        subtitle_output_path=clip.subtitle_output_path,
        cover_title=clip.cover_title,
        cover_source_image_path=clip.cover_source_image_path,
        cover_image_path=clip.cover_image_path,
        cover_intro_video_path=clip.cover_intro_video_path,
        highlight_enabled=clip.highlight_enabled,
        highlight_start_seconds=clip.highlight_start_seconds,
        highlight_end_seconds=clip.highlight_end_seconds,
        highlight_reason=clip.highlight_reason,
        highlight_confidence=clip.highlight_confidence,
        highlight_video_path=clip.highlight_video_path,
        final_video_path=clip.final_video_path,
        playable_video_path=clip.final_video_path or clip.output_path,
        subtitle_mode="none" if clip.final_video_path else "external",
        created_at=as_china_aware(clip.created_at),
    )


def _offset_datetime(value: datetime | None, seconds: float | None) -> datetime | None:
    if value is None or seconds is None:
        return None
    return value + timedelta(seconds=seconds)


async def _resolve_clip_times(
    clip: Clip,
    run: TaskRun,
    room: LiveRoom,
) -> tuple[float | None, float | None]:
    """Resolve clip start/end seconds, falling back to disk export_summary.json.

    Existing clips may have NULL start_seconds/end_seconds if they were created
    before those columns existed. This helper backfills the values from the
    export summary so the UI can display real video timestamps.
    """
    if clip.start_seconds is not None and clip.end_seconds is not None:
        return clip.start_seconds, clip.end_seconds

    summary_data = await asyncio.to_thread(_read_export_summary, clip, run, room)
    if summary_data is None:
        return clip.start_seconds, clip.end_seconds

    # Match by output path first, then by title.
    clip_file_name = Path(clip.output_path).name if clip.output_path else None
    for clip_data in summary_data.get("clips", []):
        summary_path_value = clip_data.get("clip_path")
        summary_file_name = Path(summary_path_value).name if summary_path_value else None
        if (
            clip_file_name
            and summary_file_name
            and clip_file_name == summary_file_name
        ):
            return (
                _metadata_float(clip_data, "start_time"),
                _metadata_float(clip_data, "end_time"),
            )

    for clip_data in summary_data.get("clips", []):
        if clip_data.get("title") == clip.title:
            return (
                _metadata_float(clip_data, "start_time"),
                _metadata_float(clip_data, "end_time"),
            )

    return clip.start_seconds, clip.end_seconds


def _read_export_summary(
    clip: Clip,
    run: TaskRun,
    room: LiveRoom,
) -> dict[str, object] | None:
    """Read export_summary.json from disk (synchronous, run in thread)."""
    settings = load_settings()
    summary_path = (
        Path(settings.storage.base_dir)
        / f"room_{room.id}"
        / f"run_{run.id}"
        / "clips"
        / "export_summary.json"
    )
    if not summary_path.exists():
        return None

    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning(
            "resolve_clip_times_summary_read_failed",
            clip_id=clip.id,
            run_id=run.id,
            error=str(exc),
        )
        return None


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
