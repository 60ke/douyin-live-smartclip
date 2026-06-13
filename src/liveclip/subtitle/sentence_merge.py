from __future__ import annotations

import re

from liveclip.domain.models import SubtitleEntry
from liveclip.observability import get_logger

logger = get_logger(__name__)

STRONG_END_PUNCTS = "。.!?！？；;…"
WEAK_END_PUNCTS = "，,"
GOOD_WEAK_SUFFIXES = (
    "了",
    "吧",
    "啊",
    "呀",
    "呢",
    "吗",
    "嘛",
    "可以",
    "就可以",
    "就行",
    "行了",
    "里面",
    "内",
    "里",
    "中",
    "上",
    "下",
    "效果图内",
    "项目里面",
    "能理解吧",
)
# 对齐旧项目 boundary.py 的 BAD_SUFFIXES
BAD_SUFFIXES = (
    "的",
    "和",
    "跟",
    "与",
    "把",
    "被",
    "给",
    "让",
    "是",
    "在",
    "对",
    "到",
    "向",
    "因为",
    "所以",
    "然后",
    "但是",
    "如果",
    "比如",
    "包括",
    "以及",
    "或者",
    "这个",
    "那个",
    "那这个",
    "一种",
    "给咱",
    "给我们",
    "直播间",
    "老板",
    "主播",
    "大家",
    "咱",
    "咱们",
    "刚",
    "刚刚",
    "除了",
    "然后除了",
    "接下来",
    "下面",
    "你去",
    "研究一下",
    "第一点",
    "第二点",
    "第三点",
    "第四点",
    "第五点",
    "第一年",
    "第二年",
    "第三年",
    "第四年",
    "第五年",
)
NEW_TOPIC_OPENER_RE = re.compile(
    r"^(?:家人们|老板们|各位老板|大家)?[，,、\s]*"
    r"(?:然后|接下来|下面|那我们|我们再|再来看|像我们这边)"
    r".*(?:功能|板块|内容|玩法|操作|案例|第二点|第三点)[。.!?！？；;…]?$",
)
ORDINAL_CUE_END_RE = re.compile(r"第[一二三四五六七八九十两]+[点年][。.!?！？；;…]?$")


def _strip_tail(text: str) -> str:
    return text.strip().rstrip("\"'”’）)】》> ").strip()


def _strip_sentence_punctuation(text: str) -> str:
    return _strip_tail(text).rstrip(STRONG_END_PUNCTS + WEAK_END_PUNCTS).strip()


def _is_oral_closure_with_weak_punctuation(text: str) -> bool:
    """对齐旧项目 boundary.py: 弱标点结尾的口语收束判断。"""
    value = _strip_tail(text)
    if not value or value[-1] not in WEAK_END_PUNCTS:
        return False
    without_punctuation = _strip_sentence_punctuation(value)
    if not without_punctuation or is_new_topic_opener(without_punctuation):
        return False
    if any(without_punctuation.endswith(s) for s in BAD_SUFFIXES):
        return False
    return len(without_punctuation) >= 8 and any(
        without_punctuation.endswith(s) for s in GOOD_WEAK_SUFFIXES
    )


def looks_complete(text: str) -> bool:
    """对齐旧项目 boundary.py looks_complete: 判断字幕是否表达完整。"""
    value = _strip_tail(text)
    if not value:
        return False
    if is_new_topic_opener(value):
        return False
    if ends_with_continuation_cue(value):
        return False
    if value[-1] in STRONG_END_PUNCTS:
        return True
    if value[-1] in WEAK_END_PUNCTS:
        return _is_oral_closure_with_weak_punctuation(value)
    if any(value.endswith(s) for s in BAD_SUFFIXES):
        return False
    return len(value) >= 8


def end_boundary_quality(text: str) -> str:
    """对齐旧项目 boundary.py: Return boundary quality label."""
    value = _strip_tail(text)
    if not value:
        return "bad"
    if not looks_complete(value):
        return "bad" if ends_with_continuation_cue(value) or is_new_topic_opener(value) else "weak"
    if value[-1] in STRONG_END_PUNCTS:
        return "strong"
    return "acceptable"


def is_new_topic_opener(text: str) -> bool:
    """Check if text starts a new topic."""
    stripped = _strip_tail(text)
    if not stripped:
        return False
    return bool(NEW_TOPIC_OPENER_RE.search(stripped))


def ends_with_continuation_cue(text: str) -> bool:
    """对齐旧项目 boundary.py: Check if text ends with a continuation cue."""
    stripped = _strip_sentence_punctuation(text)
    if not stripped:
        return False
    if ORDINAL_CUE_END_RE.search(stripped):
        return True
    for bad in BAD_SUFFIXES:
        if stripped.endswith(bad):
            return True
    return False


def merge_fragments(
    subtitles: list[SubtitleEntry],
    max_gap_seconds: float = 0.5,
    max_merge_seconds: float = 8.0,
) -> list[SubtitleEntry]:
    """Merge short subtitle fragments that don't form complete sentences.

    Iterates through subtitles and merges consecutive fragments when:
    1. The current fragment doesn't look complete AND
    2. The gap to the next fragment is within max_gap_seconds AND
    3. The merged duration doesn't exceed max_merge_seconds
    """
    if not subtitles:
        return []

    result: list[SubtitleEntry] = []
    current_text = subtitles[0].text
    current_start = subtitles[0].start
    current_end = subtitles[0].end
    current_index = subtitles[0].index

    for i in range(1, len(subtitles)):
        sub = subtitles[i]
        gap = sub.start - current_end
        merged_duration = sub.end - current_start

        if (
            not looks_complete(current_text)
            and gap <= max_gap_seconds
            and merged_duration <= max_merge_seconds
        ):
            # Merge
            current_text += sub.text
            current_end = sub.end
        else:
            # Emit current
            result.append(
                SubtitleEntry(
                    index=current_index,
                    start=current_start,
                    end=current_end,
                    text=current_text,
                )
            )
            current_text = sub.text
            current_start = sub.start
            current_end = sub.end
            current_index = sub.index

    # Emit last
    result.append(
        SubtitleEntry(
            index=current_index,
            start=current_start,
            end=current_end,
            text=current_text,
        )
    )

    # Re-index
    for i, entry in enumerate(result, 1):
        entry.index = i

    return result
