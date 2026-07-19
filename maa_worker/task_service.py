import copy
import subprocess
import sys
import threading
import time
import traceback
from typing import TYPE_CHECKING

from models.scheduler import PreTaskCommand, TaskOptionValue, TaskOptionsByTask

if TYPE_CHECKING:
    from maa_utils import MaaWorker


class TaskService:
    def __init__(self, worker: "MaaWorker"):
        self.worker = worker

    def _get_task_definition(self, task_entry: str):
        return next(
            (
                task
                for task in self.worker.interface.task or []
                if task.entry == task_entry
            ),
            None,
        )

    def _is_task_compatible(
        self,
        task_definition,
        controller_names: set[str],
        resource_name: str | None,
    ) -> tuple[bool, str]:
        if task_definition is None:
            return True, ""

        if task_definition.controller and not controller_names.intersection(
            task_definition.controller
        ):
            return (
                False,
                "当前控制器不受支持"
                + f" (支持: {', '.join(task_definition.controller)})",
            )

        if task_definition.resource and (
            resource_name is None or resource_name not in task_definition.resource
        ):
            return (
                False,
                "当前资源不受支持" + f" (支持: {', '.join(task_definition.resource)})",
            )

        return True, ""

    def start(
        self,
        task_list: list[str],
        options: TaskOptionsByTask,
        task_name: str | None = None,
        pre_tasks: list[PreTaskCommand] | None = None,
    ) -> bool:
        self.worker.state.task.last_error = None
        if not self.worker.state.device.connected:
            return False
        if not self.worker.state.device.current_resource_name:
            self.worker.state.device.last_resource_error = "请先设置资源"
            self.worker.events.send_log(self.worker.state.device.last_resource_error)
            return False

        controller_names = self.worker.device.get_active_controller_names()
        current_resource_name = self.worker.state.device.current_resource_name

        filtered_task_list: list[str] = []
        for task_entry in task_list:
            task_definition = self._get_task_definition(task_entry)
            compatible, reason = self._is_task_compatible(
                task_definition,
                controller_names,
                current_resource_name,
            )
            if compatible:
                filtered_task_list.append(task_entry)
                continue

            task_display_name = (
                task_definition.label or task_definition.name
                if task_definition is not None
                else task_entry
            )
            self.worker.events.send_log(f"跳过任务 {task_display_name}: {reason}")

        if not filtered_task_list:
            self.worker.state.task.last_error = "当前资源/控制器下无可执行任务"
            self.worker.events.send_log(self.worker.state.task.last_error)
            return False

        if not self.worker.agents.ensure_started_once():
            return False

        cleaned_options: TaskOptionsByTask = {}
        for task_id, task_options in options.items():
            if not isinstance(task_id, str) or not isinstance(task_options, dict):
                continue

            cleaned_task_options: dict[str, TaskOptionValue] = {}
            for key, value in task_options.items():
                if not isinstance(key, str):
                    continue
                if value is None:
                    cleaned_task_options[key] = ""
                elif isinstance(value, list):
                    cleaned_task_options[key] = [
                        item for item in value if isinstance(item, str)
                    ]
                elif isinstance(value, dict):
                    cleaned_task_options[key] = {
                        input_key: input_value
                        for input_key, input_value in value.items()
                        if isinstance(input_key, str) and isinstance(input_value, str)
                    }
                else:
                    cleaned_task_options[key] = value

            cleaned_options[task_id] = cleaned_task_options

        state = self.worker.state.task
        if not state.lock.acquire(blocking=False):
            return False
        try:
            if state.running:
                return False
            state.stop_flag = False
            state.running = True
            state.last_status = "running"
            state.last_error = None
            state.current_task_name = task_name
            state.thread = threading.Thread(
                target=self.run_process,
                args=(
                    filtered_task_list,
                    copy.deepcopy(cleaned_options),
                    pre_tasks or [],
                ),
                daemon=True,
            )
            state.thread.start()
            return True
        finally:
            state.lock.release()

    def stop(self) -> bool:
        state = self.worker.state.task
        if not state.running:
            return False
        state.stop_flag = True
        proc = state.current_pre_task_process
        if proc is not None and proc.poll() is None:
            self._terminate_process(proc)
        while self.worker.tasker.running:
            time.sleep(0.5)
        return True

    def _terminate_process(self, proc: subprocess.Popen):
        try:
            proc.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=2)
        except Exception:
            if sys.platform == "win32":
                try:
                    subprocess.run(
                        ["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                        check=False,
                    )
                except Exception:
                    pass
            else:
                try:
                    proc.kill()
                except Exception:
                    pass

    def _run_pre_tasks(self, pre_tasks: list[PreTaskCommand]) -> bool:
        state = self.worker.state.task
        enabled = [
            t
            for t in pre_tasks
            if getattr(t, "enabled", False) and t.command.strip() != ""
        ]
        if not enabled:
            return True

        for task in enabled:
            command = task.command
            timeout = task.timeout
            if state.stop_flag:
                self.worker.events.send_log("前置程序已停止")
                state.last_status = "failed"
                state.last_error = "前置程序已停止"
                return False

            self.worker.events.send_log(f"执行前置程序: {command}")
            creationflags = 0
            if sys.platform == "win32":
                creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

            try:
                process = subprocess.Popen(
                    command,
                    shell=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=creationflags,
                )
            except Exception as exc:
                print(f"前置程序启动失败: {command}\n{exc}")
                self.worker.events.send_log(f"前置程序执行失败: {command}")
                self.worker.events.send_notification(
                    "前置程序执行失败",
                    f"命令: {command}\n启动异常: {exc}",
                    notify=["notification"],
                )
                state.last_status = "failed"
                state.last_error = f"前置程序执行失败: {command}"
                return False

            state.current_pre_task_process = process
            output_lines: list[str] = []
            stdout = process.stdout

            def _reader():
                if stdout is None:
                    return
                try:
                    for line in stdout:
                        output_lines.append(line)
                except Exception:
                    pass

            reader_thread = threading.Thread(target=_reader, daemon=True)
            reader_thread.start()

            start_time = time.time()
            timed_out = False
            stopped = False
            while True:
                if process.poll() is not None:
                    break
                if state.stop_flag:
                    stopped = True
                    break
                if time.time() - start_time > timeout:
                    timed_out = True
                    break
                time.sleep(0.1)

            if stopped or timed_out:
                self._terminate_process(process)

            reader_thread.join(timeout=2)
            state.current_pre_task_process = None

            full_output = "".join(output_lines)
            if len(output_lines) > 1000:
                output_lines = output_lines[-1000:]

            if stopped:
                self.worker.events.send_log("前置程序已停止")
                state.last_status = "failed"
                state.last_error = f"前置程序已停止: {command}"
                return False

            return_code = process.returncode
            if timed_out or return_code != 0:
                try:
                    print(full_output)
                except UnicodeEncodeError:
                    sys.stdout.buffer.write(
                        full_output.encode("utf-8", errors="replace")
                    )
                    sys.stdout.buffer.write(b"\n")
                    sys.stdout.flush()
                if timed_out:
                    self.worker.events.send_log(f"前置程序执行超时: {command}")
                    self.worker.events.send_notification(
                        "前置程序执行超时",
                        f"命令: {command}\n超时时间: {timeout}s",
                        notify=["notification"],
                    )
                    state.last_error = f"前置程序执行超时: {command}"
                else:
                    self.worker.events.send_log(f"前置程序执行失败: {command}")
                    self.worker.events.send_notification(
                        "前置程序执行失败",
                        f"命令: {command}\n退出码: {return_code}",
                        notify=["notification"],
                    )
                    state.last_error = f"前置程序执行失败: {command}"
                state.last_status = "failed"
                return False

            self.worker.events.send_log(f"前置程序执行成功: {command}")

        return True

    def run_process(
        self,
        task_list: list[str],
        options: TaskOptionsByTask,
        pre_tasks: list[PreTaskCommand] | None = None,
    ):
        state = self.worker.state.task
        state.pre_tasks = pre_tasks or []
        try:
            self.worker.events.emit_task_started(task_list)
            if pre_tasks:
                if not self._run_pre_tasks(pre_tasks):
                    if not state.last_error:
                        state.last_error = "前置程序执行失败"
                    if state.last_status not in ("failed", "stopped"):
                        state.last_status = "failed"
                    self.worker.events.emit_task_failed(
                        task_list, state.last_error or "前置程序执行失败"
                    )
                    return
            for task in task_list:
                if state.stop_flag:
                    self.worker.tasker.post_stop().wait()
                    state.last_status = "stopped"
                    state.last_error = "任务已终止"
                    self.worker.events.send_log("任务已终止")
                    self.worker.events.emit_task_failed(task_list, "任务已终止")
                    return

                pipeline_override = self.worker.pipeline.build_task_pipeline_override(
                    task,
                    options.get(task, {}),
                )
                if pipeline_override:
                    task_result = self.worker.tasker.post_task(task, pipeline_override)
                else:
                    task_result = self.worker.tasker.post_task(task)
                self.worker.events.send_log("正在运行任务: " + task)
                while not task_result.done:
                    time.sleep(0.5)
                    if state.stop_flag:
                        self.worker.tasker.post_stop().wait()
                        state.last_status = "stopped"
                        state.last_error = "任务已终止"
                        self.worker.events.send_log("任务已终止")
                        self.worker.events.emit_task_failed(task_list, "任务已终止")
                        return
            state.last_status = "success"
            state.last_error = None
            self.worker.events.emit_task_completed(task_list)
        except Exception as exc:
            traceback.print_exc()
            state.last_status = "failed"
            state.last_error = str(exc) or "任务执行失败"
            self.worker.events.emit_task_failed(task_list, state.last_error)
            self.worker.events.send_log("任务出现异常，请检查终端日志")
            self.worker.events.send_log(
                f"请将日志反馈至 {self.worker.interface.github}/issues"
            )
        finally:
            state.running = False
            state.thread = None
            state.current_task_name = None
            state.current_pre_task_process = None
            time.sleep(0.5)
