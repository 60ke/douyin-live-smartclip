"""Clip cover rendering and cover-intro video generation."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from liveclip.utils.process import run_command

CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class VideoSpec:
    """Basic video properties needed for cover rendering."""

    width: int
    height: int
    duration_seconds: float


@dataclass(frozen=True)
class CoverRenderResult:
    """Generated cover assets for a clip."""

    cover_image_path: Path
    cover_intro_video_path: Path
    final_video_path: Path
    highlight_video_path: Path | None
    highlight_enabled: bool
    highlight_start_seconds: float | None
    highlight_end_seconds: float | None
    highlight_reason: str | None
    highlight_confidence: float | None
    width: int
    height: int
    duration_seconds: float


class ClipCoverRenderer:
    """Generate cover image, 1-second cover intro, and final clip video."""

    def __init__(
        self,
        *,
        ffmpeg_binary: str = "ffmpeg",
        ffprobe_binary: str = "ffprobe",
        font_path: Path | None = None,
        command_runner: CommandRunner = run_command,
    ) -> None:
        self._ffmpeg_binary = ffmpeg_binary
        self._ffprobe_binary = ffprobe_binary
        self._font_path = font_path
        self._command_runner = command_runner

    def render(
        self,
        *,
        clip_id: int,
        video_path: Path,
        output_dir: Path,
        title: str,
        source_image_path: Path | None = None,
        cover_duration_seconds: float = 1.0,
        highlight_enabled: bool = False,
        highlight_start_seconds: float | None = None,
        highlight_end_seconds: float | None = None,
    ) -> CoverRenderResult:
        """Render cover assets and prepend the cover intro to the clip video."""
        if not video_path.exists():
            raise FileNotFoundError(f"切片视频不存在: {video_path}")
        if source_image_path is not None and not source_image_path.exists():
            raise FileNotFoundError(f"封面图片不存在: {source_image_path}")
        if cover_duration_seconds <= 0:
            raise ValueError("封面时长必须大于 0")

        spec = self.probe_video(video_path)
        output_dir.mkdir(parents=True, exist_ok=True)

        stem = f"clip_{clip_id:06d}"
        cover_image_path = output_dir / f"{stem}_cover.png"
        first_frame_path = output_dir / f"{stem}_first_frame.jpg"
        cover_intro_video_path = output_dir / f"{stem}_cover_intro.mp4"
        highlight_video_path = output_dir / f"{stem}_highlight_intro.mp4"
        final_video_path = output_dir / f"{stem}_final.mp4"
        highlight = self._select_highlight(
            spec=spec,
            enabled=highlight_enabled,
            start_seconds=highlight_start_seconds,
            end_seconds=highlight_end_seconds,
        )

        self._run_ffmpeg(
            self._first_frame_command(video_path=video_path, output_path=first_frame_path)
        )
        self.render_cover_image(
            output_path=cover_image_path,
            title=title,
            width=spec.width,
            height=spec.height,
            source_image_path=source_image_path,
            frame_image_path=first_frame_path,
        )
        self._run_ffmpeg(
            self._cover_intro_command(
                cover_image_path=cover_image_path,
                output_path=cover_intro_video_path,
                spec=spec,
                duration_seconds=cover_duration_seconds,
            )
        )
        concat_paths = [cover_intro_video_path]
        if highlight.enabled:
            if highlight.start_seconds is None:
                raise ValueError("高能片头开始时间为空")
            self._run_ffmpeg(
                self._highlight_intro_command(
                    video_path=video_path,
                    output_path=highlight_video_path,
                    spec=spec,
                    start_seconds=highlight.start_seconds,
                    duration_seconds=highlight.duration_seconds,
                )
            )
            concat_paths.append(highlight_video_path)
        else:
            highlight_video_path.unlink(missing_ok=True)
        concat_paths.append(video_path)

        self._run_ffmpeg(
            self._concat_final_command(
                input_paths=concat_paths,
                output_path=final_video_path,
                spec=spec,
            )
        )

        return CoverRenderResult(
            cover_image_path=cover_image_path,
            cover_intro_video_path=cover_intro_video_path,
            final_video_path=final_video_path,
            highlight_video_path=highlight_video_path if highlight.enabled else None,
            highlight_enabled=highlight.enabled,
            highlight_start_seconds=highlight.start_seconds if highlight.enabled else None,
            highlight_end_seconds=highlight.end_seconds if highlight.enabled else None,
            highlight_reason=highlight.reason if highlight.enabled else None,
            highlight_confidence=highlight.confidence if highlight.enabled else None,
            width=spec.width,
            height=spec.height,
            duration_seconds=(
                spec.duration_seconds + cover_duration_seconds + highlight.duration_seconds
            ),
        )

    def probe_video(self, video_path: Path) -> VideoSpec:
        """Probe video width, height, and duration using ffprobe."""
        cmd = [
            self._ffprobe_binary,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height:format=duration",
            "-of",
            "json",
            str(video_path),
        ]
        result = self._command_runner(cmd)
        data = json.loads(result.stdout or "{}")
        streams = data.get("streams") or []
        if not streams:
            raise ValueError(f"无法读取视频规格: {video_path}")
        stream = streams[0]
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        duration = float((data.get("format") or {}).get("duration") or 0.0)
        if width <= 0 or height <= 0:
            raise ValueError(f"视频宽高无效: {video_path}")
        return VideoSpec(width=width, height=height, duration_seconds=duration)

    def render_cover_image(
        self,
        *,
        output_path: Path,
        title: str,
        width: int,
        height: int,
        source_image_path: Path | None = None,
        frame_image_path: Path | None = None,
    ) -> Path:
        """Render a PNG cover image matching the target video resolution."""
        if width <= 0 or height <= 0:
            raise ValueError("封面宽高必须大于 0")

        template = self._load_cover_template(source_image_path)
        canvas = self._center_crop(template, width, height).convert("RGBA")
        safe_box = (
            self._centered_aspect_box(width, height, aspect_ratio=3 / 4)
            if width >= height
            else (0, 0, width, height)
        )
        poster_width = safe_box[2] - safe_box[0]
        poster_height = safe_box[3] - safe_box[1]
        poster = self._load_frame_image(frame_image_path, poster_width, poster_height).convert(
            "RGBA"
        )
        template_overlay = self._center_crop(template, poster_width, poster_height).convert("RGBA")
        frame_box = self._frame_box(poster_width, poster_height)
        self._clear_template_frame_area(template_overlay, frame_box=frame_box)
        poster.alpha_composite(template_overlay)
        draw = ImageDraw.Draw(poster)

        title_text = title.strip() or "精彩片段"
        font_size = max(26, min(72, int(poster_width * 0.13)))
        font = self._load_font(font_size)
        max_text_width = int(poster_width * 0.76)
        lines = self._wrap_text(title_text, draw, font, max_text_width, max_lines=2)

        line_spacing = int(font_size * 0.18)
        line_heights = [self._text_size(draw, line, font)[1] for line in lines]
        y = int(poster_height * 0.11)
        x = int(poster_width * 0.12)

        current_y = y
        for line, line_height in zip(lines, line_heights, strict=True):
            self._draw_title_text(draw, (x, current_y), line, font, font_size=font_size)
            current_y += line_height + line_spacing

        separator_y = int(poster_height * 0.245)
        self._draw_dotted_line(
            draw,
            x0=int(poster_width * 0.06),
            x1=int(poster_width * 0.94),
            y=separator_y,
            color=(255, 255, 255, 112),
        )

        self._draw_frame_border(poster, frame_box=frame_box)
        canvas.alpha_composite(poster, dest=(safe_box[0], safe_box[1]))
        output = canvas.convert("RGB")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output.save(output_path, format="PNG")
        return output_path

    def _run_ffmpeg(self, cmd: list[str]) -> None:
        self._command_runner(cmd)

    def _first_frame_command(self, *, video_path: Path, output_path: Path) -> list[str]:
        return [
            self._ffmpeg_binary,
            "-y",
            "-ss",
            "0",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output_path),
        ]

    def _cover_intro_command(
        self,
        *,
        cover_image_path: Path,
        output_path: Path,
        spec: VideoSpec,
        duration_seconds: float,
    ) -> list[str]:
        return [
            self._ffmpeg_binary,
            "-y",
            "-loop",
            "1",
            "-t",
            f"{duration_seconds:.3f}",
            "-i",
            str(cover_image_path),
            "-f",
            "lavfi",
            "-t",
            f"{duration_seconds:.3f}",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-vf",
            f"scale={spec.width}:{spec.height},format=yuv420p",
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

    def _highlight_intro_command(
        self,
        *,
        video_path: Path,
        output_path: Path,
        spec: VideoSpec,
        start_seconds: float,
        duration_seconds: float,
    ) -> list[str]:
        return [
            self._ffmpeg_binary,
            "-y",
            "-ss",
            f"{start_seconds:.3f}",
            "-t",
            f"{duration_seconds:.3f}",
            "-i",
            str(video_path),
            "-vf",
            f"scale={spec.width}:{spec.height},format=yuv420p",
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-movflags",
            "+faststart",
            str(output_path),
        ]

    def _concat_final_command(
        self,
        *,
        input_paths: list[Path],
        output_path: Path,
        spec: VideoSpec,
    ) -> list[str]:
        if len(input_paths) < 2:
            raise ValueError("最终视频拼接至少需要封面片头和原视频")

        cmd = [
            self._ffmpeg_binary,
            "-y",
        ]
        for input_path in input_paths:
            cmd.extend(["-i", str(input_path)])

        filter_parts: list[str] = []
        concat_inputs: list[str] = []
        for index in range(len(input_paths)):
            filter_parts.append(
                f"[{index}:v]fps=30,scale={spec.width}:{spec.height},"
                f"setsar=1,setpts=PTS-STARTPTS[v{index}]"
            )
            filter_parts.append(
                f"[{index}:a]aformat=sample_rates=44100:channel_layouts=stereo,"
                f"asetpts=PTS-STARTPTS[a{index}]"
            )
            concat_inputs.append(f"[v{index}][a{index}]")
        filter_parts.append(
            f"{''.join(concat_inputs)}concat=n={len(input_paths)}:v=1:a=1[v][a]"
        )

        cmd.extend(
            [
                "-filter_complex",
                ";".join(filter_parts),
                "-map",
                "[v]",
                "-map",
                "[a]",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "18",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
        )
        return cmd

    def _load_cover_template(self, source_image_path: Path | None) -> Image.Image:
        for path in self._cover_template_candidates(source_image_path):
            if path.exists():
                return Image.open(path).convert("RGBA")
        return self._fallback_background(720, 1280).convert("RGBA")

    def _cover_template_candidates(self, source_image_path: Path | None) -> list[Path]:
        candidates: list[Path] = []
        if source_image_path is not None:
            candidates.append(source_image_path)
        env_path = os.getenv("LIVECLIP_COVER_TEMPLATE_PATH")
        if env_path:
            candidates.append(Path(env_path))
        candidates.append(
            Path(__file__).resolve().parents[3]
            / "assets"
            / "cover_templates"
            / "smartclip-blue-frame-template.png"
        )
        return candidates

    def _load_font(self, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        for path in self._font_candidates():
            if path.exists():
                try:
                    return ImageFont.truetype(str(path), size=size)
                except OSError:
                    continue
        return ImageFont.load_default(size=size)

    def _font_candidates(self) -> list[Path]:
        candidates: list[Path] = []
        env_path = os.getenv("LIVECLIP_COVER_FONT_PATH")
        if env_path:
            candidates.append(Path(env_path))
        if self._font_path is not None:
            candidates.append(self._font_path)
        candidates.extend(
            [
                Path(__file__).resolve().parents[3]
                / "assets"
                / "fonts"
                / "YOUSHEBIAOTIHEI-2.TTF",
                Path("/Users/k/Downloads/Noto_Sans_SC/static/NotoSansSC-Bold.ttf"),
                Path("/Users/k/Downloads/Noto_Sans_SC/static/NotoSansSC-SemiBold.ttf"),
                Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"),
                Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"),
                Path("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"),
                Path("/System/Library/Fonts/PingFang.ttc"),
                Path("/Library/Fonts/Arial Unicode.ttf"),
            ]
        )
        return candidates

    @staticmethod
    def _fallback_background(width: int, height: int) -> Image.Image:
        image = Image.new("RGB", (width, height), "#111827")
        draw = ImageDraw.Draw(image)
        for y in range(height):
            ratio = y / max(1, height - 1)
            r = int(17 + 10 * ratio)
            g = int(24 + 58 * ratio)
            b = int(39 + 68 * ratio)
            draw.line((0, y, width, y), fill=(r, g, b))
        return image

    @staticmethod
    def _center_crop(image: Image.Image, target_width: int, target_height: int) -> Image.Image:
        source_width, source_height = image.size
        scale = max(target_width / source_width, target_height / source_height)
        resized = image.resize(
            (int(source_width * scale + 0.5), int(source_height * scale + 0.5)),
            Image.Resampling.LANCZOS,
        )
        left = (resized.width - target_width) // 2
        top = (resized.height - target_height) // 2
        return resized.crop((left, top, left + target_width, top + target_height))

    @staticmethod
    def _centered_aspect_box(
        width: int,
        height: int,
        *,
        aspect_ratio: float,
    ) -> tuple[int, int, int, int]:
        if width / height >= aspect_ratio:
            box_height = height
            box_width = int(box_height * aspect_ratio + 0.5)
        else:
            box_width = width
            box_height = int(box_width / aspect_ratio + 0.5)
        left = (width - box_width) // 2
        top = (height - box_height) // 2
        return left, top, left + box_width, top + box_height

    @staticmethod
    def _frame_box(width: int, height: int) -> tuple[int, int, int, int]:
        left = int(width * 0.062)
        top = int(height * 0.292)
        right = int(width * 0.938)
        bottom = int(height * 0.828)
        return left, top, right, bottom

    def _paste_frame(
        self,
        poster: Image.Image,
        *,
        frame_box: tuple[int, int, int, int],
        frame_image_path: Path | None,
    ) -> None:
        left, top, right, bottom = frame_box
        frame_width = right - left
        frame_height = bottom - top
        frame = self._load_frame_image(frame_image_path, frame_width, frame_height).convert("RGBA")
        radius = max(8, int(frame_width * 0.035))
        mask = Image.new("L", (frame_width, frame_height), 0)
        mask_draw = ImageDraw.Draw(mask)
        mask_draw.rounded_rectangle((0, 0, frame_width, frame_height), radius=radius, fill=255)
        poster.paste(frame, (left, top), mask)

        border = Image.new("RGBA", poster.size, (0, 0, 0, 0))
        border_draw = ImageDraw.Draw(border)
        border_draw.rounded_rectangle(
            (left, top, right - 1, bottom - 1),
            radius=radius,
            outline=(255, 255, 255, 238),
            width=max(2, int(frame_width * 0.008)),
        )
        poster.alpha_composite(border)

    @staticmethod
    def _clear_template_frame_area(
        template_overlay: Image.Image,
        *,
        frame_box: tuple[int, int, int, int],
    ) -> None:
        left, top, right, bottom = frame_box
        frame_width = right - left
        radius = max(8, int(frame_width * 0.035))
        transparent_mask = Image.new("L", template_overlay.size, 0)
        mask_draw = ImageDraw.Draw(transparent_mask)
        inset = max(2, int(frame_width * 0.008))
        mask_draw.rounded_rectangle(
            (left + inset, top + inset, right - 1 - inset, bottom - 1 - inset),
            radius=max(1, radius - inset),
            fill=255,
        )
        alpha = template_overlay.getchannel("A")
        alpha.paste(0, mask=transparent_mask)
        template_overlay.putalpha(alpha)

    @staticmethod
    def _draw_frame_border(
        poster: Image.Image,
        *,
        frame_box: tuple[int, int, int, int],
    ) -> None:
        left, top, right, bottom = frame_box
        frame_width = right - left
        radius = max(8, int(frame_width * 0.035))
        border = Image.new("RGBA", poster.size, (0, 0, 0, 0))
        border_draw = ImageDraw.Draw(border)
        border_draw.rounded_rectangle(
            (left, top, right - 1, bottom - 1),
            radius=radius,
            outline=(255, 255, 255, 238),
            width=max(2, int(frame_width * 0.008)),
        )
        poster.alpha_composite(border)

    def _load_frame_image(
        self,
        frame_image_path: Path | None,
        width: int,
        height: int,
    ) -> Image.Image:
        if frame_image_path is not None and frame_image_path.exists():
            return self._center_crop(Image.open(frame_image_path).convert("RGB"), width, height)
        return Image.new("RGB", (width, height), "#050505")

    @staticmethod
    def _draw_dotted_line(
        draw: ImageDraw.ImageDraw,
        *,
        x0: int,
        x1: int,
        y: int,
        color: tuple[int, int, int, int],
    ) -> None:
        dash = 2
        gap = 3
        x = x0
        while x < x1:
            draw.line((x, y, min(x + dash, x1), y), fill=color, width=1)
            x += dash + gap

    @staticmethod
    def _wrap_text(
        text: str,
        draw: ImageDraw.ImageDraw,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
        max_width: int,
        *,
        max_lines: int,
    ) -> list[str]:
        chars = list(text)
        lines: list[str] = []
        current = ""
        for char in chars:
            candidate = current + char
            if current and ClipCoverRenderer._text_size(draw, candidate, font)[0] > max_width:
                lines.append(current)
                current = char
                if len(lines) >= max_lines:
                    break
            else:
                current = candidate
        if current and len(lines) < max_lines:
            lines.append(current)
        if not lines:
            return [text[:12] or "精彩片段"]
        if len(lines) == max_lines and "".join(lines) != text:
            lines[-1] = lines[-1].rstrip("，。,. ") + "..."
        return lines

    @staticmethod
    def _draw_title_text(
        draw: ImageDraw.ImageDraw,
        position: tuple[int, int],
        text: str,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
        *,
        font_size: int,
    ) -> None:
        draw.text(
            position,
            text,
            fill=(255, 255, 255, 255),
            font=font,
            stroke_width=max(1, int(font_size * 0.035)),
            stroke_fill=(38, 155, 255, 190),
        )

    @staticmethod
    def _text_size(
        draw: ImageDraw.ImageDraw,
        text: str,
        font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
    ) -> tuple[int, int]:
        bbox = draw.textbbox((0, 0), text, font=font)
        return int(bbox[2] - bbox[0]), int(bbox[3] - bbox[1])

    @staticmethod
    def _select_highlight(
        *,
        spec: VideoSpec,
        enabled: bool,
        start_seconds: float | None,
        end_seconds: float | None,
    ) -> HighlightSelection:
        if not enabled:
            return HighlightSelection.disabled()
        if spec.duration_seconds <= 0:
            return HighlightSelection.disabled()

        if start_seconds is not None or end_seconds is not None:
            if start_seconds is None or end_seconds is None:
                raise ValueError("高能片头开始和结束时间必须同时填写")
            if start_seconds < 0 or end_seconds <= start_seconds:
                raise ValueError("高能片头时间范围无效")
            if end_seconds > spec.duration_seconds:
                raise ValueError("高能片头结束时间不能超过切片时长")
            duration = end_seconds - start_seconds
            if duration < 1.0 or duration > 10.0:
                raise ValueError("高能片头时长需要在 1-10 秒之间")
            return HighlightSelection(
                enabled=True,
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                reason="手工指定高能片段",
                confidence=1.0,
            )

        if spec.duration_seconds < 20.0:
            return HighlightSelection.disabled(reason="切片低于 20 秒，跳过高能片头")

        duration = min(8.0, max(3.0, spec.duration_seconds * 0.08))
        duration = min(duration, spec.duration_seconds)
        start = max(0.0, spec.duration_seconds - duration)
        if start < 8.0:
            return HighlightSelection.disabled(reason="高能候选位于视频开头，跳过重复片头")
        return HighlightSelection(
            enabled=True,
            start_seconds=start,
            end_seconds=start + duration,
            reason="自动选择切片末尾高信息密度片段作为高能片头",
            confidence=0.72,
        )


@dataclass(frozen=True)
class HighlightSelection:
    enabled: bool
    start_seconds: float | None = None
    end_seconds: float | None = None
    reason: str | None = None
    confidence: float | None = None

    @property
    def duration_seconds(self) -> float:
        if not self.enabled or self.start_seconds is None or self.end_seconds is None:
            return 0.0
        return self.end_seconds - self.start_seconds

    @classmethod
    def disabled(cls, reason: str | None = None) -> HighlightSelection:
        return cls(enabled=False, reason=reason)
