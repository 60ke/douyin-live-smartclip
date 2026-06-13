"""liveclip 值对象定义。"""

from __future__ import annotations

import re
from pathlib import Path


class Timecode:
    """时间码值对象，支持秒数与 hh:mm:ss.mmm 格式互转。"""

    def __init__(self, seconds: float) -> None:
        if seconds < 0:
            raise ValueError(f"Timecode seconds must be non-negative, got {seconds}")
        self._seconds = seconds

    @property
    def seconds(self) -> float:
        """原始秒数。"""
        return self._seconds

    @property
    def hh(self) -> int:
        """小时部分。"""
        return int(self._seconds) // 3600

    @property
    def mm(self) -> int:
        """分钟部分。"""
        return (int(self._seconds) % 3600) // 60

    @property
    def ss(self) -> int:
        """秒部分。"""
        return int(self._seconds) % 60

    @property
    def mmm(self) -> int:
        """毫秒部分。"""
        return int(round((self._seconds - int(self._seconds)) * 1000))

    @property
    def formatted(self) -> str:
        """hh:mm:ss.mmm 格式字符串。"""
        return f"{self.hh:02d}:{self.mm:02d}:{self.ss:02d}.{self.mmm:03d}"

    @classmethod
    def from_string(cls, time_str: str) -> Timecode:
        """从 hh:mm:ss.mmm 或 hh:mm:ss 格式字符串解析。

        Args:
            time_str: 时间码字符串，支持 "01:23:45.678" 或 "01:23:45" 格式。

        Returns:
            对应的 Timecode 实例。

        Raises:
            ValueError: 格式无法解析时抛出。
        """
        pattern = r"^(\d+):(\d{2}):(\d{2})(?:\.(\d{1,3}))?$"
        match = re.match(pattern, time_str)
        if not match:
            raise ValueError(f"Invalid timecode format: {time_str!r}")
        hours = int(match.group(1))
        minutes = int(match.group(2))
        seconds = int(match.group(3))
        ms_str = match.group(4) or "0"
        milliseconds = int(ms_str.ljust(3, "0")[:3])
        total = hours * 3600 + minutes * 60 + seconds + milliseconds / 1000.0
        return cls(total)

    def __str__(self) -> str:
        return self.formatted

    def __repr__(self) -> str:
        return f"Timecode(seconds={self._seconds})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Timecode):
            return self._seconds == other._seconds
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._seconds)

    def __lt__(self, other: Timecode) -> bool:
        return self._seconds < other._seconds

    def __le__(self, other: Timecode) -> bool:
        return self._seconds <= other._seconds

    def __gt__(self, other: Timecode) -> bool:
        return self._seconds > other._seconds

    def __ge__(self, other: Timecode) -> bool:
        return self._seconds >= other._seconds


class SafeFilename:
    """安全文件名值对象，自动清理非法字符。"""

    _ILLEGAL_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
    _DEFAULT_NAME = "未命名片段"
    _MAX_LENGTH = 80

    def __init__(self, original: str) -> None:
        self._original = original
        self._sanitized = self._sanitize(original)

    @property
    def original(self) -> str:
        """原始文件名。"""
        return self._original

    @property
    def sanitized(self) -> str:
        """清理后的安全文件名。"""
        return self._sanitized

    def _sanitize(self, name: str) -> str:
        """清理文件名：移除非法字符、修剪空白、截断至最大长度。"""
        cleaned = self._ILLEGAL_CHARS.sub("", name)
        cleaned = cleaned.strip().strip(".")
        if not cleaned:
            cleaned = self._DEFAULT_NAME
        if len(cleaned) > self._MAX_LENGTH:
            cleaned = cleaned[: self._MAX_LENGTH].strip().strip(".")
            if not cleaned:
                cleaned = self._DEFAULT_NAME
        return cleaned

    def __str__(self) -> str:
        return self._sanitized

    def __repr__(self) -> str:
        return f"SafeFilename(original={self._original!r}, sanitized={self._sanitized!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, SafeFilename):
            return self._sanitized == other._sanitized
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._sanitized)


class FilePath:
    """存储路径值对象，Path 的类型化包装。"""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        """底层 Path 对象。"""
        return self._path

    @property
    def exists(self) -> bool:
        """路径是否存在。"""
        return self._path.exists()

    @property
    def name(self) -> str:
        """文件名。"""
        return self._path.name

    @property
    def suffix(self) -> str:
        """文件后缀。"""
        return self._path.suffix

    @property
    def stem(self) -> str:
        """文件名（不含后缀）。"""
        return self._path.stem

    @property
    def parent(self) -> FilePath:
        """父目录。"""
        return FilePath(self._path.parent)

    def joinpath(self, *other: str | Path) -> FilePath:
        """拼接子路径。"""
        return FilePath(self._path.joinpath(*other))

    def __str__(self) -> str:
        return str(self._path)

    def __repr__(self) -> str:
        return f"FilePath({self._path!r})"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, FilePath):
            return self._path == other._path
        return NotImplemented

    def __hash__(self) -> int:
        return hash(self._path)

    def __lt__(self, other: FilePath) -> bool:
        return str(self._path) < str(other._path)
