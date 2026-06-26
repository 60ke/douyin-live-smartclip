from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict

from liveclip.domain.models import ClipSegmentConfig


class ServerConfig(BaseModel):
    """HTTP server binding configuration."""

    host: str = "0.0.0.0"
    port: int = 8000


class DatabaseConfig(BaseModel):
    """Database connection configuration."""

    url: str = "mysql+asyncmy://liveclip:liveclip_password@mysql:3306/liveclip?charset=utf8mb4"


class StorageConfig(BaseModel):
    """File storage root directory."""

    base_dir: Path = Path("./data")


class FFmpegConfig(BaseModel):
    """FFmpeg binary paths and encoding defaults."""

    ffmpeg_binary: str = "ffmpeg"
    ffprobe_binary: str = "ffprobe"
    default_encoder: str = "libx264"
    preset: str = "veryfast"
    crf: int = 18


class FunASRConfig(BaseModel):
    """FunASR speech recognition configuration."""

    device: str = "auto"  # auto, cpu, cuda, mps
    model_dir: Path = Path("./cache/models/funasr")


class LLMConfig(BaseModel):
    """LLM integration configuration."""

    api_key_env: str = "LLM_API"
    model: str = "deepseek-ai/DeepSeek-V4-Flash"
    base_url: str = "https://api.siliconflow.cn/v1/chat/completions"
    default_profile_name: str = "default"


class GPTImageConfig(BaseModel):
    """GPT image edit configuration for AI cover generation."""

    enabled: bool = True
    api_key: str = ""
    api_key_env: str = "GPT_IMAGE_API_KEY"
    base_url: str = "https://api.apiyi.com"
    edit_path: str = "/v1/images/edits"
    model: str = "gpt-image-2"
    quality: str = "low"
    timeout_seconds: int = 600


class DouyinConfig(BaseModel):
    """Douyin platform integration configuration."""

    cookie_env: str = "DOUYIN_COOKIE"


class WorkerConfig(BaseModel):
    """Background worker tuning knobs."""

    auto_start_with_api: bool = True
    poll_interval_seconds: int = 5
    max_concurrent_runs: int = 1
    heartbeat_interval_seconds: int = 30
    running_timeout_seconds: int = 300
    shutdown_timeout_seconds: int = 10
    resource_cleanup_enabled: bool = True
    resource_retention_hours: int = 72
    resource_cleanup_interval_seconds: int = 3600
    resource_cleanup_dry_run: bool = False


class AppSettings(BaseSettings):
    """Top-level application settings loaded from TOML / env vars."""

    model_config = SettingsConfigDict(
        env_prefix="LIVECLIP_",
        env_nested_delimiter="__",
    )

    server: ServerConfig = ServerConfig()
    database: DatabaseConfig = DatabaseConfig()
    storage: StorageConfig = StorageConfig()
    ffmpeg: FFmpegConfig = FFmpegConfig()
    funasr: FunASRConfig = FunASRConfig()
    llm: LLMConfig = LLMConfig()
    gpt_image: GPTImageConfig = GPTImageConfig()
    douyin: DouyinConfig = DouyinConfig()
    worker: WorkerConfig = WorkerConfig()
    clip_segment: ClipSegmentConfig = ClipSegmentConfig()
