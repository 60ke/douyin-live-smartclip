"""抖音直播流地址获取适配器。"""

from __future__ import annotations

import html
import json
import re
from urllib.parse import urlsplit

from liveclip.adapters.douyin.client import DouyinWebClient
from liveclip.adapters.douyin.resolver import DouyinRoomInfo
from liveclip.exceptions import LIVE_ROOM_NOT_LIVE, LiveRoomError
from liveclip.observability import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 画质优先级映射
# ---------------------------------------------------------------------------

_QUALITY_ORDER: list[str] = ["origin", "uhd", "hd", "sd", "ld"]
_FLV_QUALITY_KEYS: dict[str, tuple[str, ...]] = {
    "origin": ("ORIGIN",),
    "uhd": ("UHD", "FULL_HD1"),
    "hd": ("HD1", "BD"),
    "sd": ("SD1", "SD2"),
    "ld": ("LD",),
}
_HTML_FLV_RE = re.compile(r"https?://[^\"'\s]*stream-\d+[^\"'\s]*\.flv[^\"'\s]*")


class DouyinStreamFetcher:
    """获取抖音直播间流地址。"""

    def __init__(self, timeout: int = 15, web_client: DouyinWebClient | None = None) -> None:
        self._web_client = web_client or DouyinWebClient(timeout=timeout)

    def get_stream_url(
        self,
        room_info: DouyinRoomInfo,
        quality: str = "origin",
        cookie: str | None = None,
    ) -> str:
        """获取指定画质的直播流地址。

        优先通过 API 获取，回退到页面解析。按画质优先级降级选取。

        Args:
            room_info: 直播间基本信息。
            quality: 目标画质，origin/uhd/hd/sd/ld。
            cookie: 可选的 Cookie 字符串。

        Returns:
            直播流 URL 字符串。

        Raises:
            LiveRoomError: 直播间未开播或无法获取流地址。
        """
        logger.info("fetching_stream_url", room_id=room_info.room_id, quality=quality)

        # 1. 尝试 API 方式
        url = self._fetch_via_api(room_info, quality, cookie)
        if url is not None:
            return url

        # 2. 回退到页面解析
        url = self._fetch_via_page(room_info, cookie)
        if url is not None:
            return url

        raise LiveRoomError(
            LIVE_ROOM_NOT_LIVE,
            f"直播间未开播或无法获取流地址: room_id={room_info.room_id}",
            details={"room_id": room_info.room_id, "quality": quality},
        )

    # ------------------------------------------------------------------
    # API 方式
    # ------------------------------------------------------------------

    def _fetch_via_api(
        self,
        room_info: DouyinRoomInfo,
        quality: str = "origin",
        cookie: str | None = None,
    ) -> str | None:
        """通过抖音 Web API 获取流地址。"""
        room = self._web_client.enter_room(room_info.web_rid, cookie)
        if room is None:
            return None

        # 检查是否正在直播
        if room.get("status", 0) != 2:
            logger.info("room_not_live_via_api", room_id=room_info.room_id)
            return None

        return self._extract_stream_from_room(room, quality)

    # ------------------------------------------------------------------
    # 页面解析方式
    # ------------------------------------------------------------------

    def _fetch_via_page(
        self,
        room_info: DouyinRoomInfo,
        cookie: str | None = None,
    ) -> str | None:
        """通过解析直播间页面获取流地址。"""
        html = self._web_client.fetch_room_page(room_info.web_rid, cookie)
        if html is None:
            return None

        direct_url = self._extract_stream_from_html(html)
        if direct_url is not None:
            return direct_url

        # 检查是否正在直播
        status_match = re.search(r'"status"\s*:\s*(\d+)', html)
        if status_match is None or int(status_match.group(1)) != 2:
            logger.info("room_not_live_via_page", room_id=room_info.room_id)
            return None

        return self._extract_stream_from_html(html)

    # ------------------------------------------------------------------
    # 解析辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_stream_from_room(room: dict, quality: str = "origin") -> str | None:
        """从 API 返回的 room 数据中提取指定画质的流地址。"""
        DouyinStreamFetcher._merge_origin_stream(room)
        stream_data = room.get("stream_url", {})
        live_core_sdk_data = stream_data.get("live_core_sdk_data", {})
        pull_data = live_core_sdk_data.get("pull_data", {})
        options = pull_data.get("options", {})

        # 构建画质优先级：目标画质优先，然后按降级顺序
        quality_idx = _QUALITY_ORDER.index(quality) if quality in _QUALITY_ORDER else 0
        ordered = _QUALITY_ORDER[quality_idx:] + _QUALITY_ORDER[:quality_idx]

        for q in ordered:
            quality_data = options.get(q, {})
            main_url = quality_data.get("main", {})
            if isinstance(main_url, str) and main_url:
                url = DouyinStreamFetcher._normalize_stream_url(main_url)
                if url:
                    return url
            if isinstance(main_url, dict):
                url = main_url.get("flv", "") or main_url.get("url", "")
                url = DouyinStreamFetcher._normalize_stream_url(url)
                if url:
                    return url

        # 回退到 flv_pull_url
        flv_pull = stream_data.get("flv_pull_url", {})
        if isinstance(flv_pull, dict):
            for key in DouyinStreamFetcher._ordered_flv_keys(quality):
                url = DouyinStreamFetcher._normalize_stream_url(flv_pull.get(key, ""))
                if url:
                    return url

        hls_pull = stream_data.get("hls_pull_url_map", {})
        if isinstance(hls_pull, dict):
            for key in DouyinStreamFetcher._ordered_flv_keys(quality):
                url = DouyinStreamFetcher._normalize_stream_url(hls_pull.get(key, ""))
                if url:
                    return url

        return None

    @staticmethod
    def _extract_stream_from_html(html: str) -> str | None:
        """从页面 HTML 中提取流地址。"""
        for match in _HTML_FLV_RE.finditer(html):
            url = DouyinStreamFetcher._normalize_stream_url(match.group(0))
            if url and DouyinStreamFetcher._is_preferred_html_flv(url):
                return url

        flv_match = re.search(r'"flv"\s*:\s*"(https?://[^"]+\.flv[^"]*)"', html)
        if flv_match:
            url = DouyinStreamFetcher._normalize_stream_url(flv_match.group(1))
            if url:
                return url

        pull_match = re.search(r'"pull_url"\s*:\s*"(https?://[^"]+)"', html)
        if pull_match:
            url = DouyinStreamFetcher._normalize_stream_url(pull_match.group(1))
            if url:
                return url

        return None

    @staticmethod
    def _merge_origin_stream(room: dict) -> None:
        """把抖音嵌套 stream_data 里的原画流合并到 flv_pull_url.ORIGIN。

        抖音 Web API 的原画流经常藏在 pull_datas[*].stream_data 或
        live_core_sdk_data.pull_data.stream_data 这个 JSON 字符串里，旧的可用录制器
        会先把它补到 flv_pull_url["ORIGIN"] 后再按画质选择。
        """
        stream_url = room.get("stream_url")
        if not isinstance(stream_url, dict):
            return

        parsed = DouyinStreamFetcher._parse_origin_stream_data(stream_url)
        if not parsed:
            return

        origin = parsed.get("data", {}).get("origin", {})
        main = origin.get("main", {})
        if not isinstance(main, dict):
            return

        flv_url = DouyinStreamFetcher._normalize_stream_url(main.get("flv", ""))
        hls_url = DouyinStreamFetcher._normalize_stream_url(main.get("hls", ""))
        if not flv_url and not hls_url:
            return

        codec = DouyinStreamFetcher._extract_origin_codec(main.get("sdk_params"))
        if codec and flv_url and "codec=" not in flv_url:
            separator = "&" if "?" in flv_url else "?"
            flv_url = f"{flv_url}{separator}codec={codec}"

        if flv_url:
            flv_pull_url = stream_url.setdefault("flv_pull_url", {})
            if isinstance(flv_pull_url, dict):
                flv_pull_url["ORIGIN"] = flv_url
        if hls_url:
            hls_pull_url_map = stream_url.setdefault("hls_pull_url_map", {})
            if isinstance(hls_pull_url_map, dict):
                hls_pull_url_map["ORIGIN"] = hls_url

    @staticmethod
    def _parse_origin_stream_data(stream_url: dict) -> dict | None:
        candidates: list[object] = []
        pull_datas = stream_url.get("pull_datas")
        if isinstance(pull_datas, list):
            candidates.extend(item.get("stream_data") for item in pull_datas if isinstance(item, dict))

        live_core_sdk_data = stream_url.get("live_core_sdk_data")
        if isinstance(live_core_sdk_data, dict):
            pull_data = live_core_sdk_data.get("pull_data")
            if isinstance(pull_data, dict):
                candidates.append(pull_data.get("stream_data"))

        for candidate in candidates:
            if isinstance(candidate, str) and candidate.strip():
                try:
                    parsed = json.loads(candidate)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return parsed
            if isinstance(candidate, dict):
                return candidate
        return None

    @staticmethod
    def _extract_origin_codec(sdk_params: object) -> str | None:
        if not isinstance(sdk_params, str) or not sdk_params.strip():
            return None
        try:
            parsed = json.loads(sdk_params)
        except json.JSONDecodeError:
            return None
        codec = parsed.get("VCodec") if isinstance(parsed, dict) else None
        return str(codec) if codec else None

    @staticmethod
    def _ordered_flv_keys(quality: str) -> list[str]:
        normalized = quality if quality in _QUALITY_ORDER else "origin"
        quality_idx = _QUALITY_ORDER.index(normalized)
        ordered = _QUALITY_ORDER[quality_idx:] + _QUALITY_ORDER[:quality_idx]
        keys: list[str] = []
        for q in ordered:
            keys.extend(_FLV_QUALITY_KEYS.get(q, ()))
        keys.extend(("ORIGIN", "FULL_HD1", "HD1", "SD1", "SD2", "LD"))
        return list(dict.fromkeys(keys))

    @staticmethod
    def _normalize_stream_url(value: object) -> str | None:
        if not isinstance(value, str) or not value.strip():
            return None

        url = value.strip()
        for separator in ("\\n", "\\r", "\n", "\r", "\t"):
            url = url.split(separator, 1)[0]

        url = html.unescape(url)
        replacements = {
            "\\u0026": "&",
            "\\u002F": "/",
            "\\u003A": ":",
            "\\u003F": "?",
            "\\u003D": "=",
            "\\/": "/",
        }
        for old, new in replacements.items():
            url = url.replace(old, new)
        url = url.strip().rstrip("\\")

        if not DouyinStreamFetcher._is_valid_stream_url(url):
            return None
        return url

    @staticmethod
    def _is_valid_stream_url(url: str) -> bool:
        if any(token in url for token in ("\n", "\r", "\t", "\\", "\\n", "\\r", " Error", "Error")):
            return False
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return False
        return ".flv" in parsed.path or ".m3u8" in parsed.path

    @staticmethod
    def _is_preferred_html_flv(url: str) -> bool:
        lowered = url.lower()
        return all(
            token not in lowered
            for token in ("_uhd.flv", "only_audio=1", "pull-hs", "wssecret")
        ) and "flv" in urlsplit(url).netloc.lower()
