"""Shared Douyin web HTTP client."""

from __future__ import annotations

import json
from typing import Any

import httpx

from liveclip.adapters.douyin.ab_sign import ab_sign
from liveclip.exceptions import DOUYIN_NEED_LOGIN, LiveRoomError
from liveclip.observability import get_logger

logger = get_logger(__name__)

LIVE_ENTER_URL = "https://live.douyin.com/webcast/room/web/enter/"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; WOW64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/116.0.5845.97 Safari/537.36 Core/1.116.567.400 QQBrowser/19.7.6764.400"
)
DEFAULT_COOKIE = (
    "ttwid=1%7C2iDIYVmjzMcpZ20fcaFde0VghXAA3NaNXE_SLR68IyE%7C1761045455%7C"
    "ab35197d5cfb21df6cbb2fa7ef1c9262206b062c315b9d04da746d0b37dfbc7d"
)


class DouyinWebClient:
    """Small HTTP client for Douyin live web endpoints."""

    def __init__(self, timeout: int = 15) -> None:
        self._timeout = timeout

    def enter_room(self, web_rid: str, cookie: str | None = None) -> dict[str, Any] | None:
        """Call Douyin's web enter endpoint and return the first room payload."""
        headers = self._headers(cookie, referer=f"https://live.douyin.com/{web_rid}")
        params = {
            "aid": "6383",
            "app_name": "douyin_web",
            "live_id": "1",
            "device_platform": "web",
            "language": "zh-CN",
            "browser_language": "zh-CN",
            "browser_platform": "Win32",
            "browser_name": "Chrome",
            "browser_version": "116.0.0.0",
            "web_rid": web_rid,
            "msToken": "",
        }
        params["a_bogus"] = ab_sign(str(httpx.QueryParams(params)), headers["User-Agent"])

        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.get(LIVE_ENTER_URL, headers=headers, params=params)
                response.raise_for_status()
                if not response.text.strip():
                    logger.warning("douyin_enter_empty_response", web_rid=web_rid)
                    return None
                data = response.json()
        except (httpx.HTTPError, json.JSONDecodeError) as exc:
            logger.warning("douyin_enter_failed", web_rid=web_rid, error=str(exc))
            return None

        if data.get("status_code") == 8:
            raise LiveRoomError(
                DOUYIN_NEED_LOGIN,
                "需要登录 Cookie 才能访问直播间",
                details={"web_rid": web_rid},
            )
        if data.get("status_code") != 0:
            logger.warning(
                "douyin_enter_error", web_rid=web_rid, status_code=data.get("status_code")
            )
            return None

        payload = data.get("data", {})
        if not isinstance(payload, dict):
            return None
        rooms = payload.get("data", [])
        room = rooms[0] if isinstance(rooms, list) and rooms else None
        if not isinstance(room, dict):
            return None
        user = payload.get("user")
        if isinstance(user, dict):
            room.setdefault("_liveclip_user", user)
        return room

    def fetch_room_page(self, web_rid: str, cookie: str | None = None) -> str | None:
        """Fetch the Douyin live room HTML page."""
        headers = self._headers(cookie)
        page_url = f"https://live.douyin.com/{web_rid}"
        try:
            with httpx.Client(follow_redirects=True, timeout=self._timeout) as client:
                response = client.get(page_url, headers=headers)
                response.raise_for_status()
                return response.text
        except httpx.HTTPError as exc:
            logger.warning("douyin_room_page_failed", web_rid=web_rid, error=str(exc))
            return None

    @staticmethod
    def _headers(
        cookie: str | None = None, referer: str = "https://live.douyin.com/"
    ) -> dict[str, str]:
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": referer,
        }
        headers["Cookie"] = cookie or DEFAULT_COOKIE
        return headers
