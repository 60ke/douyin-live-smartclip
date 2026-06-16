"""抖音直播间开播状态检测适配器。"""

from __future__ import annotations

import re
from dataclasses import dataclass

from liveclip.adapters.douyin.client import DouyinWebClient
from liveclip.adapters.douyin.resolver import DouyinRoomInfo
from liveclip.adapters.douyin.stream import DouyinStreamFetcher
from liveclip.domain.enums import LiveStatus
from liveclip.exceptions import (
    DOUYIN_NEED_LOGIN,
    LIVE_STATUS_UNKNOWN,
    LiveRoomError,
)
from liveclip.observability import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class DouyinLiveStatus:
    """抖音直播间开播状态。"""

    is_live: bool
    anchor_name: str
    title: str
    stream_url: str | None


class DouyinLiveChecker:
    """检测抖音直播间是否正在开播。"""

    def __init__(self, timeout: int = 15, web_client: DouyinWebClient | None = None) -> None:
        self._web_client = web_client or DouyinWebClient(timeout=timeout)

    def check_live(
        self,
        room_info: DouyinRoomInfo,
        cookie: str | None = None,
    ) -> DouyinLiveStatus:
        """查询直播间开播状态。

        Args:
            room_info: 直播间基本信息。
            cookie: 可选的 Cookie 字符串。

        Returns:
            包含 is_live / anchor_name / title / stream_url 的状态信息。

        Raises:
            LiveRoomError: 查询失败时抛出。
        """
        logger.info("checking_live_status", room_id=room_info.room_id)

        # 优先使用 API 方式查询
        status = self._check_via_api(room_info, cookie)
        if status is not None:
            return status

        # 回退到页面解析
        status = self._check_via_page(room_info, cookie)
        if status is not None:
            return status

        raise LiveRoomError(
            LIVE_STATUS_UNKNOWN,
            f"无法确定直播间状态: room_id={room_info.room_id}",
            details={"room_id": room_info.room_id},
        )

    # ------------------------------------------------------------------
    # API 方式
    # ------------------------------------------------------------------

    def _check_via_api(
        self,
        room_info: DouyinRoomInfo,
        cookie: str | None = None,
    ) -> DouyinLiveStatus | None:
        """通过抖音 Web API 查询开播状态。"""
        room = self._web_client.enter_room(room_info.web_rid, cookie)
        if room is None:
            return None

        return self._parse_room_data(room, room_info)

    # ------------------------------------------------------------------
    # 页面解析方式
    # ------------------------------------------------------------------

    def _check_via_page(
        self,
        room_info: DouyinRoomInfo,
        cookie: str | None = None,
    ) -> DouyinLiveStatus | None:
        """通过解析直播间页面判断开播状态。"""
        html = self._web_client.fetch_room_page(room_info.web_rid, cookie)
        if html is None:
            return None

        # 检查是否需要登录
        if "验证码" in html or ("登录" in html and "live-room" not in html):
            raise LiveRoomError(
                DOUYIN_NEED_LOGIN,
                "需要登录 Cookie 才能访问直播间",
                details={"room_id": room_info.room_id},
            )

        # 从页面中提取状态
        status_match = re.search(r'"status"\s*:\s*(\d+)', html)
        if status_match is None:
            return None

        status_val = int(status_match.group(1))
        # 抖音 status: 2=直播中, 4=未开播
        is_live = status_val == 2

        title_match = re.search(r'"title"\s*:\s*"([^"]*)"', html)
        title = title_match.group(1) if title_match else ""

        stream_url: str | None = None
        if is_live:
            stream_url = self._extract_stream_url_from_html(html)

        return DouyinLiveStatus(
            is_live=is_live,
            anchor_name=room_info.anchor_name,
            title=title,
            stream_url=stream_url,
        )

    # ------------------------------------------------------------------
    # 解析辅助
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_room_data(room: dict, room_info: DouyinRoomInfo) -> DouyinLiveStatus:
        """从 API 返回的 room 数据中解析开播状态。"""
        status = room.get("status", 0)
        # status 2 = 直播中
        is_live = status == 2

        title = room.get("title", "")
        stream_url: str | None = None

        if is_live:
            stream_url = DouyinLiveChecker._extract_stream_url_from_room(room)

        return DouyinLiveStatus(
            is_live=is_live,
            anchor_name=room_info.anchor_name,
            title=title,
            stream_url=stream_url,
        )

    @staticmethod
    def _extract_stream_url_from_room(room: dict) -> str | None:
        """从 room 数据中提取流地址。"""
        return DouyinStreamFetcher._extract_stream_from_room(room, "origin")

    @staticmethod
    def _extract_stream_url_from_html(html: str) -> str | None:
        """从页面 HTML 中提取流地址。"""
        return DouyinStreamFetcher._extract_stream_from_html(html)

    @staticmethod
    def to_live_status_enum(live_status: DouyinLiveStatus) -> LiveStatus:
        """将 DouyinLiveStatus 转换为 LiveStatus 枚举。"""
        if live_status.is_live:
            return LiveStatus.LIVE
        return LiveStatus.NOT_LIVE
