"""时区工具：将 naive datetime 统一转换为东八区（中国时间）。

liveclip 容器默认时区为 UTC，MySQL 默认时区为 +08:00，
数据库中 DATETIME 列不存储时区信息。本模块提供统一转换，
确保 API 返回的时间均为中国时间。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

_CHINA_TZ = ZoneInfo("Asia/Shanghai")
_UTC_TZ = ZoneInfo("UTC")
_LEGACY_UTC_DRIFT = timedelta(hours=6)


def to_china_time(value: datetime | None) -> datetime | None:
    """将 naive datetime 视为 UTC 并转换为东八区时间。

    - 若值为 None，返回 None。
    - 若值已带时区信息，直接转换到东八区。
    - 若值为 naive datetime，视为 UTC 时间，转换到东八区。
    """
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(_CHINA_TZ)
    # naive datetime：视为 UTC
    aware_utc = value.replace(tzinfo=_UTC_TZ)
    return aware_utc.astimezone(_CHINA_TZ)


def as_china_aware(
    value: datetime | None,
    *,
    reference: datetime | None = None,
) -> datetime | None:
    """将 naive datetime 视为东八区时间并附加时区信息。

    数据库中存储的 naive datetime 均为东八区时间（由 china_now() 写入）。
    本函数为其附加 +08:00 时区，使 Pydantic 序列化时带时区后缀，
    前端可正确显示为中国时间。

    兼容旧数据：早期运行/步骤时间由 UTC 容器中的 ``datetime.now()`` 写入，
    但同表 ``created_at`` 由 MySQL 按 +08:00 写入。若传入 reference 且 value
    明显早于 reference，则按旧 UTC naive 转换到东八区。
    """
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(_CHINA_TZ)
    if _looks_like_legacy_utc(value, reference):
        return to_china_time(value)
    return value.replace(tzinfo=_CHINA_TZ)


def china_now() -> datetime:
    """返回当前东八区时间的 naive datetime（用于写入数据库）。"""
    return datetime.now(_CHINA_TZ).replace(tzinfo=None)


def _looks_like_legacy_utc(value: datetime, reference: datetime | None) -> bool:
    if reference is None:
        return False
    reference_china = as_china_aware(reference)
    value_china = value.replace(tzinfo=_CHINA_TZ)
    if reference_china is None:
        return False
    return reference_china - value_china >= _LEGACY_UTC_DRIFT
