"""抖音直播流地址获取适配器。"""

from __future__ import annotations

import re

from liveclip.adapters.douyin.client import DouyinWebClient
from liveclip.adapters.douyin.resolver import DouyinRoomInfo
from liveclip.exceptions import LIVE_ROOM_NOT_LIVE, LiveRoomError
from liveclip.observability import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# 画质优先级映射
# ---------------------------------------------------------------------------

_QUALITY_ORDER: list[str] = ["origin", "uhd", "hd", "sd", "ld"]


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
                return main_url
            if isinstance(main_url, dict):
                url = main_url.get("flv", "") or main_url.get("url", "")
                if url:
                    return str(url)

        # 回退到 flv_pull_url
        flv_pull = stream_data.get("flv_pull_url", {})
        if isinstance(flv_pull, dict):
            for key in ("FULL_HD1", "HD1", "SD1", "SD2"):
                url = flv_pull.get(key, "")
                if url:
                    return str(url)

        return None

    @staticmethod
    def _extract_stream_from_html(html: str) -> str | None:
        """从页面 HTML 中提取流地址。"""
        flv_match = re.search(r'"flv"\s*:\s*"(https?://[^"]+\.flv[^"]*)"', html)
        if flv_match:
            return flv_match.group(1).replace("\\u0026", "&")

        pull_match = re.search(r'"pull_url"\s*:\s*"(https?://[^"]+)"', html)
        if pull_match:
            return pull_match.group(1).replace("\\u0026", "&")

        return None
