"""运行管理服务。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from liveclip.db.models import Clip, ClipPlan, Record, Subtitle, TaskRun, TaskStep
from liveclip.db.repositories.run_repo import TaskRunRepository
from liveclip.domain.enums import RecordSourceType, RunStatus, StepName, StepStatus
from liveclip.pipeline.state_machine import PIPELINE_STEPS
from liveclip.schemas.run import RunCreate

logger = structlog.get_logger(__name__)


class RunService:
    """运行业务逻辑层，封装运行状态管理与步骤操作。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repo = TaskRunRepository()

    async def get_by_id(self, run_id: int) -> TaskRun | None:
        """根据 ID 获取运行。"""
        return await self._repo.get_by_id(self._session, run_id)

    async def get_detail(self, run_id: int) -> tuple[TaskRun, list[TaskStep]]:
        """获取运行及其步骤列表。"""
        run = await self._repo.get_by_id(self._session, run_id)
        if run is None:
            raise ValueError(f"TaskRun id={run_id} 不存在")
        steps = await self._repo.get_steps_by_run(self._session, run_id)
        return run, steps

    async def get_all(self, offset: int = 0, limit: int = 100) -> tuple[list[TaskRun], int]:
        """获取运行列表及总数。"""
        items = await self._repo.get_all(self._session, offset=offset, limit=limit)
        count_stmt = select(func.count()).select_from(TaskRun)
        result = await self._session.execute(count_stmt)
        total = result.scalar_one()
        return items, total

    async def get_by_task(
        self,
        task_id: int,
        offset: int = 0,
        limit: int = 100,
    ) -> tuple[list[TaskRun], int]:
        """获取指定任务的运行列表及总数。"""
        stmt = (
            select(TaskRun)
            .where(TaskRun.task_id == task_id)
            .order_by(TaskRun.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(stmt)
        items = list(result.scalars().all())
        count_stmt = select(func.count()).select_from(TaskRun).where(TaskRun.task_id == task_id)
        count_result = await self._session.execute(count_stmt)
        return items, count_result.scalar_one()

    async def create(self, body: RunCreate) -> TaskRun:
        """创建一次任务运行及对应步骤记录。"""
        run = TaskRun(
            task_id=body.task_id,
            run_status=str(RunStatus.PENDING),
            trigger_type=str(body.trigger_type),
        )
        self._session.add(run)
        await self._session.flush()

        for step_name in PIPELINE_STEPS:
            self._session.add(
                TaskStep(
                    run_id=run.id,
                    step_name=str(StepName(step_name)),
                    step_status=str(StepStatus.PENDING),
                )
            )

        await self._session.flush()
        await self._session.refresh(run)
        logger.info("运行已创建", run_id=run.id, task_id=run.task_id)
        return run

    async def pick_next_pending(self) -> TaskRun | None:
        """获取下一个待执行的 PENDING 运行。"""
        return await self._repo.pick_next_pending_run(self._session)

    async def mark_running(self, run_id: int) -> None:
        """将运行状态设为 RUNNING，并记录 started_at。"""
        run = await self._repo.get_by_id(self._session, run_id)
        if run is None:
            raise ValueError(f"TaskRun id={run_id} 不存在")
        run.run_status = str(RunStatus.RUNNING)
        run.started_at = datetime.now()
        await self._session.flush()
        logger.info("运行已开始", run_id=run_id)

    async def mark_succeeded(self, run_id: int) -> None:
        """将运行状态设为 SUCCEEDED，并记录 finished_at。"""
        run = await self._repo.get_by_id(self._session, run_id)
        if run is None:
            raise ValueError(f"TaskRun id={run_id} 不存在")
        run.run_status = str(RunStatus.SUCCEEDED)
        run.finished_at = datetime.now()
        await self._session.flush()
        logger.info("运行已成功", run_id=run_id)

    async def mark_waiting(self, run_id: int, error_code: str, error_message: str) -> None:
        """将循环检测运行状态设为 WAITING，表示直播间暂未开播。"""
        run = await self._repo.get_by_id(self._session, run_id)
        if run is None:
            raise ValueError(f"TaskRun id={run_id} 不存在")
        run.run_status = str(RunStatus.WAITING)
        run.finished_at = datetime.now()
        run.error_code = error_code
        run.error_message = error_message
        await self._session.flush()
        logger.info(
            "运行等待开播",
            run_id=run_id,
            error_code=error_code,
            error_message=error_message,
        )

    async def mark_failed(self, run_id: int, error_code: str, error_message: str) -> None:
        """将运行状态设为 FAILED，记录错误信息。"""
        run = await self._repo.get_by_id(self._session, run_id)
        if run is None:
            raise ValueError(f"TaskRun id={run_id} 不存在")
        run.run_status = str(RunStatus.FAILED)
        run.finished_at = datetime.now()
        run.error_code = error_code
        run.error_message = error_message
        await self._session.flush()
        logger.warning(
            "运行已失败",
            run_id=run_id,
            error_code=error_code,
            error_message=error_message,
        )

    async def mark_canceled(self, run_id: int) -> None:
        """将运行状态设为 CANCELED。"""
        run = await self._repo.get_by_id(self._session, run_id)
        if run is None:
            raise ValueError(f"TaskRun id={run_id} 不存在")
        run.run_status = str(RunStatus.CANCELED)
        run.finished_at = datetime.now()
        await self._session.flush()
        logger.info("运行已取消", run_id=run_id)

    async def update_heartbeat(self, run_id: int) -> None:
        """更新运行心跳时间。"""
        await self._repo.update_heartbeat(self._session, run_id)
        logger.debug("心跳已更新", run_id=run_id)

    async def get_stale_runs(self, timeout_seconds: int) -> list[TaskRun]:
        """获取心跳超时的运行列表。"""
        return await self._repo.get_stale_runs(self._session, timeout_seconds)

    async def cancel_run(self, run_id: int) -> None:
        """取消运行（等同于 mark_canceled）。"""
        await self.mark_canceled(run_id)

    async def mark_step_running(self, step_id: int) -> None:
        """将步骤状态设为 RUNNING，并记录 started_at。"""
        step = await self._session.get(TaskStep, step_id)
        if step is None:
            raise ValueError(f"TaskStep id={step_id} 不存在")
        step.step_status = str(StepStatus.RUNNING)
        step.started_at = datetime.now()
        await self._session.flush()
        logger.info("步骤已开始", step_id=step_id, step_name=step.step_name)

    async def mark_step_succeeded(
        self,
        step_id: int,
        output_path: str | None = None,
        duration_ms: int = 0,
        metadata: dict[str, object] | None = None,
    ) -> None:
        """将步骤状态设为 SUCCEEDED，记录输出路径和耗时。"""
        step = await self._session.get(TaskStep, step_id)
        if step is None:
            raise ValueError(f"TaskStep id={step_id} 不存在")
        step.step_status = str(StepStatus.SUCCEEDED)
        step.finished_at = datetime.now()
        step.output_path = output_path
        step.duration_ms = duration_ms
        if metadata is not None:
            step.metadata_json = json.dumps(metadata, ensure_ascii=False)
        await self._sync_step_artifact(step, output_path, metadata)
        await self._session.flush()
        logger.info(
            "步骤已成功",
            step_id=step_id,
            step_name=step.step_name,
            duration_ms=duration_ms,
        )

    async def mark_step_failed(self, step_id: int, error_code: str, error_message: str) -> None:
        """将步骤状态设为 FAILED，记录错误信息。"""
        step = await self._session.get(TaskStep, step_id)
        if step is None:
            raise ValueError(f"TaskStep id={step_id} 不存在")
        step.step_status = str(StepStatus.FAILED)
        step.finished_at = datetime.now()
        step.error_code = error_code
        step.error_message = error_message
        await self._session.flush()
        logger.warning(
            "步骤已失败",
            step_id=step_id,
            step_name=step.step_name,
            error_code=error_code,
        )

    async def mark_step_skipped(
        self,
        step_id: int,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """将步骤状态设为 SKIPPED。"""
        step = await self._session.get(TaskStep, step_id)
        if step is None:
            raise ValueError(f"TaskStep id={step_id} 不存在")
        step.step_status = str(StepStatus.SKIPPED)
        step.finished_at = datetime.now()
        step.error_code = error_code
        step.error_message = error_message
        await self._session.flush()
        logger.info(
            "步骤已跳过",
            step_id=step_id,
            step_name=step.step_name,
            error_code=error_code,
        )

    async def _sync_step_artifact(
        self,
        step: TaskStep,
        output_path: str | None,
        metadata: dict[str, object] | None,
    ) -> None:
        if not output_path:
            return
        if step.step_name in (str(StepName.RECORD_TS), str(StepName.CONVERT_MP4)):
            await self._upsert_record(step, output_path, metadata)
        if step.step_name in (str(StepName.TRANSCRIBE), str(StepName.PREPROCESS_SUBTITLE)):
            await self._upsert_subtitle(step, output_path)
        if step.step_name == str(StepName.EXPORT_CLIPS):
            await self._upsert_clip_plan_and_clips(step, output_path)

    async def _upsert_record(
        self,
        step: TaskStep,
        output_path: str,
        metadata: dict[str, object] | None,
    ) -> None:
        file_path = Path(output_path)
        file_size = _metadata_int(metadata, "file_size")
        if file_size is None and file_path.exists():
            file_size = file_path.stat().st_size
        duration_seconds = step.duration_ms / 1000 if step.duration_ms else 0.0
        stmt = select(Record).where(Record.run_id == step.run_id, Record.file_path == output_path)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        if record is None:
            record = Record(
                run_id=step.run_id,
                source_type=str(RecordSourceType.DOUYIN_RECORD),
                file_path=output_path,
                file_size=file_size or 0,
                duration_seconds=duration_seconds,
                format=file_path.suffix.lstrip(".") or "video",
            )
            self._session.add(record)
        else:
            record.file_size = file_size or record.file_size
            record.duration_seconds = duration_seconds or record.duration_seconds
            record.format = file_path.suffix.lstrip(".") or record.format

    async def _upsert_subtitle(self, step: TaskStep, output_path: str) -> None:
        stmt = select(Subtitle).where(Subtitle.run_id == step.run_id, Subtitle.file_path == output_path)
        result = await self._session.execute(stmt)
        subtitle = result.scalar_one_or_none()
        word_count = _count_subtitle_words(Path(output_path))
        if subtitle is None:
            self._session.add(
                Subtitle(
                    run_id=step.run_id,
                    file_path=output_path,
                    language="zh",
                    word_count=word_count,
                )
            )
        else:
            subtitle.word_count = word_count

    async def _upsert_clip_plan_and_clips(
        self, step: TaskStep, clips_dir: str
    ) -> None:
        """从导出目录的 export_summary.json 创建 ClipPlan 与 Clip 记录。"""
        summary_path = Path(clips_dir) / "export_summary.json"
        if not summary_path.exists():
            logger.warning(
                "export_summary_not_found",
                run_id=step.run_id,
                path=str(summary_path),
            )
            return

        try:
            summary_data = json.loads(summary_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "export_summary_read_failed",
                run_id=step.run_id,
                error=str(exc),
            )
            return

        # 从 plan JSON 中加载评分数据
        plan_dir = summary_path.parent.parent / "plans"
        plan_scores = self._load_plan_scores(plan_dir)

        # 创建 ClipPlan
        clip_plan = ClipPlan(
            run_id=step.run_id,
            status="COMPLETED",
            segment_count=summary_data.get("total", 0),
        )
        self._session.add(clip_plan)
        await self._session.flush()  # 需要 plan_id

        source_record = await self._get_source_record(step.run_id)

        # 创建每个 Clip 记录
        for idx, clip_data in enumerate(summary_data.get("clips", [])):
            scores = plan_scores.get(idx, {})
            parts = clip_data.get("parts") or []
            self._session.add(
                Clip(
                    plan_id=clip_plan.id,
                    source_record_id=source_record.id if source_record else None,
                    title=clip_data.get("title", f"切片{clip_data.get('index', '')}"),
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

        logger.info(
            "clip_plan_created",
            run_id=step.run_id,
            plan_id=clip_plan.id,
            clip_count=summary_data.get("total", 0),
        )

    async def _get_source_record(self, run_id: int) -> Record | None:
        """Return the canonical source video for a run, preferring converted MP4."""
        stmt = select(Record).where(Record.run_id == run_id).order_by(Record.id.desc())
        result = await self._session.execute(stmt)
        records = list(result.scalars().all())
        for record in records:
            if record.format == "mp4":
                return record
        return records[0] if records else None

    @staticmethod
    def _load_plan_scores(plan_dir: Path) -> dict[int, dict[str, object]]:
        """从 plan_dir 下的 validated_plan.json 或 normalized_plan.json 加载评分。"""
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


def _count_subtitle_words(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return 0
    return len("".join(text.split()))
