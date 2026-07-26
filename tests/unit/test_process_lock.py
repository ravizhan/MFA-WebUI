"""Process lock unit tests: RuntimeOwnership lifecycle and Python-Go interop."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from services.process_lock import (
    AdvisoryFileLock,
    LockBusyError,
    RuntimeOwnership,
    UpdateLockBusyError,
    lock_paths,
)


def test_runtime_ownership_lock_files_survive_release(tmp_path: Path):
    ownership = RuntimeOwnership(tmp_path)
    ownership.acquire()
    try:
        runtime, update = lock_paths(tmp_path)
        assert runtime.exists()
        assert update.exists()
    finally:
        ownership.release()
    # 稳定锁文件在释放后依然存在（不删除）
    runtime, update = lock_paths(tmp_path)
    assert runtime.exists()
    assert update.exists()


def test_runtime_ownership_busy(tmp_path: Path):
    first = RuntimeOwnership(tmp_path)
    first.acquire()
    try:
        second = RuntimeOwnership(tmp_path)
        with pytest.raises(LockBusyError):
            second.acquire()
    finally:
        first.release()


def test_runtime_ownership_update_lock_busy_raises_specific_type(tmp_path: Path):
    """update 锁被占时 RuntimeOwnership.acquire 抛 UpdateLockBusyError 子类。

    这是替代 main.py 原 `"update" in str(e).lower()` 字面耦合的承重变更：
    退出码选择由该异常类型驱动。缩短超时避免 30s 阻塞（复用既有
    UPDATE_LOCK_TIMEOUT 旋钮，非依赖注入）。
    """
    _, update_path = lock_paths(tmp_path)
    holder = AdvisoryFileLock(update_path)
    holder.acquire()
    try:
        ownership = RuntimeOwnership(tmp_path)
        ownership.UPDATE_LOCK_TIMEOUT = 0.01  # 缩短超时，避免测试阻塞 30s
        with pytest.raises(UpdateLockBusyError) as excinfo:
            ownership.acquire()
        # 子类关系成立：仍是一种 LockBusyError
        assert isinstance(excinfo.value, LockBusyError)
        assert not ownership.is_acquired
    finally:
        holder.release()


def test_runtime_ownership_runtime_lock_busy_stays_plain(tmp_path: Path):
    """runtime 锁被占（update 锁空闲）时抛普通 LockBusyError，非 UpdateLockBusyError。

    这条路径对应“应用已在运行”/ 委托给运行中实例（exit 4），必须与
    UpdateLockBusyError（exit 5）严格区分。
    """
    runtime_path, _ = lock_paths(tmp_path)
    holder = AdvisoryFileLock(runtime_path)
    holder.acquire()
    try:
        ownership = RuntimeOwnership(tmp_path)
        with pytest.raises(LockBusyError) as excinfo:
            ownership.acquire()
        # 关键：不是 UpdateLockBusyError 子类
        assert not isinstance(excinfo.value, UpdateLockBusyError)
        assert not ownership.is_acquired
    finally:
        holder.release()


def test_python_go_lockhelper_interop(tmp_path: Path):
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
        import time

        deadline = time.time() + 5
        held = False
        while time.time() < deadline:
            line = hold.stdout.readline() if hold.stdout else ""
            if "held" in line.lower():
                held = True
                break
        assert held, "lockhelper did not report held"

        with pytest.raises(LockBusyError):
            AdvisoryFileLock(lock_path).acquire(timeout_seconds=None)
    finally:
        hold.terminate()
        try:
            hold.wait(timeout=5)
        except Exception:
            hold.kill()
