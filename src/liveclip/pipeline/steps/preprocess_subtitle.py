"""字幕预处理步骤：解析 SRT → 合并碎片 → 写入处理后 SRT 和句子 JSON。"""

from __future__ import annotations

import time

from liveclip.domain.enums import StepName
from liveclip.domain.models import StepResult, SubtitleEntry
from liveclip.exceptions import EMPTY_SUBTITLE, FunASRError
from liveclip.observability import get_logger
from liveclip.pipeline.context import PipelineContext
from liveclip.pipeline.steps.base import BaseStep
from liveclip.storage.local import LocalStorage
from liveclip.subtitle.parser import parse_srt_file
from liveclip.subtitle.writer import write_srt_file

logger = get_logger(__name__)


def merge_fragments(
    subtitles: list[SubtitleEntry],
    max_gap_seconds: float = 0.5,
    max_duration_seconds: float = 15.0,
) -> list[SubtitleEntry]:
    """合并短碎片字幕条目。

    将时间间隔小于 *max_gap_seconds* 的相邻条目合并，
    合并后时长不超过 *max_duration_seconds*。

    Args:
        subtitles: 原始字幕列表。
        max_gap_seconds: 最大合并间隔（秒）。
        max_duration_seconds: 合并后最大时长（秒）。

    Returns:
        合并后的字幕列表。
    """
    if not subtitles:
        return []

    merged: list[SubtitleEntry] = []
    current = subtitles[0]

    for i in range(1, len(subtitles)):
        entry = subtitles[i]
        gap = entry.start - current.end
        combined_duration = entry.end - current.start

        if gap <= max_gap_seconds and combined_duration <= max_duration_seconds:
            current = SubtitleEntry(
                index=current.index,
                start=current.start,
                end=entry.end,
                text=f"{current.text} {entry.text}".strip(),
            )
        else:
            merged.append(current)
            current = entry

    merged.append(current)

    return [
        SubtitleEntry(index=i + 1, start=e.start, end=e.end, text=e.text)
        for i, e in enumerate(merged)
    ]


def subtitles_to_sentences(subtitles: list[SubtitleEntry]) -> list[dict[str, object]]:
    """将字幕条目转换为句子列表，用于后续 LLM 分析。

    Args:
        subtitles: 字幕条目列表。

    Returns:
        句子字典列表，每项包含 index / start / end / text。
    """
    return [
        {
            "index": e.index,
            "start": e.start,
            "end": e.end,
            "text": e.text,
        }
        for e in subtitles
    ]


class PreprocessSubtitleStep(BaseStep):
    """字幕预处理步骤。

    解析原始 SRT → 合并碎片字幕 → 写入处理后 SRT → 保存句子 JSON。
    """

    @property
    def name(self) -> StepName:
        return StepName.PREPROCESS_SUBTITLE

    def execute(self, ctx: PipelineContext) -> StepResult:
        """执行字幕预处理。"""
        start_ms = time.monotonic_ns() // 1_000_000
        logger.info("preprocess_subtitle_start", run_id=ctx.run_id)

        try:
            self._check_cancelled(ctx)

            transcribe_result = ctx.get_step_result(str(StepName.TRANSCRIBE))
            if transcribe_result is None or transcribe_result.output_path is None:
                raise FunASRError(
                    EMPTY_SUBTITLE,
                    "未找到转写步骤的 SRT 输出路径",
                    details={"run_id": ctx.run_id},
                )

            srt_path = transcribe_result.output_path

            from pathlib import Path

            subtitles = parse_srt_file(Path(srt_path))
            if not subtitles:
                raise FunASRError(
                    EMPTY_SUBTITLE,
                    f"SRT 文件为空或解析失败: {srt_path}",
                    details={"path": srt_path},
                )

            logger.info("srt_parsed", run_id=ctx.run_id, entry_count=len(subtitles))

            self._check_cancelled(ctx)

            merged = merge_fragments(subtitles)
            logger.info(
                "fragments_merged",
                run_id=ctx.run_id,
                original=len(subtitles),
                merged=len(merged),
            )

            self._check_cancelled(ctx)

            processed_srt_path = ctx.paths.combined_srt_path
            write_srt_file(processed_srt_path, merged)

            sentences = subtitles_to_sentences(merged)
            LocalStorage.write_json(ctx.paths.sentences_json_path, {"sentences": sentences})

            words_data = [{"index": e.index, "text": e.text} for e in merged]
            LocalStorage.write_json(ctx.paths.words_json_path, {"words": words_data})

            elapsed = time.monotonic_ns() // 1_000_000 - start_ms
            logger.info(
                "preprocess_subtitle_done",
                run_id=ctx.run_id,
                merged_count=len(merged),
                elapsed_ms=elapsed,
            )

            return StepResult(
                success=True,
                output_path=str(processed_srt_path),
                duration_ms=elapsed,
                metadata={
                    "original_count": len(subtitles),
                    "merged_count": len(merged),
                    "sentences_path": str(ctx.paths.sentences_json_path),
                    "words_path": str(ctx.paths.words_json_path),
                },
            )

        except FunASRError:
            raise
        except Exception as exc:
            elapsed = time.monotonic_ns() // 1_000_000 - start_ms
            logger.error("preprocess_subtitle_failed", run_id=ctx.run_id, error=str(exc))
            raise FunASRError(
                EMPTY_SUBTITLE,
                f"字幕预处理失败: {exc}",
                details={"run_id": ctx.run_id, "error": str(exc)},
            ) from exc
