"""Unit tests for the unified PI and user pre-task execution service."""

from types import SimpleNamespace

import pytest

import maa_worker.pretask_service as pretask_module
from maa_worker.pretask_service import PretaskError, PretaskService
from models.interface import Option, OptionCase, Pretask
from models.scheduler import PreTaskCommand


class _FakeEvents:
    def __init__(self):
        self.logs: list[str] = []
        self.notifications: list[tuple[str, str, dict]] = []

    def send_log(self, message: str) -> None:
        self.logs.append(message)

    def send_notification(self, title: str, content: str, **kwargs) -> None:
        self.notifications.append((title, content, kwargs))


class _FakeStdout:
    def __init__(self, lines=()):
        self._lines = list(lines)

    def __iter__(self):
        return iter(self._lines)


class _FakeProcess:
    def __init__(self, *, returncode=0, output=(), running=False):
        self.stdout = _FakeStdout(output)
        self.pid = 1234
        self._running = running
        self._final_returncode = returncode if returncode is not None else -15
        self.returncode = None if running else returncode
        self.terminate_calls = 0
        self.wait_calls = 0
        self.kill_calls = 0

    def poll(self):
        if self._running:
            return None
        return self.returncode

    def terminate(self):
        self.terminate_calls += 1
        self._running = False
        self.returncode = self._final_returncode

    def wait(self, timeout=None):
        self.wait_calls += 1
        return self.returncode

    def kill(self):
        self.kill_calls += 1
        self._running = False
        self.returncode = -9


class _PopenRecorder:
    def __init__(self, processes=(), error=None):
        self.calls: list[tuple[list[str] | str, dict]] = []
        self._processes = list(processes)
        self._error = error

    def __call__(self, argv_or_command, **kwargs):
        recorded_argv = (
            list(argv_or_command)
            if isinstance(argv_or_command, list)
            else argv_or_command
        )
        self.calls.append((recorded_argv, dict(kwargs)))
        if self._error is not None:
            raise self._error
        if not self._processes:
            raise AssertionError("unexpected subprocess.Popen call")
        return self._processes.pop(0)


def _make_worker(*, pretasks=(), options=None, stop_flag=False):
    return SimpleNamespace(
        interface=SimpleNamespace(pretask=list(pretasks), option=options or {}),
        task_state=SimpleNamespace(
            stop_flag=stop_flag,
            current_pre_task_process=None,
        ),
        events=_FakeEvents(),
    )


def _patch_popen(monkeypatch, recorder: _PopenRecorder) -> None:
    monkeypatch.setattr(pretask_module.subprocess, "Popen", recorder)


def test_run_all_skips_controller_and_resource_mismatches(monkeypatch):
    worker = _make_worker(
        pretasks=[
            Pretask(
                exec="allowed",
                controller=["adb"],
                resource=["main"],
            ),
            Pretask(exec="wrong-controller", controller=["win32"]),
            Pretask(exec="wrong-resource", resource=["other"]),
        ]
    )
    recorder = _PopenRecorder([_FakeProcess()])
    _patch_popen(monkeypatch, recorder)

    PretaskService(worker).run_all("adb", "main", {}, [])

    assert [call[0] for call in recorder.calls] == [["allowed"]]
    assert recorder.calls[0][1]["shell"] is False


def test_run_all_executes_pi_pretasks_before_enabled_user_commands(monkeypatch):
    worker = _make_worker(
        pretasks=[Pretask(exec="pi-first"), Pretask(exec="pi-second")]
    )
    recorder = _PopenRecorder([_FakeProcess(), _FakeProcess(), _FakeProcess()])
    _patch_popen(monkeypatch, recorder)
    user_pre_tasks = [
        PreTaskCommand(command="echo user"),
        PreTaskCommand(command="disabled", enabled=False),
        PreTaskCommand(command="   "),
    ]

    PretaskService(worker).run_all("adb", "main", {}, user_pre_tasks)

    assert [call[0] for call in recorder.calls] == [
        ["pi-first"],
        ["pi-second"],
        "echo user",
    ]
    assert [call[1]["shell"] for call in recorder.calls] == [
        False,
        False,
        True,
    ]


def test_pi_argv_preserves_args_and_appends_compact_option_json(monkeypatch):
    options = {
        "mode": Option(
            type="select",
            cases=[OptionCase(name="fast"), OptionCase(name="safe")],
        ),
        "tags": Option(
            type="checkbox",
            cases=[OptionCase(name="red"), OptionCase(name="blue")],
        ),
    }
    worker = _make_worker(
        pretasks=[
            Pretask(
                exec="pi-tool",
                args=["--flag", "value"],
                resource=["main"],
                option=["mode", "tags"],
            )
        ],
        options=options,
    )
    recorder = _PopenRecorder([_FakeProcess()])
    _patch_popen(monkeypatch, recorder)

    PretaskService(worker).run_all(
        "adb",
        "main",
        {"main": {"mode": "safe", "tags": ["red"]}},
        [],
    )

    assert recorder.calls[0][0] == [
        "pi-tool",
        "--flag",
        "value",
        '{"mode":"safe","tags":["red"]}',
    ]


def test_option_values_use_resource_task_values_and_select_checkbox_defaults(
    monkeypatch,
):
    options = {
        "mode": Option(
            type="select",
            cases=[OptionCase(name="first"), OptionCase(name="second")],
        ),
        "tags": Option(
            type="checkbox",
            cases=[OptionCase(name="one"), OptionCase(name="two")],
        ),
    }
    worker = _make_worker(
        pretasks=[
            Pretask(
                exec="resource-values",
                resource=["main", "fallback"],
                option=["mode", "tags"],
            ),
            Pretask(exec="defaults", option=["mode", "tags"]),
        ],
        options=options,
    )
    recorder = _PopenRecorder([_FakeProcess(), _FakeProcess()])
    _patch_popen(monkeypatch, recorder)

    PretaskService(worker).run_all(
        "adb",
        "main",
        {"main": {"mode": "second"}, "fallback": {"mode": "ignored"}},
        [],
    )

    assert recorder.calls[0][0][-1] == '{"mode":"second","tags":[]}'
    assert recorder.calls[1][0][-1] == '{"mode":"first","tags":[]}'


def test_nonzero_exit_raises_pretask_error_with_output(monkeypatch):
    worker = _make_worker(pretasks=[Pretask(exec="failing")])
    recorder = _PopenRecorder([_FakeProcess(returncode=7, output=["failure output\n"])])
    _patch_popen(monkeypatch, recorder)

    with pytest.raises(PretaskError) as exc_info:
        PretaskService(worker).run_all("adb", "main", {}, [])

    message = str(exc_info.value)
    assert "退出码 7" in message
    assert "failure output" in message
    assert worker.events.notifications[-1][0] == "前置程序执行失败"


def test_missing_pi_program_raises_pretask_error(monkeypatch):
    worker = _make_worker(pretasks=[Pretask(exec="missing-program")])
    recorder = _PopenRecorder(error=FileNotFoundError("not found"))
    _patch_popen(monkeypatch, recorder)

    with pytest.raises(PretaskError, match="前置任务程序未找到: missing-program"):
        PretaskService(worker).run_all("adb", "main", {}, [])

    assert len(recorder.calls) == 1
    assert worker.events.notifications[-1][0] == "前置程序执行失败"


def test_running_pi_pretask_times_out_and_is_terminated(monkeypatch):
    worker = _make_worker(pretasks=[Pretask(exec="slow")])
    process = _FakeProcess(running=True)
    recorder = _PopenRecorder([process])
    _patch_popen(monkeypatch, recorder)
    monkeypatch.setattr(pretask_module, "PI_PRETASK_TIMEOUT", 1)

    clock_values = iter((10.0, 11.1))
    monkeypatch.setattr(
        pretask_module.time,
        "monotonic",
        lambda: next(clock_values),
    )
    monkeypatch.setattr(pretask_module.time, "sleep", lambda _: None)

    with pytest.raises(PretaskError, match="前置任务执行超时（1s）: slow"):
        PretaskService(worker).run_all("adb", "main", {}, [])

    assert process.terminate_calls == 1
    assert worker.task_state.current_pre_task_process is None


def test_stop_flag_during_pretask_terminates_process_and_raises(monkeypatch):
    worker = _make_worker(pretasks=[Pretask(exec="interruptible")])
    process = _FakeProcess(running=True)
    recorder = _PopenRecorder([process])
    _patch_popen(monkeypatch, recorder)
    monkeypatch.setattr(pretask_module.time, "monotonic", lambda: 0.0)

    def stop_after_poll(_):
        worker.task_state.stop_flag = True

    monkeypatch.setattr(pretask_module.time, "sleep", stop_after_poll)

    with pytest.raises(PretaskError, match="前置任务已停止: interruptible"):
        PretaskService(worker).run_all("adb", "main", {}, [])

    assert process.terminate_calls == 1
    assert worker.task_state.current_pre_task_process is None


def test_stop_flag_before_start_raises_without_spawning_process(monkeypatch):
    worker = _make_worker(pretasks=[Pretask(exec="not-started")], stop_flag=True)
    recorder = _PopenRecorder()
    _patch_popen(monkeypatch, recorder)

    with pytest.raises(PretaskError, match="前置任务已停止: not-started"):
        PretaskService(worker).run_all("adb", "main", {}, [])

    assert recorder.calls == []
