"""Helpers for FFmpeg temporary output files."""

from __future__ import annotations

from pathlib import Path


def temporary_output_path(output_path: Path) -> Path:
    """Return a temporary path that keeps the media suffix visible to FFmpeg."""
    if output_path.suffix:
        return output_path.with_name(f"{output_path.stem}.part{output_path.suffix}")
    return output_path.with_name(f"{output_path.name}.part")
