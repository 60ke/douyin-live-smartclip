from __future__ import annotations

from pathlib import Path

import pytest

from liveclip.worker.resource_cleanup import (
    CleanupCandidate,
    ResourceCleanupService,
    resolve_run_resource_dir,
)


class _Run:
    resource_status = "AVAILABLE"
    resource_deleted_at = None
    resource_cleanup_error = None


class _Session:
    def __init__(self, run: _Run) -> None:
        self.run = run

    async def get(self, model: object, run_id: int) -> _Run:
        return self.run


def test_resolve_run_resource_dir_targets_expected_run_dir(tmp_path: Path) -> None:
    result = resolve_run_resource_dir(tmp_path, room_id=3, run_id=9)

    assert result == (tmp_path / "room_3" / "run_9").resolve()


@pytest.mark.asyncio
async def test_cleanup_candidate_dry_run_keeps_directory(tmp_path: Path) -> None:
    run_dir = tmp_path / "room_1" / "run_2"
    run_dir.mkdir(parents=True)
    (run_dir / "clip.mp4").write_bytes(b"video")

    run = _Run()
    service = ResourceCleanupService(base_dir=tmp_path, retention_hours=72, dry_run=True)

    cleaned = await service._cleanup_candidate(  # noqa: SLF001 - verify filesystem boundary.
        _Session(run),
        CleanupCandidate(run_id=2, room_id=1),
    )

    assert cleaned is True
    assert run_dir.exists()
    assert run.resource_status == "AVAILABLE"


@pytest.mark.asyncio
async def test_cleanup_candidate_removes_directory_and_marks_run(tmp_path: Path) -> None:
    run_dir = tmp_path / "room_1" / "run_2"
    run_dir.mkdir(parents=True)
    (run_dir / "clip.mp4").write_bytes(b"video")

    run = _Run()
    service = ResourceCleanupService(base_dir=tmp_path, retention_hours=72, dry_run=False)

    cleaned = await service._cleanup_candidate(  # noqa: SLF001 - verify filesystem boundary.
        _Session(run),
        CleanupCandidate(run_id=2, room_id=1),
    )

    assert cleaned is True
    assert not run_dir.exists()
    assert run.resource_status == "CLEANED"
    assert run.resource_deleted_at is not None
