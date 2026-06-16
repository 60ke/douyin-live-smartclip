"""Post-process exported clips into publication-ready assets."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from liveclip.domain.models import PipelineConfig
from liveclip.observability import get_logger
from liveclip.services.cover_service import ClipCoverRenderer
from liveclip.services.hard_subtitle_service import HardSubtitleRenderer
from liveclip.services.highlight_service import HighlightIntroSelector

logger = get_logger(__name__)


@dataclass(frozen=True)
class ClipPostProcessOptions:
    """Options for clip post-processing."""

    hard_subtitle_enabled: bool = False
    cover_enabled: bool = False
    cover_image_path: Path | None = None
    cover_title: str | None = None
    cover_duration_seconds: float = 1.0
    highlight_enabled: bool = False

    @property
    def enabled(self) -> bool:
        return self.hard_subtitle_enabled or self.cover_enabled or self.highlight_enabled


class ClipPostProcessService:
    """Run hard subtitles, optional highlight intro, and optional cover intro."""

    def __init__(
        self,
        *,
        ffmpeg_binary: str = "ffmpeg",
        ffprobe_binary: str = "ffprobe",
    ) -> None:
        self._ffmpeg_binary = ffmpeg_binary
        self._ffprobe_binary = ffprobe_binary

    def process_summary(
        self,
        *,
        export_summary: dict[str, object],
        clips_dir: Path,
        options: ClipPostProcessOptions,
    ) -> dict[str, object]:
        """Post-process every exported clip and return an updated summary."""
        if not options.enabled:
            return export_summary

        final_dir = clips_dir / "final"
        raw_dir = clips_dir / "raw"
        work_dir = clips_dir / "work"
        for directory in (final_dir, raw_dir, work_dir):
            directory.mkdir(parents=True, exist_ok=True)
            _clean_directory_files(directory)

        subtitle_renderer = (
            HardSubtitleRenderer(ffmpeg_binary=self._ffmpeg_binary)
            if options.hard_subtitle_enabled
            else None
        )
        media_renderer = (
            ClipCoverRenderer(
                ffmpeg_binary=self._ffmpeg_binary,
                ffprobe_binary=self._ffprobe_binary,
            )
            if options.cover_enabled or options.highlight_enabled
            else None
        )
        highlight_selector = HighlightIntroSelector() if options.highlight_enabled else None

        updated_clips: list[object] = []
        for raw_item in export_summary.get("clips", []):
            if not isinstance(raw_item, dict):
                updated_clips.append(raw_item)
                continue
            item = dict(raw_item)
            try:
                updated_clips.append(
                    self._process_clip(
                        item=item,
                        final_dir=final_dir,
                        raw_dir=raw_dir,
                        work_dir=work_dir,
                        options=options,
                        subtitle_renderer=subtitle_renderer,
                        media_renderer=media_renderer,
                        highlight_selector=highlight_selector,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - keep other clips available.
                item["postprocess_status"] = "failed"
                item["postprocess_error"] = str(exc)
                raw_clip_path = item.get("raw_clip_path")
                if isinstance(raw_clip_path, str) and raw_clip_path:
                    item["clip_path"] = raw_clip_path
                logger.warning("clip_postprocess_failed", title=item.get("title"), error=str(exc))
                updated_clips.append(item)

        result = dict(export_summary)
        result["clips"] = updated_clips
        result["postprocess"] = {
            "hard_subtitle": options.hard_subtitle_enabled,
            "cover": options.cover_enabled,
            "cover_image": str(options.cover_image_path) if options.cover_image_path else None,
            "highlight_intro": options.highlight_enabled,
            "final_dir": str(final_dir),
            "raw_dir": str(raw_dir),
            "work_dir": str(work_dir),
        }
        return result

    def _process_clip(
        self,
        *,
        item: dict[str, object],
        final_dir: Path,
        raw_dir: Path,
        work_dir: Path,
        options: ClipPostProcessOptions,
        subtitle_renderer: HardSubtitleRenderer | None,
        media_renderer: ClipCoverRenderer | None,
        highlight_selector: HighlightIntroSelector | None,
    ) -> dict[str, object]:
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

        if media_renderer is not None:
            current_video = self._render_cover_and_highlight(
                item=item,
                current_video=current_video,
                subtitle_path=subtitle_path,
                final_video=final_video,
                work_dir=work_dir,
                options=options,
                media_renderer=media_renderer,
                highlight_selector=highlight_selector,
            )
        elif current_video != final_video:
            shutil.copy2(current_video, final_video)
            current_video = final_video

        item["clip_path"] = str(current_video)
        item["final_video_path"] = str(current_video)
        item["postprocess_status"] = "completed"
        return item

    def _render_cover_and_highlight(
        self,
        *,
        item: dict[str, object],
        current_video: Path,
        subtitle_path: Path | None,
        final_video: Path,
        work_dir: Path,
        options: ClipPostProcessOptions,
        media_renderer: ClipCoverRenderer,
        highlight_selector: HighlightIntroSelector | None,
    ) -> Path:
        spec = media_renderer.probe_video(current_video)
        highlight_start: float | None = None
        highlight_end: float | None = None
        highlight_reason: str | None = None
        highlight_confidence: float | None = None
        highlight_enabled = False

        if highlight_selector is not None:
            try:
                decision = highlight_selector.select(
                    title=str(options.cover_title or item.get("title") or "精彩片段"),
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
            except Exception as exc:  # noqa: BLE001 - cover can still be generated.
                highlight_reason = f"高能片头选择失败，已跳过: {exc}"
                highlight_confidence = 0.0

        if options.cover_enabled:
            cover_result = media_renderer.render(
                clip_id=int(item.get("index", 0)) + 1,
                video_path=current_video,
                output_dir=work_dir,
                title=str(options.cover_title or item.get("title") or "精彩片段"),
                source_image_path=options.cover_image_path,
                cover_duration_seconds=options.cover_duration_seconds,
                highlight_enabled=highlight_enabled,
                highlight_start_seconds=highlight_start,
                highlight_end_seconds=highlight_end,
            )
            _replace_file(cover_result.final_video_path, final_video)

            item["cover_title"] = str(options.cover_title or item.get("title") or "精彩片段")
            item["cover_source_image_path"] = (
                str(options.cover_image_path) if options.cover_image_path else None
            )
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
            item["final_video_path"] = str(final_video)
            item["final_duration_seconds"] = cover_result.duration_seconds
            return final_video

        if highlight_enabled and highlight_start is not None and highlight_end is not None:
            highlight_video = work_dir / f"{current_video.stem}_highlight_intro.mp4"
            media_renderer._run_ffmpeg(  # noqa: SLF001 - reuse ffmpeg command builder.
                media_renderer._highlight_intro_command(  # noqa: SLF001
                    video_path=current_video,
                    output_path=highlight_video,
                    spec=spec,
                    start_seconds=highlight_start,
                    duration_seconds=max(0.0, highlight_end - highlight_start),
                )
            )
            media_renderer._run_ffmpeg(  # noqa: SLF001
                media_renderer._concat_final_command(  # noqa: SLF001
                    input_paths=[highlight_video, current_video],
                    output_path=final_video,
                    spec=spec,
                )
            )
            item["highlight_enabled"] = True
            item["highlight_start_seconds"] = highlight_start
            item["highlight_end_seconds"] = highlight_end
            item["highlight_reason"] = highlight_reason
            item["highlight_confidence"] = highlight_confidence
            item["highlight_video_path"] = str(highlight_video)
            item["final_video_path"] = str(final_video)
            item["final_duration_seconds"] = spec.duration_seconds + max(
                0.0, highlight_end - highlight_start
            )
            return final_video

        shutil.copy2(current_video, final_video)
        item["highlight_enabled"] = False
        item["highlight_reason"] = highlight_reason
        item["highlight_confidence"] = highlight_confidence
        item["final_video_path"] = str(final_video)
        item["final_duration_seconds"] = spec.duration_seconds
        return final_video


def options_from_pipeline_config(
    config: PipelineConfig,
    *,
    base_dir: Path | None = None,
) -> ClipPostProcessOptions:
    """Build post-process options from task pipeline config."""
    hard_subtitle = _section(config.hard_subtitle)
    cover = _section(config.cover)
    highlight = _section(config.highlight_intro)

    cover_image_path = _optional_path(
        cover.get("source_image_path") or cover.get("image_path"),
        base_dir=base_dir,
    )
    return ClipPostProcessOptions(
        hard_subtitle_enabled=_enabled(hard_subtitle),
        cover_enabled=_enabled(cover),
        cover_image_path=cover_image_path,
        cover_title=_optional_str(cover.get("title")),
        cover_duration_seconds=_optional_float(cover.get("duration_seconds"), default=1.0),
        highlight_enabled=_enabled(highlight),
    )


def _section(value: dict[str, Any] | bool | None) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, bool):
        return {"enabled": value}
    return {}


def _enabled(section: dict[str, Any]) -> bool:
    return bool(section.get("enabled", False))


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _optional_float(value: object, *, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _optional_path(value: object, *, base_dir: Path | None = None) -> Path | None:
    text = _optional_str(value)
    if text is None:
        return None
    path = Path(text).expanduser()
    if not path.is_absolute() and base_dir is not None:
        return base_dir / path
    return path


def _clean_directory_files(directory: Path) -> None:
    for path in directory.iterdir():
        if path.is_file():
            path.unlink(missing_ok=True)


def _move_to_raw(source: Path, target: Path) -> Path:
    if source.resolve() == target.resolve():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    shutil.move(str(source), str(target))
    return target


def _replace_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target.unlink()
    shutil.move(str(source), str(target))
