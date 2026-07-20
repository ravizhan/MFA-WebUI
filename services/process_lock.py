"""跨进程内核级建议锁：协调 MWU 运行时与更新器。

规范路径（相对应用根）：
  config/locks/runtime.lock
  config/locks/update.lock

协议要点：解锁不删稳定锁文件；有界等待靠非阻塞重试；
PID 元数据仅诊断用途，获 runtime 锁后写入，仅由持有者清理。
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path

import filelock as _filelock


class LockError(Exception):
    """锁失败基类（权限/协议）；失败即关闭，不继续启动。"""


class LockBusyError(LockError):
    """排他锁被其他进程持有。"""


class LockPermissionError(LockError):
    """无法打开或加锁（权限不足）。"""


def lock_paths(app_root: Path) -> tuple[Path, Path]:
    """返回 (runtime_lock_path, update_lock_path)。"""
    locks_dir = Path(app_root) / "config" / "locks"
    return locks_dir / "runtime.lock", locks_dir / "update.lock"


def pid_metadata_path(app_root: Path) -> Path:
    return Path(app_root) / "config" / "mwu.pid"


class AdvisoryFileLock:
    """
    进程持有的 1 字节排他建议锁（filelock.FileLock 薄封装）。
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        # preserve_lock_file 必须为 True：默认释放会删文件，破坏稳定锁协议
        self._fl = _filelock.FileLock(
            str(self.path),
            timeout=0,
            poll_interval=0.05,
            preserve_lock_file=True,
        )
        self._locked = False

    @property
    def is_locked(self) -> bool:
        return self._locked

    def acquire(
        self,
        *,
        timeout_seconds: float | None = None,
        poll_interval: float = 0.05,
    ) -> None:
        """获取排他锁。

        timeout_seconds: None/≤0 为非阻塞单次；>0 则在超时前轮询重试。
        """
        if self._locked:
            return

        # filelock 不会自动创建父目录
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # MWU 超时语义 → filelock：None/≤0 非阻塞；>0 最长阻塞 N 秒
        if timeout_seconds is None or timeout_seconds <= 0:
            fl_timeout = 0
        else:
            fl_timeout = float(timeout_seconds)

        try:
            self._fl.acquire(timeout=fl_timeout, poll_interval=poll_interval)
        except _filelock.Timeout as e:
            raise LockBusyError(f"Lock busy: {self.path}") from e
        except PermissionError as e:
            raise LockPermissionError(str(e)) from e
        except OSError as e:
            raise LockError(str(e)) from e
        self._locked = True

    def release(self) -> None:
        if not self._locked:
            self._fl.release()  # 幂等释放
            return
        try:
            self._fl.release()
        finally:
            self._locked = False
            # 稳定锁文件永不删除（preserve_lock_file=True）

    def __enter__(self) -> "AdvisoryFileLock":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


class RuntimeOwnership:
    """进程生命周期内的 runtime 所有权（规范启动序列）。

    顺序：有界等待 update 锁并释放 → 非阻塞抢 runtime 锁 →
    再次检查 update 锁 → 写 PID 元数据。权限/协议错误 fail-closed。
    """

    UPDATE_LOCK_TIMEOUT = 30.0

    def __init__(self, app_root: Path):
        self.app_root = Path(app_root)
        runtime_path, update_path = lock_paths(self.app_root)
        self.runtime_lock = AdvisoryFileLock(runtime_path)
        self.update_lock = AdvisoryFileLock(update_path)
        self.owner_token = str(uuid.uuid4())
        self._pid_path = pid_metadata_path(self.app_root)
        self._acquired = False

    @property
    def is_acquired(self) -> bool:
        return self._acquired

    def acquire(self) -> None:
        if self._acquired:
            return
        # 1. 等待并释放 update 锁（与更新器交接协调）
        self._with_update_lock()
        # 2. 非阻塞独占 runtime 锁
        try:
            self.runtime_lock.acquire(timeout_seconds=None)
        except LockBusyError:
            raise LockBusyError("Another MWU instance holds the runtime lock") from None
        except Exception:
            self.runtime_lock.release()
            raise
        try:
            # 3. 再次确认 update 锁空闲
            self._with_update_lock()
            # 4. 拥有权确立后再写诊断用 PID 元数据
            self._write_pid_metadata()
            self._acquired = True
        except Exception:
            self._remove_pid_metadata()
            self.runtime_lock.release()
            raise

    def release(self) -> None:
        if not self._acquired and not self.runtime_lock.is_locked:
            return
        self._remove_pid_metadata()
        self.runtime_lock.release()
        self._acquired = False

    def __enter__(self) -> "RuntimeOwnership":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()

    def _with_update_lock(self) -> None:
        try:
            self.update_lock.acquire(timeout_seconds=self.UPDATE_LOCK_TIMEOUT)
        except LockBusyError as e:
            raise LockBusyError("Update lock held too long; aborting startup") from e
        except LockPermissionError:
            raise
        finally:
            if self.update_lock.is_locked:
                self.update_lock.release()

    def _write_pid_metadata(self) -> None:
        self._pid_path.parent.mkdir(parents=True, exist_ok=True)
        from datetime import datetime, timezone

        data = {
            "pid": os.getpid(),
            "owner_token": self.owner_token,
            "started_at": datetime.now(timezone.utc).isoformat(),
        }
        tmp = self._pid_path.with_suffix(".pid.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self._pid_path)

    def _remove_pid_metadata(self) -> None:
        try:
            if not self._pid_path.exists():
                return
            data = json.loads(self._pid_path.read_text(encoding="utf-8"))
            if data.get("owner_token") == self.owner_token:
                self._pid_path.unlink(missing_ok=True)
        except OSError:
            pass
