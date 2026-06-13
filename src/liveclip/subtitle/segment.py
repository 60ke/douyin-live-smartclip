from __future__ import annotations

from liveclip.domain.models import ClipSegment, SubtitleEntry
from liveclip.observability import get_logger
from liveclip.subtitle.parts import segment_duration_seconds, segment_time_ranges
from liveclip.subtitle.sentence_merge import looks_complete

logger = get_logger(__name__)


def slice_subtitles(
    subtitles: list[SubtitleEntry],
    start_index: int,
    end_index: int,
) -> list[SubtitleEntry]:
    """Get subtitles between start_index and end_index (inclusive, 1-based)."""
    return [sub for sub in subtitles if start_index <= sub.index <= end_index]


def get_subtitle_context(
    subtitles: list[SubtitleEntry],
    start_index: int,
    end_index: int,
    radius: int = 3,
) -> list[SubtitleEntry]:
    """Get context subtitles around a range."""
    context_start = max(1, start_index - radius)
    context_end = min(len(subtitles), end_index + radius)
    return [sub for sub in subtitles if context_start <= sub.index <= context_end]


def subtitles_to_text(subtitles: list[SubtitleEntry]) -> str:
    """Join subtitle texts into a single string."""
    return " ".join(sub.text for sub in subtitles)


def subtitles_to_payload(subtitles: list[SubtitleEntry]) -> list[dict]:
    """Convert subtitles to list of dicts for LLM input."""
    return [
        {
            "index": sub.index,
            "start": round(sub.start, 2),
            "end": round(sub.end, 2),
            "text": sub.text,
        }
        for sub in subtitles
    ]


def split_long_segment(
    segment: ClipSegment,
    subtitles: list[SubtitleEntry],
    max_seconds: float = 180.0,
) -> list[ClipSegment]:
    """Split a segment that exceeds max_seconds at natural break points."""
    sub_by_index = {sub.index: sub for sub in subtitles}
    start_sub = sub_by_index.get(segment.start_subtitle_index)
    end_sub = sub_by_index.get(segment.end_subtitle_index)
    if not start_sub or not end_sub:
        return [segment]

    duration = end_sub.end - start_sub.start
    if duration <= max_seconds:
        return [segment]

    # Find natural break points (complete sentences) near the midpoint
    mid_time = start_sub.start + duration / 2
    best_idx = segment.start_subtitle_index
    best_diff = float("inf")

    for sub in subtitles:
        if sub.index < segment.start_subtitle_index or sub.index > segment.end_subtitle_index:
            continue
        if not looks_complete(sub.text):
            continue
        diff = abs(sub.end - mid_time)
        if diff < best_diff:
            best_diff = diff
            best_idx = sub.index

    if best_idx == segment.start_subtitle_index:
        return [segment]

    seg1 = ClipSegment(
        title=f"{segment.title} (1)",
        start_subtitle_index=segment.start_subtitle_index,
        end_subtitle_index=best_idx,
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
    seg2 = ClipSegment(
        title=f"{segment.title} (2)",
        start_subtitle_index=best_idx + 1,
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

    # Recursively split if still too long
    result: list[ClipSegment] = []
    result.extend(split_long_segment(seg1, subtitles, max_seconds))
    result.extend(split_long_segment(seg2, subtitles, max_seconds))
    return result


def dedupe_segments(
    segments: list[ClipSegment],
    subtitles: list[SubtitleEntry],
    overlap_threshold: float = 0.55,
) -> list[ClipSegment]:
    """Remove duplicate/overlapping segments using old smartclip overlap semantics."""
    if len(segments) <= 1:
        return segments

    sorted_segs = sorted(segments, key=lambda s: s.score, reverse=True)
    kept: list[ClipSegment] = []

    for seg in sorted_segs:
        seg_duration = segment_duration_seconds(seg, subtitles)
        if seg_duration <= 0:
            continue
        seg_start, seg_end = _segment_outer_bounds(seg, subtitles)
        if seg_end <= seg_start:
            continue

        is_dup = False
        for kept_seg in kept:
            kept_start, kept_end = _segment_outer_bounds(kept_seg, subtitles)
            kept_duration = segment_duration_seconds(kept_seg, subtitles)
            overlap_duration = max(0.0, min(seg_end, kept_end) - max(seg_start, kept_start))
            base = max(1.0, min(seg_duration, kept_duration))
            if overlap_duration / base > overlap_threshold:
                is_dup = True
                break

        if not is_dup:
            kept.append(seg)

    # Restore original order by start_subtitle_index
    kept.sort(key=lambda s: s.start_subtitle_index)
    return kept


def _segment_outer_bounds(
    segment: ClipSegment,
    subtitles: list[SubtitleEntry],
) -> tuple[float, float]:
    ranges = segment_time_ranges(segment, subtitles)
    if ranges:
        return ranges[0][0], ranges[-1][1]
    return 0.0, 0.0


def _ranges_overlap_seconds(
    left: list[tuple[float, float]],
    right: list[tuple[float, float]],
) -> float:
    overlap = 0.0
    for left_start, left_end in left:
        for right_start, right_end in right:
            overlap += max(0.0, min(left_end, right_end) - max(left_start, right_start))
    return overlap
