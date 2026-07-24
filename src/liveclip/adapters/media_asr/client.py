"""HTTP client for shared media-asr (media-capabilities internal API)."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from liveclip.observability import get_logger

logger = get_logger(__name__)

_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".flv", ".ts"}


class MediaAsrClient:
    """Submit ASR jobs, poll status, download SRT, and cancel in-flight work."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        poll_interval_seconds: float = 2.0,
        poll_timeout_seconds: float = 3600.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._poll_interval_seconds = poll_interval_seconds
        self._poll_timeout_seconds = poll_timeout_seconds
        self._transport = transport

    def _headers(self) -> dict[str, str]:
        return {"X-DH-API-Key": self._api_key}

    def _client(self) -> httpx.Client:
        return httpx.Client(
            timeout=httpx.Timeout(60.0, connect=10.0),
            transport=self._transport,
        )

    def submit_asr_job(
        self,
        media_path: Path,
        *,
        hotwords: list[str] | None = None,
        idempotency_key: str | None = None,  # unused; kept for call-site compatibility
    ) -> str:
        """Submit an ASR job and return engine_job_id."""
        del idempotency_key  # engine no longer accepts/uses idempotency
        options = json.dumps({"output_mode": "srt"}, ensure_ascii=False)
        data: dict[str, str] = {
            "type": "asr",
            "options": options,
        }
        if hotwords:
            data["hotwords"] = " ".join(hotwords)

        file_field = "video" if media_path.suffix.lower() in _VIDEO_SUFFIXES else "audio"
        with media_path.open("rb") as media_file:
            files = {file_field: (media_path.name, media_file, "application/octet-stream")}
            with self._client() as client:
                response = client.post(
                    f"{self._base_url}/internal/dh/jobs",
                    headers=self._headers(),
                    data=data,
                    files=files,
                )
        self._raise_for_response(response, "ASR submit failed")
        body = response.json()
        if body.get("code", 0) != 0:
            raise RuntimeError(f"ASR submit error: {body}")
        return str(body["data"]["engine_job_id"])

    def poll_until_done(
        self,
        engine_job_id: str,
        *,
        cancel_check: Callable[[], bool] | None = None,
    ) -> dict:
        """Poll job status until terminal state; return job detail data."""
        elapsed = 0.0
        with self._client() as client:
            while elapsed < self._poll_timeout_seconds:
                if cancel_check and cancel_check():
                    self.cancel_job(engine_job_id, client=client)
                    raise RuntimeError("ASR job canceled")

                response = client.get(
                    f"{self._base_url}/internal/dh/jobs/{engine_job_id}",
                    headers=self._headers(),
                )
                self._raise_for_response(response, "ASR poll failed")
                detail = response.json().get("data") or {}
                status = detail.get("status")
                if status == "succeeded":
                    return detail
                if status in ("failed", "canceled", "timeout"):
                    message = detail.get("error_message") or detail.get("error_code") or status
                    raise RuntimeError(f"ASR job {engine_job_id} ended as {status}: {message}")

                time.sleep(self._poll_interval_seconds)
                elapsed += self._poll_interval_seconds

        raise RuntimeError(f"ASR job {engine_job_id} timed out after {self._poll_timeout_seconds}s")

    def cancel_job(
        self,
        engine_job_id: str,
        *,
        client: httpx.Client | None = None,
    ) -> None:
        """Request cancellation for an in-flight ASR job."""
        if client is not None:
            response = client.post(
                f"{self._base_url}/internal/dh/jobs/{engine_job_id}/cancel",
                headers=self._headers(),
            )
            self._raise_for_response(response, "ASR cancel failed")
            return

        with self._client() as owned_client:
            response = owned_client.post(
                f"{self._base_url}/internal/dh/jobs/{engine_job_id}/cancel",
                headers=self._headers(),
            )
            self._raise_for_response(response, "ASR cancel failed")

    def download_file(self, relative_path: str) -> bytes:
        """Download a result file from the media-asr data directory."""
        with self._client() as client:
            response = client.get(
                f"{self._base_url}/internal/dh/files",
                headers=self._headers(),
                params={"path": relative_path},
            )
        self._raise_for_response(response, "ASR file download failed")
        return response.content

    @staticmethod
    def _raise_for_response(response: httpx.Response, message: str) -> None:
        if response.status_code >= 400:
            raise RuntimeError(f"{message}: {response.status_code} {response.text}")
