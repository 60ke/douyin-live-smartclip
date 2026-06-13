from __future__ import annotations

from pathlib import Path

from liveclip.adapters.ffmpeg.tempfile import temporary_output_path


def test_temporary_output_path_keeps_media_suffix() -> None:
    assert temporary_output_path(Path("clip.mp4")) == Path("clip.part.mp4")


def test_temporary_output_path_handles_no_suffix() -> None:
    assert temporary_output_path(Path("clip")) == Path("clip.part")
