"""流水线步骤执行器，负责步骤实例化、执行与心跳。"""

from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING

import structlog

from liveclip.adapters.douyin.client import DouyinWebClient
from liveclip.adapters.douyin.live_status import DouyinLiveChecker
from liveclip.adapters.douyin.recorder import DouyinRecorder
from liveclip.adapters.douyin.resolver import DouyinResolver
from liveclip.adapters.douyin.stream import DouyinStreamFetcher
from liveclip.adapters.ffmpeg.clip import FFmpegClipper
from liveclip.adapters.ffmpeg.convert import FFmpegConverter
from liveclip.adapters.funasr.hotwords import HotwordManager
from liveclip.adapters.funasr.transcriber import FunASRTranscriber
from liveclip.adapters.llm.client import LLMClient
from liveclip.domain.enums import StepName
from liveclip.domain.models import StepResult
from liveclip.exceptions import WorkerError
from liveclip.pipeline.context import PipelineContext
from liveclip.pipeline.steps.base import BaseStep
from liveclip.pipeline.steps.convert_mp4 import ConvertMp4Step
from liveclip.pipeline.steps.export_clips import ExportClipsStep
from liveclip.pipeline.steps.finalize import FinalizeStep
from liveclip.pipeline.steps.plan_clips import PlanClipsStep
from liveclip.pipeline.steps.preprocess_subtitle import PreprocessSubtitleStep
from liveclip.pipeline.steps.record_ts import RecordTsStep
from liveclip.pipeline.steps.transcribe import TranscribeStep
from liveclip.pipeline.steps.validate_boundary import ValidateBoundaryStep

if TYPE_CHECKING:
    from liveclip.config.settings import AppSettings
    from liveclip.db.models import TaskStep
    from liveclip.services.run_service import RunService

logger = structlog.get_logger(__name__)

# 步骤名称 → 步骤类的映射
_STEP_NAME_MAP: dict[StepName, type[BaseStep]] = {
    StepName.RECORD_TS: RecordTsStep,
    StepName.CONVERT_MP4: ConvertMp4Step,
    StepName.TRANSCRIBE: TranscribeStep,
    StepName.PREPROCESS_SUBTITLE: PreprocessSubtitleStep,
    StepName.PLAN_CLIPS: PlanClipsStep,
    StepName.VALIDATE_BOUNDARY: ValidateBoundaryStep,
    StepName.EXPORT_CLIPS: ExportClipsStep,
    StepName.FINALIZE: FinalizeStep,
}


class StepExecutor:
    """流水线步骤执行器。

    负责根据 AppSettings 构造适配器、实例化步骤、执行步骤逻辑，
    并在执行期间维护心跳。

    Args:
        settings: 应用配置，用于构造各步骤所需的适配器实例。
    """

    def __init__(self, settings: AppSettings) -> None:
        self._settings = settings

    async def execute_step(
        self,
        step: TaskStep,
        ctx: PipelineContext,
        run_service: RunService,
    ) -> StepResult:
        """执行单个流水线步骤。

        流程：
        1. 将步骤状态标记为 RUNNING
        2. 创建步骤实例并注入适配器
        3. 启动心跳后台线程
        4. 执行步骤逻辑
        5. 根据结果标记步骤为 SUCCEEDED / FAILED
        6. 返回 StepResult

        Args:
            step: 数据库中的步骤记录。
            ctx: 流水线执行上下文。
            run_service: 运行管理服务。

        Returns:
            步骤执行结果。
        """
        step_name = StepName(step.step_name)
        log = logger.bind(run_id=ctx.run_id, step_name=str(step_name), step_id=step.id)

        # 1. 标记步骤为 RUNNING
        await run_service.mark_step_running(step.id)
        await run_service._session.commit()

        # 2. 创建步骤实例
        try:
            step_instance = self._create_step_instance(step_name, ctx)
        except Exception as exc:
            log.error("step_instantiation_failed", error=str(exc))
            await run_service.mark_step_failed(step.id, "CONFIG_INVALID", f"步骤实例化失败: {exc}")
            await run_service._session.commit()
            return StepResult(
                success=False,
                error_code="CONFIG_INVALID",
                error_message=f"步骤实例化失败: {exc}",
            )

        # 3. 启动心跳线程
        stop_heartbeat = threading.Event()
        heartbeat_interval = self._settings.worker.heartbeat_interval_seconds
        heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(ctx.run_id, stop_heartbeat, heartbeat_interval),
            daemon=True,
            name=f"heartbeat-run-{ctx.run_id}",
        )
        heartbeat_thread.start()

        # 4. 执行步骤
        try:
            log.info("step_executing")
            result = await asyncio.to_thread(step_instance.execute, ctx)

            # 5a. 成功
            if result.success:
                await run_service.mark_step_succeeded(
                    step.id,
                    output_path=result.output_path,
                    duration_ms=result.duration_ms,
                    metadata=result.metadata,
                )
                log.info("step_succeeded", duration_ms=result.duration_ms)
            else:
                await run_service.mark_step_failed(
                    step.id,
                    error_code=result.error_code or "UNKNOWN",
                    error_message=result.error_message or "步骤返回失败结果",
                )
                log.warning(
                    "step_failed_result",
                    error_code=result.error_code,
                    error_message=result.error_message,
                )

        except WorkerError as exc:
            # 取消导致的异常
            await run_service.mark_step_failed(step.id, exc.error_code, exc.message)
            log.info("step_cancelled", error_code=exc.error_code)
            result = StepResult(
                success=False,
                error_code=exc.error_code,
                error_message=exc.message,
            )

        except Exception as exc:
            # 未预期的异常
            error_code = getattr(exc, "error_code", "UNKNOWN")
            error_message = str(exc)
            await run_service.mark_step_failed(step.id, error_code, error_message)
            log.error("step_exception", error=str(exc))
            result = StepResult(
                success=False,
                error_code=error_code,
                error_message=error_message,
            )

        finally:
            stop_heartbeat.set()
            heartbeat_thread.join(timeout=5.0)
            await run_service._session.commit()

        return result

    def _create_step_instance(self, step_name: StepName, ctx: PipelineContext) -> BaseStep:
        """根据步骤名称创建步骤实例，注入对应的适配器。

        Args:
            step_name: 步骤名称枚举。
            ctx: 流水线上下文（部分步骤可能需要读取配置）。

        Returns:
            已注入适配器的步骤实例。

        Raises:
            ValueError: 当步骤名称无法识别时。
        """
        settings = self._settings

        if step_name == StepName.RECORD_TS:
            douyin_client = DouyinWebClient()
            return RecordTsStep(
                resolver=DouyinResolver(web_client=douyin_client),
                live_checker=DouyinLiveChecker(web_client=douyin_client),
                stream_fetcher=DouyinStreamFetcher(web_client=douyin_client),
                recorder=DouyinRecorder(),
            )

        if step_name == StepName.CONVERT_MP4:
            return ConvertMp4Step(
                converter=FFmpegConverter(
                    ffmpeg_binary=settings.ffmpeg.ffmpeg_binary,
                    ffprobe_binary=settings.ffmpeg.ffprobe_binary,
                ),
            )

        if step_name == StepName.TRANSCRIBE:
            return TranscribeStep(
                transcriber=FunASRTranscriber(
                    device=settings.funasr.device,
                    model_dir=str(settings.funasr.model_dir),
                ),
                hotword_manager=HotwordManager(),
            )

        if step_name == StepName.PREPROCESS_SUBTITLE:
            return PreprocessSubtitleStep()

        if step_name == StepName.PLAN_CLIPS:
            llm_cfg = ctx.llm_call_config
            api_key = _get_llm_api_key()
            model = _get_llm_model(settings.llm.model)
            return PlanClipsStep(
                llm_client=LLMClient(
                    api_key=api_key,
                    model=model,
                    temperature=llm_cfg.temperature,
                    max_tokens=llm_cfg.max_tokens,
                    timeout=llm_cfg.timeout_seconds,
                    max_retries=llm_cfg.max_retries,
                ),
            )

        if step_name == StepName.VALIDATE_BOUNDARY:
            llm_cfg = ctx.llm_call_config
            api_key = _get_llm_api_key()
            model = _get_llm_model(settings.llm.model)
            return ValidateBoundaryStep(
                llm_client=LLMClient(
                    api_key=api_key,
                    model=model,
                    temperature=llm_cfg.temperature,
                    max_tokens=llm_cfg.max_tokens,
                    timeout=llm_cfg.timeout_seconds,
                    max_retries=llm_cfg.max_retries,
                ),
            )

        if step_name == StepName.EXPORT_CLIPS:
            return ExportClipsStep(
                clipper=FFmpegClipper(
                    ffmpeg_binary=settings.ffmpeg.ffmpeg_binary,
                ),
            )

        if step_name == StepName.FINALIZE:
            return FinalizeStep()

        raise ValueError(f"未知的步骤名称: {step_name}")

    @staticmethod
    def _heartbeat_loop(
        run_id: int,
        stop_event: threading.Event,
        interval: float = 30.0,
    ) -> None:
        """心跳后台线程，定期更新运行心跳时间。

        在独立线程中运行，通过 *stop_event* 控制退出。
        使用独立的数据库会话和事件循环执行心跳更新，
        避免与主线程的会话冲突。

        Args:
            run_id: 运行 ID。
            stop_event: 停止信号事件。
            interval: 心跳间隔（秒），默认 30.0。
        """
        from liveclip.db.repositories.run_repo import TaskRunRepository
        from liveclip.db.session import get_session_context

        repo = TaskRunRepository()

        while not stop_event.is_set():
            loop = asyncio.new_event_loop()
            session = None
            try:
                session = get_session_context()
                loop.run_until_complete(repo.update_heartbeat(session, run_id))
                loop.run_until_complete(session.commit())
            except Exception as exc:
                logger.warning(
                    "heartbeat_update_failed",
                    run_id=run_id,
                    error=str(exc),
                )
            finally:
                if session is not None:
                    loop.run_until_complete(session.close())
                loop.close()
            stop_event.wait(timeout=interval)


def _get_llm_api_key() -> str:
    """从环境变量获取 LLM API Key。

    Returns:
        API Key 字符串。

    Raises:
        WorkerError: 当环境变量未设置时。
    """
    import os

    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("LLM_API", "")
    if not api_key:
        from liveclip.exceptions import CONFIG_INVALID, WorkerError

        raise WorkerError(
            CONFIG_INVALID,
            "环境变量 LLM_API_KEY 未设置",
        )
    return api_key


def _get_llm_model(configured_model: str) -> str:
    """Resolve LLM model with legacy env var taking precedence."""
    import os

    return os.environ.get("LLM_MODEL") or configured_model
