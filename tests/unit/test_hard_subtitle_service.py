from __future__ import annotations

import json
import subprocess
from pathlib import Path

from liveclip.domain.models import SubtitleEntry
from liveclip.services.hard_subtitle_service import HardSubtitleRenderer, _build_ass


def test_hard_subtitle_renderer_writes_ass_and_invokes_ffmpeg(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake-video")
    subtitle = tmp_path / "clip.srt"
    subtitle.write_text(
        "1\n"
        "00:00:01,000 --> 00:00:03,000\n"
        "这是一句用于测试自动换行的较长字幕内容\n",
        encoding="utf-8",
    )
    output = tmp_path / "clip_hard.mp4"
    commands: list[list[str]] = []

    def fake_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        if cmd[0] == "ffprobe":
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=json.dumps(
                    {
                        "streams": [{"width": 544, "height": 960}],
                        "format": {"duration": "12.0"},
                    }
                ),
                stderr="",
            )
        Path(cmd[-1]).write_bytes(b"fake-hard-video")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    result = HardSubtitleRenderer(command_runner=fake_runner).render(
        video_path=video,
        subtitle_path=subtitle,
        output_path=output,
    )

    assert result.output_video_path == output
    assert result.subtitle_count == 1
    assert result.ass_path.exists()
    ass_text = result.ass_path.read_text(encoding="utf-8")
    assert "PlayResX: 544" in ass_text
    assert "PlayResY: 960" in ass_text
    assert "Noto Sans CJK SC" in ass_text
    assert r"\N" in ass_text
    assert output.exists()
    ffmpeg_cmd = commands[1]
    assert ffmpeg_cmd[0] == "ffmpeg"
    assert "-vf" in ffmpeg_cmd
    assert "ass='" in ffmpeg_cmd[ffmpeg_cmd.index("-vf") + 1]


def test_hard_subtitle_style_scales_for_vertical_hd_video() -> None:
    ass_text = _build_ass(
        width=1080,
        height=1920,
        font_name="Noto Sans CJK SC",
        entries=[
            SubtitleEntry(
                index=1,
                start=0,
                end=2,
                text="这是一句用于验证竖屏大字号换行效果的字幕",
            )
        ],
    )

    style_line = next(line for line in ass_text.splitlines() if line.startswith("Style:"))
    fields = style_line.split(",")
    assert int(fields[2]) >= 76
    assert int(fields[16]) >= 6
    assert int(fields[17]) >= 1
    assert int(fields[21]) >= 200
    assert r"\N" in ass_text
