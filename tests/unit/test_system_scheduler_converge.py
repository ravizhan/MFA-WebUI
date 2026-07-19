"""Unit tests for SystemScheduler.converge / register with FakeBackend."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pytest

from models.scheduler import CronTriggerConfig, DateTriggerConfig, ScheduledTask
from services.native_cron import NativeCron
from services.system_scheduler import ConvergeReport, SystemScheduler
from services.system_scheduler_backend import NativeTaskSpec, SystemSchedulerBackend


# ---------------------------------------------------------------------------
# FakeBackend
# ---------------------------------------------------------------------------


@dataclass
class FakeBackend(SystemSchedulerBackend):
    """In-memory registry; inject verify failures / register exceptions."""

    registry: dict[str, NativeTaskSpec] = field(default_factory=dict)
    verify_fail_ids: set[str] = field(default_factory=set)
    register_error_ids: dict[str, Exception] = field(default_factory=dict)
    unregister_error_ids: dict[str, Exception] = field(default_factory=dict)
    register_calls: list[str] = field(default_factory=list)
    unregister_calls: list[str] = field(default_factory=list)

    @property
    def platform_name(self) -> str:
        return "fake"

    def build_identifier(self, task_id: str) -> str:
        return f"fake:{task_id}"

    def register(self, spec: NativeTaskSpec) -> None:
        self.register_calls.append(spec.task_id)
        err = self.register_error_ids.get(spec.task_id)
        if err is not None:
            raise err
        self.registry[spec.task_id] = spec
        # successful re-register clears sticky verify fail unless re-set by test
        self.verify_fail_ids.discard(spec.task_id)

    def unregister(self, task_id: str) -> None:
        self.unregister_calls.append(task_id)
        err = self.unregister_error_ids.get(task_id)
        if err is not None:
            raise err
        self.registry.pop(task_id, None)

    def is_registered(self, task_id: str) -> bool:
        return task_id in self.registry

    def verify_registration(self, spec: NativeTaskSpec) -> tuple[bool, str]:
        if spec.task_id not in self.registry:
            return False, "not registered"
        if spec.task_id in self.verify_fail_ids:
            return False, "injected verify failure"
        stored = self.registry[spec.task_id]
        if stored.cron != spec.cron or stored.exe_path != spec.exe_path:
            return False, "spec drift"
        return True, "ok"

    def list_registered_task_ids(self) -> list[str]:
        return list(self.registry.keys())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_UUID_A = "11111111-1111-1111-1111-111111111111"
_UUID_B = "22222222-2222-2222-2222-222222222222"
_UUID_C = "33333333-3333-3333-3333-333333333333"
_UUID_ORPHAN = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


def _task(
    task_id: str,
    *,
    cron: str = "0 9 * * *",
    name: str | None = None,
    wakeup_enabled: bool = True,
) -> ScheduledTask:
    return ScheduledTask(
        id=task_id,
        name=name or f"task-{task_id[:8]}",
        enabled=True,
        trigger_config=CronTriggerConfig(cron=cron),
        wakeup_enabled=wakeup_enabled,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )


def _seed_registry(backend: FakeBackend, *task_ids: str, cron: str = "0 9 * * *") -> None:
    from services.native_cron import parse_native_cron

    for tid in task_ids:
        backend.registry[tid] = NativeTaskSpec(
            task_id=tid,
            task_name=f"seed-{tid[:8]}",
            exe_path="/fake/exe",
            cli_args=["--scheduled-task", tid],
            cron=parse_native_cron(cron),
            working_dir="/fake",
        )


@pytest.fixture
def app_root(tmp_path: Path) -> Path:
    return tmp_path


# ---------------------------------------------------------------------------
# converge
# ---------------------------------------------------------------------------


def test_converge_unregisters_orphans(app_root: Path):
    backend = FakeBackend()
    _seed_registry(backend, _UUID_ORPHAN)
    sched = SystemScheduler(app_root, backend=backend)

    report = sched.converge([])

    assert report.unregistered == [_UUID_ORPHAN]
    assert report.registered == []
    assert report.failed == []
    assert _UUID_ORPHAN not in backend.registry
    assert backend.unregister_calls == [_UUID_ORPHAN]


def test_converge_registers_missing(app_root: Path):
    backend = FakeBackend()
    sched = SystemScheduler(app_root, backend=backend)
    desired = [_task(_UUID_A)]

    report = sched.converge(desired)

    assert report.registered == [_UUID_A]
    assert report.unregistered == []
    assert report.failed == []
    assert backend.is_registered(_UUID_A)
    assert _UUID_A in backend.register_calls


def test_converge_noop_when_registered_and_verified(app_root: Path):
    backend = FakeBackend()
    # Pre-seed with the same cron; register() will rebuild spec from task.
    # First register via real path so registry matches build_native_command paths.
    sched = SystemScheduler(app_root, backend=backend)
    task = _task(_UUID_A)
    sched.register(task)
    backend.register_calls.clear()

    report = sched.converge([task])

    assert report.registered == []
    assert report.unregistered == []
    assert report.failed == []
    assert backend.register_calls == []  # noop — no re-register


def test_converge_reregisters_when_verify_fails(app_root: Path):
    backend = FakeBackend()
    sched = SystemScheduler(app_root, backend=backend)
    task = _task(_UUID_A)
    sched.register(task)
    backend.register_calls.clear()
    backend.verify_fail_ids.add(_UUID_A)

    report = sched.converge([task])

    assert report.registered == [_UUID_A]
    assert report.failed == []
    assert backend.register_calls == [_UUID_A]
    # after re-register, verify_fail cleared by FakeBackend.register
    ok, _ = backend.verify_registration(backend.registry[_UUID_A])
    assert ok


def test_converge_register_exception_collected(app_root: Path):
    backend = FakeBackend()
    backend.register_error_ids[_UUID_A] = RuntimeError("boom")
    sched = SystemScheduler(app_root, backend=backend)

    report = sched.converge([_task(_UUID_A), _task(_UUID_B)])

    assert _UUID_A in {t for t, _ in report.failed}
    assert any("boom" in msg for _, msg in report.failed)
    assert _UUID_B in report.registered
    assert _UUID_B in backend.registry
    assert _UUID_A not in backend.registry


def test_converge_mixed_scenario(app_root: Path):
    """Orphan removed, missing registered, verified noop, verify-fail re-registered, error collected."""
    backend = FakeBackend()
    sched = SystemScheduler(app_root, backend=backend)

    # A: already registered & will verify ok
    task_a = _task(_UUID_A, cron="0 9 * * *")
    sched.register(task_a)

    # B: already registered but verify will fail → re-register
    task_b = _task(_UUID_B, cron="30 8 * * *")
    sched.register(task_b)
    backend.verify_fail_ids.add(_UUID_B)

    # C: not registered, register will fail
    task_c = _task(_UUID_C, cron="0 12 * * 1")
    backend.register_error_ids[_UUID_C] = RuntimeError("c-fail")

    # Orphan in OS but not desired
    _seed_registry(backend, _UUID_ORPHAN)

    backend.register_calls.clear()
    backend.unregister_calls.clear()

    report = sched.converge([task_a, task_b, task_c])

    assert _UUID_A not in report.registered  # noop
    assert _UUID_B in report.registered
    assert _UUID_C not in report.registered
    assert _UUID_ORPHAN in report.unregistered
    failed_ids = {tid for tid, _ in report.failed}
    assert _UUID_C in failed_ids
    assert _UUID_A in backend.registry
    assert _UUID_B in backend.registry
    assert _UUID_C not in backend.registry
    assert _UUID_ORPHAN not in backend.registry


# ---------------------------------------------------------------------------
# register() direct
# ---------------------------------------------------------------------------


def test_register_parse_failure_raises_value_error(app_root: Path):
    backend = FakeBackend()
    sched = SystemScheduler(app_root, backend=backend)
    task = _task(_UUID_A, cron="*/5 * * * *")  # rejected by parse_native_cron

    with pytest.raises(ValueError):
        sched.register(task)

    assert backend.register_calls == []


def test_register_non_cron_raises_value_error(app_root: Path):
    backend = FakeBackend()
    sched = SystemScheduler(app_root, backend=backend)
    task = ScheduledTask(
        id=_UUID_A,
        name="date-task",
        enabled=True,
        trigger_config=DateTriggerConfig(run_date=datetime(2030, 1, 1, 9, 0)),
        wakeup_enabled=True,
        created_at=datetime(2026, 1, 1),
        updated_at=datetime(2026, 1, 1),
    )

    with pytest.raises(ValueError, match="cron"):
        sched.register(task)


def test_register_verify_failure_raises_runtime_error(app_root: Path):
    backend = FakeBackend()
    # After register, force verify to fail by keeping id in verify_fail_ids
    # FakeBackend.register discards verify_fail — so inject via subclass:

    class AlwaysFailVerify(FakeBackend):
        def verify_registration(self, spec: NativeTaskSpec) -> tuple[bool, str]:
            return False, "always fail"

    backend = AlwaysFailVerify()
    sched = SystemScheduler(app_root, backend=backend)

    with pytest.raises(RuntimeError, match="verify failed"):
        sched.register(_task(_UUID_A))


def test_unregister_idempotent(app_root: Path):
    backend = FakeBackend()
    sched = SystemScheduler(app_root, backend=backend)
    sched.unregister(_UUID_A)  # not present — no error
    assert backend.unregister_calls == [_UUID_A]


def test_converge_report_type(app_root: Path):
    backend = FakeBackend()
    sched = SystemScheduler(app_root, backend=backend)
    report = sched.converge([])
    assert isinstance(report, ConvergeReport)
    assert report.registered == []
    assert report.unregistered == []
    assert report.failed == []
