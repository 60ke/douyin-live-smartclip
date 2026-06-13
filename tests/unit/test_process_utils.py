from __future__ import annotations

import subprocess
import sys
import time

import pytest

from liveclip.utils.process import run_long_command


def test_run_long_command_captures_stderr_without_blocking() -> None:
    result = run_long_command(
        [
            sys.executable,
            "-c",
            "import sys; print('out'); print('err', file=sys.stderr)",
        ],
        timeout=5,
    )

    assert result.returncode == 0
    assert "out" in result.stdout
    assert "err" in result.stdout


def test_run_long_command_times_out_quiet_process() -> None:
    started = time.monotonic()

    with pytest.raises(subprocess.TimeoutExpired):
        run_long_command(
            [sys.executable, "-c", "import time; time.sleep(5)"],
            timeout=1,
        )

    assert time.monotonic() - started < 3


def test_run_long_command_checks_cancel_when_process_is_quiet() -> None:
    started = time.monotonic()

    result = run_long_command(
        [sys.executable, "-c", "import time; time.sleep(5)"],
        timeout=5,
        cancel_check=lambda: time.monotonic() - started > 0.5,
    )

    assert result.returncode is not None
    assert time.monotonic() - started < 3
