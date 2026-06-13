"""Utilities for multi-part clip segments."""

from __future__ import annotations

from liveclip.domain.models import ClipSegment, SubtitleEntry


def normalize_segment_parts(
    segment: ClipSegment,
    subtitles: list[SubtitleEntry],
    max_parts: int = 4,
) -> ClipSegment:
    """Normalize segment parts into sorted, non-overlapping time/index ranges."""
    if not segment.parts:
        return segment

    by_index = {entry.index: entry for entry in subtitles}
    normalized: list[dict[str, object]] = []
    previous_end = -1.0

    for part in segment.parts:
        resolved = _resolve_part(part, by_index)
        if resolved is None:
            continue
        start_seconds, end_seconds, start_index, end_index = resolved
        if end_seconds <= start_seconds or start_seconds < previous_end:
            continue
        normalized.append(
            {
                "start": start_seconds,
                "end": end_seconds,
                "start_subtitle_index": start_index,
                "end_subtitle_index": end_index,
            }
        )
        previous_end = end_seconds
        if len(normalized) >= max_parts:
            break

    if not normalized:
        return ClipSegment(
            title=segment.title,
            start_subtitle_index=segment.start_subtitle_index,
            end_subtitle_index=segment.end_subtitle_index,
            parts=[],
            score=segment.score,
            reason=segment.reason,
            structure_score=segment.structure_score,
            structure_reason=segment.structure_reason,
            hook=segment.hook,
            validation=segment.validation,
            output=segment.output,
            subtitle_output=segment.subtitle_output,
        )

    first_start_index = _coerce_int(normalized[0]["start_subtitle_index"])
    last_end_index = _coerce_int(normalized[-1]["end_subtitle_index"])
    if first_start_index is None or last_end_index is None:
        return segment

    return ClipSegment(
        title=segment.title,
        start_subtitle_index=first_start_index,
        end_subtitle_index=last_end_index,
        parts=normalized,
        score=segment.score,
        reason=segment.reason,
        structure_score=segment.structure_score,
        structure_reason=segment.structure_reason,
        hook=segment.hook,
        validation=segment.validation,
        output=segment.output,
        subtitle_output=segment.subtitle_output,
    )


def segment_duration_seconds(segment: ClipSegment, subtitles: list[SubtitleEntry]) -> float:
    """Return the actual exported duration of a segment, respecting parts."""
    if segment.parts:
        return sum(_part_duration(part) for part in segment.parts)

    by_index = {entry.index: entry for entry in subtitles}
    start = by_index.get(segment.start_subtitle_index)
    end = by_index.get(segment.end_subtitle_index)
    if start is None or end is None:
        return 0.0
    return max(0.0, end.end - start.start)


def segment_time_ranges(
    segment: ClipSegment,
    subtitles: list[SubtitleEntry],
) -> list[tuple[float, float]]:
    """Return one or more time ranges represented by a segment."""
    if segment.parts:
        ranges = []
        for part in segment.parts:
            part_start = _coerce_float(part.get("start"))
            part_end = _coerce_float(part.get("end"))
            if part_start is not None and part_end is not None and part_end > part_start:
                ranges.append((part_start, part_end))
        return ranges

    by_index = {entry.index: entry for entry in subtitles}
    start_entry = by_index.get(segment.start_subtitle_index)
    end_entry = by_index.get(segment.end_subtitle_index)
    if start_entry is None or end_entry is None or end_entry.end <= start_entry.start:
        return []
    return [(start_entry.start, end_entry.end)]


def _resolve_part(
    part: dict[str, object],
    by_index: dict[int, SubtitleEntry],
) -> tuple[float, float, int, int] | None:
    start_index = _coerce_int(part.get("start_subtitle_index"))
    end_index = _coerce_int(part.get("end_subtitle_index"))
    if start_index is not None and end_index is not None:
        if start_index > end_index:
            start_index, end_index = end_index, start_index
        start_entry = by_index.get(start_index)
        end_entry = by_index.get(end_index)
        if start_entry is None or end_entry is None:
            return None
        return start_entry.start, end_entry.end, start_entry.index, end_entry.index

    start_seconds = _coerce_float(part.get("start"))
    end_seconds = _coerce_float(part.get("end"))
    if start_seconds is None or end_seconds is None or end_seconds <= start_seconds:
        return None
    if not by_index:
        return start_seconds, end_seconds, 0, 0

    start_entry = min(by_index.values(), key=lambda entry: abs(entry.start - start_seconds))
    end_entry = min(by_index.values(), key=lambda entry: abs(entry.end - end_seconds))
    return start_seconds, end_seconds, start_entry.index, end_entry.index


def _part_duration(part: dict[str, object]) -> float:
    start = _coerce_float(part.get("start"))
    end = _coerce_float(part.get("end"))
    if start is None or end is None:
        return 0.0
    return max(0.0, end - start)


def _coerce_int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _coerce_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None
