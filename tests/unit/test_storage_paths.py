from __future__ import annotations

from pathlib import Path

from liveclip.storage.paths import (
    RunPaths,
    ensure_unique_filename,
    sanitize_filename,
)


class TestRunPaths:
    """Tests for RunPaths directory structure."""

    def test_room_dir(self, tmp_path: Path) -> None:
        rp = RunPaths(tmp_path, room_id=1, run_id=42)
        assert rp.room_dir == tmp_path / "room_1"

    def test_run_dir(self, tmp_path: Path) -> None:
        rp = RunPaths(tmp_path, room_id=1, run_id=42)
        assert rp.run_dir == tmp_path / "room_1" / "run_42"

    def test_subdirectories(self, tmp_path: Path) -> None:
        rp = RunPaths(tmp_path, room_id=1, run_id=42)
        assert rp.raw_dir == rp.run_dir / "raw"
        assert rp.media_dir == rp.run_dir / "media"
        assert rp.subtitles_dir == rp.run_dir / "subtitles"
        assert rp.preprocess_dir == rp.run_dir / "preprocess"
        assert rp.plans_dir == rp.run_dir / "plans"
        assert rp.clips_dir == rp.run_dir / "clips"
        assert rp.logs_dir == rp.run_dir / "logs"

    def test_file_paths(self, tmp_path: Path) -> None:
        rp = RunPaths(tmp_path, room_id=1, run_id=42)
        assert rp.raw_ts_path.name == "run_42.ts"
        assert rp.mp4_path.name == "run_42.mp4"
        assert rp.srt_path.name == "run_42.srt"
        assert rp.combined_srt_path.name == "run_combine.srt"
        assert rp.combined_srt_path != rp.srt_path

    def test_ensure_all_dirs(self, tmp_path: Path) -> None:
        rp = RunPaths(tmp_path, room_id=1, run_id=42)
        rp.ensure_all_dirs()
        assert rp.raw_dir.exists()
        assert rp.media_dir.exists()
        assert rp.subtitles_dir.exists()
        assert rp.preprocess_dir.exists()
        assert rp.plans_dir.exists()
        assert rp.clips_dir.exists()
        assert rp.logs_dir.exists()


class TestSanitizeFilename:
    """Tests for sanitize_filename function."""

    def test_normal_name(self) -> None:
        assert sanitize_filename("hello world") == "hello world"

    def test_illegal_chars_removed(self) -> None:
        result = sanitize_filename('test<>:"/\\|?*file')
        assert result == "testfile"

    def test_empty_fallback(self) -> None:
        assert sanitize_filename("") == "未命名片段"

    def test_long_name_truncated(self) -> None:
        result = sanitize_filename("a" * 200)
        assert len(result) <= 80

    def test_whitespace_collapsed(self) -> None:
        result = sanitize_filename("hello   world")
        assert result == "hello world"


class TestEnsureUniqueFilename:
    """Tests for ensure_unique_filename function."""

    def test_no_collision(self, tmp_path: Path) -> None:
        result = ensure_unique_filename(tmp_path, "test", ".txt")
        assert result == tmp_path / "test.txt"

    def test_with_collision(self, tmp_path: Path) -> None:
        (tmp_path / "test.txt").write_text("existing")
        result = ensure_unique_filename(tmp_path, "test", ".txt")
        assert result == tmp_path / "test-2.txt"

    def test_multiple_collisions(self, tmp_path: Path) -> None:
        (tmp_path / "test.txt").write_text("1")
        (tmp_path / "test-2.txt").write_text("2")
        result = ensure_unique_filename(tmp_path, "test", ".txt")
        assert result == tmp_path / "test-3.txt"
