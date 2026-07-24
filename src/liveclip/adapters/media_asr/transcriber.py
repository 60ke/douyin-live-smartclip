"""HTTP-backed transcriber delegating to shared media-asr."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

from liveclip.adapters.media_asr.client import MediaAsrClient
from liveclip.config.settings import MediaAsrConfig
from liveclip.exceptions import FUNASR_TRANSCRIBE_FAILED, FunASRError
from liveclip.observability import get_logger

logger = get_logger(__name__)


class MediaAsrHttpTranscriber:
    """Transcribe media via media-capabilities ASR HTTP API."""

    def __init__(
        self,
        config: MediaAsrConfig,
        *,
        client: MediaAsrClient | None = None,
    ) -> None:
        api_key = (config.api_key or os.getenv(config.api_key_env, "")).strip()
        self._client = client or MediaAsrClient(
            base_url=config.base_url,
            api_key=api_key,
            poll_interval_seconds=config.poll_interval_seconds,
            poll_timeout_seconds=config.poll_timeout_seconds,
        )

    def transcribe(
        self,
        video_path: Path,
        output_srt_path: Path,
        hotwords: list[str] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Path:
        """Transcribe media to SRT using shared media-asr."""
        logger.info(
            "media_asr_transcribe_start",
            video_path=str(video_path),
            output_srt_path=str(output_srt_path),
        )

        if cancel_check and cancel_check():
            raise FunASRError(
                FUNASR_TRANSCRIBE_FAILED,
                "转写被取消",
                details={"video_path": str(video_path)},
            )

        if not video_path.exists():
            raise FunASRError(
                FUNASR_TRANSCRIBE_FAILED,
                f"输入文件不存在: {video_path}",
                details={"video_path": str(video_path)},
            )

        try:
            engine_job_id = self._client.submit_asr_job(video_path, hotwords=hotwords)
            detail = self._client.poll_until_done(engine_job_id, cancel_check=cancel_check)
            srt_content = self._resolve_srt_content(detail)
        except FunASRError:
            raise
        except Exception as exc:
            raise FunASRError(
                FUNASR_TRANSCRIBE_FAILED,
                f"media-asr 转写失败: {exc}",
                details={"video_path": str(video_path), "error": str(exc)},
            ) from exc

        if cancel_check and cancel_check():
            raise FunASRError(
                FUNASR_TRANSCRIBE_FAILED,
                "转写被取消",
                details={"video_path": str(video_path)},
            )

        if not srt_content.strip():
            raise FunASRError(
                FUNASR_TRANSCRIBE_FAILED,
                f"media-asr 转写结果为空: {video_path}",
                details={"video_path": str(video_path)},
            )

        output_srt_path.parent.mkdir(parents=True, exist_ok=True)
        output_srt_path.write_text(srt_content, encoding="utf-8")
        logger.info(
            "media_asr_transcribe_finished",
            output_srt_path=str(output_srt_path),
            size=len(srt_content),
        )
        return output_srt_path

    def _resolve_srt_content(self, detail: dict) -> str:
        result = detail.get("result") or {}
        inline_srt = result.get("srt")
        if isinstance(inline_srt, str) and inline_srt.strip():
            return inline_srt

        srt_path = result.get("srt_path")
        if isinstance(srt_path, str) and srt_path.strip():
            content = self._client.download_file(srt_path)
            return content.decode("utf-8")

        raise RuntimeError("media-asr succeeded but no SRT content or srt_path was returned")
