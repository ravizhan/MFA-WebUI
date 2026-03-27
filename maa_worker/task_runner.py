import copy
import threading
import time
import traceback
from typing import TYPE_CHECKING

from models.scheduler import TaskOptionValue

if TYPE_CHECKING:
    from maa_utils import MaaWorker


def start_task(
    worker: "MaaWorker",
    task_list: list[str],
    options: dict[str, TaskOptionValue],
    task_name: str | None = None,
) -> bool:
    if not worker.connected:
        return False
    if not worker._task_lock.acquire(blocking=False):
        return False
    try:
        if worker.running:
            return False
        worker.stop_flag = False
        worker.running = True
        worker.last_task_status = "running"
        worker.last_task_error = None
        worker._current_task_name = task_name
        worker._task_thread = threading.Thread(
            target=worker._run_process,
            args=(task_list, copy.deepcopy(options)),
            daemon=True,
        )
        worker._task_thread.start()
        return True
    finally:
        worker._task_lock.release()


def stop_task(worker: "MaaWorker") -> bool:
    if not worker.running:
        return False
    worker.stop_flag = True
    while worker.tasker.running:
        time.sleep(0.5)
    return True


def run_process(
    worker: "MaaWorker",
    task_list: list[str],
    options: dict[str, TaskOptionValue],
):
    try:
        worker._emit_task_started(task_list)
        for task in task_list:
            if worker.stop_flag:
                worker.tasker.post_stop().wait()
                worker.last_task_status = "stopped"
                worker.last_task_error = "任务已终止"
                worker.send_log("任务已终止")
                return
            pipeline_override = worker._build_task_pipeline_override(task, options)
            print(pipeline_override)
            if pipeline_override:
                t = worker.tasker.post_task(task, pipeline_override)
            else:
                t = worker.tasker.post_task(task)
            worker.send_log("正在运行任务: " + task)
            while not t.done:
                time.sleep(0.5)
                if worker.stop_flag:
                    worker.tasker.post_stop().wait()
                    worker.last_task_status = "stopped"
                    worker.last_task_error = "任务已终止"
                    worker.send_log("任务已终止")
                    return
        worker.last_task_status = "success"
        worker.last_task_error = None
        worker._emit_task_completed(task_list)
    except Exception as exc:
        traceback.print_exc()
        worker.last_task_status = "failed"
        worker.last_task_error = str(exc) or "任务执行失败"
        worker._emit_task_failed(task_list, worker.last_task_error)
        worker.send_log("任务出现异常，请检查终端日志")
        worker.send_log(f"请将日志反馈至 {worker.interface.github}/issues")
    finally:
        worker.running = False
        worker._task_thread = None
        worker._current_task_name = None
        time.sleep(0.5)
