"""liveclip 自定义异常与错误码定义。"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 错误码常量
# ---------------------------------------------------------------------------

LIVE_ROOM_RESOLVE_FAILED = "LIVE_ROOM_RESOLVE_FAILED"
LIVE_ROOM_NOT_LIVE = "LIVE_ROOM_NOT_LIVE"
RECORD_FAILED = "RECORD_FAILED"
RECORD_EMPTY_FILE = "RECORD_EMPTY_FILE"
FFMPEG_CONVERT_FAILED = "FFMPEG_CONVERT_FAILED"
FFPROBE_FAILED = "FFPROBE_FAILED"
FUNASR_TRANSCRIBE_FAILED = "FUNASR_TRANSCRIBE_FAILED"
EMPTY_SUBTITLE = "EMPTY_SUBTITLE"
LLM_REQUEST_FAILED = "LLM_REQUEST_FAILED"
LLM_JSON_PARSE_FAILED = "LLM_JSON_PARSE_FAILED"
CLIP_PLAN_INVALID = "CLIP_PLAN_INVALID"
BOUNDARY_VALIDATE_FAILED = "BOUNDARY_VALIDATE_FAILED"
EXPORT_CLIP_FAILED = "EXPORT_CLIP_FAILED"
STORAGE_WRITE_FAILED = "STORAGE_WRITE_FAILED"
CONFIG_INVALID = "CONFIG_INVALID"
RUN_HEARTBEAT_TIMEOUT = "RUN_HEARTBEAT_TIMEOUT"
STEP_HEARTBEAT_TIMEOUT = "STEP_HEARTBEAT_TIMEOUT"
RUN_CANCELED = "RUN_CANCELED"
DOUYIN_NEED_LOGIN = "DOUYIN_NEED_LOGIN"
LIVE_STATUS_UNKNOWN = "LIVE_STATUS_UNKNOWN"


# ---------------------------------------------------------------------------
# 基础异常
# ---------------------------------------------------------------------------


class LiveClipError(Exception):
    """liveclip 所有自定义异常的基类。

    Attributes:
        error_code: 机器可读的错误码常量。
        message: 人类可读的错误描述。
        details: 附加上下文字典，可选。
    """

    def __init__(
        self,
        error_code: str,
        message: str,
        details: dict[str, object] | None = None,
    ) -> None:
        self.error_code = error_code
        self.message = message
        self.details = details or {}
        super().__init__(message)

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"error_code={self.error_code!r}, "
            f"message={self.message!r}, "
            f"details={self.details!r})"
        )


# ---------------------------------------------------------------------------
# 具体异常子类
# ---------------------------------------------------------------------------


class LiveRoomError(LiveClipError):
    """直播间解析 / 状态相关错误。"""


class RecordError(LiveClipError):
    """录制过程相关错误。"""


class FFmpegError(LiveClipError):
    """FFmpeg / FFprobe 调用相关错误。"""


class FunASRError(LiveClipError):
    """FunASR 语音转写相关错误。"""


class LLMError(LiveClipError):
    """大模型请求 / 解析相关错误。"""


class ClipPlanError(LiveClipError):
    """切片方案生成相关错误。"""


class BoundaryError(LiveClipError):
    """切片边界校验相关错误。"""


class ExportError(LiveClipError):
    """切片导出相关错误。"""


class StorageError(LiveClipError):
    """存储写入相关错误。"""


class ConfigError(LiveClipError):
    """配置校验相关错误。"""


class WorkerError(LiveClipError):
    """Worker 运行时 / 心跳相关错误。"""
