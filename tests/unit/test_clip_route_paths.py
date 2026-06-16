from __future__ import annotations

from pathlib import Path

import pytest

from liveclip.api.routes.clips import _resolve_existing_path


def test_resolve_existing_path_accepts_path_prefixed_with_base_dir_name(tmp_path: Path) -> None:
    base_dir = tmp_path / "data"
    clip_path = base_dir / "room_1" / "run_1" / "clips" / "final" / "clip.mp4"
    clip_path.parent.mkdir(parents=True)
    clip_path.write_bytes(b"video")

    resolved = _resolve_existing_path(
        "data/room_1/run_1/clips/final/clip.mp4",
        base_dir=base_dir,
    )

    assert resolved == clip_path.resolve()


def test_resolve_existing_path_accepts_path_relative_to_base_dir(tmp_path: Path) -> None:
    base_dir = tmp_path / "data"
    clip_path = base_dir / "room_1" / "run_1" / "clips" / "final" / "clip.mp4"
    clip_path.parent.mkdir(parents=True)
    clip_path.write_bytes(b"video")

    resolved = _resolve_existing_path(
        "room_1/run_1/clips/final/clip.mp4",
        base_dir=base_dir,
    )

    assert resolved == clip_path.resolve()


def test_resolve_existing_path_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="文件不存在"):
        _resolve_existing_path("data/missing.mp4", base_dir=tmp_path / "data")
