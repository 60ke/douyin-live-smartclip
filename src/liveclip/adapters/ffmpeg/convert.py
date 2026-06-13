"""FFmpeg 视频格式转换适配器。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from liveclip.adapters.ffmpeg.command import FFmpegCommandBuilder
from liveclip.adapters.ffmpeg.tempfile import temporary_output_path
from liveclip.exceptions import FFMPEG_CONVERT_FAILED, FFPROBE_FAILED, FFmpegError
from liveclip.observability import get_logger
from liveclip.utils.process import run_command, run_long_command

logger = get_logger(__name__)


class FFmpegConverter:
    """使用 FFmpeg 进行视频格式转换。"""

    def __init__(
        self,
        ffmpeg_binary: str = "ffmpeg",
        ffprobe_binary: str = "ffprobe",
    ) -> None:
        self._ffmpeg_binary = ffmpeg_binary
        self._ffprobe_binary = ffprobe_binary

    def convert_ts_to_mp4(
        self,
        input_path: Path,
        output_path: Path,
        reencode_h264: bool = False,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Path:
        """将 TS 文件转换为 MP4 格式。

        先写入 .part 临时文件，转换完成后原子重命名为目标路径。

        Args:
            input_path: 输入 TS 文件路径。
            output_path: 输出 MP4 文件路径。
            cancel_check: 可选的取消检查回调。

        Returns:
            转换后的 MP4 文件路径。

        Raises:
            FFmpegError: 转换失败时抛出。
        """
        part_path = temporary_output_path(output_path)

        cmd = FFmpegCommandBuilder.convert_ts_to_mp4(
            input_path,
            part_path,
            reencode_h264=reencode_h264,
        )
        # 替换 ffmpeg 二进制名
        cmd[0] = self._ffmpeg_binary

        logger.info(
            "converting_ts_to_mp4",
            input_path=str(input_path),
            output_path=str(output_path),
        )

        try:
            if cancel_check is not None:
                result = run_long_command(cmd, cancel_check=cancel_check)
            else:
                result = run_command(cmd)
        except Exception as exc:
            if part_path.exists():
                part_path.unlink(missing_ok=True)
            raise FFmpegError(
                FFMPEG_CONVERT_FAILED,
                f"TS 转 MP4 失败: {exc}",
                details={"input_path": str(input_path), "error": str(exc)},
            ) from exc

        if result.returncode != 0:
            if part_path.exists():
                part_path.unlink(missing_ok=True)
            raise FFmpegError(
                FFMPEG_CONVERT_FAILED,
                f"TS 转 MP4 退出码非零: {result.returncode}",
                details={
                    "input_path": str(input_path),
                    "returncode": result.returncode,
                    "stderr": result.stderr,
                },
            )

        if not part_path.exists():
            raise FFmpegError(
                FFMPEG_CONVERT_FAILED,
                f"转换完成但未找到临时文件: {part_path}",
                details={"input_path": str(input_path), "part_path": str(part_path)},
            )

        part_path.rename(output_path)
        logger.info("ts_to_mp4_finished", output_path=str(output_path))

        return output_path

    def get_duration(self, file_path: Path) -> float:
        """获取视频文件时长。

        Args:
            file_path: 视频文件路径。

        Returns:
            时长（秒）。

        Raises:
            FFmpegError: ffprobe 执行失败时抛出。
        """
        cmd = FFmpegCommandBuilder.probe_duration(file_path)
        cmd[0] = self._ffprobe_binary

        try:
            result = run_command(cmd)
        except Exception as exc:
            raise FFmpegError(
                FFPROBE_FAILED,
                f"获取视频时长失败: {exc}",
                details={"file_path": str(file_path), "error": str(exc)},
            ) from exc

        try:
            return float(result.stdout.strip())
        except ValueError as exc:
            raise FFmpegError(
                FFPROBE_FAILED,
                f"解析视频时长失败: {result.stdout!r}",
                details={"file_path": str(file_path), "stdout": result.stdout},
            ) from exc

    def validate_file(self, file_path: Path) -> bool:
        """检查文件是否为有效媒体文件（时长 > 0）。

        Args:
            file_path: 视频文件路径。

        Returns:
            文件有效返回 True，否则 False。
        """
        try:
            duration = self.get_duration(file_path)
            return duration > 0
        except FFmpegError:
            return False
