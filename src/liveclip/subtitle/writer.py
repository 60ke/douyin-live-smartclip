"""SRT 字幕文件写入。"""

from __future__ import annotations

from pathlib import Path

from liveclip.domain.models import SubtitleEntry
from liveclip.observability import get_logger
from liveclip.utils.timecode import format_timecode

logger = get_logger(__name__)


def format_srt_entry(
    entry: SubtitleEntry,
    index: int | None = None,
    time_offset: float = 0.0,
) -> str:
    """格式化单条字幕为 SRT 文本块。

    Args:
        entry: 字幕条目。
        index: 输出序号，为 None 时使用 entry 原始 index。
        time_offset: 时间偏移量（秒），用于重置时间轴。

    Returns:
        SRT 格式的单条字幕文本。
    """
    seq = index if index is not None else entry.index
    start = max(0.0, entry.start + time_offset)
    end = max(0.0, entry.end + time_offset)
    return f"{seq}\n{format_timecode(start)} --> {format_timecode(end)}\n{entry.text}\n"


def rebase_subtitles(
    subtitles: list[SubtitleEntry],
    time_offset: float,
) -> list[SubtitleEntry]:
    """重置字幕时间轴偏移。

    将所有字幕的 start/end 减去 time_offset，并重新编号。

    Args:
        subtitles: 原始字幕列表。
        time_offset: 时间偏移量（秒）。

    Returns:
        重置后的字幕列表。
    """
    result: list[SubtitleEntry] = []
    for i, entry in enumerate(subtitles, start=1):
        new_start = max(0.0, entry.start - time_offset)
        new_end = max(0.0, entry.end - time_offset)
        result.append(SubtitleEntry(index=i, start=new_start, end=new_end, text=entry.text))
    return result


def write_srt_file(
    path: Path,
    subtitles: list[SubtitleEntry],
    rebase: bool = False,
    time_offset: float = 0.0,
) -> Path:
    """将字幕列表写入 SRT 文件。

    Args:
        path: 输出文件路径。
        subtitles: 字幕条目列表。
        rebase: 是否重置时间轴（减去 time_offset 并重新编号）。
        time_offset: 时间偏移量（秒），仅在 rebase=True 时生效。

    Returns:
        写入的文件路径。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = rebase_subtitles(subtitles, time_offset) if rebase else subtitles

    with path.open("w", encoding="utf-8") as f:
        for i, entry in enumerate(entries, start=1):
            f.write(format_srt_entry(entry, index=i))
            f.write("\n")

    logger.debug("SRT 文件已写入", path=str(path), count=len(entries))
    return path
