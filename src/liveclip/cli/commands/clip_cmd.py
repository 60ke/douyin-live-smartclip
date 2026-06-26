"""切片管理命令。"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import TYPE_CHECKING, cast

import typer
from dotenv import load_dotenv

if TYPE_CHECKING:
    from liveclip.domain.models import ClipSegment, SubtitleEntry

app = typer.Typer(help="Clip management")


def _safe_srt_stem(title: str, max_length: int = 48) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in title).strip("_")
    return (cleaned or "clip")[:max_length]


def _init_db(config: Path | None) -> None:
    """初始化数据库连接。"""
    from liveclip.config import load_settings
    from liveclip.db.session import init_db

    settings = load_settings(config)
    init_db(settings.database.url)


def _default_clip_jobs() -> int:
    """Return the default video export concurrency for local CLI runs."""
    return max(1, min(3, (os.cpu_count() or 1) // 2))


def _legacy_segment_dict(
    segment: ClipSegment,
    subtitles: list[SubtitleEntry],
    *,
    subtitle_output: Path | str | None = None,
    output: Path | str | None = None,
) -> dict[str, object]:
    """Return old smartclip-compatible segment metadata for segments.json."""
    from liveclip.subtitle.parts import segment_duration_seconds, segment_time_ranges
    from liveclip.utils.timecode import format_timecode

    ranges = segment_time_ranges(segment, subtitles)
    start_seconds = ranges[0][0] if ranges else 0.0
    end_seconds = ranges[-1][1] if ranges else 0.0
    duration = segment_duration_seconds(segment, subtitles)
    output_value = output if output is not None else segment.output
    subtitle_output_value = (
        subtitle_output if subtitle_output is not None else segment.subtitle_output
    )
    return {
        "topic": segment.title,
        "title": segment.title,
        "start_time": format_timecode(start_seconds, sep="."),
        "end_time": format_timecode(end_seconds, sep="."),
        "start_seconds": round(start_seconds, 3),
        "end_seconds": round(end_seconds, 3),
        "duration": round(duration, 3),
        "score": segment.score,
        "reason": segment.reason,
        "structure_score": segment.structure_score,
        "structure_reason": segment.structure_reason,
        "hook": segment.hook,
        "start_subtitle_index": segment.start_subtitle_index,
        "end_subtitle_index": segment.end_subtitle_index,
        "parts": segment.parts,
        "validation": segment.validation,
        "output": str(output_value) if output_value else None,
        "subtitle_output": str(subtitle_output_value) if subtitle_output_value else None,
    }


@app.command("list")
def list_clips(
    run_id: int = typer.Argument(..., help="Run ID"),
    config: str | None = typer.Option(
        None, "--config", "-c", envvar="LIVECLIP_CONFIG", help="Config file path"
    ),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List clips for a run."""
    from liveclip.db.repositories.artifact_repo import ClipPlanRepository, ClipRepository
    from liveclip.db.session import get_session_context

    _init_db(Path(config) if config else None)
    plan_repo = ClipPlanRepository()
    clip_repo = ClipRepository()

    async def _list() -> None:
        async with get_session_context() as session:
            plan = await plan_repo.get_clip_plan_by_run(session, run_id)
            if plan is None:
                typer.echo(f"No clip plan found for run_id={run_id}.")
                raise typer.Exit(code=1)
            clips = await clip_repo.get_clips_by_plan(session, plan.id)
            if output_json:
                data = [
                    {
                        "id": c.id,
                        "title": c.title,
                        "start_subtitle_index": c.start_subtitle_index,
                        "end_subtitle_index": c.end_subtitle_index,
                        "score": c.score,
                        "status": c.status,
                        "output_path": c.output_path,
                    }
                    for c in clips
                ]
                typer.echo(json.dumps(data, ensure_ascii=False, indent=2))
            else:
                if not clips:
                    typer.echo("No clips found.")
                    return
                for c in clips:
                    typer.echo(
                        f"id={c.id}  title={c.title!r}  "
                        f"score={c.score:.1f}  status={c.status}  "
                        f"range=[{c.start_subtitle_index}..{c.end_subtitle_index}]"
                    )

    asyncio.run(_list())


@app.command()
def pipeline(
    video_path: Path = typer.Argument(..., help="Path to local video file", exists=True),  # noqa: B008
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o", help="Output directory"),  # noqa: B008
    hotwords: str | None = typer.Option(
        None, "--hotwords", help="Comma-separated hotwords for ASR"
    ),
    device: str = typer.Option("auto", "--device", help="Device: auto/cpu/cuda/mps"),
    mode: str = typer.Option("full", "--mode", help="Pipeline mode: full/fast/clip-only"),
    fast: bool = typer.Option(False, "--fast", help="Shortcut for --mode fast"),
    config: str | None = typer.Option(
        None, "--config", "-c", envvar="LIVECLIP_CONFIG", help="Config file path"
    ),
) -> None:
    """Run the full pipeline (transcribe + clip) on a local video file.

    Useful for quick testing without a live room.
    """
    from liveclip.config import apply_runtime_environment, ensure_directories, load_settings
    from liveclip.observability import setup_logging

    settings = load_settings(Path(config) if config else None)
    apply_runtime_environment(settings)
    ensure_directories(settings)
    setup_logging()

    if fast:
        mode = "fast"

    if output_dir is None:
        output_dir = settings.storage.base_dir / "clips"

    typer.echo(f"Running pipeline on: {video_path}")
    typer.echo(f"  output_dir={output_dir}")
    typer.echo(f"  device={device}  mode={mode}")
    if hotwords:
        typer.echo(f"  hotwords={hotwords}")

    # TODO: integrate with PipelineOrchestrator once implemented
    typer.echo("Pipeline execution is not yet wired. Coming soon.")


@app.command("srt")
def clip_srt(
    srt_path: Path = typer.Argument(..., help="Path to a complete SRT file", exists=True),  # noqa: B008
    output_dir: Path | None = typer.Option(None, "--output-dir", "-o", help="Output directory"),  # noqa: B008
    config: str | None = typer.Option(
        None, "--config", "-c", envvar="LIVECLIP_CONFIG", help="Config file path"
    ),
    mode: str = typer.Option(
        "full",
        "--mode",
        help="Clip mode: full matches old smartclip two-stage flow; one-shot uses one LLM call",
    ),
    subtitle_source: str = typer.Option(
        "raw", "--subtitle-source", help="Subtitle index source: raw/processed"
    ),
    boundary_llm: bool = typer.Option(
        True,
        "--boundary-llm/--no-boundary-llm",
        help="Use LLM boundary validator; default matches old smartclip",
    ),
    fast: bool = typer.Option(
        False,
        "--fast",
        help="Skip secondary LLM boundary validation for speed, matching old smartclip",
    ),
    skip_llm_check: bool = typer.Option(
        False,
        "--skip-llm-check",
        help="Skip the initial LLM health check, matching old smartclip",
    ),
    reuse_plan: bool = typer.Option(
        False,
        "--reuse-plan",
        help="Reuse an existing validated plan instead of re-running LLM analysis",
    ),
    min_score: float = typer.Option(0.5, "--min-score", help="Minimum segment score"),
    min_seconds: float = typer.Option(90.0, "--min-seconds", help="Planner minimum seconds"),
    target_seconds: float = typer.Option(120.0, "--target-seconds", help="Planner target seconds"),
    max_seconds: float = typer.Option(150.0, "--max-seconds", help="Planner maximum seconds"),
    hard_max_seconds: float = typer.Option(
        180.0, "--hard-max-seconds", help="Planner hard maximum"
    ),
    min_export_seconds: float | None = typer.Option(
        None,
        "--min-export-seconds",
        help="Low-score clips shorter than this are dropped; default from config (45s)",
    ),
    export_high_score_threshold: float | None = typer.Option(
        None,
        "--export-high-score-threshold",
        help="Score required for clips shorter than --min-export-seconds",
    ),
    dump_prompts: bool = typer.Option(
        False, "--dump-prompts", help="Save all LLM prompts and responses to output dir"
    ),
    video_path: Path | None = typer.Option(
        None,
        "--video",
        exists=True,
        help="Video file to cut clips from (if omitted, only exports SRT)",
    ),
    fast_seek: bool = typer.Option(
        False,
        "--fast-seek/--precise-seek",
        help="Use input seeking for faster video clipping; default precise seek matches old smartclip",
    ),
    jobs: int | None = typer.Option(
        None,
        "--jobs",
        min=1,
        help="Number of video clips to export concurrently; default is min(3, half of CPU cores)",
    ),
    hard_subtitle: bool = typer.Option(
        False,
        "--hard-subtitle/--external-subtitle",
        help="Burn each exported clip SRT into the clip video",
    ),
    cover_image: Path | None = typer.Option(
        None,
        "--cover-image",
        exists=True,
        help="Cover image to prepend to each final clip",
    ),
    cover_title: str | None = typer.Option(
        None,
        "--cover-title",
        help="Override cover title; default uses each clip title",
    ),
    highlight_intro: bool = typer.Option(
        False,
        "--highlight-intro/--no-highlight-intro",
        help="Use LLM to select a 3-8s highlight intro for each exported clip",
    ),
) -> None:
    """Smart-clip a complete SRT file and optionally cut video clips.

    Without --video: exports per-segment SRT files only (like old subtitle-clip).
    With --video:    exports both video clips and SRT files (like old smartclip clip).
    """
    from liveclip.config import apply_runtime_environment, ensure_directories, load_settings
    from liveclip.domain.enums import StepName
    from liveclip.domain.models import (
        ClipSegment,
        ClipSegmentConfig,
        LLMCallConfig,
        PipelineConfig,
        RecordConfig,
        StepResult,
    )
    from liveclip.observability import setup_logging
    from liveclip.pipeline.context import PipelineContext
    from liveclip.pipeline.steps.export_clips import ExportClipsStep
    from liveclip.pipeline.steps.plan_clips import PlanClipsStep
    from liveclip.pipeline.steps.validate_boundary import ValidateBoundaryStep
    from liveclip.storage.local import LocalStorage
    from liveclip.storage.paths import RunPaths
    from liveclip.subtitle.parser import parse_srt_file
    from liveclip.subtitle.writer import rebase_subtitles, write_srt_file

    load_dotenv()
    settings = load_settings(Path(config) if config else None)
    apply_runtime_environment(settings)
    ensure_directories(settings)
    setup_logging()

    if mode not in {"full", "legacy", "one-shot"}:
        typer.echo("--mode must be full, legacy, or one-shot", err=True)
        raise typer.Exit(code=2)
    if subtitle_source not in {"raw", "processed"}:
        typer.echo("--subtitle-source must be raw or processed", err=True)
        raise typer.Exit(code=2)
    if fast:
        boundary_llm = False

    # mode 映射对齐旧项目: full → legacy two-stage; one-shot → single LLM call
    planner_mode = "legacy" if mode in ("full", "legacy") else "full"
    export_jobs = jobs if jobs is not None else _default_clip_jobs()

    base_dir = output_dir or settings.storage.base_dir / "local_srt_clips" / srt_path.stem
    paths = RunPaths(base_dir=base_dir, room_id=1, run_id=1)
    paths.ensure_all_dirs()

    if not skip_llm_check:
        from liveclip.adapters.llm import LLMClient

        LLMClient().chat(
            system_prompt="只返回 OK。",
            user_prompt="请回复 OK",
            timeout_seconds=30,
            max_tokens=8,
        )

    ctx = PipelineContext(
        run_id=1,
        room_id=1,
        task_id=1,
        paths=paths,
        pipeline_config=PipelineConfig(
            clip_plan_mode=planner_mode,
            clip_plan_subtitle_source=subtitle_source,
            validate_boundary_use_llm=boundary_llm,
        ),
        clip_segment_config=ClipSegmentConfig(
            target_segment_seconds=target_seconds,
            min_segment_seconds=min_seconds,
            max_segment_seconds=max_seconds,
            hard_max_segment_seconds=hard_max_seconds,
            min_score=min_score,
            min_export_segment_seconds=(
                min_export_seconds
                if min_export_seconds is not None
                else settings.clip_segment.min_export_segment_seconds
            ),
            export_high_score_threshold=(
                export_high_score_threshold
                if export_high_score_threshold is not None
                else settings.clip_segment.export_high_score_threshold
            ),
        ),
        llm_call_config=LLMCallConfig(max_tokens=4000, timeout_seconds=180),
        record_config=RecordConfig(max_duration_seconds=0),
    )
    ctx.set_step_result(
        str(StepName.TRANSCRIBE),
        StepResult(success=True, output_path=str(srt_path)),
    )

    # 保存 prompt dump 目录到 metadata 供 pipeline steps 使用
    if dump_prompts:
        prompt_dump_dir = paths.run_dir / "llm_prompts"
        prompt_dump_dir.mkdir(parents=True, exist_ok=True)
        ctx.metadata["prompt_dump_dir"] = str(prompt_dump_dir)
        typer.echo(f"Dumping prompts to: {prompt_dump_dir}")

    plan_exists = reuse_plan and paths.validated_plan_path.exists()
    if plan_exists:
        typer.echo(f"Existing plan found, skipping LLM: {paths.validated_plan_path}")
    else:
        typer.echo(f"Planning clips from SRT: {srt_path}")
        typer.echo(f"  mode={mode} → planner_mode={planner_mode}")
        plan_result = PlanClipsStep().execute(ctx)
        ctx.set_step_result(str(StepName.PLAN_CLIPS), plan_result)

        if boundary_llm:
            from liveclip.adapters.llm import LLMClient

            validate_step = ValidateBoundaryStep(
                llm_client=LLMClient(
                    temperature=ctx.llm_call_config.temperature,
                    max_tokens=ctx.llm_call_config.max_tokens,
                    timeout=ctx.llm_call_config.timeout_seconds,
                    max_retries=ctx.llm_call_config.max_retries,
                )
            )
        else:
            validate_step = ValidateBoundaryStep()
        validate_result = validate_step.execute(ctx)
        ctx.set_step_result(str(StepName.VALIDATE_BOUNDARY), validate_result)

    plan = LocalStorage.read_json(paths.validated_plan_path)
    segments = [
        ClipSegment.model_validate(item)
        for item in cast(list[object], plan.get("segments", []))
        if isinstance(item, dict)
    ]
    subtitles = parse_srt_file(srt_path)
    out_dir = paths.run_dir / "srt_segments"
    out_dir.mkdir(parents=True, exist_ok=True)
    for stale in out_dir.glob("*.srt"):
        stale.unlink(missing_ok=True)

    legacy_segments: list[dict[str, object]] = []
    for index, segment in enumerate(segments, start=1):
        clip_srt_path = out_dir / f"{index:02d}_{_safe_srt_stem(segment.title)}.srt"
        if segment.parts:
            parts = ExportClipsStep._resolve_parts(segment, subtitles)
            rows = ExportClipsStep._slice_part_subtitles(subtitles, parts)
        else:
            selected = [
                row
                for row in subtitles
                if segment.start_subtitle_index <= row.index <= segment.end_subtitle_index
            ]
            rows = rebase_subtitles(selected, selected[0].start) if selected else []
        if rows:
            _ = write_srt_file(clip_srt_path, rows)
        legacy_segments.append(
            _legacy_segment_dict(
                segment,
                subtitles,
                subtitle_output=clip_srt_path if rows else None,
            )
        )

    summary_path = out_dir / "segments.json"
    _ = summary_path.write_text(
        json.dumps(legacy_segments, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    meta_path = out_dir / "segments_meta.json"
    _ = meta_path.write_text(
        json.dumps(
            {
                "plan_path": str(paths.validated_plan_path),
                "subtitle_source": plan.get("subtitle_source"),
                "index_space": plan.get("index_space"),
                "planner_mode": plan.get("planner_mode"),
                "segment_count": len(segments),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    typer.echo(f"SRT segments: {len(segments)} → {out_dir}")

    # --- Video clipping (optional) ---
    if video_path is not None:
        from liveclip.adapters.ffmpeg import FFmpegClipper
        from liveclip.pipeline.steps.export_clips import ExportClipsStep as _ExportClipsStep

        ctx.set_step_result(
            str(StepName.CONVERT_MP4),
            StepResult(success=True, output_path=str(video_path)),
        )
        export_step = _ExportClipsStep(
            clipper=FFmpegClipper(fast_seek=fast_seek),
            max_workers=export_jobs,
        )
        export_step.execute(ctx)

        from liveclip.storage.local import LocalStorage as _LocalStorage

        export_summary = _LocalStorage.read_json(paths.clips_dir / "export_summary.json")
        exported = export_summary.get("exported", 0)
        failed = export_summary.get("failed", 0)
        typer.echo(f"Video clips:  {exported} exported, {failed} failed → {paths.clips_dir}")
        if hard_subtitle or cover_image is not None or highlight_intro:
            typer.echo("Post-processing clips...")
            post_summary = _postprocess_exported_clips(
                export_summary=export_summary,
                clips_dir=paths.clips_dir,
                hard_subtitle=hard_subtitle,
                cover_image=cover_image,
                cover_title=cover_title,
                highlight_intro=highlight_intro,
            )
            _LocalStorage.write_json(paths.clips_dir / "export_summary.json", post_summary)
            final_count = len(
                [
                    item
                    for item in post_summary.get("clips", [])
                    if isinstance(item, dict) and item.get("postprocess_status") == "completed"
                ]
            )
            typer.echo(f"Post-processed clips: {final_count} → {paths.clips_dir / 'final'}")

    typer.echo(f"Summary: {summary_path}")


def _postprocess_exported_clips(
    *,
    export_summary: dict[str, object],
    clips_dir: Path,
    hard_subtitle: bool,
    cover_image: Path | None,
    cover_title: str | None,
    highlight_intro: bool,
) -> dict[str, object]:
    """Run optional hard subtitle, cover, and highlight post-processing."""
    from liveclip.services.cover_service import ClipCoverRenderer
    from liveclip.services.hard_subtitle_service import HardSubtitleRenderer
    from liveclip.services.highlight_service import HighlightIntroSelector

    final_dir = clips_dir / "final"
    raw_dir = clips_dir / "raw"
    work_dir = clips_dir / "work"
    final_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    _clean_directory_files(final_dir)
    _clean_directory_files(raw_dir)
    _clean_directory_files(work_dir)
    subtitle_renderer = HardSubtitleRenderer() if hard_subtitle else None
    cover_renderer = ClipCoverRenderer() if cover_image is not None or highlight_intro else None
    highlight_selector = HighlightIntroSelector() if highlight_intro else None

    updated_clips: list[object] = []
    for raw_item in export_summary.get("clips", []):
        if not isinstance(raw_item, dict):
            updated_clips.append(raw_item)
            continue
        item = dict(raw_item)
        try:
            clip_path_value = item.get("clip_path")
            if not isinstance(clip_path_value, str) or not clip_path_value:
                raise ValueError("clip_path 为空")
            current_video = Path(clip_path_value)
            if not current_video.exists():
                raise FileNotFoundError(f"切片视频不存在: {current_video}")

            output_stem = current_video.stem
            final_video = final_dir / f"{output_stem}.mp4"
            raw_video = _move_to_raw(current_video, raw_dir / f"{output_stem}_raw.mp4")
            current_video = raw_video
            item["raw_clip_path"] = str(raw_video)
            item["original_clip_path"] = str(raw_video)
            subtitle_path = _optional_path(item.get("subtitle_path"))
            if subtitle_path is not None and subtitle_path.exists():
                subtitle_path = _move_to_raw(subtitle_path, raw_dir / f"{output_stem}_raw.srt")
                item["subtitle_path"] = str(subtitle_path)

            if subtitle_renderer is not None:
                if subtitle_path is None:
                    raise FileNotFoundError(f"切片缺少字幕: {current_video}")
                hard_video = work_dir / f"{output_stem}_hard.mp4"
                hard_result = subtitle_renderer.render(
                    video_path=current_video,
                    subtitle_path=subtitle_path,
                    output_path=hard_video,
                )
                current_video = hard_result.output_video_path
                item["hard_subtitle_video_path"] = str(hard_result.output_video_path)
                item["hard_subtitle_ass_path"] = str(hard_result.ass_path)
                item["subtitle_mode"] = "hard"
            else:
                item["subtitle_mode"] = "external"

            if cover_renderer is not None:
                spec = cover_renderer.probe_video(current_video)
                highlight_start: float | None = None
                highlight_end: float | None = None
                highlight_reason: str | None = None
                highlight_confidence: float | None = None
                highlight_enabled = False
                if highlight_selector is not None:
                    try:
                        decision = highlight_selector.select(
                            title=str(cover_title or item.get("title") or "精彩片段"),
                            duration_seconds=spec.duration_seconds,
                            subtitle_path=subtitle_path,
                            reason=str(item.get("reason") or ""),
                            structure_reason=str(item.get("structure_reason") or ""),
                        )
                        highlight_enabled = decision.enabled
                        highlight_start = decision.start_seconds
                        highlight_end = decision.end_seconds
                        highlight_reason = decision.reason
                        highlight_confidence = decision.confidence
                    except Exception as exc:  # noqa: BLE001 - keep batch postprocess alive.
                        highlight_enabled = False
                        highlight_reason = f"高能片头选择失败，已跳过: {exc}"
                        highlight_confidence = 0.0

                cover_result = cover_renderer.render(
                    clip_id=int(item.get("index", 0)) + 1,
                    video_path=current_video,
                    output_dir=work_dir,
                    title=str(cover_title or item.get("title") or "精彩片段"),
                    source_image_path=cover_image,
                    cover_frame_video_path=raw_video,
                    highlight_enabled=highlight_enabled,
                    highlight_start_seconds=highlight_start,
                    highlight_end_seconds=highlight_end,
                )
                current_video = cover_result.final_video_path
                _replace_file(current_video, final_video)
                current_video = final_video
                item["cover_title"] = str(cover_title or item.get("title") or "精彩片段")
                item["cover_source_image_path"] = str(cover_image) if cover_image else None
                item["cover_image_path"] = str(cover_result.cover_image_path)
                item["cover_intro_video_path"] = str(cover_result.cover_intro_video_path)
                item["highlight_enabled"] = cover_result.highlight_enabled
                item["highlight_start_seconds"] = cover_result.highlight_start_seconds
                item["highlight_end_seconds"] = cover_result.highlight_end_seconds
                item["highlight_reason"] = highlight_reason or cover_result.highlight_reason
                item["highlight_confidence"] = (
                    highlight_confidence
                    if highlight_confidence is not None
                    else cover_result.highlight_confidence
                )
                item["highlight_video_path"] = (
                    str(cover_result.highlight_video_path)
                    if cover_result.highlight_video_path
                    else None
                )
                item["final_duration_seconds"] = cover_result.duration_seconds
            elif current_video != final_video:
                shutil.copy2(current_video, final_video)
                current_video = final_video

            item["clip_path"] = str(current_video)
            item["postprocess_status"] = "completed"
        except Exception as exc:  # noqa: BLE001 - report per-clip failure in summary.
            item["postprocess_status"] = "failed"
            item["postprocess_error"] = str(exc)
        updated_clips.append(item)

    result = dict(export_summary)
    result["clips"] = updated_clips
    result["postprocess"] = {
        "hard_subtitle": hard_subtitle,
        "cover_image": str(cover_image) if cover_image else None,
        "highlight_intro": highlight_intro,
        "final_dir": str(final_dir),
        "raw_dir": str(raw_dir),
        "work_dir": str(work_dir),
    }
    return result


def _optional_path(value: object) -> Path | None:
    if not isinstance(value, str) or not value:
        return None
    return Path(value)


def _move_to_raw(source: Path, target: Path) -> Path:
    if source == target:
        return source
    if target.exists():
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    source.replace(target)
    return target


def _replace_file(source: Path, target: Path) -> None:
    if source == target:
        return
    if target.exists():
        target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)
    source.replace(target)


def _clean_directory_files(directory: Path) -> None:
    for path in directory.iterdir():
        if path.is_file():
            path.unlink()
