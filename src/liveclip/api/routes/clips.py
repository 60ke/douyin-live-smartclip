"""切片查询路由。"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.api.deps import get_clip_service, get_db_session
from liveclip.config import load_settings
from liveclip.db.models import Clip, ClipPlan, Task, TaskRun
from liveclip.observability import get_logger
from liveclip.schemas.clip import ClipPlanResponse, ClipResponse
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

    for idx, clip_data in enumerate(summary_data.get("clips", [])):
        scores = plan_scores.get(idx, {})
        session.add(
            Clip(
                plan_id=clip_plan.id,
                title=clip_data.get("title", "未命名"),
                start_subtitle_index=scores.get("start_subtitle_index", 0),
                end_subtitle_index=scores.get("end_subtitle_index", 0),
                score=scores.get("score", 0.0),
                structure_score=scores.get("structure_score", 0.0),
                reason=scores.get("reason", ""),
                structure_reason=scores.get("structure_reason", ""),
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
