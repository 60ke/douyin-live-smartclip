"""切片边界校验步骤：代码边界对齐 + 可选 LLM 校验。"""

from __future__ import annotations

import json
import time

from liveclip.adapters.llm import LLMClient
from liveclip.domain.enums import StepName
from liveclip.domain.models import ClipPlanResult, ClipSegment, StepResult, SubtitleEntry
from liveclip.exceptions import BOUNDARY_VALIDATE_FAILED, BoundaryError
from liveclip.observability import get_logger
from liveclip.pipeline.context import PipelineContext
from liveclip.pipeline.steps.base import BaseStep
from liveclip.storage.local import LocalStorage
from liveclip.subtitle.boundary import (
    snap_parts_boundaries,
    snap_segment_to_subtitles,
)
from liveclip.subtitle.parser import parse_srt_file
from liveclip.subtitle.parts import segment_duration_seconds
from liveclip.subtitle.sentence_merge import end_boundary_quality, looks_complete
from liveclip.utils.json import extract_json_object
from liveclip.utils.timecode import format_timecode

logger = get_logger(__name__)

PROMPT_VALIDATE_BOUNDARY = """你是短视频切片边界质检员。只判断片段开头和结尾是否完整。

要求：
- 开头必须像一个自然小段开始。
- 结尾必须停在完整表达结束处，不能把下一段开头带进来。
- 只允许调整到给定字幕列表中的 subtitle index。
- 如果当前边界已经自然，返回 passed=true，action="keep"。
- 如果需要调整，返回 passed=false，并给出 action 和目标 subtitle index。
- action 只能是：keep / adjust_start / adjust_end / adjust_both / reject。
- 如果 action 是 adjust_start 或 adjust_both，必须返回 target_start_subtitle_index。
- 如果 action 是 adjust_end 或 adjust_both，必须返回 target_end_subtitle_index。
- 如果 action 是 reject，必须在 reason 中说明为什么无法修复。

返回 schema：
{
  "passed": true,
  "action": "keep",
  "target_start_subtitle_index": null,
  "target_end_subtitle_index": null,
  "reason": "边界自然，无需调整"
}

返回纯 JSON 对象，不要 Markdown。第一个字符必须是 {。
"""


def snap_segment_boundaries(
    segments: list[ClipSegment],
    subtitles: list[SubtitleEntry],
) -> list[ClipSegment]:
    """将切片边界对齐到完整字幕条目（对齐旧项目 snap_segment_to_subtitles）。

    确保 start_subtitle_index 和 end_subtitle_index 在有效范围内，
    且相邻段之间不重叠。使用前向填充/后向修剪逻辑。

    Args:
        segments: 原始切片段列表。
        subtitles: 字幕条目列表。

    Returns:
        边界对齐后的切片段列表。
    """
    if not subtitles or not segments:
        return segments

    max_index = max(e.index for e in subtitles)
    min_index = min(e.index for e in subtitles)
    snapped: list[ClipSegment] = []

    for seg in segments:
        if seg.parts:
            snapped.append(snap_parts_boundaries(seg, subtitles))
            continue

        # 先确保在有效范围
        start = max(min_index, min(seg.start_subtitle_index, max_index))
        end = max(min_index, min(seg.end_subtitle_index, max_index))
        if start > end:
            start, end = end, start
        if end < start:
            continue

        seg.start_subtitle_index = start
        seg.end_subtitle_index = end

        # 对齐旧项目: 前向填充/后向修剪
        aligned = snap_segment_to_subtitles(seg, subtitles)
        snapped.append(aligned)

    # 消除重叠
    for i in range(1, len(snapped)):
        if snapped[i].parts or snapped[i - 1].parts:
            continue
        if snapped[i].start_subtitle_index <= snapped[i - 1].end_subtitle_index:
            new_start = snapped[i - 1].end_subtitle_index + 1
            if new_start > snapped[i].end_subtitle_index:
                continue
            snapped[i] = ClipSegment(
                title=snapped[i].title,
                start_subtitle_index=new_start,
                end_subtitle_index=snapped[i].end_subtitle_index,
                parts=snapped[i].parts,
                score=snapped[i].score,
                reason=snapped[i].reason,
                structure_score=snapped[i].structure_score,
                structure_reason=snapped[i].structure_reason,
                hook=snapped[i].hook,
                validation=snapped[i].validation,
                output=snapped[i].output,
                subtitle_output=snapped[i].subtitle_output,
            )

    return snapped


def _filter_short_segments_with_report(
    segments: list[ClipSegment],
    subtitles: list[SubtitleEntry],
    min_seconds: float,
    high_score_threshold: float,
) -> tuple[list[ClipSegment], list[dict[str, object]]]:
    """Filter short segments and return structured drop reasons for diagnostics."""
    if not subtitles:
        return segments, []

    kept: list[ClipSegment] = []
    filtered: list[dict[str, object]] = []
    for index, seg in enumerate(segments, start=1):
        duration = segment_duration_seconds(seg, subtitles)
        reason: str | None = None
        if duration < min_seconds and seg.score < high_score_threshold:
            reason = "duration_below_min_seconds_and_score_low"

        if reason is None:
            kept.append(seg)
            continue

        filtered.append(
            {
                "index": index,
                "title": seg.title,
                "start_subtitle_index": seg.start_subtitle_index,
                "end_subtitle_index": seg.end_subtitle_index,
                "duration_seconds": round(duration, 3),
                "score": seg.score,
                "reason": reason,
            }
        )

    return kept, filtered


class ValidateBoundaryStep(BaseStep):
    """切片边界校验步骤。

    加载方案 -> 代码边界对齐 -> 可选 LLM 校验 -> 保存校验后方案。
    当 pipeline_config.validate_boundary_use_llm 为 True 时，
    额外调用 LLM 对边界进行语义校验。
    """

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm_client = llm_client

    @property
    def name(self) -> StepName:
        return StepName.VALIDATE_BOUNDARY

    def execute(self, ctx: PipelineContext) -> StepResult:
        """执行边界校验。"""
        start_ms = time.monotonic_ns() // 1_000_000
        logger.info("validate_boundary_start", run_id=ctx.run_id)

        try:
            self._check_cancelled(ctx)

            plan_data = LocalStorage.read_json(ctx.paths.normalized_plan_path)
            plan_result = ClipPlanResult.model_validate(plan_data)
            segments = plan_result.segments

            if not segments:
                raise BoundaryError(
                    BOUNDARY_VALIDATE_FAILED,
                    "切片方案为空，无法校验边界",
                    details={"run_id": ctx.run_id},
                )

            from pathlib import Path

            preprocess_result = ctx.get_step_result(str(StepName.PREPROCESS_SUBTITLE))
            transcribe_result = ctx.get_step_result(str(StepName.TRANSCRIBE))
            if plan_result.index_space == "processed":
                srt_path = (
                    preprocess_result.output_path
                    if preprocess_result and preprocess_result.output_path
                    else None
                )
            else:
                srt_path = (
                    transcribe_result.output_path
                    if transcribe_result and transcribe_result.output_path
                    else None
                )
            if srt_path is None and preprocess_result and preprocess_result.output_path:
                srt_path = preprocess_result.output_path
            if srt_path is None and transcribe_result and transcribe_result.output_path:
                srt_path = transcribe_result.output_path
            subtitles: list[SubtitleEntry] = []
            if srt_path:
                subtitles = parse_srt_file(Path(srt_path))

            self._check_cancelled(ctx)

            if ctx.pipeline_config.validate_boundary_use_llm and self._llm_client is not None:
                validated = self._llm_validate(ctx, segments, subtitles)
            else:
                validated = snap_segment_boundaries(segments, subtitles)
                logger.info(
                    "boundaries_snapped",
                    run_id=ctx.run_id,
                    original=len(segments),
                    validated=len(validated),
                )

            validated = trim_overlaps_to_previous_complete_end(validated, subtitles)
            min_seconds = (
                min(
                    ctx.clip_segment_config.min_export_segment_seconds,
                    ctx.clip_segment_config.min_segment_seconds,
                )
                if plan_result.planner_mode == "legacy"
                else ctx.clip_segment_config.min_segment_seconds
            )
            high_score_threshold = ctx.clip_segment_config.export_high_score_threshold
            validated, filtered_out = _filter_short_segments_with_report(
                validated,
                subtitles,
                min_seconds=min_seconds,
                high_score_threshold=high_score_threshold,
            )
            if filtered_out:
                logger.info(
                    "segments_filtered_out",
                    run_id=ctx.run_id,
                    count=len(filtered_out),
                    min_seconds=min_seconds,
                    high_score_threshold=high_score_threshold,
                    segments=filtered_out,
                )

            validated_plan = ClipPlanResult(
                segments=validated,
                subtitle_source=plan_result.subtitle_source,
                index_space=plan_result.index_space,
                planner_mode=plan_result.planner_mode,
            )
            LocalStorage.write_json(
                ctx.paths.validated_plan_path,
                validated_plan.model_dump(),
            )

            LocalStorage.write_json(
                ctx.paths.boundary_report_path,
                {
                    "original_count": len(segments),
                    "validated_count": len(validated),
                    "use_llm": ctx.pipeline_config.validate_boundary_use_llm,
                    "filter_thresholds": {
                        "min_seconds": min_seconds,
                        "high_score_threshold": high_score_threshold,
                    },
                    "filtered_out": filtered_out,
                },
            )

            elapsed = time.monotonic_ns() // 1_000_000 - start_ms
            logger.info(
                "validate_boundary_done",
                run_id=ctx.run_id,
                segment_count=len(validated),
                elapsed_ms=elapsed,
            )

            return StepResult(
                success=True,
                output_path=str(ctx.paths.validated_plan_path),
                duration_ms=elapsed,
                metadata={
                    "original_count": len(segments),
                    "validated_count": len(validated),
                    "use_llm": ctx.pipeline_config.validate_boundary_use_llm,
                },
            )

        except BoundaryError:
            raise
        except Exception as exc:
            elapsed = time.monotonic_ns() // 1_000_000 - start_ms
            logger.error("validate_boundary_failed", run_id=ctx.run_id, error=str(exc))
            raise BoundaryError(
                BOUNDARY_VALIDATE_FAILED,
                f"边界校验失败: {exc}",
                details={"run_id": ctx.run_id, "error": str(exc)},
            ) from exc

    def _llm_validate(
        self,
        ctx: PipelineContext,
        segments: list[ClipSegment],
        subtitles: list[SubtitleEntry],
    ) -> list[ClipSegment]:
        """Validate each segment boundary with the old smartclip per-segment flow."""
        logger.info("llm_boundary_validation", run_id=ctx.run_id, segment_count=len(segments))

        llm_client = self._llm_client
        if llm_client is None:
            return segments

        validated: list[ClipSegment] = []
        for index, segment in enumerate(segments, start=1):
            self._check_cancelled(ctx)
            logger.info(
                "llm_boundary_segment_start",
                run_id=ctx.run_id,
                index=index,
                total=len(segments),
                title=segment.title,
            )
            validated.append(self._validate_one_boundary(llm_client, segment, subtitles))
        logger.info(
            "llm_boundary_segments_done",
            run_id=ctx.run_id,
            segment_count=len(validated),
        )
        return validated

    def _validate_one_boundary(
        self,
        llm_client: LLMClient,
        segment: ClipSegment,
        subtitles: list[SubtitleEntry],
    ) -> ClipSegment:
        if segment.parts:
            segment.validation.setdefault("passed", True)
            segment.validation["validator"] = "parts_code_boundary_snap"
            return snap_parts_boundaries(segment, subtitles)

        payload = {
            "title": segment.title,
            "current_start_time": format_timecode(
                _segment_start_seconds(segment, _by_index(subtitles)), sep="."
            ),
            "current_end_time": format_timecode(
                _segment_end_seconds(segment, _by_index(subtitles)), sep="."
            ),
            **_subtitle_context(subtitles, segment),
        }
        user_prompt = json.dumps(payload, ensure_ascii=False)
        try:
            raw = llm_client.chat(
                system_prompt=PROMPT_VALIDATE_BOUNDARY,
                user_prompt=user_prompt,
                temperature=0.2,
                max_tokens=700,
                timeout_seconds=60,
            )
            data = extract_json_object(raw) or {
                "passed": False,
                "reason": "validator parse failed",
            }
        except Exception as exc:
            data = {
                "passed": False,
                "fallback": True,
                "reason": f"boundary validator unavailable: {exc.__class__.__name__}: {exc}",
            }

        segment.validation.update(data)
        target_start = data.get("target_start_subtitle_index", data.get("target_start_index"))
        target_end = data.get("target_end_subtitle_index", data.get("target_end_index"))
        if target_start:
            segment.start_subtitle_index = int(target_start)
        if target_end:
            segment.end_subtitle_index = int(target_end)
        return snap_segment_to_subtitles(segment, subtitles)


def _subtitle_payload(subtitle: SubtitleEntry) -> dict[str, object]:
    return {
        "index": subtitle.index,
        "start_time": format_timecode(subtitle.start, sep="."),
        "end_time": format_timecode(subtitle.end, sep="."),
        "text": subtitle.text,
    }


def _subtitle_context(
    subtitles: list[SubtitleEntry],
    segment: ClipSegment,
    radius: int = 4,
) -> dict[str, object]:
    if not subtitles:
        return {"start_index": 0, "end_index": 0, "head_context": [], "tail_context": []}
    by_index = _by_index(subtitles)
    start_time = _segment_start_seconds(segment, by_index)
    end_time = _segment_end_seconds(segment, by_index)
    start_pos = min(range(len(subtitles)), key=lambda i: abs(subtitles[i].start - start_time))
    end_pos = min(range(len(subtitles)), key=lambda i: abs(subtitles[i].end - end_time))
    head = subtitles[max(0, start_pos - radius) : min(len(subtitles), start_pos + radius + 1)]
    tail = subtitles[max(0, end_pos - radius) : min(len(subtitles), end_pos + radius + 1)]
    return {
        "start_index": subtitles[start_pos].index,
        "end_index": subtitles[end_pos].index,
        "head_context": [_subtitle_payload(row) for row in head],
        "tail_context": [_subtitle_payload(row) for row in tail],
    }


def _by_index(subtitles: list[SubtitleEntry]) -> dict[int, SubtitleEntry]:
    return {row.index: row for row in subtitles}


def trim_overlaps_to_previous_complete_end(
    segments: list[ClipSegment],
    subtitles: list[SubtitleEntry],
) -> list[ClipSegment]:
    """Trim a segment that runs into the next segment back to a complete ending."""
    if not segments or not subtitles:
        return segments

    by_index = {row.index: row for row in subtitles}
    ordered = sorted(segments, key=lambda item: _segment_start_seconds(item, by_index))
    result = list(ordered)
    for idx in range(len(result) - 1):
        current = result[idx]
        next_segment = result[idx + 1]
        current_end = _segment_end_seconds(current, by_index)
        next_start = _segment_start_seconds(next_segment, by_index)
        if (
            current_end < next_start
            and current.end_subtitle_index < next_segment.start_subtitle_index
        ):
            continue

        fallback: SubtitleEntry | None = None
        for row in reversed(subtitles):
            if row.index >= next_segment.start_subtitle_index:
                continue
            if row.end <= _segment_start_seconds(current, by_index):
                break
            if not looks_complete(row.text):
                continue
            if end_boundary_quality(row.text) == "strong":
                fallback = row
                break
            if fallback is None:
                fallback = row
        if fallback is None:
            continue
        if current.parts:
            current.parts = []
        current.end_subtitle_index = fallback.index

    return [
        segment
        for segment in result
        if _segment_end_seconds(segment, by_index) > _segment_start_seconds(segment, by_index)
    ]


def _segment_start_seconds(
    segment: ClipSegment,
    by_index: dict[int, SubtitleEntry],
) -> float:
    if segment.parts:
        first = segment.parts[0].get("start")
        if isinstance(first, (int, float)):
            return float(first)
    row = by_index.get(segment.start_subtitle_index)
    return row.start if row else 0.0


def _segment_end_seconds(
    segment: ClipSegment,
    by_index: dict[int, SubtitleEntry],
) -> float:
    if segment.parts:
        last = segment.parts[-1].get("end")
        if isinstance(last, (int, float)):
            return float(last)
    row = by_index.get(segment.end_subtitle_index)
    return row.end if row else 0.0
