"""抖音直播录制适配器。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from liveclip.adapters.ffmpeg.command import FFmpegCommandBuilder
from liveclip.exceptions import RECORD_FAILED, RecordError
from liveclip.observability import get_logger
from liveclip.utils.process import run_long_command

logger = get_logger(__name__)


class DouyinRecorder:
    """使用 FFmpeg 直录抖音直播流。"""

    def __init__(self, ffmpeg_binary: str = "ffmpeg") -> None:
        self._ffmpeg_binary = ffmpeg_binary

    def record(
        self,
        stream_url: str,
        output_path: Path,
        max_duration: int | None = None,
        headers: str | None = None,
        http_proxy: str | None = None,
        cancel_check: Callable[[], bool] | None = None,
        heartbeat_callback: Callable[[], None] | None = None,
    ) -> Path:
        """录制直播流到文件。

        使用 FFmpeg 子进程拉取 HLS/FLV 流并保存为 TS。先写入 .part 临时文件，
        录制完成后原子重命名为目标路径。

        Args:
            stream_url: 直播流 URL。
            output_path: 录制文件输出路径。
            max_duration: 最大录制时长（秒），默认不限制。
            cancel_check: 可选的取消检查回调，返回 True 时终止录制。
            heartbeat_callback: 可选的心跳回调，定期调用以表明录制仍在进行。

        Returns:
            录制文件的最终路径。

        Raises:
            RecordError: 录制失败时抛出。
        """
        part_path = output_path.with_suffix(output_path.suffix + ".part")
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = FFmpegCommandBuilder.record_stream_to_ts(
            stream_url=stream_url,
            output_path=part_path,
            max_duration_seconds=max_duration,
            headers=headers,
            http_proxy=http_proxy,
        )
        cmd[0] = self._ffmpeg_binary

        logger.info(
            "starting_recording",
            output_path=str(output_path),
            max_duration=max_duration,
        )

        ffmpeg_output: list[str] = []
        try:
            result = run_long_command(
                cmd,
                timeout=max_duration + 60 if max_duration and max_duration > 0 else None,
                heartbeat_callback=heartbeat_callback,
                cancel_check=cancel_check,
                heartbeat_interval=10.0,
                log_callback=ffmpeg_output.append,
            )
        except Exception as exc:
            # 清理残留的 .part 文件
            if part_path.exists():
                part_path.unlink(missing_ok=True)
            raise RecordError(
                RECORD_FAILED,
                f"录制进程异常: {exc}",
                details={"output_path": str(output_path), "error": str(exc)},
            ) from exc

        if result.returncode != 0:
            if part_path.exists():
                part_path.unlink(missing_ok=True)
            output_tail = _tail_output(result.stdout or "\n".join(ffmpeg_output))
            raise RecordError(
                RECORD_FAILED,
                f"录制进程退出码非零: {result.returncode}; 输出: {output_tail}",
                details={
                    "output_path": str(output_path),
                    "returncode": result.returncode,
                    "stderr": output_tail,
                },
            )

        # 检查 .part 文件是否存在
        if not part_path.exists():
            raise RecordError(
                RECORD_FAILED,
                f"录制完成但未找到临时文件: {part_path}",
                details={"output_path": str(output_path), "part_path": str(part_path)},
            )

        # 原子重命名
        part_path.rename(output_path)
        logger.info("recording_finished", output_path=str(output_path))

        return output_path


def _tail_output(output: str, max_chars: int = 1200) -> str:
    cleaned = output.strip()
    if not cleaned:
        return ""
    return cleaned[-max_chars:]
