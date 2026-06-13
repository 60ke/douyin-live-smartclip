"""LLM 提示词模板。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from liveclip.observability import get_logger

logger = get_logger(__name__)


class PromptTemplate:
    """提示词模板，支持变量渲染。"""

    def __init__(self, name: str, template_text: str) -> None:
        self.name = name
        self._template_text = template_text

    def render(self, **kwargs: Any) -> str:
        """使用 Python format() 渲染模板。

        Args:
            **kwargs: 模板变量。

        Returns:
            渲染后的文本。
        """
        try:
            return self._template_text.format(**kwargs)
        except KeyError as exc:
            logger.error(
                "prompt_render_missing_key",
                template_name=self.name,
                missing_key=str(exc),
            )
            raise

    @classmethod
    def load_from_file(cls, path: Path) -> PromptTemplate:
        """从文件加载提示词模板。

        Args:
            path: 模板文件路径。

        Returns:
            PromptTemplate 实例。
        """
        name = path.stem
        template_text = path.read_text(encoding="utf-8")
        logger.info("prompt_template_loaded", name=name, path=str(path))
        return cls(name=name, template_text=template_text)
