"""FFmpeg 视频切片适配器。"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from liveclip.adapters.ffmpeg.command import FFmpegCommandBuilder
from liveclip.adapters.ffmpeg.tempfile import temporary_output_path
from liveclip.exceptions import FFMPEG_CONVERT_FAILED, FFmpegError
from liveclip.observability import get_logger
from liveclip.utils.process import run_command, run_long_command

logger = get_logger(__name__)


class FFmpegClipper:
    """使用 FFmpeg 进行视频切片。"""

    def __init__(self, ffmpeg_binary: str = "ffmpeg", fast_seek: bool = False) -> None:
        self._ffmpeg_binary = ffmpeg_binary
        self._fast_seek = fast_seek

    def clip_segment(
        self,
        input_path: Path,
        output_path: Path,
        start_seconds: float,
        duration_seconds: float,
        cancel_check: Callable[[], bool] | None = None,
    ) -> Path:
        """从视频中截取单个片段。

        先写入 .part 临时文件，截取完成后原子重命名为目标路径。

        Args:
            input_path: 输入视频文件路径。
            output_path: 输出切片文件路径。
            start_seconds: 起始时间（秒）。
            duration_seconds: 切片时长（秒）。
            cancel_check: 可选的取消检查回调。

        Returns:
            切片文件路径。

        Raises:
            FFmpegError: 切片失败时抛出。
        """
        part_path = temporary_output_path(output_path)

        cmd = FFmpegCommandBuilder.clip_video(
            input_path,
            part_path,
            start_seconds,
            duration_seconds,
            fast_seek=self._fast_seek,
        )
        cmd[0] = self._ffmpeg_binary

        logger.info(
            "clipping_segment",
            input_path=str(input_path),
            output_path=str(output_path),
            start_seconds=start_seconds,
            duration_seconds=duration_seconds,
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
                f"切片失败: {exc}",
                details={
                    "input_path": str(input_path),
                    "start_seconds": start_seconds,
                    "duration_seconds": duration_seconds,
                    "error": str(exc),
                },
            ) from exc

        if result.returncode != 0:
            if part_path.exists():
                part_path.unlink(missing_ok=True)
            raise FFmpegError(
                FFMPEG_CONVERT_FAILED,
                f"切片退出码非零: {result.returncode}",
                details={
                    "input_path": str(input_path),
                    "returncode": result.returncode,
                    "stderr": result.stderr,
                },
            )

        if not part_path.exists():
            raise FFmpegError(
                FFMPEG_CONVERT_FAILED,
                f"切片完成但未找到临时文件: {part_path}",
                details={"input_path": str(input_path), "part_path": str(part_path)},
            )

        part_path.rename(output_path)
        logger.info("clip_segment_finished", output_path=str(output_path))

        return output_path

    def clip_parts(
        self,
        input_path: Path,
        output_path: Path,
        parts: list[tuple[float, float]],
        cancel_check: Callable[[], bool] | None = None,
    ) -> Path:
        """从视频中截取多个片段并拼接。

        分别截取每个片段，生成 concat 列表文件，拼接后清理临时文件。

        Args:
            input_path: 输入视频文件路径。
            output_path: 输出拼接文件路径。
            parts: 片段列表，每个元素为 (起始秒, 时长秒)。
            cancel_check: 可选的取消检查回调。

        Returns:
            拼接后的文件路径。

        Raises:
            FFmpegError: 切片或拼接失败时抛出。
        """
        if not parts:
            raise FFmpegError(
                FFMPEG_CONVERT_FAILED,
                "片段列表为空",
                details={"input_path": str(input_path)},
            )

        logger.info(
            "clipping_parts",
            input_path=str(input_path),
            output_path=str(output_path),
            num_parts=len(parts),
        )

        temp_dir = output_path.parent
        temp_clips: list[Path] = []

        try:
            # 1. 逐段截取
            for idx, (start, duration) in enumerate(parts):
                if cancel_check and cancel_check():
                    raise FFmpegError(
                        FFMPEG_CONVERT_FAILED,
                        "切片被取消",
                        details={"input_path": str(input_path)},
                    )

                clip_path = temp_dir / f"{output_path.stem}_part{idx:04d}{output_path.suffix}"
                self.clip_segment(
                    input_path,
                    clip_path,
                    start,
                    duration,
                    cancel_check=cancel_check,
                )
                temp_clips.append(clip_path)

            # 2. 生成 concat 列表文件
            concat_list_path = temp_dir / f"{output_path.stem}_concat.txt"
            concat_lines: list[str] = []
            for clip_path in temp_clips:
                concat_lines.append(self._concat_file_line(clip_path))
            concat_list_path.write_text("\n".join(concat_lines), encoding="utf-8")

            # 3. 拼接
            concat_cmd = FFmpegCommandBuilder.concat_videos(concat_list_path, output_path)
            concat_cmd[0] = self._ffmpeg_binary

            try:
                if cancel_check is not None:
                    result = run_long_command(concat_cmd, cancel_check=cancel_check)
                else:
                    result = run_command(concat_cmd)
            except Exception as exc:
                raise FFmpegError(
                    FFMPEG_CONVERT_FAILED,
                    f"拼接失败: {exc}",
                    details={"input_path": str(input_path), "error": str(exc)},
                ) from exc

            if result.returncode != 0:
                raise FFmpegError(
                    FFMPEG_CONVERT_FAILED,
                    f"拼接退出码非零: {result.returncode}",
                    details={
                        "input_path": str(input_path),
                        "returncode": result.returncode,
                        "stderr": result.stderr,
                    },
                )

            logger.info("clip_parts_finished", output_path=str(output_path))
            return output_path

        finally:
            # 4. 清理临时文件
            for clip_path in temp_clips:
                clip_path.unlink(missing_ok=True)
            concat_list_path = temp_dir / f"{output_path.stem}_concat.txt"
            concat_list_path.unlink(missing_ok=True)

    @staticmethod
    def _concat_file_line(clip_path: Path) -> str:
        """Return a concat demuxer file line that is stable for relative output dirs."""
        escaped = clip_path.resolve().as_posix().replace("'", r"'\''")
        return f"file '{escaped}'"
