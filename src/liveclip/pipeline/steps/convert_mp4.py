"""转换 MP4 步骤：将 TS 文件转换为 MP4 格式。"""

from __future__ import annotations

import time

from liveclip.adapters.ffmpeg import FFmpegConverter
from liveclip.domain.enums import StepName
from liveclip.domain.models import StepResult
from liveclip.exceptions import FFMPEG_CONVERT_FAILED, FFmpegError
from liveclip.observability import get_logger
from liveclip.pipeline.context import PipelineContext
from liveclip.pipeline.steps.base import BaseStep

logger = get_logger(__name__)


class ConvertMp4Step(BaseStep):
    """转换 MP4 步骤。

    从上一步获取 TS 文件路径，使用 FFmpeg 转换为 MP4 格式。
    当 pipeline_config.convert_mp4 为 False 时应被跳过。
    """

    def __init__(self, converter: FFmpegConverter | None = None) -> None:
        self._converter = converter or FFmpegConverter()

    @property
    def name(self) -> StepName:
        return StepName.CONVERT_MP4

    def execute(self, ctx: PipelineContext) -> StepResult:
        """执行 TS → MP4 转换。"""
        start_ms = time.monotonic_ns() // 1_000_000
        logger.info("convert_mp4_start", run_id=ctx.run_id)

        try:
            self._check_cancelled(ctx)

            # 获取上一步的 TS 文件路径
            record_result = ctx.get_step_result(str(StepName.RECORD_TS))
            if record_result is None or record_result.output_path is None:
                raise FFmpegError(
                    FFMPEG_CONVERT_FAILED,
                    "未找到录制步骤的输出文件路径",
                    details={"run_id": ctx.run_id},
                )

            from pathlib import Path

            ts_path = Path(record_result.output_path)
            mp4_path = ctx.paths.mp4_path

            self._check_cancelled(ctx)

            # 执行转换
            self._converter.convert_ts_to_mp4(
                input_path=ts_path,
                output_path=mp4_path,
                reencode_h264=ctx.pipeline_config.convert_mp4_reencode_h264,
                cancel_check=ctx.is_cancelled,
            )

            self._check_cancelled(ctx)

            # 校验输出
            if not mp4_path.exists():
                raise FFmpegError(
                    FFMPEG_CONVERT_FAILED,
                    f"MP4 文件未生成: {mp4_path}",
                    details={"path": str(mp4_path)},
                )

            file_size = mp4_path.stat().st_size
            elapsed = time.monotonic_ns() // 1_000_000 - start_ms
            logger.info(
                "convert_mp4_done",
                run_id=ctx.run_id,
                path=str(mp4_path),
                size=file_size,
                elapsed_ms=elapsed,
            )

            return StepResult(
                success=True,
                output_path=str(mp4_path),
                duration_ms=elapsed,
                metadata={"file_size": file_size},
            )

        except FFmpegError:
            raise
        except Exception as exc:
            elapsed = time.monotonic_ns() // 1_000_000 - start_ms
            logger.error("convert_mp4_failed", run_id=ctx.run_id, error=str(exc))
            raise FFmpegError(
                FFMPEG_CONVERT_FAILED,
                f"MP4 转换失败: {exc}",
                details={"run_id": ctx.run_id, "error": str(exc)},
            ) from exc
