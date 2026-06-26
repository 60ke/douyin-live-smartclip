"""GPT image edit client used by AI cover generation."""

from __future__ import annotations

import base64
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx

from liveclip.config.settings import GPTImageConfig


@dataclass(frozen=True)
class GPTImageInput:
    """Single reference image for GPT image edit."""

    path: Path
    filename: str | None = None
    content_type: str | None = None


class GPTImageClient:
    """Small OpenAI-compatible image edit client.

    The request format mirrors the Go backend implementation:
    multipart fields model/prompt/quality/n/size and repeated "image" files.
    """

    def __init__(self, config: GPTImageConfig) -> None:
        self._config = config

    @property
    def configured(self) -> bool:
        return bool(self._api_key())

    def edit(
        self,
        *,
        images: list[GPTImageInput],
        prompt: str,
        size: str | None = None,
    ) -> bytes:
        if not images:
            raise ValueError("GPT 图片编辑输入图片为空")
        api_key = self._api_key()
        if not api_key:
            raise ValueError("GPT 图片编辑服务 Key 为空")
        prompt = prompt.strip()
        if not prompt:
            raise ValueError("GPT 图片编辑 prompt 为空")

        data: dict[str, str] = {
            "model": self._config.model or "gpt-image-2",
            "prompt": prompt,
            "quality": self._config.quality or "low",
            "n": "1",
        }
        if size:
            data["size"] = size

        files: list[tuple[str, tuple[str, bytes, str]]] = []
        for index, image in enumerate(images, start=1):
            if not image.path.exists():
                raise FileNotFoundError(f"GPT 图片编辑输入不存在: {image.path}")
            payload = image.path.read_bytes()
            if not payload:
                raise ValueError(f"GPT 图片编辑第 {index} 张输入图片为空")
            content_type = image.content_type or _guess_content_type(image.path)
            if not content_type.lower().startswith("image/"):
                raise ValueError(f"GPT 图片编辑第 {index} 张输入不是图片: {content_type}")
            filename = image.filename or image.path.name or f"image_{index}.png"
            files.append(("image", (filename, payload, content_type)))

        response = httpx.post(
            self._edit_url(),
            data=data,
            files=files,
            headers={"Authorization": _bearer(api_key)},
            timeout=self._config.timeout_seconds,
        )
        body = _json_or_error(response)
        if response.status_code >= 400:
            raise RuntimeError(_response_error(body) or f"GPT 图片编辑服务返回 {response.status_code}")
        if error := _response_error(body):
            raise RuntimeError(error)

        items = body.get("data")
        if not isinstance(items, list) or not items:
            raise RuntimeError("GPT 图片编辑响应中没有图片数据")

        for item in items:
            if not isinstance(item, dict):
                continue
            b64_json = str(item.get("b64_json") or "").strip()
            if b64_json:
                return base64.b64decode(b64_json)
            url = str(item.get("url") or "").strip()
            if url:
                return _download_image(url, timeout=self._config.timeout_seconds)
        raise RuntimeError("GPT 图片编辑响应中没有可用的 b64_json 或 url")

    def _api_key(self) -> str:
        return (self._config.api_key or os.getenv(self._config.api_key_env, "")).strip()

    def _edit_url(self) -> str:
        base_url = (self._config.base_url or "https://api.apiyi.com").rstrip("/") + "/"
        edit_path = (self._config.edit_path or "/v1/images/edits").lstrip("/")
        return urljoin(base_url, edit_path)


def _guess_content_type(path: Path) -> str:
    guessed = mimetypes.guess_type(path.name)[0]
    return guessed or "image/png"


def _bearer(api_key: str) -> str:
    api_key = api_key.strip()
    if " " in api_key:
        return api_key
    return f"Bearer {api_key}"


def _json_or_error(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        if response.status_code >= 400:
            raise RuntimeError(f"GPT 图片编辑服务返回 {response.status_code}") from exc
        raise RuntimeError("解析 GPT 图片编辑响应失败") from exc
    if not isinstance(body, dict):
        raise RuntimeError("GPT 图片编辑响应格式无效")
    return body


def _response_error(body: dict[str, Any]) -> str:
    error = body.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "").strip()
        if message:
            return f"GPT 图片编辑服务返回错误: {message}"
    return ""


def _download_image(url: str, *, timeout: int) -> bytes:
    response = httpx.get(url, timeout=timeout)
    if response.status_code >= 400:
        raise RuntimeError(f"下载 GPT 图片编辑结果返回 {response.status_code}")
    content_type = response.headers.get("content-type", "")
    if content_type and not content_type.lower().startswith("image/"):
        raise RuntimeError(f"GPT 图片编辑结果不是图片: {content_type}")
    return response.content
