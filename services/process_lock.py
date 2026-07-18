"""Cross-platform kernel advisory locks for MWU runtime/update coordination.

Canonical paths (app-root relative):
  config/locks/runtime.lock
  config/locks/update.lock

Protocol (normative):
  - Stable lock files are never deleted on unlock.
  - POSIX: fcntl.flock whole-file exclusive, mode 0666.
  - Windows: CreateFileW + LockFileEx/UnlockFileEx on offset 0 length 1 with
    GENERIC_READ|GENERIC_WRITE and FILE_SHARE_READ|WRITE|DELETE, OPEN_ALWAYS.
  - Bounded waits use nonblocking retries.
  - PID metadata is diagnostic only, written after runtime lock acquisition
    with an owner token, and removed only by that owner.
"""

from __future__ import annotations

import json
import errno
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Optional

# Windows constants (win32)
_GENERIC_READ = 0x80000000
_GENERIC_WRITE = 0x40000000
_FILE_SHARE_READ = 0x00000001
_FILE_SHARE_WRITE = 0x00000002
_FILE_SHARE_DELETE = 0x00000004
_OPEN_ALWAYS = 4
_FILE_ATTRIBUTE_NORMAL = 0x80
_LOCKFILE_EXCLUSIVE_LOCK = 0x00000002
_LOCKFILE_FAIL_IMMEDIATELY = 0x00000001
_INVALID_HANDLE_VALUE = -1


class LockError(Exception):
    """Base lock failure (permission/protocol). Fail closed."""


class LockBusyError(LockError):
    """Exclusive lock held by another process."""


class LockPermissionError(LockError):
    """Cannot open or lock the file due to permissions."""


def lock_paths(app_root: Path) -> tuple[Path, Path]:
    """Return (runtime_lock_path, update_lock_path)."""
    locks_dir = Path(app_root) / "config" / "locks"
    return locks_dir / "runtime.lock", locks_dir / "update.lock"


def pid_metadata_path(app_root: Path) -> Path:
    return Path(app_root) / "config" / "mwu.pid"


class AdvisoryFileLock:
    """One-byte exclusive advisory lock owned by a process handle/fd."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._handle = None  # Windows HANDLE or POSIX int fd
        self._locked = False

    @property
    def is_locked(self) -> bool:
        return self._locked

    def acquire(
        self,
        *,
        timeout_seconds: Optional[float] = None,
        poll_interval: float = 0.05,
    ) -> None:
        """Acquire exclusive lock.

        Args:
            timeout_seconds: None means try once (nonblocking). 0 same as None.
                Positive value retries until timeout then raises LockBusyError.
            poll_interval: sleep between nonblocking attempts.
        """
        if self._locked:
            return

        self._ensure_parent()
        deadline = None
        if timeout_seconds is not None and timeout_seconds > 0:
            deadline = time.monotonic() + timeout_seconds

        while True:
            try:
                self._open_handle()
                if self._try_lock():
                    self._locked = True
                    return
                self._close_handle()
            except LockPermissionError:
                self._close_handle()
                raise
            except LockError:
                self._close_handle()
                raise

            if deadline is None or time.monotonic() >= deadline:
                raise LockBusyError(f"Lock busy: {self.path}")
            time.sleep(poll_interval)

    def release(self) -> None:
        if not self._locked:
            self._close_handle()
            return
        try:
            self._unlock()
        finally:
            self._locked = False
            self._close_handle()
            # Stable lock files are never deleted.

    def __enter__(self) -> "AdvisoryFileLock":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()

    def _ensure_parent(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _open_handle(self) -> None:
        if self._handle is not None:
            return
        if sys.platform == "win32":
            self._open_windows()
        else:
            self._open_posix()

    def _close_handle(self) -> None:
        if self._handle is None:
            return
        if sys.platform == "win32":
            import ctypes

            ctypes.windll.kernel32.CloseHandle(self._handle)
        else:
            try:
                os.close(self._handle)
            except OSError:
                pass
        self._handle = None

    def _try_lock(self) -> bool:
        if sys.platform == "win32":
            return self._try_lock_windows()
        return self._try_lock_posix()

    def _unlock(self) -> None:
        if sys.platform == "win32":
            self._unlock_windows()
        else:
            self._unlock_posix()

    # --- POSIX ---

    def _open_posix(self) -> None:
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_CLOEXEC", 0)
        try:
            fd = os.open(str(self.path), flags, 0o666)
        except PermissionError as e:
            raise LockPermissionError(str(e)) from e
        except OSError as e:
            raise LockError(str(e)) from e
        self._handle = fd

    def _try_lock_posix(self) -> bool:
        import fcntl  # type: ignore[import-not-found]

        flock = getattr(fcntl, "flock")
        lock_ex = getattr(fcntl, "LOCK_EX")
        lock_nb = getattr(fcntl, "LOCK_NB")
        try:
            flock(self._handle, lock_ex | lock_nb)
            return True
        except BlockingIOError:
            return False
        except OSError as e:
            if e.errno in (errno.EAGAIN, errno.EWOULDBLOCK):
                return False
            if e.errno in (errno.EACCES, errno.EPERM):
                raise LockPermissionError(str(e)) from e
            raise LockError(str(e)) from e

    def _unlock_posix(self) -> None:
        import fcntl  # type: ignore[import-not-found]

        flock = getattr(fcntl, "flock")
        lock_un = getattr(fcntl, "LOCK_UN")
        try:
            flock(self._handle, lock_un)
        except OSError:
            pass

    # --- Windows ---

    def _open_windows(self) -> None:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.CreateFileW.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        kernel32.CreateFileW.restype = wintypes.HANDLE

        handle = kernel32.CreateFileW(
            str(self.path),
            _GENERIC_READ | _GENERIC_WRITE,
            _FILE_SHARE_READ | _FILE_SHARE_WRITE | _FILE_SHARE_DELETE,
            None,
            _OPEN_ALWAYS,
            _FILE_ATTRIBUTE_NORMAL,
            None,
        )
        if (
            handle == wintypes.HANDLE(_INVALID_HANDLE_VALUE).value
            or handle == _INVALID_HANDLE_VALUE
        ):
            err = ctypes.get_last_error()
            raise LockPermissionError(
                f"CreateFileW failed for {self.path}: error {err}"
            )
        self._handle = handle

    def _try_lock_windows(self) -> bool:
        import ctypes
        from ctypes import wintypes

        class OVERLAPPED(ctypes.Structure):
            _fields_ = [
                ("Internal", ctypes.c_ulonglong),
                ("InternalHigh", ctypes.c_ulonglong),
                ("Offset", wintypes.DWORD),
                ("OffsetHigh", wintypes.DWORD),
                ("hEvent", wintypes.HANDLE),
            ]

        kernel32 = ctypes.windll.kernel32
        ov = OVERLAPPED()
        ov.Offset = 0
        ov.OffsetHigh = 0
        ov.hEvent = None

        # Lock exactly 1 byte at offset 0
        ok = kernel32.LockFileEx(
            self._handle,
            _LOCKFILE_EXCLUSIVE_LOCK | _LOCKFILE_FAIL_IMMEDIATELY,
            0,
            1,  # nNumberOfBytesToLockLow
            0,  # nNumberOfBytesToLockHigh
            ctypes.byref(ov),
        )
        if ok:
            return True
        err = ctypes.GetLastError()
        # ERROR_LOCK_VIOLATION=33, ERROR_IO_PENDING=997, ERROR_LOCK_FAILED=167
        if err in (33, 167, 997):
            return False
        if err in (5,):  # ACCESS_DENIED
            raise LockPermissionError(f"LockFileEx access denied: {self.path}")
        return False

    def _unlock_windows(self) -> None:
        import ctypes
        from ctypes import wintypes

        class OVERLAPPED(ctypes.Structure):
            _fields_ = [
                ("Internal", ctypes.c_ulonglong),
                ("InternalHigh", ctypes.c_ulonglong),
                ("Offset", wintypes.DWORD),
                ("OffsetHigh", wintypes.DWORD),
                ("hEvent", wintypes.HANDLE),
            ]

        kernel32 = ctypes.windll.kernel32
        ov = OVERLAPPED()
        ov.Offset = 0
        ov.OffsetHigh = 0
        ov.hEvent = None
        kernel32.UnlockFileEx(self._handle, 0, 1, 0, ctypes.byref(ov))


class RuntimeOwnership:
    """Process-lifetime runtime ownership following the normative lock protocol.

    Startup sequence:
      1. acquire/release update.lock with bounded 30s retry
      2. acquire runtime.lock exclusively (nonblocking → busy = already running)
      3. re-acquire/release update.lock with same 30s retry
      4. write PID metadata with owner token

    On permission/protocol errors: fail closed and release runtime.lock.
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
        # 1. Wait for update lock, then release (updater handoff coordination)
        self._with_update_lock()
        # 2. Acquire runtime lock exclusively without waiting
        try:
            self.runtime_lock.acquire(timeout_seconds=None)
        except LockBusyError:
            raise LockBusyError("Another MWU instance holds the runtime lock") from None
        except Exception:
            self.runtime_lock.release()
            raise
        try:
            # 3. Recheck update lock
            self._with_update_lock()
            # 4. Diagnostic PID metadata only after ownership
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
            try:
                data = json.loads(self._pid_path.read_text(encoding="utf-8"))
            except Exception:
                # Legacy plain-PID file: only remove if we own runtime lock
                if self.runtime_lock.is_locked:
                    self._pid_path.unlink(missing_ok=True)
                return
            if data.get("owner_token") == self.owner_token:
                self._pid_path.unlink(missing_ok=True)
        except OSError:
            pass
