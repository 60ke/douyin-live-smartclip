from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

from liveclip.services.clip_post_process_service import (
    ClipPostProcessOptions,
    ClipPostProcessService,
)


def test_cover_failure_keeps_hard_subtitle_video(tmp_path: Path, monkeypatch) -> None:
    clips_dir = tmp_path / "clips"
    clips_dir.mkdir()
    clip = clips_dir / "001_demo.mp4"
    subtitle = clips_dir / "001_demo.srt"
    clip.write_bytes(b"raw-video")
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nhello\n", encoding="utf-8")

    class FakeHardSubtitleRenderer:
        def __init__(self, *, ffmpeg_binary: str = "ffmpeg") -> None:
            self.ffmpeg_binary = ffmpeg_binary

        def render(self, *, video_path: Path, subtitle_path: Path, output_path: Path):
            output_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(video_path, output_path)
            ass_path = output_path.with_suffix(".ass")
            ass_path.write_text("[Script Info]\n", encoding="utf-8")
            return SimpleNamespace(output_video_path=output_path, ass_path=ass_path)

    class FailingCoverRenderer:
        def __init__(
            self,
            *,
            ffmpeg_binary: str = "ffmpeg",
            ffprobe_binary: str = "ffprobe",
        ) -> None:
            self.ffmpeg_binary = ffmpeg_binary
            self.ffprobe_binary = ffprobe_binary

        def probe_video(self, video_path: Path):  # noqa: ARG002
            return SimpleNamespace(duration_seconds=1.0)

        def render(self, **kwargs):  # noqa: ANN003
            raise RuntimeError("AI 封面生成失败")

    monkeypatch.setattr(
        "liveclip.services.clip_post_process_service.HardSubtitleRenderer",
        FakeHardSubtitleRenderer,
    )
    monkeypatch.setattr(
        "liveclip.services.clip_post_process_service.ClipCoverRenderer",
        FailingCoverRenderer,
    )

    summary = ClipPostProcessService().process_summary(
        export_summary={
            "clips": [
                {
                    "index": 0,
                    "title": "demo",
                    "clip_path": str(clip),
                    "subtitle_path": str(subtitle),
                }
            ]
        },
        clips_dir=clips_dir,
        options=ClipPostProcessOptions(
            hard_subtitle_enabled=True,
            cover_enabled=True,
        ),
    )

    item = summary["clips"][0]
    assert item["postprocess_status"] == "failed"
    assert item["postprocess_fallback"] == "hard_subtitle"
    assert item["subtitle_mode"] == "hard"
    assert item["final_video_path"] == item["clip_path"]
    assert Path(item["final_video_path"]).parent == clips_dir / "final"
    assert Path(item["final_video_path"]).exists()
    assert Path(item["hard_subtitle_video_path"]).exists()
