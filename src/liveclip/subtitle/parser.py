"""SRT 字幕文件解析。"""

from __future__ import annotations

import re
from pathlib import Path

from liveclip.domain.models import SubtitleEntry
from liveclip.observability import get_logger
from liveclip.utils.timecode import parse_timecode

logger = get_logger(__name__)

# 匹配单个 SRT 块：序号 → 时间轴 → 文本
_SRT_BLOCK_RE = re.compile(
    r"(\d+)\s*\n"
    r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*"
    r"(\d{2}:\d{2}:\d{2}[,.]\d{3})\s*\n"
    r"(.+?)(?=\n\s*\n|\Z)",
    re.S,
)


def parse_srt_file(path: Path) -> list[SubtitleEntry]:
    """解析 SRT 文件为 SubtitleEntry 列表。

    Args:
        path: SRT 文件路径。

    Returns:
        解析后的 SubtitleEntry 列表，按出现顺序排列。
    """
    text = path.read_text(encoding="utf-8-sig", errors="ignore")
    return parse_srt_string(text)


def parse_srt_string(content: str) -> list[SubtitleEntry]:
    """解析 SRT 格式字符串为 SubtitleEntry 列表。

    支持逗号/句点作为毫秒分隔符，兼容不同换行符。

    Args:
        content: SRT 格式文本内容。

    Returns:
        解析后的 SubtitleEntry 列表。
    """
    subtitles: list[SubtitleEntry] = []
    skipped = 0

    for match in _SRT_BLOCK_RE.finditer(content):
        try:
            index = int(match.group(1))
            start = parse_timecode(match.group(2))
            end = parse_timecode(match.group(3))
            text = " ".join(line.strip() for line in match.group(4).splitlines() if line.strip())
            if end < start:
                logger.warning(
                    "跳过时间轴异常条目",
                    index=index,
                    start=start,
                    end=end,
                )
                skipped += 1
                continue
            subtitles.append(SubtitleEntry(index=index, start=start, end=end, text=text))
        except (ValueError, IndexError) as exc:
            logger.warning(
                "跳过格式异常条目",
                raw=match.group(0)[:80],
                error=str(exc),
            )
            skipped += 1

    if skipped:
        logger.info("SRT 解析完成", total=len(subtitles), skipped=skipped)
    return subtitles
