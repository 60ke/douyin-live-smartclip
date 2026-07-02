from __future__ import annotations

from pathlib import Path

import pytest

from liveclip.config.settings import AppSettings, StorageConfig
from liveclip.services.transcription_service import (
    MediaTranscriptionService,
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
