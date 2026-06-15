"""切片方案与切片管理服务。"""

from __future__ import annotations

import json
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.db.models import Clip, ClipPlan
from liveclip.db.repositories.artifact_repo import ClipPlanRepository, ClipRepository
from liveclip.domain.enums import ClipPlanStatus, ClipStatus

logger = structlog.get_logger(__name__)


class ClipService:
    """切片方案与切片管理服务。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._plan_repo = ClipPlanRepository()
        self._clip_repo = ClipRepository()

    async def get_plan_by_run(self, run_id: int) -> ClipPlan | None:
        """根据运行 ID 获取切片方案。"""
        return await self._plan_repo.get_clip_plan_by_run(self._session, run_id)

    async def get_plans_by_run(self, run_id: int) -> list[ClipPlan]:
        """根据运行 ID 获取切片方案列表。"""
        return await self._plan_repo.get_clip_plans_by_run(self._session, run_id)

    async def get_clips_by_plan(self, plan_id: int) -> list[Clip]:
        """获取方案下所有切片。"""
        return await self._clip_repo.get_clips_by_plan(self._session, plan_id)

    async def get_clips_by_run(self, run_id: int) -> list[Clip]:
        """根据运行 ID 获取最新方案下的切片。"""
        plan = await self._plan_repo.get_clip_plan_by_run(self._session, run_id)
        if plan is None:
            return []
        return await self._clip_repo.get_clips_by_plan(self._session, plan.id)

    async def create_plan(self, run_id: int, llm_profile_id: int | None = None) -> ClipPlan:
        """创建切片方案。"""
        plan = ClipPlan(
            run_id=run_id,
            llm_profile_id=llm_profile_id,
            status=str(ClipPlanStatus.PENDING),
        )
        self._session.add(plan)
        await self._session.flush()
        await self._session.refresh(plan)
        logger.info("切片方案已创建", plan_id=plan.id, run_id=run_id)
        return plan

    async def update_plan_status(
        self, plan_id: int, status: ClipPlanStatus, **kwargs: Any
    ) -> ClipPlan:
        """更新切片方案状态及字段。"""
        plan = await self._session.get(ClipPlan, plan_id)
        if not plan:
            raise ValueError(f"ClipPlan id={plan_id} 不存在")
        plan.status = str(status)
        for key, value in kwargs.items():
            if hasattr(plan, key):
                setattr(plan, key, value)
        await self._session.flush()
        await self._session.refresh(plan)
        logger.info("切片方案已更新", plan_id=plan_id, status=str(status))
        return plan

    async def create_clip(self, plan_id: int, segment: dict[str, Any]) -> Clip:
        """根据分段字典创建切片。"""
        clip = Clip(
            plan_id=plan_id,
            source_record_id=segment.get("source_record_id"),
            title=segment.get("title", "未命名片段"),
            start_subtitle_index=segment.get("start_subtitle_index", 0),
            end_subtitle_index=segment.get("end_subtitle_index", 0),
            parts_json=json.dumps(segment.get("parts", []), ensure_ascii=False),
            start_seconds=segment.get("start_seconds") or segment.get("start_time"),
            end_seconds=segment.get("end_seconds") or segment.get("end_time"),
            duration_seconds=segment.get("duration_seconds"),
            score=segment.get("score", 0.0),
            structure_score=segment.get("structure_score", 0.0),
            reason=segment.get("reason", ""),
            structure_reason=segment.get("structure_reason", ""),
            status=str(ClipStatus.PENDING),
        )
        self._session.add(clip)
        await self._session.flush()
        await self._session.refresh(clip)
        logger.info("切片已创建", clip_id=clip.id, plan_id=plan_id, title=clip.title)
        return clip

    async def update_clip_status(
        self,
        clip_id: int,
        status: ClipStatus,
        output_path: str | None = None,
        subtitle_output_path: str | None = None,
    ) -> Clip:
        """更新切片状态及输出路径。"""
        clip = await self._session.get(Clip, clip_id)
        if not clip:
            raise ValueError(f"Clip id={clip_id} 不存在")
        clip.status = str(status)
        if output_path is not None:
            clip.output_path = output_path
        if subtitle_output_path is not None:
            clip.subtitle_output_path = subtitle_output_path
        await self._session.flush()
        await self._session.refresh(clip)
        logger.info("切片已更新", clip_id=clip_id, status=str(status))
        return clip
