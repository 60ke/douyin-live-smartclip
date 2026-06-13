"""收尾步骤：收集所有步骤结果，写入运行摘要。"""

from __future__ import annotations

import time

from liveclip.domain.enums import StepName
from liveclip.domain.models import StepResult
from liveclip.exceptions import STORAGE_WRITE_FAILED, StorageError
from liveclip.observability import get_logger
from liveclip.pipeline.context import PipelineContext
from liveclip.pipeline.steps.base import BaseStep
from liveclip.storage.local import LocalStorage

logger = get_logger(__name__)


class FinalizeStep(BaseStep):
    """收尾步骤。

    收集所有步骤结果 -> 写入运行摘要 JSON -> 返回最终结果。
    """

    @property
    def name(self) -> StepName:
        return StepName.FINALIZE

    def execute(self, ctx: PipelineContext) -> StepResult:
        """执行收尾。"""
        start_ms = time.monotonic_ns() // 1_000_000
        logger.info("finalize_start", run_id=ctx.run_id)

        try:
            self._check_cancelled(ctx)

            steps_summary: dict[str, object] = {}
            for step_name, result in ctx.step_results.items():
                steps_summary[step_name] = {
                    "success": result.success,
                    "output_path": result.output_path,
                    "duration_ms": result.duration_ms,
                    "error_code": result.error_code,
                    "error_message": result.error_message,
                }

            summary: dict[str, object] = {
                "run_id": ctx.run_id,
                "room_id": ctx.room_id,
                "task_id": ctx.task_id,
                "steps": steps_summary,
                "metadata": ctx.metadata,
                "total_duration_ms": sum(r.duration_ms for r in ctx.step_results.values()),
            }

            LocalStorage.write_json(ctx.paths.summary_path, summary)

            elapsed = time.monotonic_ns() // 1_000_000 - start_ms
            logger.info(
                "finalize_done",
                run_id=ctx.run_id,
                steps_count=len(ctx.step_results),
                elapsed_ms=elapsed,
            )

            return StepResult(
                success=True,
                output_path=str(ctx.paths.summary_path),
                duration_ms=elapsed,
                metadata={
                    "steps_count": len(ctx.step_results),
                    "summary_path": str(ctx.paths.summary_path),
                },
            )

        except Exception as exc:
            elapsed = time.monotonic_ns() // 1_000_000 - start_ms
            logger.error("finalize_failed", run_id=ctx.run_id, error=str(exc))
            raise StorageError(
                STORAGE_WRITE_FAILED,
                f"收尾步骤失败: {exc}",
                details={"run_id": ctx.run_id, "error": str(exc)},
            ) from exc
