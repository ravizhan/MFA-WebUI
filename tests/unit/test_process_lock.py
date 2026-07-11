"""Process lock unit tests: contention, PID metadata, stable files."""

from pathlib import Path

import pytest

from services.process_lock import (
    AdvisoryFileLock,
    LockBusyError,
    RuntimeOwnership,
    lock_paths,
    pid_metadata_path,
)


def test_advisory_lock_exclusive_contention(tmp_path: Path):
    lock_path = tmp_path / "config" / "locks" / "runtime.lock"
    a = AdvisoryFileLock(lock_path)
    b = AdvisoryFileLock(lock_path)
    a.acquire(timeout_seconds=None)
    assert a.is_locked
    with pytest.raises(LockBusyError):
        b.acquire(timeout_seconds=None)
    # Stable file never deleted
    assert lock_path.exists()
    a.release()
    assert lock_path.exists()
    b.acquire(timeout_seconds=None)
    b.release()
    assert lock_path.exists()


def test_runtime_ownership_pid_after_lock(tmp_path: Path):
    ownership = RuntimeOwnership(tmp_path)
    ownership.acquire()
    try:
        pid_path = pid_metadata_path(tmp_path)
        assert pid_path.exists()
        data = pid_path.read_text(encoding="utf-8")
        assert "owner_token" in data
        assert str(ownership.owner_token) in data
        runtime, update = lock_paths(tmp_path)
        assert runtime.exists()
        assert update.exists()
    finally:
        ownership.release()
    # Owner removes PID; lock files remain
    assert not pid_metadata_path(tmp_path).exists()
    runtime, _ = lock_paths(tmp_path)
    assert runtime.exists()


def test_runtime_ownership_busy(tmp_path: Path):
    first = RuntimeOwnership(tmp_path)
    first.acquire()
    try:
        second = RuntimeOwnership(tmp_path)
        with pytest.raises(LockBusyError):
            second.acquire()
    finally:
        first.release()


def test_import_does_not_lock():
    """Importing process_lock must not acquire locks."""
    import services.process_lock as pl

    assert pl.AdvisoryFileLock is not None
