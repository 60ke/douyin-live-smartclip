from __future__ import annotations

import math


def format_timecode(seconds: float, sep: str = ",") -> str:
    """Convert seconds to HH:MM:SS{sep}mmm format.

    Args:
        seconds: Duration in seconds (can be fractional).
        sep: Separator between seconds and milliseconds (default: comma for SRT).

    Returns:
        Timecode string in HH:MM:SS{sep}mmm format.
    """
    if seconds < 0:
        seconds = 0.0
    total_ms = round(seconds * 1000)
    ms = total_ms % 1000
    total_secs = total_ms // 1000
    s = total_secs % 60
    total_mins = total_secs // 60
    m = total_mins % 60
    h = total_mins // 60
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def parse_timecode(value: str) -> float:
    """Parse HH:MM:SS,mmm or HH:MM:SS.mmm to seconds.

    Accepts both comma and dot as the separator between seconds and
    milliseconds.

    Args:
        value: Timecode string (e.g. "01:23:45,678" or "01:23:45.678").

    Returns:
        Duration in seconds as a float.

    Raises:
        ValueError: If the timecode format is invalid.
    """
    value = value.strip()
    normalized = value.replace(",", ".")
    parts = normalized.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid timecode format: {value!r}")

    try:
        hours = int(parts[0])
        minutes = int(parts[1])
        sec_parts = parts[2].split(".")
        secs = int(sec_parts[0])
        millis = int(sec_parts[1]) if len(sec_parts) > 1 else 0
    except (ValueError, IndexError) as exc:
        raise ValueError(f"Invalid timecode format: {value!r}") from exc

    if minutes >= 60 or secs >= 60:
        raise ValueError(f"Invalid timecode format: {value!r}")

    return hours * 3600 + minutes * 60 + secs + millis / 1000.0


def format_timecode_ms(milliseconds: int) -> str:
    """Format milliseconds to SRT time format (HH:MM:SS,mmm).

    Args:
        milliseconds: Duration in milliseconds (non-negative).

    Returns:
        SRT-formatted timecode string.
    """
    if milliseconds < 0:
        milliseconds = 0
    ms = milliseconds % 1000
    total_secs = milliseconds // 1000
    s = total_secs % 60
    total_mins = total_secs // 60
    m = total_mins % 60
    h = total_mins // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def format_duration(seconds: float) -> str:
    """Format seconds into a human-readable duration string.

    Produces strings like "1h 23m 45s", "23m 45s", or "45s" depending
    on the magnitude.  Fractional seconds are rounded down.

    Args:
        seconds: Duration in seconds (non-negative).

    Returns:
        Human-readable duration string.
    """
    if seconds < 0:
        seconds = 0.0
    total_secs = int(math.floor(seconds))
    s = total_secs % 60
    total_mins = total_secs // 60
    m = total_mins % 60
    h = total_mins // 60

    parts: list[str] = []
    if h > 0:
        parts.append(f"{h}h")
    if m > 0:
        parts.append(f"{m}m")
    if s > 0 or not parts:
        parts.append(f"{s}s")
    return " ".join(parts)
