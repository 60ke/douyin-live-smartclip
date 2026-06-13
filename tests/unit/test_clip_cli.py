from __future__ import annotations

from pathlib import Path

from pytest import MonkeyPatch

from liveclip.cli.commands import clip_cmd
from liveclip.domain.models import ClipSegment, SubtitleEntry


def test_default_clip_jobs_uses_half_cpu_cores(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(clip_cmd.os, "cpu_count", lambda: 4)

    assert clip_cmd._default_clip_jobs() == 2


def test_default_clip_jobs_is_capped_at_three(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(clip_cmd.os, "cpu_count", lambda: 8)

    assert clip_cmd._default_clip_jobs() == 3


def test_default_clip_jobs_is_at_least_one(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setattr(clip_cmd.os, "cpu_count", lambda: 1)

    assert clip_cmd._default_clip_jobs() == 1


def test_legacy_segment_dict_matches_old_segments_json_shape(tmp_path: Path) -> None:
    subtitles = [
        SubtitleEntry(index=1, start=1.0, end=3.0, text="开头。"),
        SubtitleEntry(index=2, start=3.0, end=6.5, text="结尾。"),
    ]
    segment = ClipSegment(
        title="旧结构",
        start_subtitle_index=1,
        end_subtitle_index=2,
        score=0.9,
        reason="原因",
        structure_score=0.8,
        structure_reason="完整",
        validation={"passed": True},
    )

    data = clip_cmd._legacy_segment_dict(
        segment,
        subtitles,
        subtitle_output=tmp_path / "clip.srt",
    )

    assert data["topic"] == "旧结构"
    assert data["start_time"] == "00:00:01.000"
    assert data["end_time"] == "00:00:06.500"
    assert data["duration"] == 5.5
    assert data["validation"] == {"passed": True}
    assert data["subtitle_output"] == str(tmp_path / "clip.srt")
