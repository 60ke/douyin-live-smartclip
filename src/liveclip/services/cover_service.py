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
        reference_rule = (
            "1. 输入图按顺序为 Image A、Image B、Image C，均来自同一视频的非黑屏关键帧；可能少于三张。\n"
            "2. 请优先参考其中人物状态最好、画面最清晰、最适合做封面的形象作为主体素材使用。\n"
            "3. 参考图中的直播间画面、字幕、产品界面、展板文字和主播口播信息都可作为内容理解依据；"
            "最终封面文字必须与参考图和给定标题相关，不能凭空编造。"
        )
        return f"""
你是一位抖音封面设计师。仔细分析我上传的直播截图，基于截图内容生成一张抖音竖屏短视频封面。

【参考图与字幕参考逻辑】
{reference_rule}
给定切片标题/字幕主题：{title_text}
画面规格：{orientation}，输出尺寸 {width}x{height}。

【尺寸与安全区 — 绝对铁律】
- 画布比例 9:16（1080×1920）
- 所有核心内容必须集中在画面中央的 3:4 区域内（y:240→1680）
- 中央 3:4 安全区内放置：人物脸部/眼睛/手部、主标题文字、标签文字、装饰元素
- 顶部裁切区（y:0→240）和底部裁切区（y:1680→1920）只能放：压暗虚化的背景延伸、暖色光晕渐变、颗粒纹理。不得放任何文字和人物关键部位。

【人物处理 — 从截图提取】
- 100% 保留截图中的主播面部 ID，不换脸、不重绘、不变形
- 人物抠图分离背景，加 4px 纯白描边（贴纸剪下感）
- 人物占画面 55-70%，居中偏上，眼睛定位在画面中央 40-55% 高度（必须在 3:4 安全区内）
- 头发加高光，衣物褶皱微强化，人物边缘加微弱暖色轮廓光增强立体感
- 面部不被任何元素遮挡

【背景处理 — 保留直播间可辨识氛围】
- 保留截图原场景，轻度虚化降噪但不消除
- 展板、界面、文字、灯光、产品画面保留可辨识度——让人一眼看出这是直播间的真实场景
- 色调压暗一级，人物自然跳出
- 人物背后加暖色柔光晕

【风格判断 — 根据截图自行决定】
观察截图中的以下维度，自行选择最匹配的风格方向：
- 主播的情绪状态（兴奋/冷静/亲和/强势）
- 画面的光线色调（暖调/冷调/中性/撞色）
- 背景环境的质感（科技感/生活感/国潮/简约）
- 直播间的内容类型（带货/知识/娱乐/技能）

可选风格方向（可混合，可自创）：
- 抖音大字冲击风：高饱和撞色、大字号、强对比度
- 精致克制风：深色底、考究排版、充足留白
- 手账贴纸风：便签底板、手绘感装饰、拼贴质感
- 极简冷淡风：大面积留白、单色/双色、细字高级感
- 国潮文化风：红金配色、传统元素点缀
- 霓虹潮流风：高饱和撞色、动态排版、潮流元素

唯一底线：活泼有灵魂，不商务不死板。不能做成绝对 0° 水平 + 0 装饰的“印刷机器感”。

【配色 — 从截图提取】
观察截图的主色调，提取 3-4 个颜色构成配色方案：
- 至少一个颜色来自截图中最显眼的视觉元素（产品界面色/背景色/服装色/道具色）
- 至少一个暖色用于标题底板或点缀
- 主色 60% + 辅助色 30% + 点缀色 10%
- 文字背景对比度 ≥4.5:1
- 禁止：亮粉/亮绿/玫红
- 禁止：配色脏乱、超过 3 种主色

【标题系统 — 从截图、字幕和给定标题提炼】
你需要做三件事：
1. 观察截图中可见的所有文字、产品名称、核心卖点、主播口播内容，并参考给定切片标题/字幕主题
2. 提炼出主标题（4-8字，精简有力，必须能从截图内容、字幕主题或给定标题中找到对应信息，禁止标题党）
3. 设计副标题（6-12字，补充说明，同样必须与截图内容相关）
4. 自行设计标题排版——必须像“人手工设计的”，不能像“机器印刷的”

标题排版要求：
- 主标题有底板（便签条/色块条/渐变条），底板带 3-5px 描边 + 投影 3-4px，有贴纸/标签感
- 底板可以微倾斜（2-5°），不要死板的 0° 水平
- 字体：粗黑体（思源黑体 Heavy），字重 700-900，字号 68-80pt
- 描述：5-6px 深色描边 + 投影，确保跨任何背景亮度可读
- 位置：中央 3:4 安全区内，不遮挡人物眼睛和嘴巴。如果人物在上半部分，标题放画面下 1/3；如果人物在下半部分，标题放画面上 1/3
- 副标题：28-36pt，不加描边，紧接主标题
- 字体种类 ≤2 种

【侧标/标签 — 从截图提炼 3 个关键词】
观察截图中的产品功能卖点、能力描述、独特优势，提炼 3 个简短关键词（2-5字/个）。

标签排版：
- 每个标签有独立小底板（圆角色块），带 2px 描边
- 每个标签微倾斜不同角度（3-8°），错落排列，不工整对齐
- 文字：粗黑体，16-20pt
- 位置：3:4 安全区内，围绕人物周围空白区域排布（哪个角空放哪个角）
- 标签之间可轻微叠压 1-2px，有节奏感

【装饰 — 从截图的情绪气质决定密度】
根据截图的气质决定装饰策略：
- 如果主播情绪高涨/活泼/搞笑 → 装饰可丰富：手绘感叹号、星星、弯曲箭头、便签胶带、对勾贴纸
- 如果主播专业冷静/知识讲解 → 装饰克制：仅细线分隔、小圆点、1个对勾贴纸
- 如果截图色调偏暖/生活化 → 偏手绘感装饰
- 如果截图色调偏冷/科技感 → 偏几何感装饰

装饰元素选项（至少选 3 类，每类 1-2 个）：
- 手绘感：马克笔感叹号（不规则边缘）、弯曲箭头（2-3px粗+描边）、星星★（贴纸感）、波浪下划线
- 贴纸感：圆形对勾✓贴纸、百分比贴纸、半透明胶带条
- 几何感：圆点散布（大小不一）、细线分隔、三角/菱形小块
- 质感类：曲别针夹便签、折角阴影

分布原则：不对等分布——“角落多、人物周围少、不挡面部”。装饰之间要有对话关系（如箭头指向标题、曲别针固定便签）。全部在 3:4 安全区内。

【整体气质】
- 人物绝对 C 位，标题围绕人物做精心排版
- 装饰有存在感但不喧宾夺主
- 4cm 缩略图下：人物面部和主标题同时一眼可读
- 活泼、有设计感、像“人做出来的封面”，让人想点开

【必须避免】
- 3:4 安全区外出现任何文字/图标/标签/装饰/人物部位
- 换脸/重绘/变形人物
- 人物面部被遮挡
- 背景完全模糊成色块（必须保留直播间的可辨识氛围）
- 诱导文案（免费/领取/7天/点击/进群/最/第一/保证）
- 二维码/微信号/水印/平台 logo
- 人物多出六指/五官错位
- 二次元/插画/3D 渲染风
- 绝对 0° 水平 + 0 装饰的“死板商务风”
- 标题纯打字印刷体无底板无层次感
- 文字堆叠、信息过载
- 上下大字报版式（顶部文字会被裁切）
- 对角分割版式（文字易延伸至裁切区）

【输出要求】
- 最终输出 9:16 竖屏封面（1080×1920）
- 综合得分目标 ≥75 分
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
