import copy
import threading
import time
import traceback
from typing import TYPE_CHECKING

from models.scheduler import TaskOptionValue, TaskOptionsByTask

if TYPE_CHECKING:
    from maa_utils import MaaWorker


class TaskService:
    def __init__(self, worker: "MaaWorker"):
        self.worker = worker

    def start(
        self,
        task_list: list[str],
        options: TaskOptionsByTask,
        task_name: str | None = None,
    ) -> bool:
        if not self.worker.device_state.connected:
            return False
        if not self.worker.device_state.current_resource_name:
            self.worker.device_state.last_resource_error = "请先设置资源"
            self.worker.events.send_log(self.worker.device_state.last_resource_error)
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

        state = self.worker.task_state
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
                args=(task_list, copy.deepcopy(cleaned_options)),
                daemon=True,
            )
            state.thread.start()
            return True
        finally:
            state.lock.release()

    def stop(self) -> bool:
        state = self.worker.task_state
        if not state.running:
            return False
        state.stop_flag = True
        while self.worker.tasker.running:
            time.sleep(0.5)
        return True

    def run_process(
        self,
        task_list: list[str],
        options: TaskOptionsByTask,
    ):
        state = self.worker.task_state
        try:
            self.worker.events.emit_task_started(task_list)
            for task in task_list:
                if state.stop_flag:
                    self.worker.tasker.post_stop().wait()
                    state.last_status = "stopped"
                    state.last_error = "任务已终止"
                    self.worker.events.send_log("任务已终止")
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
            time.sleep(0.5)
