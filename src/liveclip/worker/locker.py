"""基于文件的运行锁机制（防止同一 run 被重复执行）。"""

from __future__ import annotations

import os
import time
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)


class RunLocker:
    """基于文件的运行锁，防止同一 run 被多个 worker 同时执行。

    锁文件存储在 *lock_dir* 下，文件名为 ``run_{run_id}.lock``，
    内容为 ``{pid},{timestamp}`` 格式。

    Args:
        lock_dir: 锁文件存放目录，默认 ``data/.locks``。
    """

    def __init__(self, lock_dir: Path | None = None) -> None:
        self._lock_dir = lock_dir or Path("data/.locks")
        self._lock_dir.mkdir(parents=True, exist_ok=True)

    def _lock_path(self, run_id: int) -> Path:
        """返回指定 run_id 的锁文件路径。"""
        return self._lock_dir / f"run_{run_id}.lock"

    def acquire(self, run_id: int) -> bool:
        """尝试获取锁，成功返回 True。

        使用原子性文件创建（``O_EXCL``）确保竞态安全。

        Args:
            run_id: 运行 ID。

        Returns:
            是否成功获取锁。
        """
        lock_path = self._lock_path(run_id)
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o644)
        except FileExistsError:
            logger.debug("lock_already_held", run_id=run_id)
            return False
        except OSError as exc:
            logger.warning("lock_acquire_error", run_id=run_id, error=str(exc))
            return False

        content = f"{os.getpid()},{time.time()}"
        os.write(fd, content.encode())
        os.close(fd)
        logger.debug("lock_acquired", run_id=run_id, pid=os.getpid())
        return True

    def release(self, run_id: int) -> None:
        """释放锁。

        Args:
            run_id: 运行 ID。
        """
        lock_path = self._lock_path(run_id)
        try:
            lock_path.unlink()
            logger.debug("lock_released", run_id=run_id)
        except FileNotFoundError:
            logger.debug("lock_already_released", run_id=run_id)

    def is_locked(self, run_id: int) -> bool:
        """检查指定 run 是否已被锁定。

        Args:
            run_id: 运行 ID。

        Returns:
            是否处于锁定状态。
        """
        return self._lock_path(run_id).exists()

    def cleanup_stale(self, max_age_seconds: int = 3600) -> None:
        """清理超时的陈旧锁文件。

        遍历锁目录下所有 ``.lock`` 文件，若文件修改时间超过
        *max_age_seconds* 则删除。

        Args:
            max_age_seconds: 最大允许的锁文件年龄（秒），默认 3600。
        """
        now = time.time()
        cleaned = 0
        for lock_path in self._lock_dir.glob("run_*.lock"):
            try:
                mtime = lock_path.stat().st_mtime
                if now - mtime > max_age_seconds:
                    lock_path.unlink()
                    cleaned += 1
                    logger.info(
                        "stale_lock_removed",
                        lock_file=lock_path.name,
                        age_seconds=int(now - mtime),
                    )
            except FileNotFoundError:
                pass
            except OSError as exc:
                logger.warning(
                    "stale_lock_cleanup_error",
                    lock_file=lock_path.name,
                    error=str(exc),
                )
        if cleaned:
            logger.info("stale_locks_cleaned", count=cleaned)
