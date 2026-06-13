"""FunASR 热词管理。"""

from __future__ import annotations

from pathlib import Path

from liveclip.observability import get_logger

logger = get_logger(__name__)


class HotwordManager:
    """管理 FunASR 热词的加载与合并。"""

    def __init__(self, default_path: Path | None = None) -> None:
        self._default_path = default_path or Path("configs/hotwords/default.txt")

    def load_hotwords(self) -> list[str]:
        """加载默认热词文件。"""
        return self.load_from_file(self._default_path)

    @staticmethod
    def load_from_file(path: Path) -> list[str]:
        """从文本文件加载热词列表。

        每行一个热词，跳过空行和以 # 开头的注释行。

        Args:
            path: 热词文件路径。

        Returns:
            热词列表。
        """
        if not path.exists():
            logger.warning("hotword_file_not_found", path=str(path))
            return []

        words: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                words.append(stripped)

        logger.info("hotwords_loaded_from_file", path=str(path), count=len(words))
        return words

    @staticmethod
    def load_from_string(text: str) -> list[str]:
        """从字符串解析热词列表。

        支持逗号、空格、换行符分隔。

        Args:
            text: 热词字符串。

        Returns:
            热词列表。
        """
        words: list[str] = []
        for segment in text.replace(",", "\n").replace(" ", "\n").splitlines():
            stripped = segment.strip()
            if stripped:
                words.append(stripped)

        return words

    @staticmethod
    def merge_hotwords(*word_lists: list[str]) -> list[str]:
        """合并多个热词列表并去重，保持顺序。

        Args:
            *word_lists: 多个热词列表。

        Returns:
            去重后的合并热词列表。
        """
        seen: set[str] = set()
        merged: list[str] = []

        for word_list in word_lists:
            for word in word_list:
                if word not in seen:
                    seen.add(word)
                    merged.append(word)

        logger.info("hotwords_merged", total=len(merged))
        return merged
