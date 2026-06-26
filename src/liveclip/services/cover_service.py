"""Clip cover rendering and cover-intro video generation."""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from liveclip.adapters.gpt_image import GPTImageClient, GPTImageInput
from liveclip.config import load_settings
from liveclip.observability import get_logger
from liveclip.utils.process import run_command

CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]
COVER_FRAME_DURATION_SECONDS = 1 / 30
AI_COVER_MAX_REFERENCE_FRAMES = 3
AI_COVER_EDIT_MAX_ATTEMPTS = 3
AI_COVER_EDIT_RETRY_DELAY_SECONDS = 10.0
logger = get_logger(__name__)


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
    """Generate cover image, single-frame cover intro, and final clip video."""

    def __init__(
        self,
        *,
        ffmpeg_binary: str = "ffmpeg",
        ffprobe_binary: str = "ffprobe",
        font_path: Path | None = None,
        command_runner: CommandRunner = run_command,
        ai_cover_client: GPTImageClient | None = None,
        ai_cover_retry_delay_seconds: float = AI_COVER_EDIT_RETRY_DELAY_SECONDS,
    ) -> None:
        self._ffmpeg_binary = ffmpeg_binary
        self._ffprobe_binary = ffprobe_binary
        self._font_path = font_path
        self._command_runner = command_runner
        self._ai_cover_client = ai_cover_client or self._load_ai_cover_client()
        self._ai_cover_retry_delay_seconds = max(0.0, ai_cover_retry_delay_seconds)

    def render(
        self,
        *,
        clip_id: int,
        video_path: Path,
        output_dir: Path,
        title: str,
        source_image_path: Path | None = None,
        cover_frame_video_path: Path | None = None,
        highlight_enabled: bool = False,
        highlight_start_seconds: float | None = None,
        highlight_end_seconds: float | None = None,
    ) -> CoverRenderResult:
        """Render cover assets and prepend the cover intro to the clip video."""
        if not video_path.exists():
            raise FileNotFoundError(f"切片视频不存在: {video_path}")
        spec = self.probe_video(video_path)
        frame_video_path = cover_frame_video_path or video_path
        if cover_frame_video_path is not None and not cover_frame_video_path.exists():
            raise FileNotFoundError(f"封面抽帧视频不存在: {cover_frame_video_path}")
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

        selected_frame_paths = self._extract_cover_frames(
            video_path=frame_video_path,
            output_path=first_frame_path,
            duration_seconds=spec.duration_seconds,
            max_frames=AI_COVER_MAX_REFERENCE_FRAMES,
        )
        self.render_cover_image(
            output_path=cover_image_path,
            title=title,
            width=spec.width,
            height=spec.height,
            frame_image_path=selected_frame_paths[0],
            frame_image_paths=selected_frame_paths,
        )
        self._run_ffmpeg(
            self._cover_intro_command(
                cover_image_path=cover_image_path,
                output_path=cover_intro_video_path,
                spec=spec,
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
                spec.duration_seconds + COVER_FRAME_DURATION_SECONDS + highlight.duration_seconds
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
        frame_image_paths: list[Path] | None = None,
    ) -> Path:
        """Render a PNG cover image matching the target video resolution."""
        if width <= 0 or height <= 0:
            raise ValueError("封面宽高必须大于 0")

        ai_frame_paths = [
            path
            for path in (frame_image_paths or ([frame_image_path] if frame_image_path else []))
            if path.exists()
        ]
        if ai_frame_paths:
            self._render_ai_cover_image(
                output_path=output_path,
                title=title,
                width=width,
                height=height,
                frame_image_paths=ai_frame_paths[:AI_COVER_MAX_REFERENCE_FRAMES],
            )
            return output_path

        canvas = self._fallback_background(width, height).convert("RGBA")
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
        frame_box = self._frame_box(poster_width, poster_height)
        draw = ImageDraw.Draw(poster)

        title_text = title.strip() or "精彩片段"
        title_area_top = int(poster_height * 0.122)
        title_area_bottom = int(poster_height * 0.218)
        title_left, _, title_right, _ = frame_box
        max_text_width = title_right - title_left
        font, font_size, lines = self._fit_title_lines(
            title_text,
            draw,
            max_text_width=max_text_width,
            max_text_height=title_area_bottom - title_area_top,
            poster_width=poster_width,
        )

        line_spacing = int(font_size * 0.18)
        line_heights = [self._text_size(draw, line, font)[1] for line in lines]
        title_block_height = sum(line_heights) + line_spacing * max(0, len(lines) - 1)
        y = title_area_top + max(0, (title_area_bottom - title_area_top - title_block_height) // 2)

        current_y = y
        for line, line_height in zip(lines, line_heights, strict=True):
            line_width = self._text_size(draw, line, font)[0]
            x = title_left + max(0, (max_text_width - line_width) // 2)
            self._draw_title_text(
                draw,
                (x, current_y),
                line,
                font,
                font_size=font_size,
            )
            current_y += line_height + line_spacing

        separator_y = int(poster_height * 0.245)
        self._draw_dotted_line(
            draw,
            x0=int(poster_width * 0.06),
            x1=int(poster_width * 0.94),
            y=separator_y,
            color=(255, 255, 255, 112),
        )

        canvas.alpha_composite(poster, dest=(safe_box[0], safe_box[1]))
        output = canvas.convert("RGB")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output.save(output_path, format="PNG")
        return output_path

    @staticmethod
    def _load_ai_cover_client() -> GPTImageClient | None:
        try:
            settings = load_settings()
        except Exception as exc:  # noqa: BLE001 - report a clear cover-generation error later.
            logger.warning("gpt_image_settings_load_failed", error=str(exc))
            return None
        if not settings.gpt_image.enabled:
            return None
        client = GPTImageClient(settings.gpt_image)
        return client if client.configured else None

    def _render_ai_cover_image(
        self,
        *,
        output_path: Path,
        title: str,
        width: int,
        height: int,
        frame_image_paths: list[Path],
    ) -> None:
        client = self._ai_cover_client
        if client is None:
            raise RuntimeError("AI 封面生成未配置，无法生成封面")
        if not frame_image_paths:
            raise RuntimeError("AI 封面生成缺少视频关键帧")

        prepared_paths: list[Path] = []
        try:
            prompt = self._build_ai_cover_prompt(
                title=title,
                width=width,
                height=height,
            )
            reference_images: list[GPTImageInput] = []
            for index, frame_image_path in enumerate(frame_image_paths, start=1):
                frame_path = self._prepare_ai_frame_reference(frame_image_path, width, height)
                prepared_paths.append(frame_path)
                reference_images.append(
                    GPTImageInput(
                        path=frame_path,
                        filename=f"image_{index}_video_key_frame.png",
                        content_type="image/png",
                    )
                )
            image_bytes = self._edit_ai_cover_with_retry(
                client=client,
                images=reference_images,
                prompt=prompt,
                size=self._gpt_image_size(width, height),
                title=title,
            )
            self._save_ai_cover_bytes(image_bytes, output_path=output_path, width=width, height=height)
            logger.info("ai_cover_rendered", output_path=str(output_path), title=title)
        except Exception as exc:
            logger.warning(
                "ai_cover_render_failed",
                error=str(exc),
                title=title,
                exc_info=True,
            )
            raise RuntimeError(f"AI 封面生成失败: {exc}") from exc
        finally:
            for temp_path in prepared_paths:
                temp_path.unlink(missing_ok=True)

    def _edit_ai_cover_with_retry(
        self,
        *,
        client: GPTImageClient,
        images: list[GPTImageInput],
        prompt: str,
        size: str,
        title: str,
    ) -> bytes:
        last_exc: Exception | None = None
        for attempt in range(1, AI_COVER_EDIT_MAX_ATTEMPTS + 1):
            try:
                return client.edit(images=images, prompt=prompt, size=size)
            except Exception as exc:
                last_exc = exc
                if attempt >= AI_COVER_EDIT_MAX_ATTEMPTS:
                    break
                logger.warning(
                    "ai_cover_edit_retry",
                    attempt=attempt,
                    max_attempts=AI_COVER_EDIT_MAX_ATTEMPTS,
                    delay_seconds=self._ai_cover_retry_delay_seconds,
                    error=str(exc),
                    title=title,
                )
                if self._ai_cover_retry_delay_seconds > 0:
                    time.sleep(self._ai_cover_retry_delay_seconds)
        assert last_exc is not None
        raise last_exc

    def _prepare_ai_frame_reference(
        self,
        frame_image_path: Path,
        width: int,
        height: int,
    ) -> Path:
        frame = self._center_crop_with_zoom(
            Image.open(frame_image_path).convert("RGB"),
            width,
            height,
            zoom=1.04,
        )
        return self._write_ai_reference_image(frame, "ai_cover_frame")

    @staticmethod
    def _write_ai_reference_image(image: Image.Image, prefix: str) -> Path:
        temp = tempfile.NamedTemporaryFile(prefix=f"{prefix}_", suffix=".png", delete=False)
        temp_path = Path(temp.name)
        temp.close()
        image.save(temp_path, format="PNG")
        return temp_path

    @staticmethod
    def _save_ai_cover_bytes(image_bytes: bytes, *, output_path: Path, width: int, height: int) -> None:
        with tempfile.NamedTemporaryFile(prefix="ai_cover_result_", suffix=".png", delete=False) as tmp:
            tmp.write(image_bytes)
            tmp_path = Path(tmp.name)
        with Image.open(tmp_path) as image:
            cover = ClipCoverRenderer._center_crop(image.convert("RGB"), width, height)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            cover.save(output_path, format="PNG")
        tmp_path.unlink(missing_ok=True)

    @staticmethod
    def _gpt_image_size(width: int, height: int) -> str:
        if width == height:
            return "1024x1024"
        if height > width:
            return "1152x2048"
        return "2048x1152"

    @staticmethod
    def _build_ai_cover_prompt(
        *,
        title: str,
        width: int,
        height: int,
    ) -> str:
        title_text = title.strip() or "精彩片段"
        orientation = "vertical 9:16" if height >= width else "horizontal 16:9"
        crop_rule = (
            "抖音竖屏封面会从 9:16 画面中裁剪中央 3:4 区域作为列表封面。"
            "所有主标题、关键信息、人物脸部和主体动作必须集中在中央 3:4 安全区内；"
            "顶部和底部只能放可被裁掉的氛围背景、光效或纹理，不能放关键文字。"
            if height > width
            else
            "所有主标题、关键信息和主体必须位于画面中心安全区，四周只放可裁掉的背景氛围。"
        )
        reference_rule = (
            "1. 输入图按顺序为 Image A、Image B、Image C，均来自同一视频的非黑屏关键帧；可能少于三张。\n"
            "2. 请优先参考其中人物状态最好、画面最清晰、最适合做封面的形象作为主体素材使用。"
            "保留核心人物/画面内容，可进行适度抠图、描边、缩放、暗化背景、局部遮罩，让主体更突出。\n"
            "3. 没有固定模板时，请自主设计美观封面：使用清爽高对比配色、标题色块、几何贴纸、描边和层次化背景，做出中文短视频平台的成品封面。"
        )
        return f"""
你是短视频爆款封面设计师。请根据参考图生成一张完整封面图：
{reference_rule}

画面规格：{orientation}，最终会被裁剪到 {width}x{height}。
裁剪安全区要求：{crop_rule}
主标题必须准确使用这段中文，不要改字、不要多字、不要少字：{title_text}

设计要求：
- 做成中文短视频平台封面风格，强视觉冲击，类似教程案例/功能步骤/知识分享类封面。
- 所有核心内容必须放在中央 3:4 安全区域内，包括主标题、人物主体、可选补充短句；3:4 区域之外只能做背景延展、描边、光效、渐变和装饰，不能放关键信息。
- 主标题使用超大粗黑体或高对比粗体，允许分层排版、倾斜、色块承载，但必须清晰可读。
- 标题长度自适应，短标题可以更大并居中铺开，长标题自动换行或压缩，不能出画、不能被裁剪。
- 可根据画面内容提炼一句很短的补充文案，放在中央 3:4 安全区内；不要长句、不要废话、不要编造夸张承诺。
- 标题区域必须干净，主标题文字上方、下方、前后不得覆盖任何彩带、碎片、贴纸、装饰块或半透明遮挡。
- 可以添加少量小标签、箭头、几何贴纸、描边、阴影、半透明遮罩，但装饰只能放在边角、主体外侧或可裁掉的背景区域，不能进入标题文字外接矩形区域。
- 不要添加“免费领取、免费试用、7天免费、点击领取、进群领取”等诱导转化文案。
- 不要生成二维码、电话号码、水印、平台 logo、虚假按钮。
- 画面中心主体来自参考图，背景可以轻微压暗或增强层次，但尽量保留直播大屏、实景环境和关键场景可辨识；不要大面积虚化背景。
- 禁止排版杂乱、文字错误、人物变形、过多小字、核心内容超出 3:4 安全区。
- 输出单张成品封面，不要留白边，不要做多宫格，不要包含说明文字。
""".strip()

    def _run_ffmpeg(self, cmd: list[str]) -> None:
        self._command_runner(cmd)

    def _extract_cover_frame(
        self,
        *,
        video_path: Path,
        output_path: Path,
        duration_seconds: float,
    ) -> Path:
        return self._extract_cover_frames(
            video_path=video_path,
            output_path=output_path,
            duration_seconds=duration_seconds,
            max_frames=1,
        )[0]

    def _extract_cover_frames(
        self,
        *,
        video_path: Path,
        output_path: Path,
        duration_seconds: float,
        max_frames: int = 3,
    ) -> list[Path]:
        candidates = self._cover_frame_offsets(duration_seconds)
        selected_paths: list[Path] = []
        for index, offset_seconds in enumerate(candidates):
            candidate_path = (
                output_path
                if index == 0
                else output_path.with_name(f"{output_path.stem}_{index}{output_path.suffix}")
            )
            self._run_ffmpeg(
                self._frame_extract_command(
                    video_path=video_path,
                    output_path=candidate_path,
                    offset_seconds=offset_seconds,
                )
            )
            if not self._is_mostly_dark(candidate_path):
                selected_paths.append(candidate_path)
                if len(selected_paths) >= max(1, max_frames):
                    return selected_paths
        if selected_paths:
            return selected_paths
        raise ValueError(f"未能抽取到非黑屏封面参考帧: {video_path}")

    @staticmethod
    def _cover_frame_offsets(duration_seconds: float) -> list[float]:
        max_offset = max(0.0, duration_seconds - 0.1)
        offsets: list[float] = []
        candidate_offsets = (
            0.0,
            0.5,
            1.0,
            2.0,
            3.0,
            duration_seconds * 0.25,
            duration_seconds * 0.5,
            duration_seconds * 0.75,
            max_offset,
        )
        for offset in candidate_offsets:
            bounded = min(offset, max_offset)
            if all(abs(bounded - existing) > 0.05 for existing in offsets):
                offsets.append(bounded)
        return offsets or [0.0]

    def _frame_extract_command(
        self,
        *,
        video_path: Path,
        output_path: Path,
        offset_seconds: float,
    ) -> list[str]:
        return [
            self._ffmpeg_binary,
            "-y",
            "-ss",
            f"{offset_seconds:.3f}",
            "-i",
            str(video_path),
            "-frames:v",
            "1",
            "-q:v",
            "2",
            str(output_path),
        ]

    @staticmethod
    def _is_mostly_dark(image_path: Path) -> bool:
        try:
            with Image.open(image_path) as image:
                sample = image.convert("L").resize((32, 32), Image.Resampling.BOX)
                histogram = sample.histogram()
        except OSError:
            return True
        pixel_count = sum(histogram)
        if pixel_count == 0:
            return True
        average_luma = sum(value * count for value, count in enumerate(histogram)) / pixel_count
        bright_ratio = sum(histogram[35:]) / pixel_count
        return average_luma < 18 and bright_ratio < 0.08

    def _cover_intro_command(
        self,
        *,
        cover_image_path: Path,
        output_path: Path,
        spec: VideoSpec,
    ) -> list[str]:
        return [
            self._ffmpeg_binary,
            "-y",
            "-loop",
            "1",
            "-framerate",
            "30",
            "-t",
            f"{COVER_FRAME_DURATION_SECONDS:.6f}",
            "-i",
            str(cover_image_path),
            "-f",
            "lavfi",
            "-t",
            f"{COVER_FRAME_DURATION_SECONDS:.6f}",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=44100",
            "-vf",
            f"scale={spec.width}:{spec.height},format=yuv420p",
            "-r",
            "30",
            "-frames:v",
            "1",
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

    def _load_frame_image(
        self,
        frame_image_path: Path | None,
        width: int,
        height: int,
    ) -> Image.Image:
        if frame_image_path is not None and frame_image_path.exists():
            return self._center_crop_with_zoom(
                Image.open(frame_image_path).convert("RGB"),
                width,
                height,
                zoom=1.08,
            )
        return Image.new("RGB", (width, height), "#050505")

    @staticmethod
    def _center_crop_with_zoom(
        image: Image.Image,
        target_width: int,
        target_height: int,
        *,
        zoom: float = 1.0,
    ) -> Image.Image:
        source_width, source_height = image.size
        scale = max(target_width / source_width, target_height / source_height) * max(1.0, zoom)
        resized = image.resize(
            (int(source_width * scale + 0.5), int(source_height * scale + 0.5)),
            Image.Resampling.LANCZOS,
        )
        left = (resized.width - target_width) // 2
        top = (resized.height - target_height) // 2
        return resized.crop((left, top, left + target_width, top + target_height))

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

    def _fit_title_lines(
        self,
        text: str,
        draw: ImageDraw.ImageDraw,
        *,
        max_text_width: int,
        max_text_height: int,
        poster_width: int,
    ) -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, int, list[str]]:
        min_size = 30
        max_size = max(min_size, min(96, int(poster_width * 0.19)))
        fallback_font = self._load_font(min_size)
        fallback_lines = self._wrap_text(
            text,
            draw,
            fallback_font,
            max_text_width,
            max_lines=2,
        )
        for font_size in range(max_size, min_size - 1, -2):
            font = self._load_font(font_size)
            lines = self._wrap_text(text, draw, font, max_text_width, max_lines=2)
            line_spacing = int(font_size * 0.18)
            line_sizes = [self._text_size(draw, line, font) for line in lines]
            block_height = sum(height for _, height in line_sizes) + line_spacing * max(
                0,
                len(lines) - 1,
            )
            widest_line = max((width for width, _ in line_sizes), default=0)
            if block_height <= max_text_height and widest_line <= max_text_width:
                return font, font_size, lines
        return fallback_font, min_size, fallback_lines

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
