"""导出游标与直播间筛选测试。"""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime

import pytest

from liveclip.schemas.export import ExportCursor, normalize_room_ids


def test_normalize_room_ids_sorts_and_deduplicates() -> None:
    assert normalize_room_ids([3, 1, 3, 2]) == (1, 2, 3)


def test_normalize_room_ids_rejects_non_positive_values() -> None:
    with pytest.raises(ValueError, match="positive integers"):
        normalize_room_ids([0, 1])


def test_cursor_round_trip_preserves_room_filter() -> None:
    cursor = ExportCursor(
        created_at=datetime(2026, 7, 31, 8, 0, tzinfo=UTC),
        id=42,
        room_ids=(9, 2, 9),
    )

    decoded = ExportCursor.decode(cursor.encode())

    assert decoded.created_at == cursor.created_at
    assert decoded.id == 42
    assert decoded.room_ids == (2, 9)
    decoded.validate_room_filter((2, 9))


def test_cursor_rejects_different_room_filter() -> None:
    cursor = ExportCursor(
        created_at=datetime(2026, 7, 31, 8, 0, tzinfo=UTC),
        id=42,
        room_ids=(2, 9),
    )

    with pytest.raises(ValueError, match="does not match"):
        cursor.validate_room_filter((2, 10))


def test_old_cursor_without_room_ids_remains_compatible_for_unfiltered_requests() -> None:
    payload = {
        "t": datetime(2026, 7, 31, 8, 0, tzinfo=UTC).isoformat(),
        "i": 42,
    }
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()

    cursor = ExportCursor.decode(raw)

    assert cursor.room_ids == ()
    cursor.validate_room_filter(())
