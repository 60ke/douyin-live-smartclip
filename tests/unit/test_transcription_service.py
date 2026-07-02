from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import liveclip.api.routes.media as media_routes
from liveclip.api.app import create_app
from liveclip.config.settings import AppSettings, StorageConfig
from liveclip.services.transcription_service import (
    MediaTranscriptionService,
    TranscriptionResult,
    build_extract_audio_command,
    classify_media_file,
)


class FakeTranscriber:
    def __init__(self) -> None:
        self.video_path: Path | None = None
        self.hotwords: list[str] | None = None

    def transcribe(
        self,
        video_path: Path,
        output_srt_path: Path,
        hotwords: list[str] | None = None,
        cancel_check: object | None = None,
    ) -> Path:
        self.video_path = video_path
        self.hotwords = hotwords
        output_srt_path.write_text(
            "\n".join(
                [
                    "1",
                    "00:00:00,000 --> 00:00:01,000",
                    "你好",
                    "",
                    "2",
                    "00:00:01,200 --> 00:00:02,000",
                    "欢迎来到直播间",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        return output_srt_path


class FakeHotwordManager:
    def load_hotwords(self) -> list[str]:
        return ["菜鸟"]


def test_classify_media_file_by_extension_and_content_type() -> None:
    assert classify_media_file("sample.mp4") == "video"
    assert classify_media_file("sample.wav") == "audio"
    assert classify_media_file("upload", "video/mp4") == "video"
    assert classify_media_file("upload", "audio/wav") == "audio"


def test_classify_media_file_rejects_unknown_type() -> None:
    with pytest.raises(ValueError, match="不支持"):
        classify_media_file("sample.txt", "text/plain")


def test_build_extract_audio_command_uses_16k_mono_wav() -> None:
    cmd = build_extract_audio_command("ffmpeg", Path("input.mp4"), Path("audio.wav"))

    assert cmd == [
        "ffmpeg",
        "-y",
        "-i",
        "input.mp4",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "wav",
        "audio.wav",
    ]


def test_transcribe_upload_audio_reuses_live_subtitle_processing(tmp_path: Path) -> None:
    input_path = tmp_path / "source.wav"
    input_path.write_bytes(b"fake audio")
    transcriber = FakeTranscriber()
    service = MediaTranscriptionService(
        AppSettings(storage=StorageConfig(base_dir=tmp_path)),
        transcriber=transcriber,  # type: ignore[arg-type]
        hotword_manager=FakeHotwordManager(),  # type: ignore[arg-type]
    )

    result = service.transcribe_upload(input_path, filename="source.wav", model="sensevoice")

    assert result.media_kind == "audio"
    assert result.audio_path == input_path
    assert transcriber.video_path == input_path
    assert transcriber.hotwords == ["菜鸟"]
    assert result.raw_srt_path.exists()
    assert result.processed_srt_path.exists()
    assert "你好 欢迎来到直播间" in result.processed_srt_path.read_text(encoding="utf-8")


def test_save_upload_stores_under_transcription_workspace(tmp_path: Path) -> None:
    service = MediaTranscriptionService(
        AppSettings(storage=StorageConfig(base_dir=tmp_path)),
        transcriber=FakeTranscriber(),  # type: ignore[arg-type]
        hotword_manager=FakeHotwordManager(),  # type: ignore[arg-type]
    )

    path = service.save_upload(b"fake audio", "sample.wav", "audio/wav")

    assert path.name == "source.wav"
    assert path.read_bytes() == b"fake audio"
    assert path.parent.parent == tmp_path / "transcriptions"


def test_media_transcription_endpoint_returns_raw_srt(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    raw_path = tmp_path / "raw.srt"
    processed_path = tmp_path / "subtitles.srt"
    raw_path.write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n短字幕\n\n",
        encoding="utf-8",
    )
    processed_path.write_text(
        "1\n00:00:00,000 --> 00:00:14,000\n合并后的长字幕\n\n",
        encoding="utf-8",
    )

    class FakeService:
        def __init__(self, settings: AppSettings) -> None:
            self.settings = settings

        def save_upload(self, content: bytes, filename: str, content_type: str | None = None) -> Path:
            input_path = tmp_path / "source.wav"
            input_path.write_bytes(content)
            return input_path

        def transcribe_upload(
            self,
            input_path: Path,
            *,
            filename: str,
            content_type: str | None = None,
            model: str = "sensevoice",
        ) -> TranscriptionResult:
            return TranscriptionResult(
                raw_srt_path=raw_path,
                processed_srt_path=processed_path,
                input_path=input_path,
                audio_path=input_path,
                media_kind="audio",
                model=model,
            )

    monkeypatch.setattr(media_routes, "MediaTranscriptionService", FakeService)
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/media/transcriptions",
        files={"file": ("sample.wav", b"fake audio", "audio/wav")},
        data={"model": "sensevoice"},
    )

    assert response.status_code == 200
    assert "短字幕" in response.text
    assert "合并后的长字幕" not in response.text
