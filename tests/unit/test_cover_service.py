from __future__ import annotations

import json
import subprocess
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image

from liveclip.services.cover_service import ClipCoverRenderer


class FakeAIImageClient:
    def __init__(self, color: str = "#22c55e") -> None:
        self.color = color
        self.calls: list[dict[str, object]] = []

    def edit(self, *, images: list[object], prompt: str, size: str | None = None) -> bytes:
        self.calls.append({"images": images, "prompt": prompt, "size": size})
        buffer = BytesIO()
        Image.new("RGB", (360, 640), self.color).save(buffer, format="PNG")
        return buffer.getvalue()


class FailingAIImageClient:
    def __init__(self) -> None:
        self.calls = 0

    def edit(self, *, images: list[object], prompt: str, size: str | None = None) -> bytes:
        self.calls += 1
        raise RuntimeError("image service unavailable")


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

    renderer = ClipCoverRenderer(ai_cover_client=FakeAIImageClient())
    renderer.render_cover_image(
        output_path=output,
        title="直播间爆款片段",
        width=360,
        height=640,
        source_image_path=template,
        frame_image_path=frame,
    )

    with Image.open(output) as image:
        assert image.getpixel((180, 360)) == (34, 197, 94)


def test_render_cover_skips_black_video_start_frame(tmp_path: Path) -> None:
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake-video")
    source = tmp_path / "template.png"
    Image.new("RGBA", (360, 640), (255, 0, 0, 255)).save(source)
    commands: list[list[str]] = []

    def fake_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        if cmd[0] == "ffprobe":
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=json.dumps(
                    {
                        "streams": [{"width": 360, "height": 640}],
                        "format": {"duration": "12.5"},
                    }
                ),
                stderr="",
            )
        output_path = Path(cmd[-1])
        if output_path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            color = "#000000" if "0.000" in cmd else "#22c55e"
            Image.new("RGB", (360, 640), color).save(output_path)
        else:
            output_path.write_bytes(b"fake-output")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    ai_client = FakeAIImageClient()
    renderer = ClipCoverRenderer(command_runner=fake_runner, ai_cover_client=ai_client)

    result = renderer.render(
        clip_id=4,
        video_path=video,
        output_dir=tmp_path / "covers",
        title="直播间爆款片段",
        source_image_path=source,
    )

    assert result.cover_image_path.exists()
    with Image.open(result.cover_image_path) as image:
        r, g, b = image.getpixel((180, 360))
        assert abs(r - 34) <= 2
        assert abs(g - 197) <= 2
        assert abs(b - 94) <= 2
    assert len(ai_client.calls) == 1


def test_render_cover_extracts_frame_from_non_subtitle_video(tmp_path: Path) -> None:
    hard_video = tmp_path / "clip_hard.mp4"
    raw_video = tmp_path / "clip_raw.mp4"
    hard_video.write_bytes(b"fake-hard-video")
    raw_video.write_bytes(b"fake-raw-video")
    commands: list[list[str]] = []

    def fake_runner(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        commands.append(cmd)
        if cmd[0] == "ffprobe":
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=json.dumps(
                    {
                        "streams": [{"width": 360, "height": 640}],
                        "format": {"duration": "12.5"},
                    }
                ),
                stderr="",
            )
        output_path = Path(cmd[-1])
        if output_path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            Image.new("RGB", (360, 640), "#22c55e").save(output_path)
        else:
            output_path.write_bytes(b"fake-output")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    renderer = ClipCoverRenderer(command_runner=fake_runner, ai_cover_client=FakeAIImageClient())

    renderer.render(
        clip_id=5,
        video_path=hard_video,
        output_dir=tmp_path / "covers",
        title="直播间爆款片段",
        cover_frame_video_path=raw_video,
    )

    frame_extract_cmd = next(
        cmd for cmd in commands if "-frames:v" in cmd and str(cmd[-1]).endswith(".jpg")
    )
    assert str(raw_video) in frame_extract_cmd
    assert str(hard_video) not in frame_extract_cmd


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

    renderer = ClipCoverRenderer(command_runner=fake_runner, ai_cover_client=FakeAIImageClient())

    result = renderer.render(
        clip_id=3,
        video_path=video,
        output_dir=tmp_path / "covers",
        title="直播间爆款片段",
        source_image_path=source,
    )

    assert result.cover_image_path.name == "clip_000003_cover.png"
    assert result.cover_intro_video_path.name == "clip_000003_cover_intro.mp4"
    assert result.final_video_path.name == "clip_000003_final.mp4"
    assert result.highlight_video_path is None
    assert result.highlight_enabled is False
    assert result.width == 720
    assert result.height == 1280
    assert result.duration_seconds == 12.5 + 1 / 30
    assert result.cover_image_path.exists()
    assert result.cover_intro_video_path.exists()
    assert result.final_video_path.exists()
    assert commands[0][0] == "ffprobe"
    assert commands[1][0] == "ffmpeg"
    first_frame_cmd = next(
        cmd for cmd in commands if "-frames:v" in cmd and str(cmd[-1]).endswith(".jpg")
    )
    assert "-frames:v" in first_frame_cmd
    cover_intro_cmd = next(cmd for cmd in commands if str(result.cover_intro_video_path) in cmd)
    assert "-framerate" in cover_intro_cmd
    assert "0.033333" in cover_intro_cmd
    assert cover_intro_cmd.count("-t") == 2
    assert "-frames:v" in cover_intro_cmd
    final_cmd = commands[-1]
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

    renderer = ClipCoverRenderer(command_runner=fake_runner, ai_cover_client=FakeAIImageClient())

    result = renderer.render(
        clip_id=8,
        video_path=video,
        output_dir=tmp_path / "covers",
        title="直播间爆款片段",
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
    assert result.duration_seconds == 125.0 + 1 / 30
    assert result.highlight_video_path.exists()
    assert commands[0][0] == "ffprobe"
    assert len([cmd for cmd in commands if cmd[0] == "ffmpeg"]) == 6
    highlight_cmd = next(cmd for cmd in commands if str(result.highlight_video_path) in cmd)
    assert "-ss" in highlight_cmd
    assert "115.000" in highlight_cmd
    final_cmd = commands[-1]
    assert "-filter_complex" in final_cmd
    assert "concat=n=3:v=1:a=1" in " ".join(final_cmd)
    assert str(result.cover_intro_video_path) in final_cmd
    assert str(result.highlight_video_path) in final_cmd
    assert str(video) in final_cmd


def test_render_cover_ai_failure_raises_without_local_fallback(tmp_path: Path) -> None:
    frame = tmp_path / "first_frame.png"
    output = tmp_path / "cover.png"
    Image.new("RGB", (360, 640), "#22c55e").save(frame)

    ai_client = FailingAIImageClient()
    renderer = ClipCoverRenderer(ai_cover_client=ai_client, ai_cover_retry_delay_seconds=0)

    with pytest.raises(RuntimeError, match="AI 封面生成失败"):
        renderer.render_cover_image(
            output_path=output,
            title="直播间爆款片段",
            width=360,
            height=640,
            frame_image_path=frame,
        )

    assert not output.exists()
    assert ai_client.calls == 3
