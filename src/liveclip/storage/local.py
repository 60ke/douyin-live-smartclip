from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


class LocalStorage:
    """Local filesystem storage with atomic writes."""

    @staticmethod
    def save_file(source: Path, dest: Path) -> Path:
        """Copy *source* to *dest* atomically (write to ``.part`` then rename).

        Returns:
            The final destination path.
        """
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_suffix(dest.suffix + ".part")
        try:
            part.write_bytes(source.read_bytes())
            part.replace(dest)
        except BaseException:
            if part.exists():
                part.unlink()
            raise
        return dest

    @staticmethod
    def read_text(path: Path) -> str:
        """Read and return the text content of *path*."""
        return path.read_text(encoding="utf-8")

    @staticmethod
    def write_text(path: Path, content: str) -> None:
        """Write *content* to *path* atomically."""
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=path.parent,
            prefix=path.stem + ".tmp",
            suffix=path.suffix,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    @staticmethod
    def write_json(path: Path, data: dict[str, Any]) -> None:
        """Serialize *data* as JSON and write atomically to *path*."""
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(data, ensure_ascii=False, indent=2)
        fd, tmp = tempfile.mkstemp(
            dir=path.parent,
            prefix=path.stem + ".tmp",
            suffix=path.suffix,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmp, path)
        except BaseException:
            if os.path.exists(tmp):
                os.unlink(tmp)
            raise

    @staticmethod
    def read_json(path: Path) -> dict[str, Any]:
        """Read and deserialize JSON from *path*."""
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            msg = f"JSON file must contain an object: {path}"
            raise TypeError(msg)
        return data

    @staticmethod
    def exists(path: Path) -> bool:
        """Return ``True`` if *path* exists on disk."""
        return path.exists()

    @staticmethod
    def file_size(path: Path) -> int:
        """Return the size of *path* in bytes."""
        return path.stat().st_size

    @staticmethod
    def ensure_dir(path: Path) -> Path:
        """Create *path* (and parents) if it does not exist, then return it."""
        path.mkdir(parents=True, exist_ok=True)
        return path
