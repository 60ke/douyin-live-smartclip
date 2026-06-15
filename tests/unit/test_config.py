from __future__ import annotations

from liveclip.config.settings import (
    AppSettings,
    DatabaseConfig,
    DouyinConfig,
    FFmpegConfig,
    FunASRConfig,
    LLMConfig,
    ServerConfig,
    StorageConfig,
    WorkerConfig,
)


class TestAppSettings:
    """Tests for AppSettings defaults."""

    def test_defaults(self) -> None:
        settings = AppSettings()
        assert isinstance(settings.server, ServerConfig)
        assert isinstance(settings.database, DatabaseConfig)
        assert isinstance(settings.storage, StorageConfig)
        assert isinstance(settings.ffmpeg, FFmpegConfig)
        assert isinstance(settings.funasr, FunASRConfig)
        assert isinstance(settings.llm, LLMConfig)
        assert isinstance(settings.douyin, DouyinConfig)
        assert isinstance(settings.worker, WorkerConfig)


class TestServerConfig:
    """Tests for ServerConfig defaults."""

    def test_defaults(self) -> None:
        config = ServerConfig()
        assert config.host == "0.0.0.0"
        assert config.port == 8000


class TestDatabaseConfig:
    """Tests for DatabaseConfig defaults."""

    def test_defaults(self) -> None:
        config = DatabaseConfig()
        assert config.url.startswith("mysql+asyncmy://")


class TestStorageConfig:
    """Tests for StorageConfig defaults."""

    def test_defaults(self) -> None:
        config = StorageConfig()
        assert str(config.base_dir) == "data"


class TestFFmpegConfig:
    """Tests for FFmpegConfig defaults."""

    def test_defaults(self) -> None:
        config = FFmpegConfig()
        assert config.ffmpeg_binary == "ffmpeg"
        assert config.ffprobe_binary == "ffprobe"
        assert config.default_encoder == "libx264"
        assert config.preset == "veryfast"
        assert config.crf == 18


class TestFunASRConfig:
    """Tests for FunASRConfig defaults."""

    def test_defaults(self) -> None:
        config = FunASRConfig()
        assert config.device == "auto"


class TestLLMConfig:
    """Tests for LLMConfig defaults."""

    def test_defaults(self) -> None:
        config = LLMConfig()
        assert config.default_profile_name == "default"


class TestDouyinConfig:
    """Tests for DouyinConfig defaults."""

    def test_defaults(self) -> None:
        config = DouyinConfig()
        assert config.cookie_env == "DOUYIN_COOKIE"


class TestWorkerConfig:
    """Tests for WorkerConfig defaults."""

    def test_defaults(self) -> None:
        config = WorkerConfig()
        assert config.poll_interval_seconds == 5
        assert config.max_concurrent_runs == 1
