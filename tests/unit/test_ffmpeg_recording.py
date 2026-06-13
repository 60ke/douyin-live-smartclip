from __future__ import annotations

from pathlib import Path
from subprocess import CompletedProcess

from pytest import MonkeyPatch

from liveclip.adapters.douyin import recorder as recorder_module
from liveclip.adapters.douyin.recorder import DouyinRecorder
from liveclip.adapters.ffmpeg.clip import FFmpegClipper
from liveclip.adapters.ffmpeg.command import FFmpegCommandBuilder


def test_record_stream_to_ts_uses_ffmpeg_not_streamlink(tmp_path: Path) -> None:
    output_path = tmp_path / "raw.ts"

    cmd = FFmpegCommandBuilder.record_stream_to_ts(
        "https://example.com/live.m3u8",
        output_path,
        max_duration_seconds=12,
    )

    assert cmd[0] == "ffmpeg"
    assert "streamlink" not in cmd
    assert "-t" in cmd
    assert "12" in cmd
    assert "-f" in cmd
    assert "mpegts" in cmd
    assert cmd[cmd.index("-analyzeduration") + 1] == "20000000"
    assert str(output_path) == cmd[-1]


def test_record_stream_to_ts_accepts_headers_and_proxy(tmp_path: Path) -> None:
    output_path = tmp_path / "raw.ts"

    cmd = FFmpegCommandBuilder.record_stream_to_ts(
        "https://example.com/live.m3u8",
        output_path,
        headers="referer:https://example.com",
        http_proxy="http://127.0.0.1:7890",
    )

    assert cmd[1:3] == ["-http_proxy", "http://127.0.0.1:7890"]
    assert cmd[cmd.index("-headers") + 1] == "referer:https://example.com"
    assert cmd.index("-headers") < cmd.index("-i")


def test_convert_ts_to_mp4_defaults_to_stream_copy_like_old_project(tmp_path: Path) -> None:
    cmd = FFmpegCommandBuilder.convert_ts_to_mp4(tmp_path / "in.ts", tmp_path / "out.mp4")

    assert cmd == [
        "ffmpeg",
        "-y",
        "-i",
        str(tmp_path / "in.ts"),
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        "-f",
        "mp4",
        str(tmp_path / "out.mp4"),
    ]


def test_convert_ts_to_mp4_reencode_matches_old_h264_parameters(tmp_path: Path) -> None:
    cmd = FFmpegCommandBuilder.convert_ts_to_mp4(
        tmp_path / "in.ts",
        tmp_path / "out.mp4",
        reencode_h264=True,
    )

    assert cmd[cmd.index("-crf") + 1] == "23"
    assert cmd[cmd.index("-vf") + 1] == "format=yuv420p"
    assert cmd[cmd.index("-c:a") + 1] == "copy"
    assert "-movflags" not in cmd
    assert cmd[cmd.index("-f") + 1] == "mp4"


def test_clip_video_uses_precise_seek_order_like_old_smartclip(tmp_path: Path) -> None:
    cmd = FFmpegCommandBuilder.clip_video(
        tmp_path / "in.mp4",
        tmp_path / "out.mp4",
        start_seconds=12.5,
        duration_seconds=30.0,
    )

    assert cmd.index("-i") < cmd.index("-ss")
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    assert cmd[cmd.index("-b:a") + 1] == "160k"


def test_clip_video_can_use_fast_input_seek(tmp_path: Path) -> None:
    cmd = FFmpegCommandBuilder.clip_video(
        tmp_path / "in.mp4",
        tmp_path / "out.mp4",
        start_seconds=12.5,
        duration_seconds=30.0,
        fast_seek=True,
    )

    assert cmd.index("-ss") < cmd.index("-i")


def test_concat_videos_keeps_faststart_like_old_smartclip(tmp_path: Path) -> None:
    cmd = FFmpegCommandBuilder.concat_videos(tmp_path / "concat.txt", tmp_path / "out.mp4")

    assert cmd[cmd.index("-movflags") + 1] == "+faststart"


def test_concat_file_line_uses_absolute_escaped_path(tmp_path: Path) -> None:
    clip_path = tmp_path / "clip with 'quote'.mp4"

    line = FFmpegClipper._concat_file_line(clip_path)

    assert line.startswith("file '")
    assert str(tmp_path.resolve()) in line
    assert "with '\\''quote'\\''.mp4" in line


def test_douyin_recorder_writes_part_then_renames(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    output_path = tmp_path / "record.ts"
    captured: dict[str, object] = {}

    def fake_run_long_command(cmd: list[str], **kwargs: object) -> CompletedProcess[str]:
        captured["cmd"] = cmd
        captured["timeout"] = kwargs.get("timeout")
        part_path = Path(cmd[-1])
        part_path.parent.mkdir(parents=True, exist_ok=True)
        part_path.write_bytes(b"ts-data")
        return CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(recorder_module, "run_long_command", fake_run_long_command)

    result = DouyinRecorder().record(
        stream_url="https://example.com/live.m3u8",
        output_path=output_path,
        max_duration=9,
    )

    assert result == output_path
    assert output_path.read_bytes() == b"ts-data"
    assert captured["timeout"] == 69
    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert cmd[0] == "ffmpeg"


def test_douyin_recorder_unlimited_duration_has_no_outer_timeout(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    output_path = tmp_path / "record.ts"
    captured: dict[str, object] = {}

    def fake_run_long_command(cmd: list[str], **kwargs: object) -> CompletedProcess[str]:
        captured["cmd"] = cmd
        captured["timeout"] = kwargs.get("timeout")
        Path(cmd[-1]).write_bytes(b"ts-data")
        return CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(recorder_module, "run_long_command", fake_run_long_command)

    DouyinRecorder().record(
        stream_url="https://example.com/live.m3u8",
        output_path=output_path,
        max_duration=0,
    )

    cmd = captured["cmd"]
    assert isinstance(cmd, list)
    assert "-t" not in cmd
    assert captured["timeout"] is None
