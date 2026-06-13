"""liveclip CLI 主应用。"""

from __future__ import annotations

import typer

app = typer.Typer(
    name="liveclip",
    help="Douyin live stream recording and AI smart-clipping system",
    no_args_is_help=True,
)

# Import sub-command apps
from liveclip.cli.commands.api_cmd import app as api_app  # noqa: E402
from liveclip.cli.commands.clip_cmd import app as clip_app  # noqa: E402
from liveclip.cli.commands.db_cmd import app as db_app  # noqa: E402
from liveclip.cli.commands.room_cmd import app as room_app  # noqa: E402
from liveclip.cli.commands.run_cmd import app as run_app  # noqa: E402
from liveclip.cli.commands.task_cmd import app as task_app  # noqa: E402
from liveclip.cli.commands.worker_cmd import app as worker_app  # noqa: E402

app.add_typer(api_app, name="api")
app.add_typer(worker_app, name="worker")
app.add_typer(room_app, name="room")
app.add_typer(task_app, name="task")
app.add_typer(run_app, name="run")
app.add_typer(clip_app, name="clip")
app.add_typer(db_app, name="db")


@app.command()
def version() -> None:
    """Show version information."""
    typer.echo("liveclip-server 0.1.0")


if __name__ == "__main__":
    app()
