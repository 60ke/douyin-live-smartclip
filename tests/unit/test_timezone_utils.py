from __future__ import annotations

from datetime import UTC, datetime

from liveclip.utils.timezone import as_china_aware, to_china_time


def test_to_china_time_treats_naive_datetime_as_utc() -> None:
    result = to_china_time(datetime(2026, 6, 16, 2, 30))

    assert result is not None
    assert result.isoformat() == "2026-06-16T10:30:00+08:00"


def test_as_china_aware_treats_new_naive_datetime_as_china_time() -> None:
    result = as_china_aware(datetime(2026, 6, 16, 10, 30))

    assert result is not None
    assert result.isoformat() == "2026-06-16T10:30:00+08:00"


def test_as_china_aware_converts_legacy_utc_datetime_with_reference() -> None:
    result = as_china_aware(
        datetime(2026, 6, 16, 2, 30),
        reference=datetime(2026, 6, 16, 10, 29),
    )

    assert result is not None
    assert result.isoformat() == "2026-06-16T10:30:00+08:00"


def test_as_china_aware_converts_aware_datetime() -> None:
    result = as_china_aware(datetime(2026, 6, 16, 2, 30, tzinfo=UTC))

    assert result is not None
    assert result.isoformat() == "2026-06-16T10:30:00+08:00"
