"""直播间管理命令。"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import typer

app = typer.Typer(help="Room management")


def _init_db(config: Path | None) -> None:
    """初始化数据库连接。"""
    from liveclip.config import load_settings
    from liveclip.db.session import init_db

    settings = load_settings(config)
    init_db(settings.database.url)


def _resolve_room_name(url: str, config: Path | None, explicit_name: str) -> str:
    """Resolve room display name from Douyin when no explicit name is provided."""
    if explicit_name.strip():
        return explicit_name.strip()

    from liveclip.adapters.douyin.resolver import DouyinResolver
    from liveclip.config import load_settings

    settings = load_settings(config)
    cookie = os.environ.get(settings.douyin.cookie_env)
    try:
        room_info = DouyinResolver().resolve_room_info(url, cookie)
    except Exception as exc:
        typer.echo(f"Room name auto-resolve failed, using empty name: {exc}")
        return ""
    return room_info.anchor_name


@app.command("list")
def list_rooms(
    config: str | None = typer.Option(
        None, "--config", "-c", envvar="LIVECLIP_CONFIG", help="Config file path"
    ),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List all rooms."""
    from liveclip.db.repositories.live_room_repo import LiveRoomRepository
    from liveclip.db.session import get_session_context

    _init_db(Path(config) if config else None)
    repo = LiveRoomRepository()

    async def _list() -> None:
        async with get_session_context() as session:
            rooms = await repo.get_all(session)
            if output_json:
                data = [
                    {
                        "id": r.id,
                        "url": r.url,
                        "name": r.name,
                        "platform": r.platform,
                        "quality": r.quality,
                        "enabled": r.enabled,
                    }
                    for r in rooms
                ]
                typer.echo(json.dumps(data, ensure_ascii=False, indent=2))
            else:
                if not rooms:
                    typer.echo("No rooms found.")
                    return
                for r in rooms:
                    status = "✓" if r.enabled else "✗"
                    typer.echo(
                        f"[{status}] id={r.id}  name={r.name!r}  "
                        f"platform={r.platform}  quality={r.quality}  url={r.url}"
                    )

    asyncio.run(_list())


@app.command()
def add(
    url: str = typer.Argument(..., help="Live room URL"),
    name: str = typer.Option("", "--name", "-n", help="Room display name"),
    platform: str = typer.Option("douyin", "--platform", help="Platform name"),
    quality: str = typer.Option("origin", "--quality", "-q", help="Stream quality"),
    max_duration: int = typer.Option(
        0, "--max-duration", help="Max recording duration in seconds; 0 means unlimited"
    ),
    config: str | None = typer.Option(
        None, "--config", "-c", envvar="LIVECLIP_CONFIG", help="Config file path"
    ),
) -> None:
    """Add a new room."""
    from liveclip.db.repositories.live_room_repo import LiveRoomRepository
    from liveclip.db.session import get_session_context

    config_path = Path(config) if config else None
    _init_db(config_path)
    repo = LiveRoomRepository()
    resolved_name = _resolve_room_name(url, config_path, name)

    async def _add() -> None:
        async with get_session_context() as session:
            existing = await repo.get_by_url(session, url)
            if existing is not None:
                typer.echo(f"Room with URL already exists: id={existing.id}")
                raise typer.Exit(code=1)
            room = await repo.create(
                session,
                url=url,
                name=resolved_name,
                platform=platform,
                quality=quality,
                max_duration_seconds=max_duration,
            )
            await session.commit()
            typer.echo(f"Room created: id={room.id}  name={room.name!r}  url={url}")

    asyncio.run(_add())


@app.command()
def update(
    room_id: int = typer.Argument(..., help="Room ID"),
    name: str | None = typer.Option(None, "--name", "-n", help="Room display name"),
    quality: str | None = typer.Option(None, "--quality", "-q", help="Stream quality"),
    max_duration: int | None = typer.Option(
        None, "--max-duration", help="Max recording duration in seconds; 0 means unlimited"
    ),
    enabled: bool | None = typer.Option(None, "--enabled/--disabled", help="Enable or disable"),
    config: str | None = typer.Option(
        None, "--config", "-c", envvar="LIVECLIP_CONFIG", help="Config file path"
    ),
) -> None:
    """Update a room."""
    from liveclip.db.repositories.live_room_repo import LiveRoomRepository
    from liveclip.db.session import get_session_context

    _init_db(Path(config) if config else None)
    repo = LiveRoomRepository()

    async def _update() -> None:
        async with get_session_context() as session:
            kwargs: dict[str, object] = {}
            if name is not None:
                kwargs["name"] = name
            if quality is not None:
                kwargs["quality"] = quality
            if max_duration is not None:
                kwargs["max_duration_seconds"] = max_duration
            if enabled is not None:
                kwargs["enabled"] = enabled
            if not kwargs:
                typer.echo("Nothing to update. Provide at least one option.")
                raise typer.Exit(code=1)
            room = await repo.update(session, room_id, **kwargs)
            await session.commit()
            typer.echo(f"Room updated: id={room.id}")

    asyncio.run(_update())


@app.command()
def remove(
    room_id: int = typer.Argument(..., help="Room ID"),
    config: str | None = typer.Option(
        None, "--config", "-c", envvar="LIVECLIP_CONFIG", help="Config file path"
    ),
) -> None:
    """Remove a room."""
    from liveclip.db.repositories.live_room_repo import LiveRoomRepository
    from liveclip.db.session import get_session_context

    _init_db(Path(config) if config else None)
    repo = LiveRoomRepository()

    async def _remove() -> None:
        async with get_session_context() as session:
            deleted = await repo.delete(session, room_id)
            if not deleted:
                typer.echo(f"Room id={room_id} not found.")
                raise typer.Exit(code=1)
            await session.commit()
            typer.echo(f"Room removed: id={room_id}")

    asyncio.run(_remove())
