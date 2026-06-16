from __future__ import annotations

import json

from liveclip.adapters.douyin.stream import DouyinStreamFetcher


def test_extract_stream_from_room_merges_origin_stream_data() -> None:
    origin_flv = "http://pull-flv.example.com/third/stream-123.flv?expire=1\\u0026sign=abc"
    room = {
        "stream_url": {
            "live_core_sdk_data": {
                "pull_data": {
                    "stream_data": json.dumps(
                        {
                            "data": {
                                "origin": {
                                    "main": {
                                        "flv": origin_flv,
                                        "sdk_params": json.dumps({"VCodec": "h264"}),
                                    }
                                }
                            }
                        }
                    )
                }
            },
            "flv_pull_url": {
                "FULL_HD1": "http://pull-flv.example.com/third/stream-123_hd.flv?expire=1",
            },
        }
    }

    url = DouyinStreamFetcher._extract_stream_from_room(room, "origin")

    assert url == "http://pull-flv.example.com/third/stream-123.flv?expire=1&sign=abc&codec=h264"
    assert room["stream_url"]["flv_pull_url"]["ORIGIN"] == url


def test_extract_stream_from_room_prefers_origin_flv_map_for_origin_quality() -> None:
    room = {
        "stream_url": {
            "flv_pull_url": {
                "ORIGIN": "http://pull-flv.example.com/third/stream-123_origin.flv?expire=1",
                "FULL_HD1": "http://pull-flv.example.com/third/stream-123_hd.flv?expire=1",
            }
        }
    }

    url = DouyinStreamFetcher._extract_stream_from_room(room, "origin")

    assert url == "http://pull-flv.example.com/third/stream-123_origin.flv?expire=1"


def test_extract_stream_from_html_trims_error_tail_and_decodes_escapes() -> None:
    html = (
        'window.__ROOM__="http://pull-flv-l26.douyincdn.com/third/'
        'stream-696019530767663590_or4.flv?expire=6a39fbd8\\u0026sign=c5'
        '\\u0026t_id=037-abc\\\\nError";'
    )

    url = DouyinStreamFetcher._extract_stream_from_html(html)

    assert url == (
        "http://pull-flv-l26.douyincdn.com/third/"
        "stream-696019530767663590_or4.flv?expire=6a39fbd8&sign=c5&t_id=037-abc"
    )


def test_normalize_stream_url_rejects_error_polluted_url() -> None:
    url = "http://pull-flv.example.com/third/stream-123.flv?x=1Error"

    assert DouyinStreamFetcher._normalize_stream_url(url) is None
