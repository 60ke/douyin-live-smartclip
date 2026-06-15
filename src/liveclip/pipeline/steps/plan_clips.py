"""切片方案规划步骤：基于 LLM 分析字幕，生成切片方案。"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import cast

from liveclip.adapters.llm import LLMClient, PromptTemplate
from liveclip.domain.enums import StepName
from liveclip.domain.models import ClipPlanResult, ClipSegment, StepResult, SubtitleEntry
from liveclip.exceptions import (
    CLIP_PLAN_INVALID,
    LLM_JSON_PARSE_FAILED,
    ClipPlanError,
    LLMError,
)
from liveclip.observability import get_logger
from liveclip.pipeline.context import PipelineContext
from liveclip.pipeline.steps.base import BaseStep
from liveclip.storage.local import LocalStorage
from liveclip.subtitle.parser import parse_srt_file
from liveclip.subtitle.parts import (
    normalize_segment_parts,
)
from liveclip.subtitle.parts import (
    segment_duration_seconds as _part_segment_duration,
)
from liveclip.subtitle.segment import dedupe_segments
from liveclip.subtitle.sentence_merge import looks_complete as _sentence_looks_complete
from liveclip.utils.json import clamp_score, extract_json_value
from liveclip.utils.timecode import format_timecode, parse_timecode

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 与旧项目 segmenter.py 对齐的分段拆分常量
# ---------------------------------------------------------------------------
SPLIT_MIN_SECONDS: float = 45.0  # 对应旧 MIN_SPLIT_SECONDS
PLAN_LLM_MAX_TOKENS: int = 8000
REFINE_LLM_MAX_TOKENS: int = 4000

PROMPT_FULL_CLIP_TEMPLATE = """你是直播视频智能剪辑导演。你会收到一整段视频的完整字幕，字幕包含 subtitle index、开始时间、结束时间和文本。
任务：从完整字幕中规划可以独立发布的多个成片。你必须从全局语义出发，优先留下主要内容、完整表达和可观看价值。

你具备两种剪辑能力：
1. 连续裁剪：一个成片就是一段连续字幕区间。默认优先使用这种方式。
2. 裁剪拼接：一个成片可以由多个连续小段拼接而成，用 parts 表示。例如保留 0-1 分钟和 3-5 分钟，中间 1-3 分钟如果只是等待、重复、闲聊、跑题、无关操作，可以丢掉。

裁剪拼接原则：
- 非必要不要拼接。只有中间内容明显不影响理解、且删除后主题更集中时才使用 parts。
- 拼接后的成片必须像一个自然完整的视频，不能让观众感觉跳跃、断裂或缺少因果。
- 不要为了追求紧凑而删掉必要铺垫、解释、条件、步骤、转折、结论。
- 如果两个片段之间存在强语义依赖，应保留中间内容，使用连续裁剪。
- parts 必须按时间升序，不能重叠，每个 part 都必须从自然句/小段开始，到完整表达结束。
- 每个成片最多 4 个 parts。超过 4 个说明主题过散，应拆成多个成片或放弃。

核心标准：
1. 完整度最重要：每个成片都必须有自然开头、清晰主体、自然结尾，观众不需要看前后文也能理解。
2. 主要内容优先：保留观点、方法、演示步骤、核心结论、关键决策、重要讲解；丢弃等待、重复口播、无关闲聊、明显跑题和低信息密度片段。
3. 片段必须来自原始字幕，只能用 subtitle index 表示起止。
4. 不要从半句话、承接词、代词指代、解释中段开始；不要在悬念、原因、条件、步骤、列举中间结束。
5. 可以把相邻的弱片段合并成一个更完整的成片；也可以放弃看似有价值但不完整的内容。
6. 你必须把完整字幕当作一个全局 window 来规划，输出多个完整主题成片；不要只保留一个长片，也不要把明显独立的小主题硬合成一个成片。
7. 单个成片必须以主题完整度为准。只要同一主题自然连贯，且总时长不超过 {max_window_seconds} 秒，就不要为了压到 {target_segment_seconds} 秒左右而强行拆开。
8. 只有当一个主题超过 {max_window_seconds} 秒，才按自然小节拆成多个独立成片；每个成片内部仍可以用 parts 删除等待、重复、闲聊、跑题内容。
9. 每个成片最多 4 个 parts；每个 part 也必须是自然完整的小段。
10. 如果整段内容没有足够完整的成片，返回空 segments。

时长约束：
- 目标时长：{min_segment_seconds} 秒 ～ {target_segment_seconds} 秒。
- 可接受上限：{max_segment_seconds} 秒。
- 硬性上限：{hard_max_segment_seconds} 秒。
- 完整性优先于时长；但超过硬性上限时，必须优先寻找内部自然断点、缩短铺垫或拆成多个完整成片。

评分要求：
- score 是综合分，但完整度权重最高：完整度 70%，内容价值 20%，节奏/信息密度 10%。
- structure_score 专门表示完整度，必须严格打分。
- score 和 structure_score 都必须使用 0.0-1.0 小数，不要使用 1-10 分制。
- 如果 structure_score < 0.60，score 通常不得高于 0.55。
- 低于 0.40 的完整度不要保留。
- 使用 parts 时，structure_reason 必须说明为什么删除中间内容后仍然完整自然。

返回纯 JSON 对象，不要 Markdown。schema：
{
  "segments": [
    {
      "topic": "成片主题",
      "title": "成片标题",
      "start_subtitle_index": 85,
      "end_subtitle_index": 180,
      "parts": [
        {"start_subtitle_index": 85, "end_subtitle_index": 110},
        {"start_subtitle_index": 145, "end_subtitle_index": 180}
      ],
      "score": 0.82,
      "reason": "为什么值得剪，主要保留了什么，删除了什么",
      "structure_score": 0.9,
      "structure_reason": "开头、主体、结尾为什么完整；如果使用 parts，说明拼接为什么自然"
    }
  ]
}

如果不需要拼接，可以省略 parts，只返回 start_subtitle_index 和 end_subtitle_index。"""

PROMPT_LIVE_STRUCTURE_TEMPLATE = """你是直播内容结构分析员。你只负责从完整字幕里找“值得进一步精修的候选主题”，不要做最终切片。

任务：
1. 通读字幕，合并理解被 SRT 切碎的句子。
2. 找出适合独立传播的候选主题区间：操作演示、功能介绍、场景案例、痛点解决、费用/领取说明。
3. 只给粗边界。边界可以略宽，后续精修阶段会负责精确 start/end、parts、时长和评分。

候选主题规则：
- 一个候选主题必须有明确内容价值，纯互动、闲聊、等待、重复口播不要选。
- 同一大主题下如果有多个小闭环，拆成多个候选主题。
- 不要把明显无关的多个功能强行合成一个候选主题。
- 可以包含少量引流或现场互动，但要在 drop_notes 里标注。
- 如果内容主要依赖画面，仍可保留，但在 screen_dependency 填 "有"。

粗边界规则：
- start_subtitle_index/end_subtitle_index 必须来自原始字幕 index。
- 粗边界优先覆盖完整主题，宁可略宽，不要漏掉上下文。
- 不要以“第一点/第二点/第一年/第二年”这类要点开头或结尾作为完整主题收束。

输出 JSON：
{
  "candidates": [
    {
      "topic": "候选主题",
      "start_subtitle_index": 85,
      "end_subtitle_index": 180,
      "content_type": "feature_demo",
      "screen_dependency": "无",
      "why_keep": "为什么值得进入精修",
      "drop_notes": "候选区间里可在精修时删除的噪音或跑题内容"
    }
  ]
}

只返回 JSON 对象，不要 Markdown。第一个字符必须是 {。
"""

PROMPT_REFINE_TOPIC_TEMPLATE = """你是直播切片边界精修员。你会收到一个候选主题，以及该主题前后上下文字幕。

任务：输出最终可切的视频片段。你可以：
1. 保留为一条连续片段；
2. 按自然小节拆成多条；
3. 用 parts 删除中间直播互动/等待/无关插话。

硬规则：
- 完整性是底线。禁止在句子中间、话题中间、步骤中间截断。
- 标点不是边界依据，语义收束才是边界依据。即使最后一句有句号，只要它是新话题开头、承接句、列举开头或功能引入句，也必须回退。
- 结尾优先落在强结束点：。！？；.!?;
- 如果没有强标点，结尾必须是口语完整收束，例如“好吧”“能理解吧”“点击就可以生成了”“全部都可以免费去使用”。
- 禁止以这些状态结尾：逗号且后面明显承接；“然后/但是/因为/比如/包括/除了/接下来/下面/我们刚/你去研究一下”。
- 禁止把下一主题开头纳入当前结尾：如“家人们，然后像我们这边XX的功能”“接下来我们看XX”“下面给大家讲第二点”。遇到这种情况应回退到上一句完整收束处。
- 如果上一句是当前主题的口语收束，即使 ASR 以逗号结尾，也可以作为 acceptable 边界，例如“这个是我们的文化墙，平面转3D效果图啊，”。
- 选择 end 后必须检查后续 3-5 条字幕：如果后续是在补完当前句子或展示当前步骤结果，必须纳入；如果进入新主题/互动/转化，才可以结束。

时长策略：
- 理想区间：{min_segment_seconds}-{target_segment_seconds} 秒。
- 可接受上限：{max_segment_seconds} 秒；硬性上限：{hard_max_segment_seconds} 秒。
- 功能演示或案例展示为了完整可超过硬性上限，但必须说明原因。
- 当超长时，按顺序尝试：找内部自然断点、缩短铺垫、拆成两个完整片段、最后才允许完整性优先超长。
- 宁可换一个更短的完整片段，也不能截断当前片段。

输出字段要求：
- duration_status: normal / too_short / over_limit / unavoidable_overrun
- first_sentence: 片段第一句或第一条字幕文本
- last_sentence: 片段最后一句或最后一条字幕文本
- end_boundary_quality: strong / acceptable / weak / bad
- trim_attempts: 说明尝试过哪些截断点，为什么接受或放弃

返回纯 JSON 对象，不要 Markdown。schema：
{
  "segments": [
    {
      "topic": "成片主题",
      "title": "成片标题",
      "content_type": "feature_demo",
      "start_subtitle_index": 85,
      "end_subtitle_index": 110,
      "parts": [
        {"start_subtitle_index": 85, "end_subtitle_index": 98},
        {"start_subtitle_index": 120, "end_subtitle_index": 150}
      ],
      "score": 0.86,
      "structure_score": 0.9,
      "duration_status": "normal",
      "first_sentence": "片段第一句",
      "last_sentence": "片段最后一句",
      "end_boundary_quality": "strong",
      "trim_attempts": "尝试在 xxx 截断，但该处是承接句，改到 yyy",
      "reason": "为什么值得剪",
      "structure_reason": "为什么开头、主体、结尾完整"
    }
  ]
}
"""


def deduplicate_segments(segments: list[ClipSegment]) -> list[ClipSegment]:
    """去除重叠的切片段。

    当两个段存在字幕索引重叠时，保留评分较高的段。

    Args:
        segments: 原始切片段列表。

    Returns:
        去重后的切片段列表。
    """
    if not segments:
        return []

    sorted_segments = sorted(segments, key=lambda s: s.score, reverse=True)
    selected: list[ClipSegment] = []

    for seg in sorted_segments:
        overlaps = False
        for existing in selected:
            if (
                seg.start_subtitle_index <= existing.end_subtitle_index
                and seg.end_subtitle_index >= existing.start_subtitle_index
            ):
                overlaps = True
                break
        if not overlaps:
            selected.append(seg)

    selected.sort(key=lambda s: s.start_subtitle_index)
    return selected


def split_long_segments(
    segments: list[ClipSegment],
    max_subtitle_count: int = 60,
) -> list[ClipSegment]:
    """拆分过长的切片段。

    当段的字幕条目数超过 *max_subtitle_count* 时，按中点拆分为两个段。

    Args:
        segments: 切片段列表。
        max_subtitle_count: 最大字幕条目数阈值。

    Returns:
        拆分后的切片段列表。
    """
    result: list[ClipSegment] = []
    for seg in segments:
        count = seg.end_subtitle_index - seg.start_subtitle_index + 1
        if count <= max_subtitle_count:
            result.append(seg)
            continue

        mid = (seg.start_subtitle_index + seg.end_subtitle_index) // 2
        result.append(
            ClipSegment(
                title=f"{seg.title}（上）",
                start_subtitle_index=seg.start_subtitle_index,
                end_subtitle_index=mid,
                parts=seg.parts[: len(seg.parts) // 2] if seg.parts else [],
                score=seg.score,
                reason=seg.reason,
                structure_score=seg.structure_score,
                structure_reason=seg.structure_reason,
                hook=seg.hook,
                validation=seg.validation,
                output=seg.output,
                subtitle_output=seg.subtitle_output,
            )
        )
        result.append(
            ClipSegment(
                title=f"{seg.title}（下）",
                start_subtitle_index=mid + 1,
                end_subtitle_index=seg.end_subtitle_index,
                parts=seg.parts[len(seg.parts) // 2 :] if seg.parts else [],
                score=seg.score,
                reason=seg.reason,
                structure_score=seg.structure_score,
                structure_reason=seg.structure_reason,
                hook=seg.hook,
                validation=seg.validation,
                output=seg.output,
                subtitle_output=seg.subtitle_output,
            )
        )
    return result


def parse_llm_response(
    raw: str,
    subtitles: list[SubtitleEntry] | None = None,
) -> list[ClipSegment]:
    """解析 LLM 返回的 JSON 为 ClipSegment 列表。

    Args:
        raw: LLM 原始返回文本。

    Returns:
        解析后的切片段列表。

    Raises:
        LLMError: JSON 解析失败时抛出。
    """
    data = extract_json_value(raw)
    if data is None:
        raise LLMError(
            LLM_JSON_PARSE_FAILED,
            f"无法从 LLM 响应中提取 JSON: {raw[:200]}",
            details={"raw_preview": raw[:200]},
        )

    if isinstance(data, dict):
        segments_data = (
            data.get("segments")
            or data.get("clips")
            or data.get("candidates")
            or data.get("items")
            or data.get("data")
        )
        if segments_data is None and _looks_like_segment_object(data):
            segments_data = [data]
    else:
        segments_data = data
    if not isinstance(segments_data, list):
        raise LLMError(
            LLM_JSON_PARSE_FAILED,
            "LLM 响应 JSON 缺少 segments 数组",
            details={
                "data_type": type(data).__name__,
                "keys": list(data.keys()) if isinstance(data, dict) else None,
                "raw_preview": raw[:500],
            },
        )

    rows = subtitles or []
    segments: list[ClipSegment] = []
    for i, item in enumerate(segments_data):
        if not isinstance(item, dict):
            continue
        if item.get("keep") is False:
            continue
        try:
            content_score = clamp_score(float(item.get("score", 0.7)))
            structure_score = clamp_score(float(item.get("structure_score", 0.0)))
            if structure_score and structure_score < 0.4:
                continue
            score = content_score
            if structure_score:
                score = round((structure_score * 0.65) + (content_score * 0.35), 3)
            if structure_score and structure_score < 0.6:
                score = min(score, 0.55)
            parts = _parse_segment_parts(item, rows)
            start_index, end_index = _parse_segment_indices(item, rows, parts)
            if start_index is None or end_index is None:
                continue
            segments.append(
                ClipSegment(
                    title=str(item.get("title") or item.get("topic") or f"片段{i + 1}"),
                    start_subtitle_index=start_index,
                    end_subtitle_index=end_index,
                    parts=parts,
                    score=score,
                    reason=str(item.get("score_reason") or item.get("reason") or ""),
                    structure_score=structure_score,
                    structure_reason=str(item.get("structure_reason", "")),
                    hook=str(item.get("hook") or ""),
                    validation=_segment_validation_from_llm_item(item),
                )
            )
        except (ValueError, TypeError) as exc:
            logger.warning("skip_invalid_segment", index=i, error=str(exc))
            continue

    return segments


def _looks_like_segment_object(data: dict[str, object]) -> bool:
    return bool(
        data.get("start_subtitle_index") is not None
        or data.get("start_index") is not None
        or data.get("start") is not None
    ) and bool(
        data.get("end_subtitle_index") is not None
        or data.get("end_index") is not None
        or data.get("end") is not None
    )


def _segment_validation_from_llm_item(item: dict[str, object]) -> dict[str, object]:
    """Preserve old smartclip validation metadata returned by refine prompts."""
    validation: dict[str, object] = {}
    for source_key, target_key in (
        ("duration_status", "duration_status"),
        ("content_unit_type", "content_unit_type"),
        ("content_type", "content_type"),
        ("noise_density", "noise_density"),
        ("screen_dependency", "screen_dependency"),
        ("first_sentence", "first_sentence"),
        ("last_sentence", "last_sentence"),
        ("standalone_score", "standalone_score"),
        ("split_pair", "split_pair"),
        ("overlap_seconds", "overlap_seconds"),
        ("trim_note", "trim_note"),
        ("trim_attempts", "trim_attempts"),
        ("end_boundary_quality", "end_boundary_quality"),
    ):
        value = item.get(source_key)
        if value not in (None, ""):
            validation[target_key] = value
    if "trim_attempts" in validation and "trim_note" not in validation:
        validation["trim_note"] = validation["trim_attempts"]
    return validation


def _parse_segment_parts(
    item: dict[str, object],
    subtitles: list[SubtitleEntry],
) -> list[dict[str, object]]:
    raw_parts = item.get("parts") or item.get("ranges") or []
    if not isinstance(raw_parts, list):
        return []

    parsed: list[dict[str, object]] = []
    by_index = {row.index: row for row in subtitles}
    previous_end = -1.0
    for raw_part in raw_parts:
        if not isinstance(raw_part, dict):
            continue
        start_value = raw_part.get("start_subtitle_index", raw_part.get("start_index"))
        end_value = raw_part.get("end_subtitle_index", raw_part.get("end_index"))
        start_index = _coerce_int(start_value)
        end_index = _coerce_int(end_value)
        if start_index is None or end_index is None:
            continue
        if start_index > end_index:
            start_index, end_index = end_index, start_index
        start_row = by_index.get(start_index)
        end_row = by_index.get(end_index)
        if start_row is None or end_row is None:
            parsed.append(
                {
                    "start_subtitle_index": start_index,
                    "end_subtitle_index": end_index,
                }
            )
            continue
        if end_row.end <= start_row.start or start_row.start < previous_end:
            continue
        parsed.append(
            {
                "start": start_row.start,
                "end": end_row.end,
                "start_subtitle_index": start_index,
                "end_subtitle_index": end_index,
            }
        )
        previous_end = end_row.end
        if len(parsed) >= 4:
            break
    return parsed


def _parse_segment_indices(
    item: dict[str, object],
    subtitles: list[SubtitleEntry],
    parts: list[dict[str, object]],
) -> tuple[int | None, int | None]:
    if parts:
        return (
            _coerce_int(parts[0].get("start_subtitle_index")),
            _coerce_int(parts[-1].get("end_subtitle_index")),
        )

    start_index = _coerce_int(item.get("start_subtitle_index", item.get("start_index")))
    end_index = _coerce_int(item.get("end_subtitle_index", item.get("end_index")))
    if start_index is not None and end_index is not None:
        if start_index > end_index:
            return end_index, start_index
        return start_index, end_index

    if not subtitles:
        return None, None
    start_seconds = _parse_seconds(item.get("start_time", item.get("start")))
    end_seconds = _parse_seconds(item.get("end_time", item.get("end")))
    if start_seconds is None or end_seconds is None:
        return None, None
    start_row = min(subtitles, key=lambda row: abs(row.start - start_seconds))
    end_row = min(subtitles, key=lambda row: abs(row.end - end_seconds))
    return start_row.index, end_row.index


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


def _float_val(value: object) -> float:
    """Safely convert a dict value to float, defaulting to 0.0."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _parse_seconds(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return parse_timecode(value)
        except ValueError:
            try:
                return float(value)
            except ValueError:
                return None
    return None


def subtitles_from_sentences(sentences: list[dict[str, object]]) -> list[SubtitleEntry]:
    """Build typed subtitle entries from preprocessed sentence payloads."""
    subtitles: list[SubtitleEntry] = []
    for item in sentences:
        try:
            index = cast(int | str, item["index"])
            start = cast(float | int | str, item["start"])
            end = cast(float | int | str, item["end"])
            subtitles.append(
                SubtitleEntry(
                    index=int(index),
                    start=float(start),
                    end=float(end),
                    text=str(item["text"]),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("skip_invalid_sentence", item=item, error=str(exc))
    return subtitles


def subtitles_to_sentences(subtitles: list[SubtitleEntry]) -> list[dict[str, object]]:
    """Convert subtitle entries into the JSON payload sent to LLMs."""
    return [
        {
            "index": row.index,
            "start": row.start,
            "end": row.end,
            "text": row.text,
        }
        for row in subtitles
    ]


def subtitle_payload(subtitle: SubtitleEntry) -> dict[str, object]:
    """Build one subtitle payload using old smartclip-compatible fields."""
    return {
        "index": subtitle.index,
        "start_time": format_timecode(subtitle.start, sep="."),
        "end_time": format_timecode(subtitle.end, sep="."),
        "text": subtitle.text,
    }


def postprocess_segments(
    segments: list[ClipSegment],
    subtitles: list[SubtitleEntry],
    ctx: PipelineContext,
) -> list[ClipSegment]:
    """Apply code-level score, overlap and duration policies after LLM planning.

    Mirrors the post-LLM pipeline of the old smartclip project:
    dedupe → split_long_segments (time-based) → filter.
    """
    if not segments:
        return []

    logger.info(
        "postprocess_segments_start",
        run_id=ctx.run_id,
        input_count=len(segments),
    )
    normalized = [normalize_segment_parts(seg, subtitles) for seg in segments]
    filtered = dedupe_segments(normalized, subtitles)
    logger.info(
        "candidates_kept_after_dedupe_score",
        run_id=ctx.run_id,
        segment_count=len(filtered),
    )
    before_score_count = len(filtered)
    filtered = [seg for seg in filtered if seg.score >= ctx.clip_segment_config.min_score]
    logger.info(
        "segments_after_score_filter",
        run_id=ctx.run_id,
        input_count=before_score_count,
        kept_count=len(filtered),
        min_score=ctx.clip_segment_config.min_score,
    )

    # 时间维度拆分长段。旧项目 smart_clip(mode="full") 这里使用 window_seconds
    # 作为 target/max/hard，因此不会把 LLM 规划出的完整主题按 120/150/180 秒强拆。
    if ctx.pipeline_config.clip_plan_mode == "legacy":
        split_target_seconds = PlanClipsStep._max_window_seconds(ctx)
        split_max_seconds = split_target_seconds
        split_hard_max_seconds = split_target_seconds
    else:
        split_target_seconds = ctx.clip_segment_config.target_segment_seconds
        split_max_seconds = ctx.clip_segment_config.max_segment_seconds
        split_hard_max_seconds = ctx.clip_segment_config.hard_max_segment_seconds

    filtered = _split_long_segments_by_duration(
        filtered,
        subtitles,
        target_segment_seconds=split_target_seconds,
        min_segment_seconds=ctx.clip_segment_config.min_segment_seconds,
        max_segment_seconds=split_max_seconds,
        hard_max_segment_seconds=split_hard_max_seconds,
    )
    logger.info(
        "segments_after_max_window_split",
        run_id=ctx.run_id,
        segment_count=len(filtered),
        planner_mode=ctx.pipeline_config.clip_plan_mode,
        max_window_seconds=split_max_seconds,
    )

    return filtered


# ---------------------------------------------------------------------------
# 对齐旧项目 split_long_segments（时间维度拆分）
# ---------------------------------------------------------------------------


def _subtitle_rows_between(
    subtitles: list[SubtitleEntry], start_index: int, end_index: int
) -> list[SubtitleEntry]:
    return [row for row in subtitles if start_index <= row.index <= end_index]


def _pick_split_end(
    rows: list[SubtitleEntry],
    start_pos: int,
    target_segment_seconds: float,
    max_segment_seconds: float,
    hard_max_segment_seconds: float,
) -> int:
    """Pick the best subtitle index to split at, preferring natural boundaries."""
    start_time = rows[start_pos].start
    best_pos = start_pos
    fallback_pos = start_pos
    for pos in range(start_pos, len(rows)):
        duration = rows[pos].end - start_time
        if duration <= hard_max_segment_seconds:
            fallback_pos = pos
            if duration >= target_segment_seconds * 0.75 and _sentence_looks_complete(
                rows[pos].text
            ):
                best_pos = pos
        if duration >= target_segment_seconds and best_pos != start_pos:
            return best_pos
        if duration > max_segment_seconds and best_pos != start_pos:
            return best_pos
        if duration > hard_max_segment_seconds:
            return best_pos if best_pos != start_pos else fallback_pos
    return len(rows) - 1


def _split_part_by_duration(
    part: dict[str, object],
    subtitles: list[SubtitleEntry],
    target_segment_seconds: float,
    max_segment_seconds: float,
    hard_max_segment_seconds: float,
) -> list[dict[str, object]]:
    start_value = _coerce_int(part.get("start_subtitle_index"))
    end_value = _coerce_int(part.get("end_subtitle_index"))
    if start_value is None or end_value is None:
        return []
    rows = _subtitle_rows_between(subtitles, start_value, end_value)
    if not rows:
        return []

    split_parts: list[dict[str, object]] = []
    pos = 0
    while pos < len(rows):
        end_pos = _pick_split_end(
            rows, pos, target_segment_seconds, max_segment_seconds, hard_max_segment_seconds
        )
        start_row = rows[pos]
        end_row = rows[end_pos]
        if end_row.end > start_row.start:
            split_parts.append(
                {
                    "start": start_row.start,
                    "end": end_row.end,
                    "start_subtitle_index": start_row.index,
                    "end_subtitle_index": end_row.index,
                }
            )
        pos = end_pos + 1
    return split_parts


def _clone_segment_with_parts(
    segment: ClipSegment, parts: list[dict[str, object]], title: str
) -> ClipSegment:
    first_start_idx = _coerce_int(parts[0]["start_subtitle_index"])
    last_end_idx = _coerce_int(parts[-1]["end_subtitle_index"])
    if first_start_idx is None or last_end_idx is None:
        return segment
    start_index: int = first_start_idx
    end_index: int = last_end_idx
    # parts 长度 >1 或边界变化时才输出 parts
    same_bounds = (
        len(parts) == 1
        and start_index == segment.start_subtitle_index
        and end_index == segment.end_subtitle_index
    )
    output_parts: list[dict[str, object]] = parts if not same_bounds else []
    return ClipSegment(
        title=title,
        start_subtitle_index=start_index,
        end_subtitle_index=end_index,
        parts=output_parts,
        score=segment.score,
        reason=segment.reason,
        structure_score=segment.structure_score,
        structure_reason=segment.structure_reason,
        hook=segment.hook,
        validation=segment.validation,
        output=segment.output,
        subtitle_output=segment.subtitle_output,
    )


def _split_long_segments_by_duration(
    segments: list[ClipSegment],
    subtitles: list[SubtitleEntry],
    target_segment_seconds: float = 120.0,
    min_segment_seconds: float = 90.0,
    max_segment_seconds: float = 150.0,
    hard_max_segment_seconds: float = 180.0,
) -> list[ClipSegment]:
    """Split segments that exceed max_segment_seconds at natural boundaries.

    Mirrors the old project's split_long_segments() in segmenter.py.
    """
    target_segment_seconds = max(1.0, target_segment_seconds)
    min_segment_seconds = max(1.0, min_segment_seconds)
    max_segment_seconds = max(min_segment_seconds, max_segment_seconds)
    hard_max_segment_seconds = max(max_segment_seconds, hard_max_segment_seconds)

    split_segments: list[ClipSegment] = []
    for segment in segments:
        seg_duration = _part_segment_duration(segment, subtitles)
        if seg_duration <= max_segment_seconds:
            split_segments.append(segment)
            continue

        source_parts = segment.parts or [
            {
                "start": 0.0,
                "end": 0.0,
                "start_subtitle_index": segment.start_subtitle_index,
                "end_subtitle_index": segment.end_subtitle_index,
            }
        ]
        atomic_parts: list[dict[str, object]] = []
        for part in source_parts:
            if part.get("start_subtitle_index") is None or part.get("end_subtitle_index") is None:
                continue
            atomic_parts.extend(
                _split_part_by_duration(
                    part,
                    subtitles,
                    target_segment_seconds,
                    max_segment_seconds,
                    hard_max_segment_seconds,
                )
            )

        # Group atomic parts into segments
        grouped: list[list[dict[str, object]]] = []
        current: list[dict[str, object]] = []
        current_duration = 0.0
        for part in atomic_parts:
            part_duration = max(0.0, _float_val(part["end"]) - _float_val(part["start"]))
            if (
                current
                and current_duration >= min(SPLIT_MIN_SECONDS, min_segment_seconds)
                and current_duration + part_duration > hard_max_segment_seconds
            ):
                grouped.append(current)
                current = []
                current_duration = 0.0
            current.append(part)
            current_duration += part_duration

        if current:
            previous_duration = (
                sum(max(0.0, _float_val(p["end"]) - _float_val(p["start"])) for p in grouped[-1])
                if grouped
                else 0.0
            )
            if (
                grouped
                and current_duration < min_segment_seconds
                and previous_duration + current_duration <= hard_max_segment_seconds
            ):
                grouped[-1].extend(current)
            else:
                grouped.append(current)

        if len(grouped) <= 1:
            split_segments.append(segment)
            continue

        for idx, parts in enumerate(grouped, start=1):
            split_segments.append(
                _clone_segment_with_parts(segment, parts, f"{segment.title}_{idx}")
            )
    return split_segments


def _extract_items(raw: str, keys: tuple[str, ...]) -> list[dict[str, object]]:
    data = extract_json_value(raw)
    logger.info(
        "llm_items_parse",
        parsed_type=type(data).__name__ if data is not None else "None",
        response_len=len(raw),
    )
    if isinstance(data, dict):
        raw_items = None
        for key in keys:
            raw_items = data.get(key)
            if raw_items:
                break
    elif isinstance(data, list):
        raw_items = data
    else:
        recovered = _extract_partial_array_items(raw, keys)
        logger.info(
            "llm_items_partial_recovery",
            recovered_count=len(recovered),
            response_looks_truncated=_looks_truncated_json(raw),
        )
        return recovered
    items = (
        [item for item in raw_items if isinstance(item, dict)]
        if isinstance(raw_items, list)
        else []
    )
    if not items:
        recovered = _extract_partial_array_items(raw, keys)
        if recovered:
            logger.info(
                "llm_items_partial_recovery",
                recovered_count=len(recovered),
                response_looks_truncated=_looks_truncated_json(raw),
            )
            return recovered
    return items


def _looks_truncated_json(raw: str) -> bool:
    stripped = raw.rstrip()
    if not stripped:
        return False
    return stripped[-1] not in ("}", "]")


def _extract_partial_array_items(raw: str, keys: tuple[str, ...]) -> list[dict[str, object]]:
    """Recover complete objects from a truncated top-level item array."""
    for key in keys:
        items = _extract_partial_array_items_for_key(raw, key)
        if items:
            return items
    return []


def _extract_partial_array_items_for_key(raw: str, key: str) -> list[dict[str, object]]:
    marker_index = raw.find(f'"{key}"')
    if marker_index < 0:
        return []

    array_start = raw.find("[", marker_index)
    if array_start < 0:
        return []

    decoder = json.JSONDecoder()
    items: list[dict[str, object]] = []
    pos = array_start + 1
    while pos < len(raw):
        while pos < len(raw) and raw[pos] in " \t\r\n,":
            pos += 1
        if pos >= len(raw) or raw[pos] == "]":
            break
        try:
            value, offset = decoder.raw_decode(raw[pos:])
        except json.JSONDecodeError:
            break
        if isinstance(value, dict):
            items.append(cast(dict[str, object], value))
        pos += offset
    return items


class PlanClipsStep(BaseStep):
    """切片方案规划步骤。

    加载 Prompt 模板 -> 渲染配置 -> 调用 LLM -> 解析响应 -> 去重拆分 -> 保存方案。
    支持两种模式:
    - legacy: 两阶段（结构分析 → 逐候选精修），对齐旧项目 smart_clip(mode="full")
    - full:   单次全量字幕分析

    可通过 ctx.metadata["prompt_dump_dir"] 设置 prompt dump 目录。
    """

    def __init__(
        self,
        llm_client: LLMClient | None = None,
        prompt_template: PromptTemplate | None = None,
    ) -> None:
        self._llm_client = llm_client or LLMClient()
        self._prompt_template = prompt_template
        self._dump_counter: int = 0

    @property
    def name(self) -> StepName:
        return StepName.PLAN_CLIPS

    # ------------------------------------------------------------------
    # Prompt dump helper
    # ------------------------------------------------------------------

    def _dump_dir(self, ctx: PipelineContext) -> Path | None:
        d = ctx.metadata.get("prompt_dump_dir") or os.environ.get("LIVECLIP_LLM_DUMP_DIR")
        return Path(d) if d else None

    def _dump_llm(
        self,
        ctx: PipelineContext,
        tag: str,
        system_prompt: str,
        user_prompt: str,
        response: str = "",
    ) -> None:
        dump_dir = self._dump_dir(ctx)
        if dump_dir is None:
            return
        dump_dir.mkdir(parents=True, exist_ok=True)
        self._dump_counter += 1
        prefix = f"{self._dump_counter:03d}_{tag}"
        _ = (dump_dir / f"{prefix}_system.txt").write_text(system_prompt, encoding="utf-8")
        _ = (dump_dir / f"{prefix}_user.json").write_text(user_prompt, encoding="utf-8")
        if response:
            _ = (dump_dir / f"{prefix}_response.txt").write_text(response, encoding="utf-8")
        logger.info("llm_dump_written", dump_dir=str(dump_dir), tag=tag, prefix=prefix)

    def execute(self, ctx: PipelineContext) -> StepResult:
        """执行切片方案规划。"""
        start_ms = time.monotonic_ns() // 1_000_000
        logger.info("plan_clips_start", run_id=ctx.run_id)
        raw_response: str | None = None

        try:
            self._check_cancelled(ctx)

            subtitles, subtitle_source = self._load_planning_subtitles(ctx)
            sentences = subtitles_to_sentences(subtitles)
            LocalStorage.write_json(
                ctx.paths.sentences_json_path,
                {
                    "sentences": sentences,
                    "subtitle_source": subtitle_source,
                    "index_space": subtitle_source,
                },
            )

            if not sentences:
                raise ClipPlanError(
                    CLIP_PLAN_INVALID,
                    "句子数据为空，无法生成切片方案",
                    details={"run_id": ctx.run_id},
                )

            self._check_cancelled(ctx)

            segments, raw_response, planner_mode = self._plan_segments(
                ctx,
                subtitles,
                sentences,
            )

            LocalStorage.write_json(
                ctx.paths.raw_llm_response_path,
                {"raw_response": raw_response},
            )

            if not segments:
                raise ClipPlanError(
                    CLIP_PLAN_INVALID,
                    "LLM 未生成有效的切片段",
                    details={"run_id": ctx.run_id},
                )

            segments = postprocess_segments(segments, subtitles, ctx)
            if not segments:
                raise ClipPlanError(
                    CLIP_PLAN_INVALID,
                    "LLM 生成的切片段未通过评分/时长过滤",
                    details={"run_id": ctx.run_id},
                )

            plan_result = ClipPlanResult(
                segments=segments,
                subtitle_source=subtitle_source,
                index_space=subtitle_source,
                planner_mode=planner_mode,
            )
            LocalStorage.write_json(
                ctx.paths.normalized_plan_path,
                plan_result.model_dump(),
            )

            elapsed = time.monotonic_ns() // 1_000_000 - start_ms
            logger.info(
                "plan_clips_done",
                run_id=ctx.run_id,
                segment_count=len(segments),
                elapsed_ms=elapsed,
            )

            return StepResult(
                success=True,
                output_path=str(ctx.paths.normalized_plan_path),
                duration_ms=elapsed,
                metadata={
                    "segment_count": len(segments),
                    "raw_response_path": str(ctx.paths.raw_llm_response_path),
                    "normalized_plan_path": str(ctx.paths.normalized_plan_path),
                    "subtitle_source": subtitle_source,
                    "planner_mode": planner_mode,
                },
            )

        except (ClipPlanError, LLMError) as exc:
            if raw_response is not None:
                LocalStorage.write_json(
                    ctx.paths.raw_llm_response_path,
                    {
                        "raw_response": raw_response,
                        "error_code": getattr(exc, "error_code", None),
                        "error_message": str(exc),
                    },
                )
            raise
        except Exception as exc:
            elapsed = time.monotonic_ns() // 1_000_000 - start_ms
            logger.error("plan_clips_failed", run_id=ctx.run_id, error=str(exc))
            raise ClipPlanError(
                CLIP_PLAN_INVALID,
                f"切片方案规划失败: {exc}",
                details={"run_id": ctx.run_id, "error": str(exc)},
            ) from exc

    def _build_prompt(self, ctx: PipelineContext, sentences: list[dict[str, object]]) -> str:
        """构建 LLM Prompt。"""
        if self._prompt_template is not None:
            return self._prompt_template.render(
                sentences=sentences,
                clip_config=ctx.clip_segment_config.model_dump(),
            )

        sentences_text = json.dumps(sentences, ensure_ascii=False, indent=2)
        prompt = self._render_full_prompt(ctx)
        return f"{prompt}\n\n字幕内容：\n{sentences_text}"

    def _render_full_prompt(self, ctx: PipelineContext) -> str:
        """Render the old smartclip full-video prompt with configured durations."""
        max_window_seconds = (
            ctx.record_config.max_duration_seconds
            if ctx.record_config.max_duration_seconds > 0
            else 7200
        )
        return (
            PROMPT_FULL_CLIP_TEMPLATE.replace(
                "{target_segment_seconds}",
                str(int(ctx.clip_segment_config.target_segment_seconds)),
            )
            .replace("{min_segment_seconds}", str(int(ctx.clip_segment_config.min_segment_seconds)))
            .replace("{max_segment_seconds}", str(int(ctx.clip_segment_config.max_segment_seconds)))
            .replace(
                "{hard_max_segment_seconds}",
                str(int(ctx.clip_segment_config.hard_max_segment_seconds)),
            )
            .replace("{max_window_seconds}", str(int(max_window_seconds)))
        )

    def _load_planning_subtitles(self, ctx: PipelineContext) -> tuple[list[SubtitleEntry], str]:
        """Load subtitles in the index space requested by the planning config."""
        source = ctx.pipeline_config.clip_plan_subtitle_source
        if source not in {"raw", "processed"}:
            source = "raw"

        if source == "raw":
            raw_subtitles = self._load_raw_subtitles(ctx)
            if raw_subtitles:
                return raw_subtitles, "raw"

        processed_result = ctx.get_step_result(str(StepName.PREPROCESS_SUBTITLE))
        if processed_result and processed_result.output_path:
            processed_path = Path(processed_result.output_path)
            if processed_path.exists():
                subtitles = parse_srt_file(processed_path)
                if subtitles:
                    return subtitles, "processed"

        raw_subtitles = self._load_raw_subtitles(ctx)
        if raw_subtitles:
            return raw_subtitles, "raw"

        sentences_data = LocalStorage.read_json(ctx.paths.sentences_json_path)
        return subtitles_from_sentences(sentences_data.get("sentences", [])), "processed"

    @staticmethod
    def _load_raw_subtitles(ctx: PipelineContext) -> list[SubtitleEntry]:
        transcribe_result = ctx.get_step_result(str(StepName.TRANSCRIBE))
        if transcribe_result and transcribe_result.output_path:
            transcribe_path = Path(transcribe_result.output_path)
            if transcribe_path.exists():
                subtitles = parse_srt_file(transcribe_path)
                if subtitles:
                    return subtitles
        return []

    def _plan_segments(
        self,
        ctx: PipelineContext,
        subtitles: list[SubtitleEntry],
        sentences: list[dict[str, object]],
    ) -> tuple[list[ClipSegment], str, str]:
        if self._prompt_template is not None or ctx.pipeline_config.clip_plan_mode != "legacy":
            raw_response = self._call_full_prompt(ctx, subtitles, sentences)
            LocalStorage.write_json(
                ctx.paths.raw_llm_response_path,
                {"raw_response": raw_response, "planner_mode": "full"},
            )
            return parse_llm_response(raw_response, subtitles), raw_response, "full"

        legacy_segments, legacy_raw = self._plan_segments_legacy(ctx, subtitles)
        if legacy_segments:
            return legacy_segments, legacy_raw, "legacy"

        raw_response = self._call_full_prompt(ctx, subtitles, sentences)
        LocalStorage.write_json(
            ctx.paths.raw_llm_response_path,
            {"raw_response": raw_response, "planner_mode": "full_fallback"},
        )
        return parse_llm_response(raw_response, subtitles), raw_response, "full_fallback"

    def _call_full_prompt(
        self,
        ctx: PipelineContext,
        subtitles: list[SubtitleEntry],
        sentences: list[dict[str, object]],
    ) -> str:
        logger.info("calling_llm_full", run_id=ctx.run_id, sentence_count=len(sentences))
        if self._prompt_template is not None:
            prompt = self._build_prompt(ctx, sentences)
            return self._llm_client.chat(
                prompt=prompt,
                temperature=ctx.llm_call_config.temperature,
                max_tokens=max(ctx.llm_call_config.max_tokens, PLAN_LLM_MAX_TOKENS),
                timeout_seconds=max(ctx.llm_call_config.timeout_seconds, 180),
                max_retries=ctx.llm_call_config.max_retries,
                json_mode=True,
            )

        payload = {
            "video_start": format_timecode(subtitles[0].start, sep=".")
            if subtitles
            else "00:00:00.000",
            "video_end": format_timecode(subtitles[-1].end, sep=".")
            if subtitles
            else "00:00:00.000",
            "subtitles": [subtitle_payload(row) for row in subtitles],
        }
        system_prompt = self._render_full_prompt(ctx)
        user_prompt = json.dumps(payload, ensure_ascii=False)
        self._dump_llm(ctx, "full_system", system_prompt, user_prompt)

        response = self._llm_client.chat(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=ctx.llm_call_config.temperature,
            max_tokens=max(ctx.llm_call_config.max_tokens, PLAN_LLM_MAX_TOKENS),
            timeout_seconds=max(ctx.llm_call_config.timeout_seconds, 180),
            max_retries=ctx.llm_call_config.max_retries,
            json_mode=True,
        )
        self._dump_llm(ctx, "full_response", "", "", response=response)
        return response

    def _plan_segments_legacy(
        self,
        ctx: PipelineContext,
        subtitles: list[SubtitleEntry],
    ) -> tuple[list[ClipSegment], str]:
        """旧项目两阶段流程: structure analysis → refine each candidate."""
        user_payload = json.dumps(
            {
                "video_start": format_timecode(subtitles[0].start, sep="."),
                "video_end": format_timecode(subtitles[-1].end, sep="."),
                "subtitles": [subtitle_payload(row) for row in subtitles],
            },
            ensure_ascii=False,
        )

        # Phase 1: 结构分析
        logger.info(
            "legacy_structure_start",
            run_id=ctx.run_id,
            subtitle_count=len(subtitles),
        )
        self._dump_llm(ctx, "structure_system", PROMPT_LIVE_STRUCTURE_TEMPLATE, user_payload)

        raw_structure = self._llm_client.chat(
            system_prompt=PROMPT_LIVE_STRUCTURE_TEMPLATE,
            user_prompt=user_payload,
            temperature=ctx.llm_call_config.temperature,
            max_tokens=max(ctx.llm_call_config.max_tokens, PLAN_LLM_MAX_TOKENS),
            timeout_seconds=max(ctx.llm_call_config.timeout_seconds, 180),
            max_retries=ctx.llm_call_config.max_retries,
            json_mode=True,
        )
        self._dump_llm(ctx, "structure_response", "", "", response=raw_structure)

        candidates = _extract_items(raw_structure, ("clips", "candidates", "segments"))
        logger.info(
            "legacy_structure_done",
            run_id=ctx.run_id,
            candidate_count=len(candidates),
        )
        for i, c in enumerate(candidates, start=1):
            topic = c.get("topic", "?")
            si = c.get("start_subtitle_index", "?")
            ei = c.get("end_subtitle_index", "?")
            logger.info(f"  candidate [{i}/{len(candidates)}]: {topic} [{si}..{ei}]")

        # Phase 2: 逐候选精修
        refined: list[ClipSegment] = []
        refine_raw: list[str] = []
        refined_candidate_count = 0
        for index, candidate in enumerate(candidates, start=1):
            self._check_cancelled(ctx)
            topic = candidate.get("topic", f"候选{index}")
            logger.info(
                "legacy_refine_start",
                run_id=ctx.run_id,
                index=index,
                total=len(candidates),
                topic=topic,
            )
            refined_segments, raw = self._refine_candidate(ctx, candidate, subtitles)
            refine_raw.append(raw)
            refined.extend(refined_segments)
            if refined_segments:
                refined_candidate_count += 1
            logger.info(
                "legacy_refine_done",
                run_id=ctx.run_id,
                index=index,
                segment_count=len(refined_segments),
            )
        logger.info(
            "legacy_refine_summary",
            run_id=ctx.run_id,
            candidate_count=len(candidates),
            refined_candidate_count=refined_candidate_count,
            refined_segment_count=len(refined),
            dropped_candidate_count=max(0, len(candidates) - refined_candidate_count),
        )

        # Fallback: 精修未产出时直接用候选
        if not refined:
            logger.info(
                "legacy_fallback_direct",
                run_id=ctx.run_id,
                candidate_count=len(candidates),
            )
            for candidate in candidates:
                fallback = parse_llm_response(
                    json.dumps({"segments": [{**candidate, "keep": True}]}, ensure_ascii=False),
                    subtitles,
                )
                refined.extend(fallback)

        raw_response = json.dumps(
            {
                "structure_response": raw_structure,
                "refine_responses": refine_raw,
                "segments": [segment.model_dump() for segment in refined],
            },
            ensure_ascii=False,
        )
        return refined, raw_response

    def _refine_candidate(
        self,
        ctx: PipelineContext,
        candidate: dict[str, object],
        subtitles: list[SubtitleEntry],
    ) -> tuple[list[ClipSegment], str]:
        start_index = _coerce_int(
            candidate.get("start_subtitle_index", candidate.get("start_index"))
        )
        end_index = _coerce_int(candidate.get("end_subtitle_index", candidate.get("end_index")))
        if start_index is None or end_index is None:
            logger.warning("refine_skip_invalid_indices", candidate_topic=candidate.get("topic"))
            return [], ""

        max_subtitle_index = max((row.index for row in subtitles), default=0)
        lower = max(0, start_index - 6)
        upper = min(max_subtitle_index, end_index + 10)
        rows = [row for row in subtitles if lower <= row.index <= upper]
        payload = {
            "candidate": candidate,
            "constraints": {
                "target_segment_seconds": ctx.clip_segment_config.target_segment_seconds,
                "min_segment_seconds": ctx.clip_segment_config.min_segment_seconds,
                "max_segment_seconds": ctx.clip_segment_config.max_segment_seconds,
                "hard_max_segment_seconds": ctx.clip_segment_config.hard_max_segment_seconds,
                "max_window_seconds": self._max_window_seconds(ctx),
            },
            "context_subtitles": [subtitle_payload(row) for row in rows],
        }
        prompt = (
            PROMPT_REFINE_TOPIC_TEMPLATE.replace(
                "{target_segment_seconds}", str(int(ctx.clip_segment_config.target_segment_seconds))
            )
            .replace("{min_segment_seconds}", str(int(ctx.clip_segment_config.min_segment_seconds)))
            .replace("{max_segment_seconds}", str(int(ctx.clip_segment_config.max_segment_seconds)))
            .replace(
                "{hard_max_segment_seconds}",
                str(int(ctx.clip_segment_config.hard_max_segment_seconds)),
            )
        )
        user_payload = json.dumps(payload, ensure_ascii=False)
        tag = f"refine_{_safe_tag(str(candidate.get('topic', '')))}"
        self._dump_llm(ctx, tag + "_system", prompt, user_payload)

        try:
            raw = self._llm_client.chat(
                system_prompt=prompt,
                user_prompt=user_payload,
                temperature=ctx.llm_call_config.temperature,
                max_tokens=max(ctx.llm_call_config.max_tokens, REFINE_LLM_MAX_TOKENS),
                timeout_seconds=75,
                max_retries=ctx.llm_call_config.max_retries,
                json_mode=True,
            )
            self._dump_llm(ctx, tag + "_response", "", "", response=raw)
        except LLMError as exc:
            logger.warning(
                "refine_llm_failed", candidate_topic=candidate.get("topic"), error=str(exc)
            )
            fallback = parse_llm_response(
                json.dumps({"segments": [{**candidate, "keep": True}]}, ensure_ascii=False),
                subtitles,
            )
            return fallback, ""
        try:
            return parse_llm_response(raw, subtitles), raw
        except LLMError as exc:
            logger.warning(
                "refine_parse_failed",
                candidate_topic=candidate.get("topic"),
                error=str(exc),
                raw_preview=raw[:500],
            )
            return [], raw

    @staticmethod
    def _max_window_seconds(ctx: PipelineContext) -> float:
        return float(ctx.record_config.max_duration_seconds or 7200)


def _safe_tag(text: str, max_len: int = 40) -> str:
    """Create a safe filename tag from topic text."""
    if not text:
        return "unknown"
    cleaned = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in text).strip("_")
    return (cleaned or "unknown")[:max_len]
