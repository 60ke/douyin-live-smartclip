from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from liveclip.adapters.funasr.transcriber import FunASRTranscriber
from liveclip.adapters.media_asr.client import MediaAsrClient
from liveclip.adapters.media_asr.factory import build_transcriber
from liveclip.adapters.media_asr.transcriber import MediaAsrHttpTranscriber
from liveclip.config.settings import AppSettings, MediaAsrConfig
from liveclip.exceptions import FunASRError

SAMPLE_SRT = "\n".join(
    [
        "1",
        "00:00:00,000 --> 00:00:01,000",
        "你好",
        "",
    ]
)


def _mock_transport(*, poll_count: int = 1) -> httpx.MockTransport:
    poll_calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/internal/dh/jobs":
            assert request.headers.get("X-DH-API-Key") == "test-key"
            return httpx.Response(
                200,
                json={"code": 0, "message": "ok", "data": {"engine_job_id": "job-123", "status": "queued"}},
            )

        if request.method == "GET" and request.url.path == "/internal/dh/jobs/job-123":
            poll_calls["count"] += 1
            if poll_calls["count"] < poll_count:
                return httpx.Response(
                    200,
                    json={"code": 0, "message": "ok", "data": {"status": "running"}},
                )
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "message": "ok",
                    "data": {
                        "status": "succeeded",
                        "result": {"srt_path": "jobs/job-123/output/transcript.srt"},
                    },
                },
            )

        if request.method == "GET" and request.url.path == "/internal/dh/files":
            assert request.url.params.get("path") == "jobs/job-123/output/transcript.srt"
            return httpx.Response(200, content=SAMPLE_SRT.encode("utf-8"))

        if request.method == "POST" and request.url.path == "/internal/dh/jobs/job-123/cancel":
            return httpx.Response(
                200,
                json={"code": 0, "message": "ok", "data": {"engine_job_id": "job-123", "status": "cancel_requested"}},
            )

        return httpx.Response(404, json={"detail": "not found"})

    return httpx.MockTransport(handler)


def test_media_asr_client_submit_poll_and_download(tmp_path: Path) -> None:
    media_path = tmp_path / "sample.mp4"
    media_path.write_bytes(b"fake-video")

    client = MediaAsrClient(
        base_url="http://media-asr.test",
        api_key="test-key",
        poll_interval_seconds=0.01,
        poll_timeout_seconds=5.0,
        transport=_mock_transport(poll_count=2),
    )

    engine_job_id = client.submit_asr_job(media_path, hotwords=["菜鸟", "直播"])
    detail = client.poll_until_done(engine_job_id)
    content = client.download_file(detail["result"]["srt_path"])

    assert engine_job_id == "job-123"
    assert content.decode("utf-8") == SAMPLE_SRT


def test_media_asr_http_transcriber_writes_srt(tmp_path: Path) -> None:
    media_path = tmp_path / "sample.wav"
    media_path.write_bytes(b"fake-audio")
    output_path = tmp_path / "output.srt"

    client = MediaAsrClient(
        base_url="http://media-asr.test",
        api_key="test-key",
        poll_interval_seconds=0.01,
        poll_timeout_seconds=5.0,
        transport=_mock_transport(),
    )
    transcriber = MediaAsrHttpTranscriber(
        MediaAsrConfig(base_url="http://media-asr.test", api_key="test-key"),
        client=client,
    )

    result = transcriber.transcribe(media_path, output_path, hotwords=["菜鸟"])

    assert result == output_path
    assert output_path.read_text(encoding="utf-8") == SAMPLE_SRT


def test_media_asr_http_transcriber_cancel_raises_funasr_error(tmp_path: Path) -> None:
    media_path = tmp_path / "sample.mp4"
    media_path.write_bytes(b"fake-video")
    output_path = tmp_path / "output.srt"
    cancel_after_submit = {"ready": False}

    def cancel_check() -> bool:
        return cancel_after_submit["ready"]

    transport = _mock_transport(poll_count=5)
    client = MediaAsrClient(
        base_url="http://media-asr.test",
        api_key="test-key",
        poll_interval_seconds=0.01,
        poll_timeout_seconds=5.0,
        transport=transport,
    )
    transcriber = MediaAsrHttpTranscriber(
        MediaAsrConfig(base_url="http://media-asr.test", api_key="test-key"),
        client=client,
    )

    original_submit = client.submit_asr_job

    def submit_and_flag_cancel(media_path: Path, *, hotwords: list[str] | None = None, idempotency_key: str | None = None) -> str:
        job_id = original_submit(media_path, hotwords=hotwords, idempotency_key=idempotency_key)
        cancel_after_submit["ready"] = True
        return job_id

    client.submit_asr_job = submit_and_flag_cancel  # type: ignore[method-assign]

    with pytest.raises(FunASRError, match="转写被取消|media-asr"):
        transcriber.transcribe(media_path, output_path, cancel_check=cancel_check)


def test_media_asr_http_transcriber_failed_job_raises_funasr_error(tmp_path: Path) -> None:
    media_path = tmp_path / "sample.mp4"
    media_path.write_bytes(b"fake-video")
    output_path = tmp_path / "output.srt"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/internal/dh/jobs":
            return httpx.Response(
                200,
                json={"code": 0, "message": "ok", "data": {"engine_job_id": "job-fail"}},
            )
        if request.method == "GET" and request.url.path == "/internal/dh/jobs/job-fail":
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "message": "ok",
                    "data": {"status": "failed", "error_message": "gpu oom"},
                },
            )
        return httpx.Response(404)

    client = MediaAsrClient(
        base_url="http://media-asr.test",
        api_key="test-key",
        poll_interval_seconds=0.01,
        poll_timeout_seconds=1.0,
        transport=httpx.MockTransport(handler),
    )
    transcriber = MediaAsrHttpTranscriber(
        MediaAsrConfig(base_url="http://media-asr.test", api_key="test-key"),
        client=client,
    )

    with pytest.raises(FunASRError, match="media-asr"):
        transcriber.transcribe(media_path, output_path)


def test_build_transcriber_defaults_to_funasr() -> None:
    transcriber = build_transcriber(AppSettings())
    assert isinstance(transcriber, FunASRTranscriber)


def test_build_transcriber_uses_media_asr_when_enabled() -> None:
    settings = AppSettings(media_asr=MediaAsrConfig(enabled=True, api_key="test-key"))
    transcriber = build_transcriber(settings)
    assert isinstance(transcriber, MediaAsrHttpTranscriber)
