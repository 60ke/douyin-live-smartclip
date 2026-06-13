"""Worker 管理命令。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from dotenv import load_dotenv
import typer

app = typer.Typer(help="Worker management")


@app.command()
def run(
    config: str | None = typer.Option(
        None, "--config", "-c", envvar="LIVECLIP_CONFIG", help="Config file path"
    ),
    once: bool = typer.Option(False, "--once", help="Run once and exit"),
) -> None:
    """Start the worker process."""
    from liveclip.config import apply_runtime_environment, ensure_directories, load_settings
    from liveclip.observability import setup_logging
    from liveclip.worker.runner import WorkerRunner

    load_dotenv()  # 加载 .env 文件中的环境变量

    settings = load_settings(Path(config) if config else None)
    apply_runtime_environment(settings)
    ensure_directories(settings)
    setup_logging()

    runner = WorkerRunner(settings)
    if once:
        asyncio.run(runner.run_once())
    else:
        try:
            asyncio.run(runner.run())
        except KeyboardInterrupt:
            runner.shutdown()
