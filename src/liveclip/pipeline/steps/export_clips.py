"""切片导出步骤：根据校验后方案，逐段裁剪视频并导出字幕。"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from liveclip.adapters.ffmpeg import FFmpegClipper
from liveclip.domain.enums import StepName
from liveclip.domain.models import ClipPlanResult, ClipSegment, StepResult, SubtitleEntry
from liveclip.exceptions import EXPORT_CLIP_FAILED, ExportError
from liveclip.observability import get_logger
from liveclip.pipeline.context import PipelineContext
from liveclip.pipeline.steps.base import BaseStep
from liveclip.services.clip_post_process_service import (
    ClipPostProcessService,
    options_from_pipeline_config,
)
from liveclip.storage.local import LocalStorage
from liveclip.storage.paths import sanitize_filename
from liveclip.subtitle.parser import parse_srt_file
from liveclip.subtitle.parts import segment_duration_seconds
from liveclip.subtitle.writer import rebase_subtitles, write_srt_file

logger = get_logger(__name__)


class ExportClipsStep(BaseStep):
    """切片导出步骤。

    加载校验后方案 -> 逐段裁剪视频 -> 导出对应字幕 -> 保存导出摘要。
    """

    def __init__(self, clipper: FFmpegClipper | None = None, max_workers: int = 1) -> None:
        self._clipper = clipper or FFmpegClipper()
        self._max_workers = max(1, max_workers)

    @property
    def name(self) -> StepName:
        return StepName.EXPORT_CLIPS

    def execute(self, ctx: PipelineContext) -> StepResult:
        """执行切片导出。"""
        start_ms = time.monotonic_ns() // 1_000_000
        logger.info("export_clips_start", run_id=ctx.run_id)

        try:
            self._check_cancelled(ctx)

            plan_data = LocalStorage.read_json(ctx.paths.validated_plan_path)
            plan_result = ClipPlanResult.model_validate(plan_data)
            segments = plan_result.segments

            if not segments:
                raise ExportError(
                    EXPORT_CLIP_FAILED,
                    "校验后方案为空，无法导出",
                    details={"run_id": ctx.run_id},
                )

            video_path = self._resolve_video_path(ctx)
            if video_path is None:
                raise ExportError(
                    EXPORT_CLIP_FAILED,
                    "未找到源视频文件",
                    details={"run_id": ctx.run_id},
                )

            video_file = Path(video_path)
            timing_subtitles = self._load_timing_subtitles(ctx, video_file, plan_result.index_space)
            export_subtitles = self._load_export_subtitles(ctx, video_file)

            self._prepare_clips_dir(ctx.paths.clips_dir)

            exported, failed = self._export_segments(
                ctx=ctx,
                segments=segments,
                video_path=video_path,
                timing_subtitles=timing_subtitles,
                export_subtitles=export_subtitles,
            )

            summary = {
                "total": len(segments),
                "exported": len(exported),
                "failed": len(failed),
                "clips": exported,
                "failed_clips": failed,
            }
            summary_path = ctx.paths.clips_dir / "export_summary.json"
            postprocess_options = options_from_pipeline_config(
                ctx.pipeline_config,
                base_dir=ctx.paths.base_dir,
            )
            if postprocess_options.enabled:
                summary = ClipPostProcessService().process_summary(
                    export_summary=summary,
                    clips_dir=ctx.paths.clips_dir,
                    options=postprocess_options,
                )
            LocalStorage.write_json(summary_path, summary)

            elapsed = time.monotonic_ns() // 1_000_000 - start_ms
            logger.info(
                "export_clips_done",
                run_id=ctx.run_id,
                exported=len(exported),
                failed=len(failed),
                elapsed_ms=elapsed,
            )

            return StepResult(
                success=True,
                output_path=str(ctx.paths.clips_dir),
                duration_ms=elapsed,
                metadata={
                    "exported_count": len(exported),
                    "failed_count": len(failed),
                    "summary_path": str(summary_path),
                    "max_workers": self._max_workers,
                },
            )

        except ExportError:
            raise
        except Exception as exc:
            elapsed = time.monotonic_ns() // 1_000_000 - start_ms
            logger.error("export_clips_failed", run_id=ctx.run_id, error=str(exc))
            raise ExportError(
                EXPORT_CLIP_FAILED,
                f"切片导出失败: {exc}",
                details={"run_id": ctx.run_id, "error": str(exc)},
            ) from exc

    def _export_segments(
        self,
        ctx: PipelineContext,
        segments: list[ClipSegment],
        video_path: str,
        timing_subtitles: list[SubtitleEntry],
        export_subtitles: list[SubtitleEntry],
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        """Export all segments, optionally running independent clips concurrently."""
        if self._max_workers == 1 or len(segments) == 1:
            return self._export_segments_sequential(
                ctx=ctx,
                segments=segments,
                video_path=video_path,
                timing_subtitles=timing_subtitles,
                export_subtitles=export_subtitles,
            )

        logger.info(
            "export_clips_parallel",
            run_id=ctx.run_id,
            max_workers=self._max_workers,
            segment_count=len(segments),
        )

        exported: list[dict[str, object]] = []
        failed: list[dict[str, object]] = []
        with ThreadPoolExecutor(max_workers=self._max_workers) as executor:
            futures = {}
            for index, seg in enumerate(segments):
                self._check_cancelled(ctx)
                future = executor.submit(
                    self._export_segment,
                    ctx=ctx,
                    seg=seg,
                    index=index,
                    video_path=video_path,
                    timing_subtitles=timing_subtitles,
                    export_subtitles=export_subtitles,
                )
                futures[future] = (index, seg)

            for future in as_completed(futures):
                index, seg = futures[future]
                try:
                    exported.append(future.result())
                except Exception as exc:
                    failed.append(self._build_failed_segment(ctx, index, seg, exc))

        exported.sort(key=lambda item: int(str(item["index"])))
        failed.sort(key=lambda item: int(str(item["segment_index"])))
        return exported, failed

    def _export_segments_sequential(
        self,
        ctx: PipelineContext,
        segments: list[ClipSegment],
        video_path: str,
        timing_subtitles: list[SubtitleEntry],
        export_subtitles: list[SubtitleEntry],
    ) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
        """Export segments one by one, matching the old smartclip execution order."""
        exported: list[dict[str, object]] = []
        failed: list[dict[str, object]] = []

        for index, seg in enumerate(segments):
            self._check_cancelled(ctx)
            try:
                clip_info = self._export_segment(
                    ctx=ctx,
                    seg=seg,
                    index=index,
                    video_path=video_path,
                    timing_subtitles=timing_subtitles,
                    export_subtitles=export_subtitles,
                )
                exported.append(clip_info)
            except Exception as exc:
                failed.append(self._build_failed_segment(ctx, index, seg, exc))

        return exported, failed

    @staticmethod
    def _build_failed_segment(
        ctx: PipelineContext,
        index: int,
        seg: ClipSegment,
        exc: Exception,
    ) -> dict[str, object]:
        """Build a serializable failed-segment entry and log the exception."""
        logger.warning(
            "export_segment_failed",
            run_id=ctx.run_id,
            segment_index=index,
            error=str(exc),
        )
        return {
            "segment_index": index,
            "title": seg.title,
            "error": str(exc),
        }

    def _export_segment(
        self,
        ctx: PipelineContext,
        seg: ClipSegment,
        index: int,
        video_path: str,
        timing_subtitles: list[SubtitleEntry],
        export_subtitles: list[SubtitleEntry],
    ) -> dict[str, object]:
        """导出单个切片段。"""
        safe_title = sanitize_filename(seg.title)
        clip_filename = f"{index + 1:03d}_{safe_title}"
        clip_mp4 = ctx.paths.clips_dir / f"{clip_filename}.mp4"
        clip_srt = ctx.paths.clips_dir / f"{clip_filename}.srt"

        start_time = 0.0
        end_time = 0.0
        seg_timing_subtitles = [
            e
            for e in timing_subtitles
            if seg.start_subtitle_index <= e.index <= seg.end_subtitle_index
        ]

        if seg_timing_subtitles:
            start_time = seg_timing_subtitles[0].start
            end_time = seg_timing_subtitles[-1].end
        else:
            logger.warning(
                "no_matching_subtitles",
                segment_index=index,
                start=seg.start_subtitle_index,
                end=seg.end_subtitle_index,
            )

        video_file = Path(video_path)
        clip_subtitles: list[SubtitleEntry] = []

        # 单 part 或空 parts 视为连续片段，直接用 clip_segment 避免不必要的 concat
        use_parts = bool(seg.parts) and len(seg.parts) > 1
        if use_parts:
            parts = self._resolve_parts(seg, timing_subtitles)
            self._clipper.clip_parts(
                input_path=video_file,
                output_path=clip_mp4,
                parts=parts,
                cancel_check=ctx.is_cancelled,
            )
            clip_subtitles = self._slice_part_subtitles(export_subtitles, parts)
        else:
            self._clipper.clip_segment(
                input_path=video_file,
                output_path=clip_mp4,
                start_seconds=start_time,
                duration_seconds=max(0.0, end_time - start_time),
                cancel_check=ctx.is_cancelled,
            )
            clip_subtitles = rebase_subtitles(
                self._slice_subtitles_by_time(export_subtitles, start_time, end_time),
                time_offset=start_time,
            )

        if clip_subtitles:
            write_srt_file(clip_srt, clip_subtitles)

        return {
            "index": index,
            "title": seg.title,
            "clip_path": str(clip_mp4),
            "subtitle_path": str(clip_srt) if clip_subtitles else None,
            "start_time": start_time,
            "end_time": end_time,
            "duration_seconds": segment_duration_seconds(seg, timing_subtitles),
            "parts": [
                {"start": start, "end": start + duration, "duration_seconds": duration}
                for start, duration in self._resolve_parts(seg, timing_subtitles)
            ]
            if seg.parts
            else [],
        }

    @staticmethod
    def _prepare_clips_dir(clips_dir: Path) -> None:
        """Create the clips directory and remove stale clip media from previous exports."""
        clips_dir.mkdir(parents=True, exist_ok=True)
        for pattern in ("*.mp4", "*.srt", "*.part", "*_concat.txt"):
            for path in clips_dir.glob(pattern):
                if path.is_file():
                    path.unlink(missing_ok=True)

    @staticmethod
    def _load_timing_subtitles(
        ctx: PipelineContext,
        video_path: Path,
        index_space: str = "processed",
    ) -> list[SubtitleEntry]:
        """Load subtitles using the same index space as the validated plan."""
        if index_space == "processed":
            preprocess_result = ctx.get_step_result(str(StepName.PREPROCESS_SUBTITLE))
            if preprocess_result and preprocess_result.output_path:
                preprocessed_path = Path(preprocess_result.output_path)
                if preprocessed_path.exists():
                    return parse_srt_file(preprocessed_path)

        if index_space == "raw":
            transcribe_result = ctx.get_step_result(str(StepName.TRANSCRIBE))
            if transcribe_result and transcribe_result.output_path:
                transcribe_path = Path(transcribe_result.output_path)
                if transcribe_path.exists():
                    subtitles = parse_srt_file(transcribe_path)
                    if subtitles:
                        return subtitles

        sidecar_srt = video_path.with_suffix(".srt")
        if sidecar_srt.exists():
            subtitles = parse_srt_file(sidecar_srt)
            if subtitles:
                return subtitles

        transcribe_result = ctx.get_step_result(str(StepName.TRANSCRIBE))
        if transcribe_result and transcribe_result.output_path:
            transcribe_path = Path(transcribe_result.output_path)
            if transcribe_path.exists():
                return parse_srt_file(transcribe_path)

        return []

    @staticmethod
    def _load_export_subtitles(ctx: PipelineContext, video_path: Path) -> list[SubtitleEntry]:
        """Load fine-grained subtitles for clip SRT export."""
        transcribe_result = ctx.get_step_result(str(StepName.TRANSCRIBE))
        if transcribe_result and transcribe_result.output_path:
            transcribe_path = Path(transcribe_result.output_path)
            if transcribe_path.exists():
                subtitles = parse_srt_file(transcribe_path)
                if subtitles:
                    return subtitles

        sidecar_srt = video_path.with_suffix(".srt")
        if sidecar_srt.exists():
            subtitles = parse_srt_file(sidecar_srt)
            if subtitles:
                return subtitles

        return ExportClipsStep._load_timing_subtitles(ctx, video_path)

    @staticmethod
    def _slice_subtitles_by_time(
        subtitles: list[SubtitleEntry],
        start_seconds: float,
        end_seconds: float,
    ) -> list[SubtitleEntry]:
        """Slice subtitles by time overlap and clamp entries to the clip range."""
        rows: list[SubtitleEntry] = []
        for sub in subtitles:
            if sub.end <= start_seconds or sub.start >= end_seconds:
                continue
            rows.append(
                SubtitleEntry(
                    index=sub.index,
                    start=max(start_seconds, sub.start),
                    end=min(end_seconds, sub.end),
                    text=sub.text,
                )
            )
        return rows

    @staticmethod
    def _slice_part_subtitles(
        subtitles: list[SubtitleEntry],
        parts: list[tuple[float, float]],
    ) -> list[SubtitleEntry]:
        """Slice and rebase raw subtitles for a multi-part exported clip."""
        rows: list[SubtitleEntry] = []
        output_offset = 0.0
        for start_seconds, duration_seconds in parts:
            end_seconds = start_seconds + duration_seconds
            for sub in ExportClipsStep._slice_subtitles_by_time(
                subtitles, start_seconds, end_seconds
            ):
                rows.append(
                    SubtitleEntry(
                        index=len(rows) + 1,
                        start=sub.start - start_seconds + output_offset,
                        end=sub.end - start_seconds + output_offset,
                        text=sub.text,
                    )
                )
            output_offset += duration_seconds
        return rows

    @staticmethod
    def _resolve_parts(
        seg: ClipSegment,
        subtitles: list[SubtitleEntry],
    ) -> list[tuple[float, float]]:
        """Resolve segment part subtitle ranges into ffmpeg start/duration tuples."""
        resolved: list[tuple[float, float]] = []
        by_index = {entry.index: entry for entry in subtitles}
        for part in seg.parts:
            start_value = part.get("start_subtitle_index")
            end_value = part.get("end_subtitle_index")
            if start_value is None or end_value is None:
                start_seconds = part.get("start")
                end_seconds = part.get("end")
                if isinstance(start_seconds, (int, float)) and isinstance(
                    end_seconds, (int, float)
                ):
                    duration = max(0.0, float(end_seconds) - float(start_seconds))
                    if duration > 0:
                        resolved.append((float(start_seconds), duration))
                continue
            start_index = _coerce_part_index(start_value)
            end_index = _coerce_part_index(end_value)
            if start_index is None or end_index is None:
                continue
            try:
                start_entry = by_index[start_index]
                end_entry = by_index[end_index]
            except KeyError:
                continue
            duration = max(0.0, end_entry.end - start_entry.start)
            if duration > 0:
                resolved.append((start_entry.start, duration))
        return resolved

    @staticmethod
    def _resolve_video_path(ctx: PipelineContext) -> str | None:
        """从上下文中获取视频文件路径，优先 MP4，回退 TS。"""
        mp4_result = ctx.get_step_result(str(StepName.CONVERT_MP4))
        if mp4_result is not None and mp4_result.success and mp4_result.output_path:
            return mp4_result.output_path

        record_result = ctx.get_step_result(str(StepName.RECORD_TS))
        if record_result is not None and record_result.success and record_result.output_path:
            return record_result.output_path

        return None


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
