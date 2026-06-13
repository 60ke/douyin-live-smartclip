"""liveclip CLI 命令子模块。"""

from __future__ import annotations

from liveclip.cli.commands.api_cmd import app as api_app
from liveclip.cli.commands.clip_cmd import app as clip_app
from liveclip.cli.commands.db_cmd import app as db_app
from liveclip.cli.commands.room_cmd import app as room_app
from liveclip.cli.commands.run_cmd import app as run_app
from liveclip.cli.commands.task_cmd import app as task_app
from liveclip.cli.commands.worker_cmd import app as worker_app

__all__ = [
    "api_app",
    "clip_app",
    "db_app",
    "room_app",
    "run_app",
    "task_app",
    "worker_app",
]
