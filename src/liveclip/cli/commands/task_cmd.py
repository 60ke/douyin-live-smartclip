"""任务管理命令。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import typer

app = typer.Typer(help="Task management")


def _init_db(config: Path | None) -> None:
    """初始化数据库连接。"""
    from liveclip.config import load_settings
    from liveclip.db.session import init_db

    settings = load_settings(config)
    init_db(settings.database.url)


@app.command("list")
def list_tasks(
    room_id: int | None = typer.Option(None, "--room", "-r", help="Filter by room ID"),
    config: str | None = typer.Option(
        None, "--config", "-c", envvar="LIVECLIP_CONFIG", help="Config file path"
    ),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List tasks, optionally filtered by room."""
    from liveclip.db.repositories.task_repo import TaskRepository
    from liveclip.db.session import get_session_context

    _init_db(Path(config) if config else None)
    repo = TaskRepository()

    async def _list() -> None:
        async with get_session_context() as session:
            if room_id is not None:
                tasks = await repo.get_by_room_id(session, room_id)
            else:
                tasks = await repo.get_all(session)
            if output_json:
                data = [
                    {
                        "id": t.id,
                        "room_id": t.room_id,
                        "task_type": t.task_type,
                        "cron_expression": t.cron_expression,
                        "enabled": t.enabled,
                    }
                    for t in tasks
                ]
                typer.echo(json.dumps(data, ensure_ascii=False, indent=2))
            else:
                if not tasks:
                    typer.echo("No tasks found.")
                    return
                for t in tasks:
                    status = "✓" if t.enabled else "✗"
                    cron = f"  cron={t.cron_expression}" if t.cron_expression else ""
                    typer.echo(
                        f"[{status}] id={t.id}  room_id={t.room_id}  type={t.task_type}{cron}"
                    )

    asyncio.run(_list())


@app.command()
def create(
    room_id: int = typer.Option(..., "--room", "-r", help="Room ID"),
    task_type: str = typer.Option("ONCE", "--type", "-t", help="Task type (ONCE/CRON)"),
    cron: str | None = typer.Option(None, "--cron", help="Cron expression (for CRON type)"),
    config: str | None = typer.Option(
        None, "--config", "-c", envvar="LIVECLIP_CONFIG", help="Config file path"
    ),
) -> None:
    """Create a new task."""
    from liveclip.db.repositories.task_repo import TaskRepository
    from liveclip.db.session import get_session_context

    _init_db(Path(config) if config else None)
    repo = TaskRepository()

    async def _create() -> None:
        async with get_session_context() as session:
            task = await repo.create(
                session,
                room_id=room_id,
                task_type=task_type,
                cron_expression=cron,
            )
            await session.commit()
            typer.echo(f"Task created: id={task.id}  room_id={room_id}  type={task_type}")

    asyncio.run(_create())


@app.command()
def update(
    task_id: int = typer.Argument(..., help="Task ID"),
    task_type: str | None = typer.Option(None, "--type", "-t", help="Task type"),
    cron: str | None = typer.Option(None, "--cron", help="Cron expression"),
    enabled: bool | None = typer.Option(None, "--enabled/--disabled", help="Enable or disable"),
    config: str | None = typer.Option(
        None, "--config", "-c", envvar="LIVECLIP_CONFIG", help="Config file path"
    ),
) -> None:
    """Update a task."""
    from liveclip.db.repositories.task_repo import TaskRepository
    from liveclip.db.session import get_session_context

    _init_db(Path(config) if config else None)
    repo = TaskRepository()

    async def _update() -> None:
        async with get_session_context() as session:
            kwargs: dict[str, object] = {}
            if task_type is not None:
                kwargs["task_type"] = task_type
            if cron is not None:
                kwargs["cron_expression"] = cron
            if enabled is not None:
                kwargs["enabled"] = enabled
            if not kwargs:
                typer.echo("Nothing to update. Provide at least one option.")
                raise typer.Exit(code=1)
            task = await repo.update(session, task_id, **kwargs)
            await session.commit()
            typer.echo(f"Task updated: id={task.id}")

    asyncio.run(_update())


@app.command()
def remove(
    task_id: int = typer.Argument(..., help="Task ID"),
    config: str | None = typer.Option(
        None, "--config", "-c", envvar="LIVECLIP_CONFIG", help="Config file path"
    ),
) -> None:
    """Remove a task."""
    from liveclip.db.repositories.task_repo import TaskRepository
    from liveclip.db.session import get_session_context

    _init_db(Path(config) if config else None)
    repo = TaskRepository()

    async def _remove() -> None:
        async with get_session_context() as session:
            deleted = await repo.delete(session, task_id)
            if not deleted:
                typer.echo(f"Task id={task_id} not found.")
                raise typer.Exit(code=1)
            await session.commit()
            typer.echo(f"Task removed: id={task_id}")

    asyncio.run(_remove())
