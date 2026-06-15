"""FFmpeg 命令行构建器。"""

from __future__ import annotations

from pathlib import Path


class FFmpegCommandBuilder:
    """构建 FFmpeg/FFprobe 命令行参数。"""

    @staticmethod
    def record_stream_to_ts(
        stream_url: str,
        output_path: Path,
        max_duration_seconds: int | None = None,
        headers: str | None = None,
        http_proxy: str | None = None,
        user_agent: str = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        ),
    ) -> list[str]:
        """构建直播流录制为 TS 的 ffmpeg 命令。"""
        cmd = [
            "ffmpeg",
            "-y",
            "-v",
            "verbose",
            "-rw_timeout",
            "30000000",
            "-loglevel",
            "error",
            "-hide_banner",
            "-user_agent",
            user_agent,
            "-protocol_whitelist",
            "rtmp,crypto,file,http,https,tcp,tls,udp,rtp,httpproxy",
            "-thread_queue_size",
            "1024",
            "-analyzeduration",
            "20000000",
            "-probesize",
            "10000000",
            "-fflags",
            "+discardcorrupt",
            "-reconnect_delay_max",
            "60",
            "-reconnect_streamed",
            "1",
            "-reconnect_at_eof",
            "1",
            "-re",
            "-i",
            stream_url,
            "-bufsize",
            "8000k",
            "-sn",
            "-dn",
            "-max_muxing_queue_size",
            "1024",
            "-correct_ts_overflow",
            "1",
            "-avoid_negative_ts",
            "1",
        ]
        if headers:
            user_agent_value_index = cmd.index(user_agent)
            cmd[user_agent_value_index + 1 : user_agent_value_index + 1] = ["-headers", headers]
        if http_proxy:
            cmd[1:1] = ["-http_proxy", http_proxy]
        if max_duration_seconds and max_duration_seconds > 0:
            cmd.extend(["-t", str(max_duration_seconds)])
        cmd.extend(["-map", "0", "-c", "copy", "-f", "mpegts", str(output_path)])
        return cmd

    @staticmethod
    def convert_ts_to_mp4(
        input_path: Path,
        output_path: Path,
        encoder: str = "libx264",
        preset: str = "veryfast",
        crf: int = 23,
        reencode_h264: bool = False,
    ) -> list[str]:
        """构建 TS 转 MP4 的 ffmpeg 命令。

        Args:
            input_path: 输入 TS 文件路径。
            output_path: 输出 MP4 文件路径。
            encoder: 视频编码器，默认 libx264。
            preset: 编码预设，默认 veryfast。
            crf: 恒定质量因子，默认 18。

        Returns:
            ffmpeg 命令参数列表。
        """
        if reencode_h264:
            return [
                "ffmpeg",
                "-y",
                "-i",
                str(input_path),
                "-c:v",
                encoder,
                "-preset",
                preset,
                "-crf",
                str(crf),
                "-vf",
                "format=yuv420p",
                "-c:a",
                "copy",
                "-f",
                "mp4",
                str(output_path),
            ]
        return [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-f",
            "mp4",
            str(output_path),
        ]

    @staticmethod
    def clip_video(
        input_path: Path,
        output_path: Path,
        start_seconds: float,
        duration_seconds: float,
        encoder: str = "libx264",
        preset: str = "veryfast",
        crf: int = 18,
        fast_seek: bool = False,
    ) -> list[str]:
        """构建视频切片的 ffmpeg 命令。

        Args:
            input_path: 输入视频文件路径。
            output_path: 输出切片文件路径。
            start_seconds: 起始时间（秒）。
            duration_seconds: 切片时长（秒）。
            encoder: 视频编码器，默认 libx264。
            preset: 编码预设，默认 veryfast。
            crf: 恒定质量因子，默认 18。

        Returns:
            ffmpeg 命令参数列表。
        """
        seek_args = ["-ss", str(start_seconds)]
        input_args = ["-i", str(input_path)]
        if fast_seek:
            seek_and_input_args = [*seek_args, *input_args]
        else:
            seek_and_input_args = [*input_args, *seek_args]

        return [
            "ffmpeg",
            "-y",
            *seek_and_input_args,
            "-t",
            str(duration_seconds),
            "-map",
            "0:v:0?",
            "-map",
            "0:a:0?",
            "-c:v",
            encoder,
            "-preset",
            preset,
            "-crf",
            str(crf),
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-avoid_negative_ts",
            "make_zero",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

    @staticmethod
    def concat_videos(
        concat_list_path: Path,
        output_path: Path,
    ) -> list[str]:
        """构建视频拼接的 ffmpeg 命令。

        Args:
            concat_list_path: concat 列表文件路径。
            output_path: 输出拼接文件路径。

        Returns:
            ffmpeg 命令参数列表。
        """
        return [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list_path),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

    @staticmethod
    def probe_duration(file_path: Path) -> list[str]:
        """构建获取视频时长的 ffprobe 命令。

        Args:
            file_path: 视频文件路径。

        Returns:
            ffprobe 命令参数列表。
        """
        return [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(file_path),
        ]
