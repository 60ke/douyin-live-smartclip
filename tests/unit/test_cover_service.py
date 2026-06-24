from __future__ import annotations

import json
import subprocess
from pathlib import Path

from PIL import Image

from liveclip.services.cover_service import ClipCoverRenderer


def test_render_cover_image_matches_video_resolution(tmp_path: Path) -> None:
    source = tmp_path / "source.png"
    Image.new("RGB", (320, 180), "#1f6feb").save(source)
    output = tmp_path / "cover.png"
    font_path = Path("/Users/k/Downloads/Noto_Sans_SC/static/NotoSansSC-Bold.ttf")

    renderer = ClipCoverRenderer(font_path=font_path)
    renderer.render_cover_image(
        output_path=output,
        title="高转化直播切片封面测试",
        width=360,
        height=640,
        source_image_path=source,
    )

    assert output.exists()
    with Image.open(output) as image:
        assert image.size == (360, 640)


def test_render_cover_uses_first_frame_under_transparent_template_frame(tmp_path: Path) -> None:
    template = tmp_path / "template.png"
    frame = tmp_path / "first_frame.png"
    output = tmp_path / "cover.png"
    Image.new("RGBA", (360, 640), (255, 0, 0, 255)).save(template)
    Image.new("RGB", (360, 640), (0, 255, 0)).save(frame)

    renderer = ClipCoverRenderer()
    renderer.render_cover_image(
        output_path=output,
        title="直播间爆款片段",
        width=360,
        height=640,
        source_image_path=template,
        frame_image_path=frame,
    )

    with Image.open(output) as image:
        assert image.getpixel((180, 360)) == (0, 255, 0)


def test_render_generates_cover_intro_and_final_video_paths(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake-video")
    source = tmp_path / "source.png"
    Image.new("RGB", (120, 180), "#2dd4bf").save(source)
    commands: list[list[str]] = []

    def fake_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        if cmd[0] == "ffprobe":
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=json.dumps(
                    {
                        "streams": [{"width": 720, "height": 1280}],
                        "format": {"duration": "12.5"},
                    }
                ),
                stderr="",
            )
        output_path = Path(cmd[-1])
        if output_path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            Image.new("RGB", (320, 180), "#111827").save(output_path)
        else:
            output_path.write_bytes(b"fake-output")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    renderer = ClipCoverRenderer(command_runner=fake_runner)

    result = renderer.render(
        clip_id=3,
        video_path=video,
        output_dir=tmp_path / "covers",
        title="直播间爆款片段",
        source_image_path=source,
        cover_duration_seconds=1.0,
    )

    assert result.cover_image_path.name == "clip_000003_cover.png"
    assert result.cover_intro_video_path.name == "clip_000003_cover_intro.mp4"
    assert result.final_video_path.name == "clip_000003_final.mp4"
    assert result.highlight_video_path is None
    assert result.highlight_enabled is False
    assert result.width == 720
    assert result.height == 1280
    assert result.duration_seconds == 13.5
    assert result.cover_image_path.exists()
    assert result.cover_intro_video_path.exists()
    assert result.final_video_path.exists()
    assert commands[0][0] == "ffprobe"
    assert commands[1][0] == "ffmpeg"
    assert commands[2][0] == "ffmpeg"
    first_frame_cmd = commands[1]
    assert "-frames:v" in first_frame_cmd
    final_cmd = commands[3]
    assert "-filter_complex" in final_cmd
    assert "concat=n=2:v=1:a=1" in " ".join(final_cmd)
    assert str(result.cover_intro_video_path) in final_cmd
    assert str(video) in final_cmd


def test_render_prepends_highlight_intro_when_enabled(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake-video")
    commands: list[list[str]] = []

    def fake_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        if cmd[0] == "ffprobe":
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=json.dumps(
                    {
                        "streams": [{"width": 720, "height": 1280}],
                        "format": {"duration": "120.0"},
                    }
                ),
                stderr="",
            )
        output_path = Path(cmd[-1])
        if output_path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            Image.new("RGB", (320, 180), "#111827").save(output_path)
        else:
            output_path.write_bytes(b"fake-output")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    renderer = ClipCoverRenderer(command_runner=fake_runner)

    result = renderer.render(
        clip_id=8,
        video_path=video,
        output_dir=tmp_path / "covers",
        title="直播间爆款片段",
        cover_duration_seconds=1.0,
        highlight_enabled=True,
        highlight_start_seconds=115.0,
        highlight_end_seconds=120.0,
    )

    assert result.highlight_enabled is True
    assert result.highlight_video_path is not None
    assert result.highlight_video_path.name == "clip_000008_highlight_intro.mp4"
    assert result.highlight_start_seconds == 115.0
    assert result.highlight_end_seconds == 120.0
    assert result.highlight_confidence == 1.0
    assert result.duration_seconds == 126.0
    assert result.highlight_video_path.exists()
    assert commands[0][0] == "ffprobe"
    assert len([cmd for cmd in commands if cmd[0] == "ffmpeg"]) == 4
    highlight_cmd = commands[3]
    assert "-ss" in highlight_cmd
    assert "115.000" in highlight_cmd
    final_cmd = commands[4]
    assert "-filter_complex" in final_cmd
    assert "concat=n=3:v=1:a=1" in " ".join(final_cmd)
    assert str(result.cover_intro_video_path) in final_cmd
    assert str(result.highlight_video_path) in final_cmd
    assert str(video) in final_cmd
