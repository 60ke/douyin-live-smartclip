from __future__ import annotations

import json
from types import SimpleNamespace

from liveclip.worker.runner import WorkerRunner


def test_runtime_pipeline_config_uses_live_room_config_only() -> None:
    task_config = json.dumps({"cover": {"enabled": False}, "task_mode": "LOOP"})
    room_config = json.dumps({"cover": {"enabled": True}, "task_mode": "LOOP"})
    task = SimpleNamespace(
        pipeline_config_json=task_config,
        room=SimpleNamespace(pipeline_config_json=room_config),
    )

    assert WorkerRunner._live_room_pipeline_config_json(task) == room_config


def test_runtime_pipeline_config_does_not_fall_back_to_task_config() -> None:
    task_config = json.dumps({"cover": {"enabled": False}, "task_mode": "LOOP"})
    task = SimpleNamespace(
        pipeline_config_json=task_config,
        room=SimpleNamespace(pipeline_config_json=None),
    )

    assert WorkerRunner._live_room_pipeline_config_json(task) is None
