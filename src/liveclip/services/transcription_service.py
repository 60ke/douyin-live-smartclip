"""Ad-hoc media transcription service used by the public upload API."""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from liveclip.adapters.funasr import FunASRTranscriber, HotwordManager
from liveclip.config.settings import AppSettings
from liveclip.exceptions import FFMPEG_CONVERT_FAILED, FFmpegError
from liveclip.observability import get_logger
from liveclip.pipeline.steps.preprocess_subtitle import merge_fragments
from liveclip.subtitle.parser import parse_srt_file
from liveclip.subtitle.writer import write_srt_file
from liveclip.utils.process import run_command

logger = get_logger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".flv", ".ts"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".amr"}


@dataclass(frozen=True)
class TranscriptionResult:
    """Result paths for one uploaded media transcription."""

    raw_srt_path: Path
    processed_srt_path: Path
    input_path: Path
    audio_path: Path
    media_kind: str
    model: str


def classify_media_file(filename: str, content_type: str | None = None) -> str:
    """Classify an uploaded file as audio or video using extension first."""
    suffix = Path(filename).suffix.lower()
    if suffix in VIDEO_EXTENSIONS:
        return "video"
    if suffix in AUDIO_EXTENSIONS:
        return "audio"

    normalized_content_type = (content_type or "").lower()
    if normalized_content_type.startswith("video/"):
        return "video"
    if normalized_content_type.startswith("audio/"):
        return "audio"

    raise ValueError(f"不支持的媒体文件类型: {filename}")


def build_extract_audio_command(ffmpeg_binary: str, input_path: Path, output_path: Path) -> list[str]:
    """Build an ffmpeg command that extracts mono 16k WAV audio from video."""
    return [
        ffmpeg_binary,
        "-y",
        "-i",
        str(input_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "wav",
        str(output_path),
    ]


class MediaTranscriptionService:
    """Transcribe uploaded audio/video into processed SRT subtitles."""

    def __init__(
        self,
        settings: AppSettings,
        transcriber: FunASRTranscriber | None = None,
        hotword_manager: HotwordManager | None = None,
    ) -> None:
        self._settings = settings
        self._transcriber = transcriber or FunASRTranscriber(
            device=settings.funasr.device,
            model_dir=str(settings.funasr.model_dir),
        )
        self._hotword_manager = hotword_manager or HotwordManager()

    def transcribe_upload(
        self,
        input_path: Path,
        *,
        filename: str,
        content_type: str | None = None,
        model: str = "sensevoice",
    ) -> TranscriptionResult:
        """Transcribe one uploaded media file and return the processed SRT path."""
        media_kind = classify_media_file(filename, content_type)
        work_dir = input_path.parent
        raw_srt_path = work_dir / "raw.srt"
        processed_srt_path = work_dir / "subtitles.srt"

        if media_kind == "video":
            audio_path = work_dir / "audio.wav"
            self._extract_audio(input_path, audio_path)
        else:
            audio_path = input_path

        hotwords = self._hotword_manager.load_hotwords()
        logger.info(
            "media_transcription_start",
            input_path=str(input_path),
            audio_path=str(audio_path),
            media_kind=media_kind,
            model=model,
            hotword_count=len(hotwords),
        )
        self._transcriber.transcribe(
            video_path=audio_path,
            output_srt_path=raw_srt_path,
            hotwords=hotwords,
        )

        subtitles = parse_srt_file(raw_srt_path)
        if not subtitles:
            raise ValueError("字幕为空或解析失败")
        processed = merge_fragments(subtitles)
        write_srt_file(processed_srt_path, processed)

        logger.info(
            "media_transcription_done",
            raw_srt_path=str(raw_srt_path),
            processed_srt_path=str(processed_srt_path),
            original_count=len(subtitles),
            processed_count=len(processed),
        )
        return TranscriptionResult(
            raw_srt_path=raw_srt_path,
            processed_srt_path=processed_srt_path,
            input_path=input_path,
            audio_path=audio_path,
            media_kind=media_kind,
            model=model,
        )

    def save_upload(self, content: bytes, filename: str, content_type: str | None = None) -> Path:
        """Persist uploaded bytes under the storage root and return the saved path."""
        media_kind = classify_media_file(filename, content_type)
        suffix = Path(filename).suffix.lower()
        if not suffix:
            suffix = ".mp4" if media_kind == "video" else ".wav"

        work_dir = self._settings.storage.base_dir / "transcriptions" / uuid.uuid4().hex
        work_dir.mkdir(parents=True, exist_ok=True)
        input_path = work_dir / f"source{suffix}"
        input_path.write_bytes(content)
        return input_path

    def _extract_audio(self, input_path: Path, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = output_path.with_suffix(f"{output_path.suffix}.part")
        tmp_path.unlink(missing_ok=True)
        cmd = build_extract_audio_command(self._settings.ffmpeg.ffmpeg_binary, input_path, tmp_path)
        try:
            run_command(cmd)
        except Exception as exc:
            tmp_path.unlink(missing_ok=True)
            raise FFmpegError(
                FFMPEG_CONVERT_FAILED,
                f"视频提取音频失败: {exc}",
                details={"input_path": str(input_path), "error": str(exc)},
            ) from exc
        if not tmp_path.exists():
            raise FFmpegError(
                FFMPEG_CONVERT_FAILED,
                f"视频提取音频完成但未找到输出文件: {tmp_path}",
                details={"input_path": str(input_path), "output_path": str(output_path)},
            )
        shutil.move(str(tmp_path), str(output_path))
        return output_path
