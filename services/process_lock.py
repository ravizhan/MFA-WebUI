"""Cross-platform kernel advisory locks for MWU runtime/update coordination.

Thin facade over filelock (PyPI: filelock, by tox-dev). Kernel primitives match
the Go updater's gofrs/flock (Phase 2 interop):
  - Unix: fcntl.flock(fd, LOCK_EX|LOCK_NB)
  - Windows: LockFileEx 1-byte region at offset 0

Canonical paths (app-root relative):
  config/locks/runtime.lock
  config/locks/update.lock

Protocol (normative):
  - Stable lock files are never deleted on unlock (preserve_lock_file=True).
  - Bounded waits use nonblocking retries (filelock poll).
  - PID metadata is diagnostic only, written after runtime lock acquisition
    with an owner token, and removed only by that owner.

Note: filelock may truncate the lock file to 0 bytes after acquire. MWU never
writes content into lock files, so this is a behavioral no-op.
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Optional

import filelock as _filelock


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
    """One-byte exclusive advisory lock owned by a process handle/fd.

    Thin facade over filelock.FileLock. Kernel primitives (flock on Unix,
    LockFileEx 1-byte region at offset 0 on Windows) match MWU's Go updater's
    gofrs/flock, preserving cross-language interop (Phase 2 hardening).
    """

    def __init__(self, path: Path):
        self.path = Path(path)
        # preserve_lock_file=True is CRITICAL: default filelock deletes the file
        # on release, which would break the stable lock files protocol.
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

        # filelock does NOT create parent dirs by default
        self.path.parent.mkdir(parents=True, exist_ok=True)

        # Map MWU timeout semantics → filelock:
        #   None / <=0 → non-blocking one-shot (filelock timeout=0)
        #   >0         → block up to N seconds
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
            self._fl.release()  # idempotent, safe
            return
        try:
            self._fl.release()
        finally:
            self._locked = False
            # Stable lock files are NEVER deleted (preserve_lock_file=True).

    def __enter__(self) -> "AdvisoryFileLock":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()


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
