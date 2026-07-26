"""跨进程内核级建议锁：协调 MWU 运行时与更新器。

规范路径（相对应用根）：
  config/locks/runtime.lock
  config/locks/update.lock

协议要点：解锁不删稳定锁文件；有界等待靠非阻塞重试。
"""

from __future__ import annotations

from pathlib import Path

import filelock as _filelock


class LockError(Exception):
    """锁失败基类（权限/协议）；失败即关闭，不继续启动。"""


class LockBusyError(LockError):
    """排他锁被其他进程持有。"""


class UpdateLockBusyError(LockBusyError):
    """更新锁超时被占（更新器正在运行）。

    与普通 LockBusyError 区分，使启动入口按类型选择退出码，
    而非解析异常消息文本（原先 `"update" in str(e).lower()` 的字面耦合）。
    """


class LockPermissionError(LockError):
    """无法打开或加锁（权限不足）。"""


def lock_paths(app_root: Path) -> tuple[Path, Path]:
    """返回 (runtime_lock_path, update_lock_path)。"""
    locks_dir = Path(app_root) / "config" / "locks"
    return locks_dir / "runtime.lock", locks_dir / "update.lock"


class AdvisoryFileLock:
    """
    进程持有的 1 字节排他建议锁（filelock.FileLock 薄封装）。
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        # preserve_lock_file=True：默认释放会删文件，破坏稳定锁协议。
        # thread_local=False：获取与释放可能跨线程（事件循环线程获取，信号
        #   handler / atexit / run_in_executor / MAA worker 线程释放）；
        #   默认 True 时 fd 与锁计数挂在 threading.local()，跨线程释放为
        #   静默 no-op，runtime.lock 永不放，导致下次启动 exit 4
        #   "应用已在运行"。
        # fallback_to_soft=False：默认 True，遇到返回 ENOSYS 的文件系统会
        #   静默降级为基于文件存在的 SoftFileLock，Go 更新器的 gofrs/flock
        #   无法感知，跨语言互锁会静默失效；置 False 使其 fail-closed。
        self._fl = _filelock.FileLock(
            str(self.path),
            timeout=0,
            poll_interval=0.05,
            preserve_lock_file=True,
            thread_local=False,
            fallback_to_soft=False,
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
            return
        try:
            self._fl.release()
        finally:
            self._locked = False
            # 稳定锁文件永不删除（preserve_lock_file=True）


class RuntimeOwnership:
    """进程生命周期内的 runtime 所有权（规范启动序列）。

    顺序：有界等待 update 锁并释放 → 非阻塞抢 runtime 锁。
    权限/协议错误 fail-closed。
    """

    UPDATE_LOCK_TIMEOUT = 30.0

    def __init__(self, app_root: Path):
        self.app_root = Path(app_root)
        runtime_path, update_path = lock_paths(self.app_root)
        self.runtime_lock = AdvisoryFileLock(runtime_path)
        self.update_lock = AdvisoryFileLock(update_path)
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
        self._acquired = True

    def release(self) -> None:
        if not self._acquired and not self.runtime_lock.is_locked:
            return
        self.runtime_lock.release()
        self._acquired = False

    def _with_update_lock(self) -> None:
        try:
            self.update_lock.acquire(timeout_seconds=self.UPDATE_LOCK_TIMEOUT)
        except LockBusyError as e:
            # 用子类标记“update 锁超时”，使 main.py 按类型分流退出码，
            # 不再解析异常文本
            raise UpdateLockBusyError(
                "Update lock held too long; aborting startup"
            ) from e
        except LockPermissionError:
            raise
        finally:
            if self.update_lock.is_locked:
                self.update_lock.release()
