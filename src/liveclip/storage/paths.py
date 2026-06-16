from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path


class RunPaths:
    """Compute all filesystem paths for a single pipeline run.

    All properties return :class:`Path` objects rooted under the run directory.
    """

    def __init__(
        self,
        base_dir: Path,
        room_id: int,
        run_id: int,
        room_name: str | None = None,
        recording_started_at: datetime | None = None,
    ) -> None:
        self.base_dir = base_dir
        self.room_id = room_id
        self.run_id = run_id
        self.room_name = room_name
        self.recording_started_at = recording_started_at

    # -- directories -----------------------------------------------------------

    @property
    def room_dir(self) -> Path:
        return get_room_dir(self.base_dir, self.room_id)

    @property
    def run_dir(self) -> Path:
        return get_run_dir(self.base_dir, self.room_id, self.run_id)

    @property
    def raw_dir(self) -> Path:
        return self.run_dir / "raw"

    @property
    def media_dir(self) -> Path:
        return self.run_dir / "media"

    @property
    def subtitles_dir(self) -> Path:
        return self.run_dir / "subtitles"

    @property
    def preprocess_dir(self) -> Path:
        return self.run_dir / "preprocess"

    @property
    def plans_dir(self) -> Path:
        return self.run_dir / "plans"

    @property
    def clips_dir(self) -> Path:
        return self.run_dir / "clips"

    @property
    def logs_dir(self) -> Path:
        return self.run_dir / "logs"

    # -- specific files --------------------------------------------------------

    @property
    def _recording_stem(self) -> str:
        """Generate a human-readable recording file stem.

        Pattern: ``<room_name>_<YYYYMMDDhhmm>_run_<run_id>`` when room metadata
        is available, otherwise falls back to ``run_<run_id>``.
        """
        if self.room_name and self.recording_started_at is not None:
            sanitized = sanitize_filename(self.room_name, max_length=80)
            timestamp = self.recording_started_at.strftime("%Y%m%d%H%M")
            return f"{sanitized}_{timestamp}_run_{self.run_id}"
        return f"run_{self.run_id}"

    @property
    def raw_ts_path(self) -> Path:
        return self.raw_dir / f"{self._recording_stem}.ts"

    @property
    def mp4_path(self) -> Path:
        return self.media_dir / f"{self._recording_stem}.mp4"

    @property
    def srt_path(self) -> Path:
        return self.subtitles_dir / f"{self._recording_stem}.srt"

    @property
    def combined_srt_path(self) -> Path:
        return self.subtitles_dir / "run_combine.srt"

    @property
    def words_json_path(self) -> Path:
        return self.preprocess_dir / "words.json"

    @property
    def sentences_json_path(self) -> Path:
        return self.preprocess_dir / "sentences.json"

    @property
    def raw_llm_response_path(self) -> Path:
        return self.plans_dir / "raw_llm_response.json"

    @property
    def normalized_plan_path(self) -> Path:
        return self.plans_dir / "normalized_plan.json"

    @property
    def validated_plan_path(self) -> Path:
        return self.plans_dir / "validated_plan.json"

    @property
    def boundary_report_path(self) -> Path:
        return self.plans_dir / "boundary_report.json"

    @property
    def summary_path(self) -> Path:
        return self.run_dir / "summary.json"

    @property
    def run_log_path(self) -> Path:
        return self.logs_dir / "run.log"

    # -- helpers ---------------------------------------------------------------

    def ensure_all_dirs(self) -> None:
        """Create every directory this object references."""
        for d in (
            self.raw_dir,
            self.media_dir,
            self.subtitles_dir,
            self.preprocess_dir,
            self.plans_dir,
            self.clips_dir,
            self.logs_dir,
        ):
            d.mkdir(parents=True, exist_ok=True)


def get_room_dir(base_dir: Path, room_id: int) -> Path:
    """Return the directory for a given room."""
    return base_dir / f"room_{room_id}"


def get_run_dir(base_dir: Path, room_id: int, run_id: int) -> Path:
    """Return the directory for a specific run under a room."""
    return get_room_dir(base_dir, room_id) / f"run_{run_id}"


def get_run_paths(
    base_dir: Path,
    room_id: int,
    run_id: int,
    room_name: str | None = None,
    recording_started_at: datetime | None = None,
) -> RunPaths:
    """Construct a :class:`RunPaths` for the given run."""
    return RunPaths(base_dir, room_id, run_id, room_name, recording_started_at)


_ILLEGAL_CHARS_RE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WHITESPACE_RE = re.compile(r"\s+")


def sanitize_filename(title: str, max_length: int = 80) -> str:
    """Strip illegal characters and trim *title* for use as a filename.

    Falls back to ``"未命名片段"`` when the result would be empty.
    """
    cleaned = _ILLEGAL_CHARS_RE.sub("", title)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    if not cleaned:
        cleaned = "未命名片段"
    return cleaned[:max_length]


def ensure_unique_filename(directory: Path, stem: str, suffix: str) -> Path:
    """Return a unique file path, appending ``-2``, ``-3``, ... on collision.

    Args:
        directory: Target directory.
        stem: Filename stem (without extension).
        suffix: File extension including the leading dot.

    Returns:
        A path that does not yet exist in *directory*.
    """
    candidate = directory / f"{stem}{suffix}"
    if not candidate.exists():
        return candidate

    counter = 2
    while True:
        candidate = directory / f"{stem}-{counter}{suffix}"
        if not candidate.exists():
            return candidate
        counter += 1
