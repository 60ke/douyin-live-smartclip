"""LLM API 客户端适配器。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, cast

import requests

from liveclip.exceptions import LLM_REQUEST_FAILED, LLMError
from liveclip.observability import get_logger
from liveclip.utils.retry import retry_with_backoff

logger = get_logger(__name__)
_API_DUMP_COUNTER = 0


class LLMClient:
    """OpenAI 兼容的 LLM API 客户端。"""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 1200,
        timeout: int = 90,
        max_retries: int = 4,
    ) -> None:
        self._api_key = api_key or os.environ.get("LLM_API") or os.environ.get("LLM_API_KEY", "")
        self._model = model or os.environ.get("LLM_MODEL") or "deepseek-v4-flash"
        self._base_url = (
            base_url
            or os.environ.get("LLM_BASE_URL")
            or "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ).rstrip("/")
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout = timeout
        self._max_retries = max_retries

    def chat(
        self,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
        *,
        prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_seconds: int | None = None,
        max_retries: int | None = None,
        json_mode: bool = False,
    ) -> str:
        """调用 OpenAI 兼容的 Chat API。

        使用指数退避重试 429/5xx 错误。

        Args:
            system_prompt: 系统提示词。
            user_prompt: 用户提示词。

        Returns:
            模型回复文本。

        Raises:
            LLMError: 请求失败时抛出。
        """
        if not self._api_key:
            raise LLMError(
                LLM_REQUEST_FAILED,
                "LLM API key is required. Set LLM_API_KEY or LLM_API.",
                details={"model": self._model},
            )
        if prompt is not None:
            system_prompt = system_prompt or "你是一个严谨的 JSON 输出助手。"
            user_prompt = prompt
        if system_prompt is None or user_prompt is None:
            raise ValueError("system_prompt and user_prompt are required")

        logger.info(
            "llm_chat_request",
            model=self._model,
            system_prompt_len=len(system_prompt),
            user_prompt_len=len(user_prompt),
        )

        def _do_request() -> str:
            return self._send_request(
                system_prompt,
                user_prompt,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout_seconds=timeout_seconds,
                json_mode=json_mode,
            )

        try:
            result = retry_with_backoff(
                _do_request,
                max_retries=max_retries if max_retries is not None else self._max_retries,
                base_delay=1.0,
                max_delay=30.0,
                retryable_exceptions=(requests.HTTPError, requests.RequestException),
            )
        except requests.HTTPError as exc:
            response = exc.response
            raise LLMError(
                LLM_REQUEST_FAILED,
                f"LLM 请求失败 (HTTP {response.status_code if response else 'unknown'}): {exc}",
                details={
                    "model": self._model,
                    "status_code": response.status_code if response else None,
                    "error": str(exc),
                },
            ) from exc
        except requests.RequestException as exc:
            raise LLMError(
                LLM_REQUEST_FAILED,
                f"LLM 请求传输错误: {exc}",
                details={"model": self._model, "error": str(exc)},
            ) from exc
        except Exception as exc:
            raise LLMError(
                LLM_REQUEST_FAILED,
                f"LLM 请求异常: {exc}",
                details={"model": self._model, "error": str(exc)},
            ) from exc

        logger.info("llm_chat_response", model=self._model, response_len=len(result))
        return cast(str, result)

    def check_health(self) -> bool:
        """简单健康检查，发送最小请求验证 API 可用。

        Returns:
            API 可用返回 True，否则 False。
        """
        try:
            self._send_request("Hi", "Hi")
            return True
        except Exception:
            return False

    def _send_request(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout_seconds: int | None = None,
        json_mode: bool = False,
    ) -> str:
        """发送单次 API 请求。"""
        url = self._chat_completions_url()
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature if temperature is not None else self._temperature,
            "max_tokens": max_tokens if max_tokens is not None else self._max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        logger.info(
            "llm_chat_payload",
            model=self._model,
            base_url=self._chat_completions_url(),
            temperature=payload["temperature"],
            max_tokens=payload["max_tokens"],
            timeout_seconds=timeout_seconds or self._timeout,
        )
        _dump_api_payload(
            "request",
            {
                "url": url,
                "timeout": timeout_seconds or self._timeout,
                "json": payload,
            },
        )

        try:
            resp = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=timeout_seconds or self._timeout,
            )
            if json_mode and _looks_like_unsupported_json_mode(resp):
                logger.warning(
                    "llm_json_mode_unsupported_retry_plain",
                    model=self._model,
                    status_code=resp.status_code,
                )
                payload.pop("response_format", None)
                resp = requests.post(
                    url,
                    headers=headers,
                    json=payload,
                    timeout=timeout_seconds or self._timeout,
                )
            if resp.status_code == 429 or resp.status_code >= 500:
                raise requests.HTTPError(f"HTTP {resp.status_code}", response=resp)
            resp.raise_for_status()
        except Exception as exc:
            _dump_api_payload(
                "error",
                {
                    "type": exc.__class__.__name__,
                    "message": str(exc),
                },
            )
            raise

        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            raise LLMError(
                LLM_REQUEST_FAILED,
                "LLM 返回结果无 choices",
                details={"model": self._model, "response": data},
            )

        message = choices[0].get("message", {}) or {}
        content = message.get("content") or message.get("reasoning_content") or ""
        if not content:
            raise LLMError(
                LLM_REQUEST_FAILED,
                "LLM 返回内容为空",
                details={"model": self._model, "response": data},
            )
        _dump_api_payload(
            "response",
            {
                "status_code": resp.status_code,
                "json": data,
                "content": content,
            },
        )

        return str(content)

    def _chat_completions_url(self) -> str:
        if self._base_url.endswith("/chat/completions"):
            return self._base_url
        return f"{self._base_url}/chat/completions"


def _dump_api_payload(kind: str, payload: dict[str, object]) -> None:
    """Dump API-level request/response payloads for comparisons."""
    dump_dir_raw = os.environ.get("LIVECLIP_LLM_DUMP_DIR")
    if not dump_dir_raw:
        return

    global _API_DUMP_COUNTER
    if kind == "request":
        _API_DUMP_COUNTER += 1
    dump_dir = Path(dump_dir_raw)
    dump_dir.mkdir(parents=True, exist_ok=True)
    dump_path = dump_dir / f"{_API_DUMP_COUNTER:03d}_api_{kind}.json"
    dump_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("llm_api_payload_dumped", kind=kind, path=str(dump_path))


def _looks_like_unsupported_json_mode(response: requests.Response) -> bool:
    """Return true when an OpenAI-compatible provider rejects response_format."""
    if response.status_code not in {400, 404, 422}:
        return False
    text = response.text.lower()
    return "response_format" in text or "json_object" in text
