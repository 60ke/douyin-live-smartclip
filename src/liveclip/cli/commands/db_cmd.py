"""数据库管理命令。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer

app = typer.Typer(help="Database management")


def _init_db(config: Path | None) -> None:
    """初始化数据库连接。"""
    from liveclip.config import load_settings
    from liveclip.db.session import init_db

    settings = load_settings(config)
    init_db(settings.database.url)


@app.command()
def init(
    config: str | None = typer.Option(
        None, "--config", "-c", envvar="LIVECLIP_CONFIG", help="Config file path"
    ),
) -> None:
    """Initialize database (create all tables)."""
    from liveclip.db import session as db_session
    from liveclip.db.models import Base

    _init_db(Path(config) if config else None)

    if db_session.engine is None:
        typer.echo("Database engine not initialized.")
        raise typer.Exit(code=1)

    async def _init() -> None:
        if db_session.engine is None:
            typer.echo("Database engine not initialized.")
            raise typer.Exit(code=1)
        async with db_session.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        typer.echo("Database tables created.")

    asyncio.run(_init())


@app.command()
def migrate(
    config: str | None = typer.Option(
        None, "--config", "-c", envvar="LIVECLIP_CONFIG", help="Config file path"
    ),
    revision: str = typer.Option("head", "--revision", "-r", help="Target revision"),
) -> None:
    """Run Alembic migrations."""
    from alembic.config import Config as AlembicConfig

    from alembic import command

    alembic_cfg = AlembicConfig("alembic.ini")

    # Override sqlalchemy.url from app settings if config provided
    if config is not None:
        from liveclip.config import load_settings

        settings = load_settings(Path(config))
        alembic_cfg.set_main_option("sqlalchemy.url", settings.database.url)

    command.upgrade(alembic_cfg, revision)
    typer.echo(f"Migrated to revision: {revision}")


@app.command()
def reset(
    config: str | None = typer.Option(
        None, "--config", "-c", envvar="LIVECLIP_CONFIG", help="Config file path"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
) -> None:
    """Drop and recreate all tables (with confirmation)."""
    from liveclip.db import session as db_session
    from liveclip.db.models import Base

    if not yes:
        confirmed = typer.confirm("This will drop ALL tables and data. Are you sure?")
        if not confirmed:
            typer.echo("Aborted.")
            raise typer.Abort()

    _init_db(Path(config) if config else None)

    if db_session.engine is None:
        typer.echo("Database engine not initialized.")
        raise typer.Exit(code=1)

    async def _reset() -> None:
        if db_session.engine is None:
            typer.echo("Database engine not initialized.")
            raise typer.Exit(code=1)
        async with db_session.engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
        typer.echo("Database reset complete.")

    asyncio.run(_reset())
