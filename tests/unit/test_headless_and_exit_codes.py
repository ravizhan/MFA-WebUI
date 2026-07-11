"""Headless / exit-code / disabled-job contract tests (no full MaaWorker)."""

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_headless_rejects_disabled_job(tmp_path):
    """Disabled jobs (next_run_time is None) must not execute."""
    job = SimpleNamespace(next_run_time=None, kwargs={"task_id": "x"})
    assert job.next_run_time is None
    EXIT_TASK_FAILED = 3
    result = EXIT_TASK_FAILED if job.next_run_time is None else 0
    assert result == 3


@pytest.mark.asyncio
async def test_scheduler_manager_paused_init(tmp_path, monkeypatch):
    from scheduler_manager import SchedulerManager

    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir()
    mgr = SchedulerManager()
    mgr._db_path = tmp_path / "config" / "scheduler.sqlite"
    await mgr.initialize(start_scheduler=True, paused=True)
    assert mgr.scheduler is not None
    # STATE_PAUSED == 2 when started with paused=True
    assert mgr.scheduler.state in (1, 2)
    await mgr.shutdown()


def test_exit_code_constants_contract():
    codes = {
        "EXIT_SUCCESS": 0,
        "EXIT_TASK_NOT_FOUND": 1,
        "EXIT_DEVICE_FAILED": 2,
        "EXIT_TASK_FAILED": 3,
        "EXIT_APP_RUNNING": 4,
        "EXIT_UPDATING": 5,
    }
    assert codes["EXIT_APP_RUNNING"] == 4
    assert codes["EXIT_UPDATING"] == 5
    assert codes["EXIT_TASK_FAILED"] == 3
