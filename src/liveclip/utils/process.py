from __future__ import annotations

import logging
import selectors
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import TextIO, cast

logger = logging.getLogger(__name__)


def run_command(
    cmd: list[str],
    timeout: int | None = None,
    cwd: Path | None = None,
    log_callback: Callable[[str], None] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command and return its result.

    Captures stdout and stderr.  Optionally logs each output line via
    *log_callback*.

    Args:
        cmd: Command and arguments.
        timeout: Maximum execution time in seconds.
        cwd: Working directory for the command.
        log_callback: Optional callback invoked with each output line.

    Returns:
        CompletedProcess with captured stdout/stderr.

    Raises:
        subprocess.CalledProcessError: If the command exits non-zero.
        subprocess.TimeoutExpired: If the command exceeds *timeout*.
    """
    logger.debug("Running command: %s", " ".join(cmd))
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )

    if log_callback and result.stdout:
        for line in result.stdout.splitlines():
            log_callback(line)

    if result.returncode != 0:
        logger.error(
            "Command failed (rc=%d): %s\nstderr: %s",
            result.returncode,
            " ".join(cmd),
            result.stderr,
        )
        raise subprocess.CalledProcessError(
            result.returncode,
            cmd,
            result.stdout,
            result.stderr,
        )

    return result


def run_long_command(
    cmd: list[str],
    timeout: int | None = None,
    cwd: Path | None = None,
    heartbeat_callback: Callable[[], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
    log_callback: Callable[[str], None] | None = None,
    heartbeat_interval: float = 30.0,
) -> subprocess.CompletedProcess[str]:
    """Run a long-lived command with heartbeat and cancellation support.

    Uses ``subprocess.Popen`` to stream merged stdout/stderr line-by-line.
    Periodically invokes *heartbeat_callback* so callers can signal liveness.
    Checks *cancel_check* even when the child process is quiet.

    Args:
        cmd: Command and arguments.
        timeout: Maximum execution time in seconds.
        cwd: Working directory for the command.
        heartbeat_callback: Optional callback invoked every *heartbeat_interval*
            seconds.
        cancel_check: Optional callback; return ``True`` to cancel execution.
        log_callback: Optional callback invoked with each stdout line.
        heartbeat_interval: Seconds between heartbeat invocations.

    Returns:
        CompletedProcess with captured stdout/stderr.

    Raises:
        subprocess.CalledProcessError: If the command exits non-zero.
        subprocess.TimeoutExpired: If the command exceeds *timeout*.
    """
    logger.debug("Running long command: %s", " ".join(cmd))
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        cwd=cwd,
    )

    stdout_lines: list[str] = []
    last_heartbeat = time.monotonic()
    started_at = last_heartbeat

    assert proc.stdout is not None  # guaranteed by PIPE
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)

    try:
        while proc.poll() is None:
            now = time.monotonic()
            if heartbeat_callback and (now - last_heartbeat) >= heartbeat_interval:
                heartbeat_callback()
                last_heartbeat = now

            if cancel_check and cancel_check():
                logger.info("Cancellation requested; terminating process")
                terminate_process(proc)
                break

            if timeout is not None and (now - started_at) >= timeout:
                logger.warning("Command timeout; terminating process")
                terminate_process(proc)
                raise subprocess.TimeoutExpired(cmd, timeout, output="\n".join(stdout_lines))

            for key, _ in selector.select(timeout=0.2):
                stream = cast(TextIO, key.fileobj)
                line = stream.readline()
                if not line:
                    continue
                stripped = line.rstrip("\n")
                stdout_lines.append(stripped)
                if log_callback:
                    log_callback(stripped)

        for line in proc.stdout:
            stripped = line.rstrip("\n")
            if stripped:
                stdout_lines.append(stripped)
                if log_callback:
                    log_callback(stripped)
    except Exception:
        terminate_process(proc)
        raise
    finally:
        selector.close()

    proc.wait(timeout=5)

    return subprocess.CompletedProcess(
        args=cmd,
        returncode=proc.returncode,
        stdout="\n".join(stdout_lines),
        stderr="",
    )


def terminate_process(proc: subprocess.Popen, timeout: float = 5.0) -> int | None:
    """Gracefully terminate a process, then kill if it doesn't exit.

    Sends SIGTERM first, waits up to *timeout* seconds, then sends
    SIGKILL if the process is still alive.

    Args:
        proc: The subprocess to terminate.
        timeout: Seconds to wait after SIGTERM before escalating to SIGKILL.

    Returns:
        The process return code, or ``None`` if it could not be collected.
    """
    if proc.poll() is not None:
        return proc.returncode

    proc.terminate()
    try:
        return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            return proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            return None
