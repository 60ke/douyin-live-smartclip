"""运行管理命令。"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import typer

app = typer.Typer(help="Run management")


def _init_db(config: Path | None) -> None:
    """初始化数据库连接。"""
    from liveclip.config import load_settings
    from liveclip.db.session import init_db

    settings = load_settings(config)
    init_db(settings.database.url)


async def _create_tables() -> None:
    """Create database tables for first-run CLI workflows."""
    from liveclip.db import session as db_session
    from liveclip.db.models import Base

    if db_session.engine is None:
        msg = "Database engine not initialized."
        raise RuntimeError(msg)
    async with db_session.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


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
def list_runs(
    task_id: int | None = typer.Option(None, "--task", "-t", help="Filter by task ID"),
    config: str | None = typer.Option(
        None, "--config", "-c", envvar="LIVECLIP_CONFIG", help="Config file path"
    ),
    output_json: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """List runs, optionally filtered by task."""
    from sqlalchemy import select

    from liveclip.db.models import TaskRun
    from liveclip.db.session import get_session_context

    _init_db(Path(config) if config else None)

    async def _list() -> None:
        async with get_session_context() as session:
            stmt = select(TaskRun).order_by(TaskRun.id.desc())
            if task_id is not None:
                stmt = stmt.where(TaskRun.task_id == task_id)
            stmt = stmt.limit(50)
            result = await session.execute(stmt)
            runs = list(result.scalars().all())
            if output_json:
                data = [
                    {
                        "id": r.id,
                        "task_id": r.task_id,
                        "run_status": r.run_status,
                        "trigger_type": r.trigger_type,
                        "started_at": str(r.started_at) if r.started_at else None,
                        "finished_at": str(r.finished_at) if r.finished_at else None,
                    }
                    for r in runs
                ]
                typer.echo(json.dumps(data, ensure_ascii=False, indent=2))
            else:
                if not runs:
                    typer.echo("No runs found.")
                    return
                for r in runs:
                    typer.echo(
                        f"id={r.id}  task_id={r.task_id}  "
                        f"status={r.run_status}  trigger={r.trigger_type}  "
                        f"started={r.started_at}"
                    )

    asyncio.run(_list())


@app.command()
def trigger(
    task_id: int = typer.Argument(..., help="Task ID to trigger"),
    config: str | None = typer.Option(
        None, "--config", "-c", envvar="LIVECLIP_CONFIG", help="Config file path"
    ),
) -> None:
    """Trigger a new run for a task."""
    from liveclip.db.session import get_session_context
    from liveclip.domain.enums import TriggerType
    from liveclip.schemas.run import RunCreate
    from liveclip.services.run_service import RunService

    _init_db(Path(config) if config else None)

    async def _trigger() -> None:
        async with get_session_context() as session:
            run_service = RunService(session)
            run = await run_service.create(RunCreate(task_id=task_id, trigger_type=TriggerType.CLI))
            await session.commit()
            typer.echo(f"Run triggered: id={run.id}  task_id={task_id}")

    asyncio.run(_trigger())


@app.command("start")
def start(
    url: str = typer.Option(..., "--url", help="Douyin live room URL"),
    name: str = typer.Option("", "--name", "-n", help="Room display name"),
    quality: str = typer.Option("origin", "--quality", "-q", help="Stream quality"),
    max_duration: int = typer.Option(
        300, "--max-duration", help="Max recording duration in seconds"
    ),
    config: str | None = typer.Option(
        None, "--config", "-c", envvar="LIVECLIP_CONFIG", help="Config file path"
    ),
) -> None:
    """Create room/task/run and execute the full pipeline once."""
    from liveclip.config import apply_runtime_environment, ensure_directories, load_settings
    from liveclip.db.repositories.live_room_repo import LiveRoomRepository
    from liveclip.db.repositories.task_repo import TaskRepository
    from liveclip.db.session import get_session_context, init_db
    from liveclip.domain.enums import RunStatus, TaskType, TriggerType
    from liveclip.observability import setup_logging
    from liveclip.schemas.run import RunCreate
    from liveclip.services.run_service import RunService
    from liveclip.worker.runner import WorkerRunner

    config_path = Path(config) if config else None
    settings = load_settings(config_path)
    apply_runtime_environment(settings)
    ensure_directories(settings)
    setup_logging()
    init_db(settings.database.url)

    resolved_name = _resolve_room_name(url, config_path, name)
    room_repo = LiveRoomRepository()
    task_repo = TaskRepository()

    async def _start() -> None:
        await _create_tables()

        async with get_session_context() as session:
            room = await room_repo.get_by_url(session, url)
            if room is None:
                room = await room_repo.create(
                    session,
                    url=url,
                    name=resolved_name,
                    platform="douyin",
                    quality=quality,
                    max_duration_seconds=max_duration,
                )
                typer.echo(f"Room created: id={room.id}  name={room.name!r}")
            else:
                update_values: dict[str, object] = {
                    "quality": quality,
                    "max_duration_seconds": max_duration,
                }
                if resolved_name:
                    update_values["name"] = resolved_name
                room = await room_repo.update(session, room.id, **update_values)
                typer.echo(f"Room reused: id={room.id}  name={room.name!r}")

            task = await task_repo.create(
                session,
                room_id=room.id,
                task_type=str(TaskType.ONCE),
                cron_expression=None,
            )
            typer.echo(f"Task created: id={task.id}  room_id={room.id}")

            run_service = RunService(session)
            run = await run_service.create(RunCreate(task_id=task.id, trigger_type=TriggerType.CLI))
            await session.commit()
            typer.echo(f"Run triggered: id={run.id}  task_id={task.id}")

        runner = WorkerRunner(settings)
        processed = await runner.run_by_id(run.id)
        if not processed:
            typer.echo(f"Run id={run.id} was not processed.")
            raise typer.Exit(code=1)

        async with get_session_context() as session:
            run_service = RunService(session)
            finished_run = await run_service.get_by_id(run.id)
            if finished_run is None:
                typer.echo(f"Run id={run.id} not found after worker execution.")
                raise typer.Exit(code=1)
            typer.echo(f"Run finished: id={finished_run.id}  status={finished_run.run_status}")
            typer.echo(f"Output: {settings.storage.base_dir}/room_{room.id}/run_{run.id}")
            if finished_run.run_status == str(RunStatus.FAILED):
                if finished_run.error_message:
                    typer.echo(f"Error: {finished_run.error_message}", err=True)
                raise typer.Exit(code=1)

    asyncio.run(_start())


@app.command()
def cancel(
    run_id: int = typer.Argument(..., help="Run ID to cancel"),
    config: str | None = typer.Option(
        None, "--config", "-c", envvar="LIVECLIP_CONFIG", help="Config file path"
    ),
) -> None:
    """Cancel a running run."""
    from liveclip.db.repositories.run_repo import TaskRunRepository
    from liveclip.db.session import get_session_context
    from liveclip.domain.enums import RunStatus

    _init_db(Path(config) if config else None)
    repo = TaskRunRepository()

    async def _cancel() -> None:
        async with get_session_context() as session:
            run = await repo.get_by_id(session, run_id)
            if run is None:
                typer.echo(f"Run id={run_id} not found.")
                raise typer.Exit(code=1)
            if run.run_status != RunStatus.RUNNING and run.run_status != RunStatus.PENDING:
                typer.echo(f"Run id={run_id} is not cancellable (status={run.run_status}).")
                raise typer.Exit(code=1)
            run = await repo.update(session, run_id, run_status=RunStatus.CANCELED)
            await session.commit()
            typer.echo(f"Run canceled: id={run_id}")

    asyncio.run(_cancel())


@app.command()
def detail(
    run_id: int = typer.Argument(..., help="Run ID"),
    config: str | None = typer.Option(
        None, "--config", "-c", envvar="LIVECLIP_CONFIG", help="Config file path"
    ),
) -> None:
    """Show run detail with steps."""
    from liveclip.db.repositories.run_repo import TaskRunRepository
    from liveclip.db.session import get_session_context

    _init_db(Path(config) if config else None)
    repo = TaskRunRepository()

    async def _detail() -> None:
        async with get_session_context() as session:
            run = await repo.get_by_id(session, run_id)
            if run is None:
                typer.echo(f"Run id={run_id} not found.")
                raise typer.Exit(code=1)
            steps = await repo.get_steps_by_run(session, run_id)
            typer.echo(f"Run id={run.id}")
            typer.echo(
                f"  task_id={run.task_id}  status={run.run_status}  trigger={run.trigger_type}"
            )
            typer.echo(f"  started={run.started_at}  finished={run.finished_at}")
            if run.error_message:
                typer.echo(f"  error: {run.error_message}")
            typer.echo(f"  Steps ({len(steps)}):")
            for s in steps:
                typer.echo(
                    f"    {s.step_name}: {s.step_status}  "
                    f"({s.started_at} -> {s.finished_at})  "
                    f"dur={s.duration_ms}ms"
                )
                if s.error_message:
                    typer.echo(f"      error: {s.error_message}")

    asyncio.run(_detail())
