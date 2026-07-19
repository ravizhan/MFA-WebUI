import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from maa_worker.event_service import load_settings
from models.scheduler import (
    ExecutionOrigin,
    ExecutionStatus,
    ManualStartPayload,
    ScheduledTask,
    ScheduledTaskDeviceConfig,
    StartConflict,
    TaskExecution,
    TaskOptionsByTask,
)
from models.task_config import normalize_task_execution_payload
from scheduler_job_codec import compute_occurrence
from services.execution_store import ExecutionStore

logger = logging.getLogger(__name__)

MISFIRE_GRACE = timedelta(minutes=15)
MANUAL_TASK_NAME = "手动执行"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _occurrence_id(task_id: str, scheduled_for: datetime) -> str:
    return f"{task_id}:{_to_utc(scheduled_for).isoformat()}"


def _device_as_dict(
    device: ScheduledTaskDeviceConfig | dict[str, Any] | None,
) -> dict[str, Any] | None:
    if device is None:
        return None
    if isinstance(device, ScheduledTaskDeviceConfig):
        return device.model_dump()
    return device


@dataclass
class ActiveRun:
    run_id: str
    origin: ExecutionOrigin
    task_name: str
    occurrence_id: str | None


@dataclass
class Admission:
    accepted: bool
    run_id: str | None = None
    conflict: StartConflict | None = None
    skip_status: ExecutionStatus | None = None
    deduplicated: bool = False


class ExecutionCoordinator:
    """asyncio.Lock admission gate + shared prepare/run path."""

    def __init__(self, store: ExecutionStore) -> None:
        self._store = store
        self._worker = None
        self._lock = asyncio.Lock()
        self._active: ActiveRun | None = None
        self._update_in_progress = False

    def set_worker(self, worker) -> None:
        self._worker = worker

    def active_run(self) -> ActiveRun | None:
        return self._active

    def set_update_in_progress(self) -> None:
        """One-way gate: after set, all admission is rejected (update → shutdown)."""
        self._update_in_progress = True

    def _conflict_for_active(self, active: ActiveRun) -> StartConflict:
        if active.origin == "manual":
            code: Literal["busy_manual", "busy_scheduled"] = "busy_manual"
            message = f"当前有手动任务「{active.task_name}」正在执行"
        else:
            code = "busy_scheduled"
            message = f"当前有定时任务「{active.task_name}」正在执行"
        return StartConflict(
            code=code,
            message=message,
            active_run_id=active.run_id,
            active_task_name=active.task_name,
            active_origin=active.origin,
        )

    def _update_conflict(self) -> StartConflict:
        active = self._active
        return StartConflict(
            code="update_in_progress",
            message="系统正在更新，无法启动任务",
            active_run_id=active.run_id if active else "",
            active_task_name=active.task_name if active else "",
            active_origin=active.origin if active else "manual",
        )

    async def submit_manual(self, payload: ManualStartPayload) -> Admission:
        run_id = str(uuid.uuid4())
        async with self._lock:
            if self._update_in_progress:
                return Admission(accepted=False, conflict=self._update_conflict())
            if self._active is not None:
                return Admission(
                    accepted=False, conflict=self._conflict_for_active(self._active)
                )
            self._active = ActiveRun(
                run_id=run_id,
                origin="manual",
                task_name=MANUAL_TASK_NAME,
                occurrence_id=None,
            )

        now = _utc_now()
        await self._store.add(
            TaskExecution(
                id=run_id,
                task_id=None,
                task_name=MANUAL_TASK_NAME,
                origin="manual",
                status="running",
                started_at=now,
            )
        )
        try:
            status, error = await self._prepare_and_run(
                task_list=payload.task_list,
                task_options=payload.task_options,
                pre_tasks=payload.preTasks,
                controller_name=payload.controller_name,
                device=payload.device,
                resource_name=payload.resource_name,
                run_id=run_id,
                log_label=MANUAL_TASK_NAME,
            )
            await self._store.finish(run_id, status, error)
            return Admission(accepted=True, run_id=run_id)
        finally:
            async with self._lock:
                if self._active and self._active.run_id == run_id:
                    self._active = None

    async def submit_scheduled(
        self,
        task: ScheduledTask,
        origin: Literal["in_app", "native"],
    ) -> Admission:
        now_local = _local_now()
        now_utc = _utc_now()
        scheduled_for = compute_occurrence(task.trigger_config, now_local)
        scheduled_for_utc = _to_utc(scheduled_for)
        occurrence_id = _occurrence_id(task.id, scheduled_for_utc)

        # Native late window: beyond 15min → missed_deadline, no claim.
        if origin == "native" and now_utc - scheduled_for_utc > MISFIRE_GRACE:
            run_id = str(uuid.uuid4())
            await self._store.add(
                TaskExecution(
                    id=run_id,
                    task_id=task.id,
                    task_name=task.name,
                    origin=origin,
                    occurrence_id=occurrence_id,
                    scheduled_for=scheduled_for_utc,
                    status="missed_deadline",
                    started_at=now_utc,
                    finished_at=now_utc,
                    error_message="超过 15 分钟 misfire 窗口",
                )
            )
            return Admission(
                accepted=False,
                run_id=run_id,
                skip_status="missed_deadline",
            )

        run_id = str(uuid.uuid4())
        claimed = await self._store.try_claim(
            occurrence_id=occurrence_id,
            task_id=task.id,
            scheduled_for=scheduled_for_utc,
            origin=origin,
            run_id=run_id,
        )
        if not claimed:
            return Admission(accepted=False, deduplicated=True)

        skip_status: ExecutionStatus | None = None
        blocker: ActiveRun | None = None

        async with self._lock:
            if self._update_in_progress:
                skip_status = "skipped_update_in_progress"
                blocker = self._active
            elif self._active is not None:
                if self._active.origin == "manual":
                    skip_status = "skipped_busy_manual"
                else:
                    skip_status = "skipped_busy_scheduled"
                blocker = self._active
            else:
                self._active = ActiveRun(
                    run_id=run_id,
                    origin=origin,
                    task_name=task.name,
                    occurrence_id=occurrence_id,
                )

        if skip_status is not None:
            skip_now = _utc_now()
            await self._store.add(
                TaskExecution(
                    id=run_id,
                    task_id=task.id,
                    task_name=task.name,
                    origin=origin,
                    occurrence_id=occurrence_id,
                    scheduled_for=scheduled_for_utc,
                    status=skip_status,
                    blocker_run_id=blocker.run_id if blocker else None,
                    blocker_task_name=blocker.task_name if blocker else None,
                    started_at=skip_now,
                    finished_at=skip_now,
                )
            )
            await self._store.finish_claim(occurrence_id, abandoned=False)
            return Admission(
                accepted=False,
                run_id=run_id,
                skip_status=skip_status,
            )

        await self._store.add(
            TaskExecution(
                id=run_id,
                task_id=task.id,
                task_name=task.name,
                origin=origin,
                occurrence_id=occurrence_id,
                scheduled_for=scheduled_for_utc,
                status="running",
                started_at=_utc_now(),
            )
        )
        await self._store.mark_running(occurrence_id)
        try:
            status, error = await self._prepare_and_run(
                task_list=task.task_list,
                task_options=task.task_options,
                pre_tasks=task.preTasks,
                controller_name=task.controller_name,
                device=task.device,
                resource_name=task.resource_name,
                run_id=run_id,
                log_label=task.id,
            )
            await self._store.finish(run_id, status, error)
            await self._store.finish_claim(occurrence_id, abandoned=False)
            return Admission(accepted=True, run_id=run_id)
        except Exception:
            await self._store.finish_claim(occurrence_id, abandoned=True)
            raise
        finally:
            async with self._lock:
                if self._active and self._active.run_id == run_id:
                    self._active = None

    async def stop_active(self) -> bool:
        if self._active is None:
            return False
        worker = self._worker
        if worker is None:
            return False
        worker.tasks.stop()
        return True

    def _normalize_task_payload(
        self,
        task_list: Any,
        task_options: Any,
        pre_tasks: Any = None,
    ) -> tuple[list[str], TaskOptionsByTask, list]:
        worker = self._worker
        if not worker or not getattr(worker, "interface", None):
            normalized_task_list: list[str] = []
            if isinstance(task_list, list):
                seen: set[str] = set()
                for task_id in task_list:
                    if not isinstance(task_id, str) or task_id in seen:
                        continue
                    normalized_task_list.append(task_id)
                    seen.add(task_id)
            return (
                normalized_task_list,
                {tid: {} for tid in normalized_task_list},
                [],
            )
        return normalize_task_execution_payload(
            task_list,
            task_options,
            worker.interface,
            pre_tasks,
        )

    async def _prepare_and_run(
        self,
        task_list: list[str],
        task_options: TaskOptionsByTask,
        pre_tasks: Any,
        controller_name: str | None,
        device: ScheduledTaskDeviceConfig | dict[str, Any] | None,
        resource_name: str | None,
        run_id: str,
        log_label: str,
    ) -> tuple[str, str | None]:
        """Port of SchedulerManager._execute_task body (connect → start → poll).

        Returns ``(status, error_message)``. Does not touch ActiveRun or claims.
        """
        del run_id  # reserved for future correlation / logging
        worker = self._worker
        if not worker:
            logger.error("Worker 未就绪，无法执行任务 %s", log_label)
            return "failed", "Worker 未就绪"

        device_dict = _device_as_dict(device)

        try:
            # Device/resource required for prepare path
            if device_dict is None or resource_name is None:
                _settings = load_settings()
                worker.events.send_notification(
                    "配置缺失",
                    f"任务 {log_label} 执行失败：设备或资源配置缺失",
                    event="task.failed",
                    level="error",
                    notify=["notification"]
                    if _settings.notification.notifyOnError
                    else [],
                )
                return "failed", "设备或资源配置缺失"

            # Connection match / reuse
            device_state = worker.device_state
            device_controller_name = (
                device_dict.get("controller_name") or controller_name
            )
            need_connect = True
            if (
                device_state.connected
                and device_state.configuration_locked
                and device_state.controller_name == device_controller_name
                and device_state.current_resource_name == resource_name
            ):
                need_connect = False

            if need_connect and device_state.configuration_locked:
                await asyncio.to_thread(worker.device.reset_connection_state)

            if need_connect:
                device_model = worker.device.build_device_model_from_config(
                    device_controller_name,
                    device_dict["device_type"],
                    device_dict["device_address"],
                )
                _settings = load_settings()
                max_retry = _settings.runtime.maxRetryCount
                retry_interval = _settings.runtime.retryInterval

                connect_success = False
                for attempt in range(1, max_retry + 1):
                    try:
                        connected = await asyncio.to_thread(
                            worker.device.connect, device_model
                        )
                        if not connected:
                            raise RuntimeError("connect() 返回 False")
                        resource_set = await asyncio.to_thread(
                            worker.device.set_resource, resource_name
                        )
                        if not resource_set:
                            raise RuntimeError("set_resource() 返回 False")
                        connect_success = True
                        break
                    except Exception as e:
                        if attempt < max_retry:
                            worker.events.send_log(
                                f"连接失败，第 {attempt} 次重试...: {e}"
                            )
                            await asyncio.sleep(retry_interval)
                        else:
                            worker.events.send_log(
                                f"连接失败，已达最大重试次数 {max_retry}: {e}"
                            )

                if not connect_success:
                    _settings = load_settings()
                    worker.events.send_notification(
                        "连接失败",
                        f"任务 {log_label} 执行失败：设备连接失败",
                        event="task.failed",
                        level="error",
                        notify=["notification"]
                        if _settings.notification.notifyOnError
                        else [],
                    )
                    await asyncio.to_thread(worker.device.reset_connection_state)
                    return "failed", "设备连接失败"

            normalized_task_list, normalized_task_options, normalized_pre_tasks = (
                self._normalize_task_payload(task_list, task_options, pre_tasks)
            )
            if not normalized_task_list:
                return "failed", "任务列表为空"

            if not worker.tasks.start(
                normalized_task_list,
                normalized_task_options,
                task_name=log_label,
                pre_tasks=normalized_pre_tasks,
            ):
                worker.events.send_log(f"任务 {log_label} 已被跳过：任务已在运行")
                return "stopped", "任务已在运行"

            while worker and worker.task_state.running:
                await asyncio.sleep(1)

            task_status = getattr(worker.task_state, "last_status", "failed")
            task_error = getattr(worker.task_state, "last_error", None)

            if task_status == "success":
                logger.info("任务 %s 执行成功", log_label)
                return "success", None
            if task_status == "stopped":
                worker.events.send_log(f"任务 {log_label} 已停止")
                return "stopped", task_error or "任务已终止"

            logger.error("任务 %s 执行失败: %s", log_label, task_error)
            worker.events.send_log(f"任务 {log_label} 执行失败")
            return "failed", task_error or "任务执行失败"

        except Exception as e:
            logger.error("任务 %s 执行失败: %s", log_label, e)
            if worker:
                worker.events.send_log(f"任务 {log_label} 执行异常: {e}")
            return "failed", str(e)
