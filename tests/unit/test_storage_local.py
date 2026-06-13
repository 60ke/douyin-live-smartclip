from __future__ import annotations

from pathlib import Path

from liveclip.storage.local import LocalStorage


class TestLocalStorage:
    """Tests for LocalStorage class."""

    def test_write_and_read_text(self, tmp_path: Path) -> None:
        path = tmp_path / "test.txt"
        LocalStorage.write_text(path, "你好世界")
        assert LocalStorage.read_text(path) == "你好世界"

    def test_write_and_read_json(self, tmp_path: Path) -> None:
        path = tmp_path / "test.json"
        data = {"key": "value", "count": 42}
        LocalStorage.write_json(path, data)
        result = LocalStorage.read_json(path)
        assert result["key"] == "value"
        assert result["count"] == 42

    def test_atomic_write_creates_file(self, tmp_path: Path) -> None:
        path = tmp_path / "atomic.txt"
        LocalStorage.write_text(path, "atomic content")
        assert path.exists()

    def test_atomic_write_no_partial(self, tmp_path: Path) -> None:
        path = tmp_path / "clean.txt"
        LocalStorage.write_text(path, "clean write")
        tmp_files = list(tmp_path.glob("*.tmp"))
        part_files = list(tmp_path.glob("*.part"))
        assert len(tmp_files) == 0
        assert len(part_files) == 0

    def test_exists(self, tmp_path: Path) -> None:
        path = tmp_path / "exists.txt"
        assert LocalStorage.exists(path) is False
        LocalStorage.write_text(path, "content")
        assert LocalStorage.exists(path) is True

    def test_file_size(self, tmp_path: Path) -> None:
        path = tmp_path / "sized.txt"
        LocalStorage.write_text(path, "hello")
        assert LocalStorage.file_size(path) > 0

    def test_ensure_dir(self, tmp_path: Path) -> None:
        dir_path = tmp_path / "new" / "nested" / "dir"
        result = LocalStorage.ensure_dir(dir_path)
        assert dir_path.exists()
        assert result == dir_path

    def test_write_creates_parent_dirs(self, tmp_path: Path) -> None:
        path = tmp_path / "sub" / "dir" / "test.txt"
        LocalStorage.write_text(path, "nested")
        assert path.exists()
        assert LocalStorage.read_text(path) == "nested"
