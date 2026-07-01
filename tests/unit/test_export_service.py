from __future__ import annotations

from liveclip.services.export_service import build_media_url


def test_build_media_url_encodes_path_query() -> None:
    media_url = build_media_url("data/room_2/final/001_AI整体功能 #1.mp4")

    assert media_url == (
        "/api/v1/media/?path=data/room_2/final/"
        "001_AI%E6%95%B4%E4%BD%93%E5%8A%9F%E8%83%BD%20%231.mp4"
    )


def test_build_media_url_returns_none_for_empty_path() -> None:
    assert build_media_url(None) is None
    assert build_media_url("") is None
