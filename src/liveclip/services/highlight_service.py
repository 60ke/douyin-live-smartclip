"""LLM-assisted highlight intro selection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from liveclip.adapters.llm import LLMClient
from liveclip.domain.models import SubtitleEntry
from liveclip.observability import get_logger
from liveclip.subtitle.parser import parse_srt_file
from liveclip.utils.json import clamp_score, extract_json_value

logger = get_logger(__name__)


@dataclass(frozen=True)
class HighlightIntroDecision:
    """Decision returned by the highlight intro selector."""

    enabled: bool
    start_seconds: float | None = None
    end_seconds: float | None = None
    reason: str | None = None
    confidence: float | None = None
    source: str = "llm"


class HighlightIntroSelector:
    """Select a short high-energy intro segment for a clip using LLM."""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self._llm_client = llm_client or LLMClient()

    def select(
        self,
        *,
        title: str,
        duration_seconds: float,
        subtitle_path: Path | None,
        reason: str = "",
        structure_reason: str = "",
    ) -> HighlightIntroDecision:
        """Ask LLM to choose a 3-8s highlight intro segment.

        Returns a disabled decision when the clip is too short or the LLM
        declines. Raises ``ValueError`` for malformed LLM output and
        ``LLMError`` for API failures.
        """
        if duration_seconds < 20:
            return HighlightIntroDecision(
                enabled=False,
                reason="切片低于 20 秒，跳过高能片头",
                confidence=0.0,
            )

        subtitles = _load_subtitles(subtitle_path)
        prompt = _build_highlight_prompt(
            title=title,
            duration_seconds=duration_seconds,
            subtitles=subtitles,
            reason=reason,
            structure_reason=structure_reason,
        )
        raw = self._llm_client.chat(
            system_prompt=(
                "你是短视频剪辑导演，只返回严格 JSON。"
                "你的任务是在当前切片内部选择最适合作为开头钩子的高能片段。"
            ),
            user_prompt=prompt,
            temperature=0.1,
            max_tokens=800,
            timeout_seconds=60,
            json_mode=True,
        )
        data = extract_json_value(raw)
        if not isinstance(data, dict):
            raise ValueError("LLM 高能片头结果不是 JSON 对象")
        return _parse_highlight_decision(data, duration_seconds=duration_seconds)


def _load_subtitles(path: Path | None) -> list[SubtitleEntry]:
    if path is None or not path.exists():
        return []
    try:
        return parse_srt_file(path)
    except OSError as exc:
        logger.warning("highlight_subtitle_read_failed", path=str(path), error=str(exc))
        return []


def _build_highlight_prompt(
    *,
    title: str,
    duration_seconds: float,
    subtitles: list[SubtitleEntry],
    reason: str,
    structure_reason: str,
) -> str:
    transcript = _format_transcript(subtitles)
    return f"""请为这个直播切片选择一个适合复制到视频开头的“高能片头”。

目标：
- 高能片头应是 3-8 秒，必须来自当前切片内部。
- 片头应优先选择结果展示、强观点、冲突、承诺、转折、惊喜、用户最想看的画面说明。
- 不要选择寒暄、等待、铺垫、无意义口播。
- 如果没有足够强的片头，返回 enabled=false。
- 如果候选片段位于视频最开始 0-8 秒内，通常返回 enabled=false，避免重复开头。

切片标题：{title}
切片时长：{duration_seconds:.3f} 秒
切片推荐理由：{reason}
完整性说明：{structure_reason}

字幕（时间为当前切片内相对秒数）：
{transcript or "无字幕"}

只返回 JSON，不要 Markdown：
{{
  "enabled": true,
  "start_seconds": 115.0,
  "end_seconds": 120.0,
  "reason": "这里展示最终效果，最适合作为开头钩子",
  "confidence": 0.86
}}
"""


def _format_transcript(subtitles: list[SubtitleEntry]) -> str:
    lines: list[str] = []
    for item in subtitles:
        lines.append(f"[{item.start:.2f}-{item.end:.2f}] {item.text}")
    text = "\n".join(lines)
    if len(text) <= 12000:
        return text
    head = "\n".join(lines[:80])
    tail = "\n".join(lines[-80:])
    return f"{head}\n...\n{tail}"


def _parse_highlight_decision(
    data: dict[str, Any], *, duration_seconds: float
) -> HighlightIntroDecision:
    enabled = bool(data.get("enabled"))
    reason = str(data.get("reason") or "")
    confidence = _coerce_float(data.get("confidence"))
    confidence = clamp_score(confidence if confidence is not None else 0.0)
    if not enabled:
        return HighlightIntroDecision(
            enabled=False,
            reason=reason or "LLM 判断无需高能片头",
            confidence=confidence,
        )

    start = _coerce_float(data.get("start_seconds"))
    end = _coerce_float(data.get("end_seconds"))
    if start is None or end is None:
        raise ValueError("LLM 高能片头缺少 start_seconds 或 end_seconds")
    if start < 0 or end <= start or end > duration_seconds:
        raise ValueError("LLM 高能片头时间范围无效")

    highlight_duration = end - start
    if highlight_duration < 3.0 or highlight_duration > 8.0:
        raise ValueError("LLM 高能片头时长需要在 3-8 秒之间")
    if start < 8.0:
        return HighlightIntroDecision(
            enabled=False,
            reason=reason or "LLM 候选位于开头 8 秒内，跳过重复片头",
            confidence=confidence,
        )
    if confidence < 0.55:
        return HighlightIntroDecision(
            enabled=False,
            reason=reason or "LLM 置信度低，跳过高能片头",
            confidence=confidence,
        )
    return HighlightIntroDecision(
        enabled=True,
        start_seconds=start,
        end_seconds=end,
        reason=reason,
        confidence=confidence,
    )


def _coerce_float(value: object) -> float | None:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None
