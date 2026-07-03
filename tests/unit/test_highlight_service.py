from __future__ import annotations

from pathlib import Path

import pytest

from liveclip.services.highlight_service import HighlightIntroSelector


class FakeLLMClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def chat(self, **kwargs: object) -> str:
        self.prompts.append(str(kwargs.get("user_prompt") or ""))
        return self.response


def test_highlight_selector_uses_llm_json(tmp_path: Path) -> None:
    subtitle = tmp_path / "clip.srt"
    subtitle.write_text(
        "1\n00:00:10,000 --> 00:00:13,000\n先铺垫一下\n\n"
        "2\n00:01:55,000 --> 00:02:00,000\n这里直接展示最终效果\n",
        encoding="utf-8",
    )
    llm = FakeLLMClient(
        '{"enabled": true, "start_seconds": 115, "end_seconds": 120, '
        '"content_type": "result_showcase", '
        '"is_complete_sentence": true, "has_clear_value": true, '
        '"reason": "最终效果最吸引人", "confidence": 0.88}'
    )

    decision = HighlightIntroSelector(llm_client=llm).select(
        title="爆款切片",
        duration_seconds=130,
        subtitle_path=subtitle,
        reason="展示关键能力",
    )

    assert decision.enabled is True
    assert decision.start_seconds == 114.85
    assert decision.end_seconds == 120.25
    assert decision.reason == "最终效果最吸引人"
    assert decision.confidence == 0.88
    assert "这里直接展示最终效果" in llm.prompts[0]
    assert "result_showcase" in llm.prompts[0]
    assert "产品核心优势" in llm.prompts[0]


def test_highlight_selector_skips_short_clip() -> None:
    decision = HighlightIntroSelector(llm_client=FakeLLMClient("{}")).select(
        title="短视频",
        duration_seconds=12,
        subtitle_path=None,
    )

    assert decision.enabled is False
    assert decision.confidence == 0.0


def test_highlight_selector_rejects_bad_llm_duration() -> None:
    llm = FakeLLMClient(
        '{"enabled": true, "start_seconds": 20, "end_seconds": 40, '
        '"content_type": "result_showcase", '
        '"is_complete_sentence": true, "has_clear_value": true, '
        '"reason": "太长", "confidence": 0.9}'
    )

    with pytest.raises(ValueError, match="3-8 秒"):
        HighlightIntroSelector(llm_client=llm).select(
            title="异常片头",
            duration_seconds=80,
            subtitle_path=None,
        )


def test_highlight_selector_requires_high_confidence() -> None:
    llm = FakeLLMClient(
        '{"enabled": true, "start_seconds": 20, "end_seconds": 25, '
        '"content_type": "product_advantage", '
        '"is_complete_sentence": true, "has_clear_value": true, '
        '"reason": "优势介绍", "confidence": 0.84}'
    )

    decision = HighlightIntroSelector(llm_client=llm).select(
        title="优势片段",
        duration_seconds=80,
        subtitle_path=None,
    )

    assert decision.enabled is False
    assert decision.confidence == 0.84
    assert "置信度低于 0.85" in (decision.reason or "")


def test_highlight_selector_rejects_non_whitelisted_content_type() -> None:
    llm = FakeLLMClient(
        '{"enabled": true, "start_seconds": 20, "end_seconds": 25, '
        '"content_type": "chat_interaction", '
        '"is_complete_sentence": true, "has_clear_value": true, '
        '"reason": "互动", "confidence": 0.95}'
    )

    decision = HighlightIntroSelector(llm_client=llm).select(
        title="互动片段",
        duration_seconds=80,
        subtitle_path=None,
    )

    assert decision.enabled is False
    assert decision.reason == "高能片头类型不在白名单内，跳过"


def test_highlight_selector_rejects_incomplete_sentence() -> None:
    llm = FakeLLMClient(
        '{"enabled": true, "start_seconds": 20, "end_seconds": 25, '
        '"content_type": "strong_conclusion", '
        '"is_complete_sentence": false, "has_clear_value": true, '
        '"reason": "半句话", "confidence": 0.95}'
    )

    decision = HighlightIntroSelector(llm_client=llm).select(
        title="半句话片段",
        duration_seconds=80,
        subtitle_path=None,
    )

    assert decision.enabled is False
    assert decision.reason == "高能片头不是完整句/完整小段，跳过"
