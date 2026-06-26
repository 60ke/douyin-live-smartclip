"""Render hard subtitles into clip videos."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from liveclip.domain.models import SubtitleEntry
from liveclip.services.cover_service import ClipCoverRenderer
from liveclip.subtitle.parser import parse_srt_file
from liveclip.utils.process import run_command

CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class HardSubtitleResult:
    """Generated hard-subtitle media assets."""

    ass_path: Path
    output_video_path: Path
    subtitle_count: int


class HardSubtitleRenderer:
    """Burn clip SRT subtitles into the video stream using ASS styling."""

    def __init__(
        self,
        *,
        ffmpeg_binary: str = "ffmpeg",
        font_name: str = "Noto Sans CJK SC",
        command_runner: CommandRunner = run_command,
    ) -> None:
        self._ffmpeg_binary = ffmpeg_binary
        self._font_name = font_name
        self._command_runner = command_runner
        self._probe = ClipCoverRenderer(command_runner=command_runner)

    def render(
        self,
        *,
        video_path: Path,
        subtitle_path: Path,
        output_path: Path,
        ass_path: Path | None = None,
    ) -> HardSubtitleResult:
        """Render hard subtitles into ``output_path``."""
        if not video_path.exists():
            raise FileNotFoundError(f"视频文件不存在: {video_path}")
        if not subtitle_path.exists():
            raise FileNotFoundError(f"字幕文件不存在: {subtitle_path}")

        spec = self._probe.probe_video(video_path)
        subtitles = parse_srt_file(subtitle_path)
        if not subtitles:
            raise ValueError(f"字幕为空，无法生成硬字幕: {subtitle_path}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_ass_path = ass_path or output_path.with_suffix(".ass")
        resolved_ass_path.write_text(
            _build_ass(
                width=spec.width,
                height=spec.height,
                font_name=self._font_name,
                entries=subtitles,
            ),
            encoding="utf-8",
        )

        cmd = [
            self._ffmpeg_binary,
            "-y",
            "-i",
            str(video_path),
            "-vf",
            f"ass='{_escape_filter_path(resolved_ass_path)}'",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        self._command_runner(cmd)
        return HardSubtitleResult(
            ass_path=resolved_ass_path,
            output_video_path=output_path,
            subtitle_count=len(subtitles),
        )


def _build_ass(
    *,
    width: int,
    height: int,
    font_name: str,
    entries: list[SubtitleEntry],
) -> str:
    font_size = max(32, min(84, int(height * 0.041)))
    margin_h = max(40, int(width * 0.105))
    margin_v = max(64, int(height * 0.25))
    outline = max(3, int(font_size * 0.085))
    shadow = max(1, int(font_size * 0.018))
    safe_text_width = width - margin_h * 2
    max_chars_per_line = max(7, min(11, int(safe_text_width / max(30, font_size * 0.95))))
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "",
        "[V4+ Styles]",
        (
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
            "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
            "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
            "Alignment, MarginL, MarginR, MarginV, Encoding"
        ),
        (
            f"Style: Default,{font_name},{font_size},&H00FFFFFF,&H000000FF,"
            f"&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,{outline},{shadow},"
            f"2,{margin_h},{margin_h},{margin_v},1"
        ),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for entry in entries:
        wrapped = _wrap_subtitle_text(entry.text, max_chars_per_line=max_chars_per_line)
        lines.append(
            "Dialogue: 0,"
            f"{_ass_time(entry.start)},{_ass_time(entry.end)},"
            f"Default,,0,0,0,,{_escape_ass_text(wrapped)}"
        )
    return "\n".join(lines) + "\n"


def _wrap_subtitle_text(text: str, *, max_chars_per_line: int) -> str:
    normalized = " ".join(text.replace("\n", " ").split())
    if len(normalized) <= max_chars_per_line:
        return normalized
    lines = [
        normalized[start : start + max_chars_per_line]
        for start in range(0, len(normalized), max_chars_per_line)
    ]
    lines = _fix_cjk_punctuation_wrap(lines)
    if len(lines) > 2:
        lines = lines[:2]
        lines[-1] = lines[-1].rstrip("，。,. ") + "..."
    return r"\N".join(lines)


def _fix_cjk_punctuation_wrap(lines: list[str]) -> list[str]:
    if len(lines) <= 1:
        return lines
    fixed: list[str] = [lines[0]]
    punctuation = "，。！？、；：,.!?:;"
    for line in lines[1:]:
        current = line
        while current and current[0] in punctuation:
            fixed[-1] += current[0]
            current = current[1:]
        if current:
            fixed.append(current)
    return fixed


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centiseconds = int(round((seconds - int(seconds)) * 100))
    if centiseconds >= 100:
        secs += 1
        centiseconds = 0
    return f"{hours}:{minutes:02d}:{secs:02d}.{centiseconds:02d}"


def _escape_ass_text(text: str) -> str:
    return text.replace("{", r"\{").replace("}", r"\}")


def _escape_filter_path(path: Path) -> str:
    return path.resolve().as_posix().replace("\\", "\\\\").replace("'", r"\\'")
