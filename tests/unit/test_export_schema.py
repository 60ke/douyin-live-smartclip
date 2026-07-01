from __future__ import annotations

from datetime import datetime

import pytest

from liveclip.schemas.export import ExportCursor


def test_export_cursor_round_trip() -> None:
    cursor = ExportCursor(created_at=datetime(2026, 7, 1, 11, 30, 26), id=123)

    decoded = ExportCursor.decode(cursor.encode())

    assert decoded == cursor


def test_export_cursor_rejects_invalid_base64() -> None:
    with pytest.raises(ValueError, match="Invalid cursor"):
        ExportCursor.decode("not-a-valid-cursor")
