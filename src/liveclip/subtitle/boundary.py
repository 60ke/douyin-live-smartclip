from __future__ import annotations

from liveclip.domain.models import ClipSegment, SubtitleEntry
from liveclip.observability import get_logger
from liveclip.subtitle.parts import normalize_segment_parts, segment_duration_seconds
from liveclip.subtitle.sentence_merge import (
    end_boundary_quality,
    ends_with_continuation_cue,
    looks_complete,
)

logger = get_logger(__name__)

# 对齐旧项目 boundary.py 的前向填充/后向修剪常量
FORWARD_FILL_SECONDS: float = 45.0
BACKWARD_TRIM_SECONDS: float = 18.0
FORWARD_START_TRIM_SECONDS: float = 18.0
START_FRAGMENT_PREFIXES: tuple[str, ...] = (
    "的情况下",
    "多的情况下",
    "情况下",
    "这种情况下",
    "这个情况下",
    "的时候",
    "这个时候",
    "那这个时候",
    "的话",
    "这样的话",
    "所以的话",
)


def _strip_tail(text: str) -> str:
    return text.strip().rstrip("\"'”’）)】》> ").strip()


def _trim_to_previous_complete_end(
    segment: ClipSegment,
    subtitles: list[SubtitleEntry],
    end_pos: int,
) -> bool:
    """向后修剪到上一个完整字幕结尾（对齐旧项目）。"""
    for pos in range(end_pos - 1, -1, -1):
        if segment.end_subtitle_index is None:
            continue
        end_row = _find_subtitle_by_index(subtitles, segment.end_subtitle_index)
        if end_row is None:
            continue
        if end_row.end - subtitles[pos].end > BACKWARD_TRIM_SECONDS:
            break
        if looks_complete(subtitles[pos].text):
            segment.end_subtitle_index = subtitles[pos].index
            segment.validation["auto_policy"] = "trim_end_to_complete_subtitle"
            return True
    return False


def _strip_sentence_head(text: str) -> str:
    return text.strip().lstrip("\"'“‘（(【《< ，,、。.!?！？；;…").strip()


def _looks_like_start_fragment(text: str) -> bool:
    """Return true for ASR fragments that clearly continue the previous sentence."""
    value = _strip_sentence_head(text)
    if not value:
        return False
    return any(value.startswith(prefix) for prefix in START_FRAGMENT_PREFIXES)


def _trim_to_next_natural_start(
    segment: ClipSegment,
    subtitles: list[SubtitleEntry],
    start_pos: int,
) -> bool:
    """Trim an obvious leading half-sentence from the segment start."""
    original_start = subtitles[start_pos]
    for pos in range(start_pos + 1, len(subtitles)):
        if subtitles[pos].start - original_start.start > FORWARD_START_TRIM_SECONDS:
            break
        if not _looks_like_start_fragment(subtitles[pos].text):
            segment.start_subtitle_index = subtitles[pos].index
            segment.validation["auto_start_policy"] = "trim_start_fragment_to_natural_subtitle"
            return True
    return False


def _find_subtitle_by_index(subtitles: list[SubtitleEntry], index: int) -> SubtitleEntry | None:
    for sub in subtitles:
        if sub.index == index:
            return sub
    return None


def snap_segment_to_subtitles(
    segment: ClipSegment,
    subtitles: list[SubtitleEntry],
) -> ClipSegment:
    """对齐旧项目 boundary.py snap_segment_to_subtitles。

    将切片边界对齐到完整字幕条目，包含前向填充和后向修剪逻辑。
    """
    if not subtitles:
        return segment

    start_row = _find_subtitle_by_index(subtitles, segment.start_subtitle_index)
    end_row = _find_subtitle_by_index(subtitles, segment.end_subtitle_index)

    if start_row:
        segment.start_subtitle_index = start_row.index
    if end_row:
        segment.end_subtitle_index = end_row.index

    if start_row and _looks_like_start_fragment(start_row.text):
        start_pos = _subtitle_position(subtitles, start_row)
        if start_pos is not None:
            _trim_to_next_natural_start(segment, subtitles, start_pos)

    if end_row and not looks_complete(end_row.text):
        end_pos = _subtitle_position(subtitles, end_row)
        if end_pos is not None:
            if ends_with_continuation_cue(end_row.text):
                _trim_to_previous_complete_end(segment, subtitles, end_pos)
            else:
                # 前向填充到完整字幕
                for pos in range(end_pos + 1, len(subtitles)):
                    if subtitles[pos].end - (end_row.end if end_row else 0) > FORWARD_FILL_SECONDS:
                        break
                    if looks_complete(subtitles[pos].text):
                        segment.end_subtitle_index = subtitles[pos].index
                        segment.validation["auto_policy"] = "extend_end_to_complete_subtitle"
                        break
                else:
                    _trim_to_previous_complete_end(segment, subtitles, end_pos)

    final_start = _find_subtitle_by_index(subtitles, segment.start_subtitle_index)
    final_end = _find_subtitle_by_index(subtitles, segment.end_subtitle_index)
    if final_start:
        segment.validation["first_sentence"] = _strip_tail(final_start.text)
    if final_end:
        segment.validation["last_sentence"] = _strip_tail(final_end.text)
        segment.validation["end_boundary_quality"] = end_boundary_quality(final_end.text)

    return segment


def snap_segment_boundaries(
    segment: ClipSegment,
    subtitles: list[SubtitleEntry],
) -> ClipSegment:
    """Snap segment start/end to complete subtitle boundaries (simple version for batch)."""
    if not subtitles:
        return segment

    if segment.parts:
        return snap_parts_boundaries(segment, subtitles)
    return snap_segment_to_subtitles(segment, subtitles)


def _subtitle_position(subtitles: list[SubtitleEntry], target: SubtitleEntry) -> int | None:
    for i, sub in enumerate(subtitles):
        if sub is target or sub.index == target.index:
            return i
    return None


def snap_to_complete_subtitle(
    subtitles: list[SubtitleEntry],
    time_seconds: float,
    direction: str = "forward",
) -> tuple[float, int]:
    """Snap a time point to the nearest complete subtitle boundary.

    Kept for backward compatibility with tests.
    """
    if not subtitles:
        return time_seconds, 0
    closest_idx = 0
    min_diff = abs(subtitles[0].start - time_seconds)
    for i, sub in enumerate(subtitles):
        diff = abs(sub.start - time_seconds)
        if diff < min_diff:
            min_diff = diff
            closest_idx = i

    direction_int = 1 if direction == "forward" else -1
    for offset in range(1, 6):
        idx = closest_idx + offset * direction_int
        if 0 <= idx < len(subtitles):
            if looks_complete(subtitles[idx].text):
                sub = subtitles[idx]
                return (sub.end if direction == "forward" else sub.start), sub.index

    sub = subtitles[closest_idx]
    return (sub.end if direction == "forward" else sub.start), sub.index


def snap_parts_boundaries(
    segment: ClipSegment,
    subtitles: list[SubtitleEntry],
) -> ClipSegment:
    """Snap parts boundaries to complete subtitle boundaries."""
    if not segment.parts or not subtitles:
        return segment

    snapped_parts: list[dict[str, object]] = []
    part_notes: list[dict[str, object]] = []
    for part in segment.parts:
        start_index = _coerce_part_index(part.get("start_subtitle_index"))
        end_index = _coerce_part_index(part.get("end_subtitle_index"))
        if start_index is None or end_index is None:
            continue
        start_idx = max(0, start_index - 1)
        end_idx = min(len(subtitles) - 1, end_index - 1)

        # Snap start backward
        while start_idx > 0 and ends_with_continuation_cue(subtitles[start_idx].text):
            start_idx -= 1

        # Snap end forward
        while end_idx < len(subtitles) - 1 and not looks_complete(subtitles[end_idx].text):
            end_idx += 1

        part_segment = ClipSegment(
            title=segment.title,
            start_subtitle_index=subtitles[start_idx].index,
            end_subtitle_index=subtitles[end_idx].index,
            score=segment.score,
        )
        snapped = snap_segment_to_subtitles(part_segment, subtitles)

        snapped_parts.append(
            {
                "start_subtitle_index": snapped.start_subtitle_index,
                "end_subtitle_index": snapped.end_subtitle_index,
            }
        )
        part_notes.append(snapped.validation)

    segment.parts = snapped_parts
    normalized = normalize_segment_parts(segment, subtitles)
    normalized.validation.update(segment.validation)
    normalized.validation["part_boundaries"] = part_notes
    start_row = _find_subtitle_by_index(subtitles, normalized.start_subtitle_index)
    end_row = _find_subtitle_by_index(subtitles, normalized.end_subtitle_index)
    if start_row:
        normalized.validation["first_sentence"] = _strip_tail(start_row.text)
    if end_row:
        normalized.validation["last_sentence"] = _strip_tail(end_row.text)
        normalized.validation["end_boundary_quality"] = end_boundary_quality(end_row.text)
    return normalized


def filter_short_segments(
    segments: list[ClipSegment],
    subtitles: list[SubtitleEntry],
    min_seconds: float = 45.0,
    high_score_threshold: float = 0.8,
) -> list[ClipSegment]:
    """Remove low-score segments shorter than min_seconds."""
    if not subtitles:
        return segments

    result: list[ClipSegment] = []
    for seg in segments:
        duration = segment_duration_seconds(seg, subtitles)

        if duration < min_seconds and seg.score < high_score_threshold:
            logger.debug(
                "segment_short_low_score", title=seg.title, duration=duration, score=seg.score
            )
            continue

        result.append(seg)

    return result


def _coerce_part_index(value: object) -> int | None:
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
