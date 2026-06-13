"""抖音直播间 URL 解析适配器。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

import httpx

from liveclip.adapters.douyin.client import DouyinWebClient
from liveclip.exceptions import DOUYIN_NEED_LOGIN, LIVE_ROOM_RESOLVE_FAILED, LiveRoomError
from liveclip.observability import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# URL 正则
# ---------------------------------------------------------------------------

# live.douyin.com/{web_rid}
_LIVE_DOUYIN_PATTERN = re.compile(r"live\.douyin\.com/(?P<web_rid>\d+)", re.IGNORECASE)
# v.douyin.com 短链接
_SHORT_DOUYIN_PATTERN = re.compile(r"v\.douyin\.com/(?P<short_id>[A-Za-z0-9]+)", re.IGNORECASE)
# www.douyin.com
_DOUYIN_WEB_PATTERN = re.compile(r"(?:www\.)?douyin\.com", re.IGNORECASE)

_DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Referer": "https://live.douyin.com/",
}


@dataclass(frozen=True)
class DouyinRoomInfo:
    """抖音直播间基本信息。"""

    room_id: str
    web_rid: str
    sec_user_id: str
    anchor_name: str


class DouyinResolver:
    """解析抖音直播间 URL，提取房间信息。"""

    def __init__(self, timeout: int = 15, web_client: DouyinWebClient | None = None) -> None:
        self._timeout = timeout
        self._web_client = web_client or DouyinWebClient(timeout=timeout)

    def resolve_room_info(self, url: str, cookie: str | None = None) -> DouyinRoomInfo:
        """解析直播间 URL，返回房间信息。

        支持 live.douyin.com/{web_rid}、v.douyin.com 短链接等格式。

        Args:
            url: 抖音直播间 URL。
            cookie: 可选的 Cookie 字符串，用于鉴权。

        Returns:
            包含 room_id / web_rid / sec_user_id / anchor_name 的房间信息。

        Raises:
            LiveRoomError: 解析失败时抛出。
        """
        logger.info("resolving_room_url", url=url)

        # 1. 尝试直接从 URL 提取 web_rid
        web_rid = self._extract_web_rid(url)

        # 2. 若为短链接，跟随重定向获取真实 URL
        if web_rid is None:
            web_rid = self._resolve_short_url(url, cookie)

        if web_rid is None:
            raise LiveRoomError(
                LIVE_ROOM_RESOLVE_FAILED,
                f"无法从 URL 中提取直播间 ID: {url}",
                details={"url": url},
            )

        # 3. 优先使用 Web API 获取结构化信息，回退到页面解析
        api_info = self._fetch_room_info_via_api(web_rid, cookie)
        if api_info is not None:
            return api_info
        return self._fetch_room_info_via_page(web_rid, cookie)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _extract_web_rid(self, url: str) -> str | None:
        """从 URL 中直接提取 web_rid。"""
        match = _LIVE_DOUYIN_PATTERN.search(url)
        if match:
            return match.group("web_rid")
        return None

    def _resolve_short_url(self, url: str, cookie: str | None = None) -> str | None:
        """跟随短链接重定向，从最终 URL 提取 web_rid。"""
        if not _SHORT_DOUYIN_PATTERN.search(url) and not _DOUYIN_WEB_PATTERN.search(url):
            return None

        headers = {**_DEFAULT_HEADERS}
        if cookie:
            headers["Cookie"] = cookie

        try:
            with httpx.Client(follow_redirects=True, timeout=self._timeout) as client:
                resp = client.get(url, headers=headers)
                final_url = str(resp.url)
                logger.debug("short_url_resolved", original=url, final=final_url)
                return self._extract_web_rid(final_url)
        except httpx.HTTPError as exc:
            logger.warning("short_url_resolve_failed", url=url, error=str(exc))
            return None

    def _fetch_room_info_via_api(
        self,
        web_rid: str,
        cookie: str | None = None,
    ) -> DouyinRoomInfo | None:
        """通过抖音 Web API 获取 room_id / sec_user_id / anchor_name。

        当 API 要求登录 (status_code=8) 时静默回退到页面解析，不抛异常。
        """
        try:
            room = self._web_client.enter_room(web_rid, cookie)
        except LiveRoomError as exc:
            if exc.error_code == DOUYIN_NEED_LOGIN:
                logger.info(
                    "douyin_api_need_login_fallback",
                    web_rid=web_rid,
                )
                return None
            raise
        if room is None:
            return None

        room_id = _first_string(room, "id_str", "room_id", "roomId")
        owner = room.get("owner") if isinstance(room.get("owner"), dict) else {}
        user = room.get("_liveclip_user") if isinstance(room.get("_liveclip_user"), dict) else {}
        sec_user_id = _first_string(owner, "sec_uid", "secUid") or _first_string(
            user, "sec_uid", "secUid"
        )
        anchor_name = _first_string(owner, "nickname") or _first_string(user, "nickname")

        if not room_id:
            return None

        return DouyinRoomInfo(
            room_id=room_id,
            web_rid=web_rid,
            sec_user_id=sec_user_id or "",
            anchor_name=anchor_name or f"直播间{web_rid}",
        )

    def _fetch_room_info_via_page(
        self,
        web_rid: str,
        cookie: str | None = None,
    ) -> DouyinRoomInfo:
        """请求直播间页面，从内嵌转义 JSON 状态块中解析房间信息。

        逻辑来自 douyin-live-recorder-smartclip 参考项目的 get_douyin_stream_data。
        若页面获取失败或解析不到关键字段，回退为默认房间信息，不阻塞后续流程。
        """
        html = self._web_client.fetch_room_page(web_rid, cookie)
        if html is None:
            logger.warning(
                "douyin_page_fetch_failed_fallback",
                web_rid=web_rid,
            )
            return self._fallback_room_info(web_rid)

        room_info = self._parse_embedded_json_state(html, web_rid)
        if room_info is not None:
            return room_info

        logger.warning(
            "douyin_page_parse_failed_fallback",
            web_rid=web_rid,
        )
        return self._fallback_room_info(web_rid)

    # ------------------------------------------------------------------
    # 页面解析
    # ------------------------------------------------------------------

    def _parse_embedded_json_state(
        self, html: str, web_rid: str
    ) -> DouyinRoomInfo | None:
        """从 HTML 中提取转义 JSON 状态块，清洗后解析 room_id/昵称等信息。

        这是来自 douyin-live-recorder-smartclip 参考项目的核心解析逻辑，
        针对抖音页面 \\\\ 转义的嵌套 JSON 结构设计。
        """
        # 匹配内嵌的转义 JSON 状态块
        json_match = re.search(r'(\{\\"state\\":.*?)]\\n"]\)', html)
        if not json_match:
            json_match = re.search(
                r'(\{\\"common\\":.*?)]\\n"]\)</script><div hidden', html
            )
        if not json_match:
            return None

        json_str = json_match.group(1)
        # 清洗转义：反斜杠、Unicode 转义符
        cleaned = json_str.replace("\\", "").replace("u0026", "&")

        # 提取 roomStore JSON 对象
        room_match = re.search(
            r'"roomStore":(.*?),"linkmicStore"', cleaned, re.DOTALL
        )
        if not room_match:
            return None

        room_store_raw = room_match.group(1)

        # 提取主播昵称
        anchor_name = f"直播间{web_rid}"
        name_match = re.search(
            r'"nickname":"(.*?)","avatar_thumb', room_store_raw, re.DOTALL
        )
        if name_match:
            anchor_name = name_match.group(1)

        # 裁剪 roomStore 使其成为合法 JSON（截断到 has_commerce_goods 之前，补闭合花括号）
        room_store_cut = room_store_raw.split(',"has_commerce_goods"')[0] + "}}}"
        try:
            room_data: dict[str, Any] = json.loads(room_store_cut)
            room = room_data.get("roomInfo", {}).get("room", {})  # type: ignore[union-attr]
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.warning(
                "embedded_json_parse_failed", web_rid=web_rid
            )
            return None

        if not isinstance(room, dict):
            return None

        room_id = self._pick_room_id(room)
        if not room_id:
            return None

        sec_user_id = self._pick_sec_uid(room) or ""

        logger.info(
            "room_info_resolved_via_embedded_json",
            room_id=room_id,
            web_rid=web_rid,
            anchor_name=anchor_name,
        )
        return DouyinRoomInfo(
            room_id=room_id,
            web_rid=web_rid,
            sec_user_id=sec_user_id,
            anchor_name=anchor_name,
        )

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _fallback_room_info(self, web_rid: str) -> DouyinRoomInfo:
        """当所有解析方式都失败时，用 web_rid 构造默认房间信息。

        这允许录制流程继续执行，而不因页面解析失败而中断整个流水线。
        """
        logger.info(
            "room_info_fallback_default",
            web_rid=web_rid,
        )
        return DouyinRoomInfo(
            room_id=web_rid,
            web_rid=web_rid,
            sec_user_id="",
            anchor_name=f"直播间{web_rid}",
        )

    @staticmethod
    def _pick_room_id(room: dict[str, Any]) -> str | None:
        """从 room 字典中提取 room_id（兼容多种字段名）。"""
        for key in ("id_str", "room_id", "roomId"):
            val = room.get(key)
            if isinstance(val, str) and val:
                return val
            if isinstance(val, int):
                return str(val)
        return None

    @staticmethod
    def _pick_sec_uid(room: dict[str, Any]) -> str | None:
        """从 room 字典中提取 sec_user_id。"""
        owner = room.get("owner")
        if isinstance(owner, dict):
            for key in ("sec_uid", "secUid"):
                val = owner.get(key)
                if isinstance(val, str) and val:
                    return val
        for key in ("sec_uid", "secUid"):
            val = room.get(key)
            if isinstance(val, str) and val:
                return val
        return None


def _first_string(data: object, *keys: str) -> str | None:
    if not isinstance(data, dict):
        return None
    typed_data: dict[Any, Any] = data
    for key in keys:
        value = typed_data.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, int):
            return str(value)
    return None
