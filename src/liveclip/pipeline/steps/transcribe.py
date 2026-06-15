"""语音转写步骤：将视频文件转写为 SRT 字幕。"""

from __future__ import annotations

import time

from liveclip.adapters.funasr import FunASRTranscriber, HotwordManager
from liveclip.domain.enums import StepName
from liveclip.domain.models import StepResult
from liveclip.exceptions import FUNASR_TRANSCRIBE_FAILED, FunASRError
from liveclip.observability import get_logger
from liveclip.pipeline.context import PipelineContext
from liveclip.pipeline.steps.base import BaseStep

logger = get_logger(__name__)


class TranscribeStep(BaseStep):
    """语音转写步骤。

    从上一步获取视频文件路径（MP4 或 TS），使用 FunASR 转写为 SRT 字幕。
    支持通过 HotwordManager 加载热词词典以提升识别准确率。
    """

    def __init__(
        self,
        transcriber: FunASRTranscriber | None = None,
        hotword_manager: HotwordManager | None = None,
    ) -> None:
        self._transcriber = transcriber or FunASRTranscriber()
        self._hotword_manager = hotword_manager or HotwordManager()

    @property
    def name(self) -> StepName:
        return StepName.TRANSCRIBE

    def execute(self, ctx: PipelineContext) -> StepResult:
        """执行语音转写。"""
        start_ms = time.monotonic_ns() // 1_000_000
        logger.info("transcribe_start", run_id=ctx.run_id)

        try:
            self._check_cancelled(ctx)

            # 确定输入视频路径：优先 MP4，回退 TS
            video_path = self._resolve_video_path(ctx)
            if video_path is None:
                raise FunASRError(
                    FUNASR_TRANSCRIBE_FAILED,
                    "未找到可转写的视频文件",
                    details={"run_id": ctx.run_id},
                )

            self._check_cancelled(ctx)

            # 加载热词
            hotwords = self._hotword_manager.load_hotwords()

            # 执行转写
            from pathlib import Path

            srt_path = ctx.paths.srt_path
            self._transcriber.transcribe(
                video_path=Path(video_path),
                output_srt_path=srt_path,
                hotwords=hotwords,
                cancel_check=ctx.is_cancelled,
            )

            self._check_cancelled(ctx)

            # 校验输出
            if not srt_path.exists():
                raise FunASRError(
                    FUNASR_TRANSCRIBE_FAILED,
                    f"SRT 文件未生成: {srt_path}",
                    details={"path": str(srt_path)},
                )

            elapsed = time.monotonic_ns() // 1_000_000 - start_ms
            logger.info(
                "transcribe_done",
                run_id=ctx.run_id,
                path=str(srt_path),
                elapsed_ms=elapsed,
            )

            return StepResult(
                success=True,
                output_path=str(srt_path),
                duration_ms=elapsed,
                metadata={"video_path": video_path, "hotword_count": len(hotwords)},
            )

        except FunASRError:
            raise
        except Exception as exc:
            elapsed = time.monotonic_ns() // 1_000_000 - start_ms
            logger.error("transcribe_failed", run_id=ctx.run_id, error=str(exc))
            raise FunASRError(
                FUNASR_TRANSCRIBE_FAILED,
                f"转写失败: {exc}",
                details={"run_id": ctx.run_id, "error": str(exc)},
            ) from exc

    @staticmethod
    def _resolve_video_path(ctx: PipelineContext) -> str | None:
        """从上下文中获取视频文件路径，优先 MP4，回退 TS。"""
        mp4_result = ctx.get_step_result(str(StepName.CONVERT_MP4))
        if mp4_result is not None and mp4_result.success and mp4_result.output_path:
            return mp4_result.output_path

        record_result = ctx.get_step_result(str(StepName.RECORD_TS))
        if record_result is not None and record_result.success and record_result.output_path:
            return record_result.output_path

        return None
