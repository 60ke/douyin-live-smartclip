"""Transcriber factory selecting local FunASR or shared media-asr."""

from __future__ import annotations

from liveclip.adapters.funasr.transcriber import FunASRTranscriber
from liveclip.adapters.media_asr.transcriber import MediaAsrHttpTranscriber
from liveclip.config.settings import AppSettings

Transcriber = FunASRTranscriber | MediaAsrHttpTranscriber


def build_transcriber(settings: AppSettings) -> Transcriber:
    """Return the configured transcriber implementation."""
    if settings.media_asr.enabled:
        return MediaAsrHttpTranscriber(settings.media_asr)
    return FunASRTranscriber(
        device=settings.funasr.device,
        model_dir=str(settings.funasr.model_dir),
    )
