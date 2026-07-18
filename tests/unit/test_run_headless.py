"""Headless real path tests (mocked heavy deps)."""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

TID = "550e8400-e29b-41d4-a716-446655440000"


class TestRunHeadless:
    @pytest.mark.asyncio
    async def test_disabled_job_exit_code(self, main_module, tmp_path, monkeypatch):
        monkeypatch.setattr(main_module, "APP_ROOT_DIR", tmp_path)
        monkeypatch.setattr(main_module, "LOGS_DIR", tmp_path / "config" / "logs")
        (tmp_path / "config" / "logs").mkdir(parents=True)

        ownership = MagicMock()
        monkeypatch.setattr(main_module, "acquire_runtime_ownership", lambda: ownership)
        monkeypatch.setattr(main_module, "release_runtime_ownership", lambda: None)

        job = SimpleNamespace(next_run_time=None, kwargs={})
        sched = MagicMock()
        sched.get_job.return_value = job

        class SM:
            def __init__(self):
                pass

            def set_worker(self, w):
                pass

            async def initialize(self, **kw):
                self.scheduler = sched

            async def shutdown(self):
                pass

        monkeypatch.setattr(main_module, "SchedulerManager", SM)
        monkeypatch.setattr(
            main_module,
            "MaaWorker",
            lambda *a, **k: MagicMock(task_state=SimpleNamespace(last_status="failed")),
        )

        code = await main_module.run_headless(TID)
        assert code == main_module.EXIT_TASK_FAILED
        ownership.release.assert_not_called()  # release via release_runtime_ownership

    @pytest.mark.asyncio
    async def test_log_setup_failure_releases_lock(self, main_module, tmp_path, monkeypatch):
        released = {"v": False}

        class Own:
            def release(self):
                released["v"] = True

        monkeypatch.setattr(main_module, "acquire_runtime_ownership", lambda: Own())
        monkeypatch.setattr(
            main_module,
            "release_runtime_ownership",
            lambda: released.__setitem__("v", True),
        )
        # Force log dir failure by making LOGS_DIR a file
        bad = tmp_path / "notadir"
        bad.write_text("x", encoding="utf-8")
        monkeypatch.setattr(main_module, "LOGS_DIR", bad / "nested")

        code = await main_module.run_headless(TID)
        assert code == main_module.EXIT_TASK_FAILED
        assert released["v"] is True

    @pytest.mark.asyncio
    async def test_executes_exactly_once(self, main_module, tmp_path, monkeypatch):
        monkeypatch.setattr(main_module, "LOGS_DIR", tmp_path / "logs")
        (tmp_path / "logs").mkdir()
        monkeypatch.setattr(main_module, "acquire_runtime_ownership", lambda: MagicMock())
        monkeypatch.setattr(main_module, "release_runtime_ownership", lambda: None)

        calls = {"n": 0}

        async def exec_task(**kwargs):
            calls["n"] += 1

        job = SimpleNamespace(
            next_run_time=datetime.now(),
            kwargs={
                "task_id": TID,
                "task_name": "t",
                "task_description": "",
                "task_list": [],
                "task_options": {},
            },
        )
        sched = MagicMock()
        sched.get_job.return_value = job

        class SM:
            def __init__(self):
                self.scheduler = None

            def set_worker(self, w):
                self._w = w

            async def initialize(self, **kw):
                self.scheduler = sched
                assert kw.get("paused") is True

            async def shutdown(self):
                pass

        worker = MagicMock()
        worker.task_state = SimpleNamespace(last_status="success")
        monkeypatch.setattr(main_module, "SchedulerManager", SM)
        monkeypatch.setattr(main_module, "MaaWorker", lambda *a, **k: worker)

        with patch("scheduler_manager.execute_scheduled_task", exec_task):
            code = await main_module.run_headless(TID)
        assert code == main_module.EXIT_SUCCESS
        assert calls["n"] == 1
