"""Process lock unit tests: contention, PID metadata, stable files."""

import shutil
import subprocess
import sys
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


# ---------------------------------------------------------------------------
# Process lock cross-process + Go interop
# ---------------------------------------------------------------------------


class TestProcessLockCrossProcess:
    def test_cross_process_python_contention(self, tmp_path: Path):
        lock_path = tmp_path / "config" / "locks" / "runtime.lock"
        lock_path.parent.mkdir(parents=True)
        holder = AdvisoryFileLock(lock_path)
        holder.acquire()
        try:
            code = (
                "from services.process_lock import AdvisoryFileLock, LockBusyError\n"
                f"p = r'''{lock_path}'''\n"
                "try:\n"
                "    AdvisoryFileLock(p).acquire(timeout_seconds=None)\n"
                "    print('ACQUIRED')\n"
                "except LockBusyError:\n"
                "    print('BUSY')\n"
            )
            proc = subprocess.run(
                [sys.executable, "-c", code],
                capture_output=True,
                text=True,
                cwd=str(Path(__file__).resolve().parents[2]),
                timeout=15,
            )
            assert "BUSY" in proc.stdout
        finally:
            holder.release()

    def test_python_go_lockhelper_interop(self, tmp_path: Path):
        """Build lockhelper from source into temp binary; test both directions."""
        root = Path(__file__).resolve().parents[2]
        go = shutil.which("go")
        if not go:
            pytest.skip("Go toolchain unavailable; cannot build lockhelper")

        helper_dir = tmp_path / "lockhelper_build"
        helper_dir.mkdir()
        helper = helper_dir / (
            "lockhelper.exe" if sys.platform == "win32" else "lockhelper"
        )
        build = subprocess.run(
            [go, "build", "-o", str(helper), "./cmd/lockhelper"],
            cwd=str(root / "updater"),
            capture_output=True,
            text=True,
            timeout=120,
        )
        if build.returncode != 0:
            pytest.skip(f"go build lockhelper failed: {build.stderr}")

        lock_path = tmp_path / "config" / "locks" / "runtime.lock"
        lock_path.parent.mkdir(parents=True)

        # Direction 1: Python holds, Go tries
        plock = AdvisoryFileLock(lock_path)
        plock.acquire()
        try:
            proc = subprocess.run(
                [str(helper), "try", "-path", str(lock_path)],
                capture_output=True,
                text=True,
                timeout=15,
            )
            assert proc.returncode == 2
            assert "busy" in proc.stdout.lower()
        finally:
            plock.release()

        # Direction 2: Go holds, Python tries
        hold = subprocess.Popen(
            [str(helper), "hold", "-path", str(lock_path), "-seconds", "5"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            # wait until held
            import time

            deadline = time.time() + 5
            held = False
            while time.time() < deadline:
                line = hold.stdout.readline() if hold.stdout else ""
                if "held" in line.lower():
                    held = True
                    break
            assert held, "lockhelper did not report held"
            from services.process_lock import LockBusyError

            with pytest.raises(LockBusyError):
                AdvisoryFileLock(lock_path).acquire(timeout_seconds=None)
        finally:
            hold.terminate()
            try:
                hold.wait(timeout=5)
            except Exception:
                hold.kill()
