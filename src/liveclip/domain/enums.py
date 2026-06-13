"""liveclip 业务枚举定义。"""

from __future__ import annotations

from enum import StrEnum


class _StrEnum(StrEnum):
    """兼容 Python 3.11 的字符串枚举基类。"""

    def __str__(self) -> str:
        return self.value


class TaskType(_StrEnum):
    """任务类型。"""

    ONCE = "ONCE"
    CRON = "CRON"


class RunStatus(_StrEnum):
    """运行状态。"""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class StepStatus(_StrEnum):
    """步骤状态。"""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class StepName(_StrEnum):
    """流水线步骤名称。"""

    RECORD_TS = "RECORD_TS"
    CONVERT_MP4 = "CONVERT_MP4"
    TRANSCRIBE = "TRANSCRIBE"
    PREPROCESS_SUBTITLE = "PREPROCESS_SUBTITLE"
    PLAN_CLIPS = "PLAN_CLIPS"
    VALIDATE_BOUNDARY = "VALIDATE_BOUNDARY"
    EXPORT_CLIPS = "EXPORT_CLIPS"
    FINALIZE = "FINALIZE"


class TriggerType(_StrEnum):
    """触发方式。"""

    API = "API"
    CLI = "CLI"
    MANUAL = "MANUAL"
    CRON = "CRON"
    DEBUG_FROM_FILE = "DEBUG_FROM_FILE"


class LiveStatus(_StrEnum):
    """直播间状态。"""

    LIVE = "LIVE"
    NOT_LIVE = "NOT_LIVE"
    ENDED = "ENDED"
    NEED_LOGIN = "NEED_LOGIN"
    UNKNOWN = "UNKNOWN"


class RecordSourceType(_StrEnum):
    """录制来源类型。"""

    DOUYIN_RECORD = "DOUYIN_RECORD"
    LOCAL_FILE = "LOCAL_FILE"


class ClipPlanStatus(_StrEnum):
    """切片方案状态。"""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ClipStatus(_StrEnum):
    """单个切片状态。"""

    PENDING = "PENDING"
    EXPORTING = "EXPORTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
