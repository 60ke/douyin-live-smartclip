from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

from liveclip.config.settings import AppSettings


def load_settings(config_path: Path | None = None) -> AppSettings:
    """Load application settings from a TOML file with env-var overrides.

    Args:
        config_path: Optional explicit path to a TOML config file.  When
            provided it takes precedence over the ``LIVECLIP_CONFIG`` env var
            and the default ``configs/app.toml`` location.

    Returns:
        Fully-resolved :class:`AppSettings` instance.
    """
    if config_path is not None:
        config_path = config_path.resolve()
        if not config_path.exists():
            msg = f"Config file not found: {config_path}"
            raise FileNotFoundError(msg)
        return AppSettings(**_read_toml(config_path))

    env_path = os.environ.get("LIVECLIP_CONFIG")
    if env_path:
        p = Path(env_path).resolve()
        if not p.exists():
            msg = f"Config file from LIVECLIP_CONFIG not found: {p}"
            raise FileNotFoundError(msg)
        return AppSettings(**_read_toml(p))

    default_path = Path("configs/app.toml")
    if default_path.exists():
        return AppSettings(**_read_toml(default_path))
    return AppSettings()


def _read_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as file:
        data = tomllib.load(file)
    return data


def apply_runtime_environment(settings: AppSettings) -> None:
    """Set process-wide env vars derived from settings.

    Sets ``MODELSCOPE_CACHE``, ``HF_HOME``, and ``TORCH_HOME`` so that
    downstream libraries (modelscope, transformers, torch) respect the
    configured cache locations.
    """
    funasr_cache = settings.funasr.model_dir.resolve()
    storage_cache = settings.storage.base_dir.resolve() / "cache"

    env_mappings: dict[str, Path] = {
        "MODELSCOPE_CACHE": funasr_cache,
        "HF_HOME": storage_cache / "huggingface",
        "TORCH_HOME": storage_cache / "torch",
    }

    for key, value in env_mappings.items():
        os.environ.setdefault(key, str(value))

    if settings.llm.model:
        os.environ.setdefault("LLM_MODEL", settings.llm.model)
    if settings.llm.base_url:
        os.environ.setdefault("LLM_BASE_URL", settings.llm.base_url)


def ensure_directories(settings: AppSettings) -> None:
    """Create all runtime directories that the application expects to exist."""
    dirs_to_create: list[Path] = [
        settings.storage.base_dir.resolve(),
        settings.funasr.model_dir.resolve(),
    ]

    # Ensure common sub-directories under storage.base_dir
    base = settings.storage.base_dir.resolve()
    for subdir in ("raw", "media", "subtitles", "preprocess", "plans", "clips", "logs"):
        dirs_to_create.append(base / subdir)

    for d in dirs_to_create:
        d.mkdir(parents=True, exist_ok=True)
