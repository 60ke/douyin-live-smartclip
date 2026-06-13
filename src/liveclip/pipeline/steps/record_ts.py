"""录制 TS 步骤：解析直播间 → 检测开播 → 获取流地址 → 录制 TS 文件。"""

from __future__ import annotations

import time

from liveclip.adapters.douyin.live_status import DouyinLiveChecker
from liveclip.adapters.douyin.recorder import DouyinRecorder
from liveclip.adapters.douyin.resolver import DouyinResolver
from liveclip.adapters.douyin.stream import DouyinStreamFetcher
from liveclip.domain.enums import StepName
from liveclip.domain.models import StepResult
from liveclip.exceptions import LIVE_ROOM_NOT_LIVE, RECORD_EMPTY_FILE, RecordError
from liveclip.observability import get_logger
from liveclip.pipeline.context import PipelineContext
from liveclip.pipeline.steps.base import BaseStep

logger = get_logger(__name__)


class RecordTsStep(BaseStep):
    """录制 TS 步骤。

    依次执行：解析直播间 URL → 检测开播状态 → 获取流地址 → 录制 TS → 校验文件。
    """

    def __init__(
        self,
        resolver: DouyinResolver | None = None,
        live_checker: DouyinLiveChecker | None = None,
        stream_fetcher: DouyinStreamFetcher | None = None,
        recorder: DouyinRecorder | None = None,
    ) -> None:
        self._resolver = resolver or DouyinResolver()
        self._live_checker = live_checker or DouyinLiveChecker()
        self._stream_fetcher = stream_fetcher or DouyinStreamFetcher()
        self._recorder = recorder or DouyinRecorder()

    @property
    def name(self) -> StepName:
        return StepName.RECORD_TS

    def execute(self, ctx: PipelineContext) -> StepResult:
        """执行录制 TS 步骤。"""
        start_ms = time.monotonic_ns() // 1_000_000
        logger.info("record_ts_start", run_id=ctx.run_id, room_id=ctx.room_id)

        try:
            self._check_cancelled(ctx)

            # 1. 解析直播间
            room_url = ctx.metadata.get("room_url", "")
            cookie = ctx.metadata.get("cookie")
            room_info = self._resolver.resolve_room_info(room_url, cookie)
            logger.info(
                "room_resolved",
                room_id=ctx.room_id,
                anchor_name=room_info.anchor_name,
            )
            ctx.metadata["anchor_name"] = room_info.anchor_name
            ctx.metadata["douyin_room_id"] = room_info.room_id

            self._check_cancelled(ctx)

            # 2. 检测开播状态
            live_status = self._live_checker.check_live(room_info, cookie)
            if not live_status.is_live:
                raise RecordError(
                    LIVE_ROOM_NOT_LIVE,
                    f"直播间未开播: room_id={ctx.room_id}",
                    details={"room_id": ctx.room_id},
                )

            self._check_cancelled(ctx)

            # 3. 获取流地址
            quality = ctx.record_config.quality
            stream_url = self._stream_fetcher.get_stream_url(room_info, quality, cookie)
            logger.info("stream_url_obtained", room_id=ctx.room_id)

            self._check_cancelled(ctx)

            # 4. 录制 TS
            output_path = ctx.paths.raw_ts_path
            max_duration = ctx.record_config.max_duration_seconds
            self._recorder.record(
                stream_url=stream_url,
                output_path=output_path,
                max_duration=max_duration,
                cancel_check=ctx.is_cancelled,
            )

            self._check_cancelled(ctx)

            # 5. 校验文件
            if not output_path.exists():
                raise RecordError(
                    RECORD_EMPTY_FILE,
                    f"录制文件不存在: {output_path}",
                    details={"path": str(output_path)},
                )
            file_size = output_path.stat().st_size
            if file_size == 0:
                raise RecordError(
                    RECORD_EMPTY_FILE,
                    f"录制文件为空: {output_path}",
                    details={"path": str(output_path), "size": file_size},
                )

            elapsed = time.monotonic_ns() // 1_000_000 - start_ms
            logger.info(
                "record_ts_done",
                run_id=ctx.run_id,
                path=str(output_path),
                size=file_size,
                elapsed_ms=elapsed,
            )

            return StepResult(
                success=True,
                output_path=str(output_path),
                duration_ms=elapsed,
                metadata={"file_size": file_size, "anchor_name": room_info.anchor_name},
            )

        except RecordError:
            raise
        except Exception as exc:
            elapsed = time.monotonic_ns() // 1_000_000 - start_ms
            logger.error("record_ts_failed", run_id=ctx.run_id, error=str(exc))
            raise RecordError(
                "RECORD_FAILED",
                f"录制失败: {exc}",
                details={"run_id": ctx.run_id, "error": str(exc)},
            ) from exc
