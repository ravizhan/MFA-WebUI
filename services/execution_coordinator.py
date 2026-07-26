from __future__ import annotations

import asyncio
import logging
import uuid
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Literal

from app_state import ActiveRun
from maa_worker.event_service import load_settings
from models.scheduler import (
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

if TYPE_CHECKING:
    from app_state import AppState
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


@dataclass(frozen=True)
class RunRequest:
    """submit_manual/submit_scheduled → _complete_run 的一次执行请求。"""

    run_id: str
    task_list: list[str]
    task_options: TaskOptionsByTask
    pre_tasks: Any
    controller_name: str | None
    device: ScheduledTaskDeviceConfig | dict[str, Any] | None
    resource_name: str | None
    log_label: str


@dataclass
class Admission:
    """调度入场结果：接受则带 run_id，拒绝则带冲突或跳过状态。"""

    accepted: bool
    run_id: str | None = None
    conflict: StartConflict | None = None
    skip_status: ExecutionStatus | None = None


class ExecutionCoordinator:
    """调度执行编排：入场裁决、后台完成、与 ExecutionStore 交互。"""

    def __init__(self, state: AppState, store: ExecutionStore) -> None:
        self._state = state
        self._store = store

    def active_run(self) -> ActiveRun | None:
        return self._state.active_run

    def _conflict_for_active(self, active: ActiveRun) -> StartConflict:
        if active.origin == "manual":
            code: Literal["busy_manual"] = "busy_manual"
            message = f"当前有手动任务「{active.task_name}」正在执行"
        else:
            code: Literal["busy_scheduled"] = "busy_scheduled"
            message = f"当前有定时任务「{active.task_name}」正在执行"
        return StartConflict(
            code=code,
            message=message,
            active_run_id=active.run_id,
            active_task_name=active.task_name,
            active_origin=active.origin,
        )

    def _update_conflict(self) -> StartConflict:
        active = self._state.active_run
        return StartConflict(
            code="update_in_progress",
            message="系统正在更新，无法启动任务",
            active_run_id=active.run_id if active else "",
            active_task_name=active.task_name if active else "",
            active_origin=active.origin if active else "manual",
        )

    def _is_stop_requested(self, run_id: str) -> bool:
        active = self._state.active_run
        return active is not None and active.run_id == run_id and active.stop_requested

    async def _complete_run(self, *, req: RunRequest) -> None:
        """后台完成：prepare/run → finish → 无条件清理 active 槽位。"""
        try:
            try:
                status, error = await self._prepare_and_run(req=req)
                await asyncio.to_thread(self._store.finish, req.run_id, status, error)
            except asyncio.CancelledError:
                # CancelledError 继承自 BaseException（不被下面的 except Exception 捕获），
                # 但 finally 仍清空 active 槽位——若不显式写终态，DB 行将残留 running。
                # 用 shield 保护 finish 写入本身不被取消；suppress 避免写入失败掩盖取消语义。
                with suppress(Exception):
                    await asyncio.shield(
                        asyncio.to_thread(
                            self._store.finish, req.run_id, "stopped", "任务被取消"
                        )
                    )
                raise
            except Exception as e:
                logger.error("任务 %s 后台完成失败: %s", req.log_label, e)
                try:
                    await asyncio.to_thread(
                        self._store.finish, req.run_id, "failed", str(e)
                    )
                except Exception as finish_err:
                    logger.error(
                        "任务 %s 写入失败状态异常: %s", req.log_label, finish_err
                    )
        finally:
            if self._state.active_run and self._state.active_run.run_id == req.run_id:
                self._state.active_run = None
            if self._state.active_execution_task is asyncio.current_task():
                self._state.active_execution_task = None

    async def submit_manual(self, payload: ManualStartPayload) -> Admission:
        """手动启动：准入后立即返回；实际执行在后台完成协程中。"""
        run_id = str(uuid.uuid4())
        if self._state.update_in_progress:
            return Admission(accepted=False, conflict=self._update_conflict())
        if self._state.active_run is not None:
            return Admission(
                accepted=False,
                conflict=self._conflict_for_active(self._state.active_run),
            )
        self._state.active_run = ActiveRun(
            run_id=run_id,
            origin="manual",
            task_name=MANUAL_TASK_NAME,
            occurrence_id=None,
        )

        now = _utc_now()
        try:
            await asyncio.to_thread(
                self._store.add,
                TaskExecution(
                    id=run_id,
                    task_id=None,
                    task_name=MANUAL_TASK_NAME,
                    origin="manual",
                    status="running",
                    started_at=now,
                ),
            )
        except Exception:
            self._state.active_run = None
            raise

        req = RunRequest(
            run_id=run_id,
            task_list=payload.task_list,
            task_options=payload.task_options,
            pre_tasks=payload.preTasks,
            controller_name=payload.controller_name,
            device=payload.device,
            resource_name=payload.resource_name,
            log_label=MANUAL_TASK_NAME,
        )
        self._state.active_execution_task = asyncio.create_task(
            self._complete_run(req=req)
        )
        return Admission(accepted=True, run_id=run_id)

    async def submit_scheduled(
        self,
        task: ScheduledTask,
        origin: Literal["in_app", "native"],
    ) -> Admission:
        """定时/原生唤醒入场：超时/忙碌记 skip，否则占槽并后台执行。"""
        now_local = _local_now()
        now_utc = _utc_now()
        scheduled_for = compute_occurrence(task.trigger_config, now_local)
        scheduled_for_utc = _to_utc(scheduled_for)
        occurrence_id = _occurrence_id(task.id, scheduled_for_utc)

        # 原生唤醒迟到超过 15 分钟 → missed_deadline
        if origin == "native" and now_utc - scheduled_for_utc > MISFIRE_GRACE:
            run_id = str(uuid.uuid4())
            await asyncio.to_thread(
                self._store.add,
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
                ),
            )
            return Admission(
                accepted=False,
                run_id=run_id,
                skip_status="missed_deadline",
            )

        run_id = str(uuid.uuid4())
        skip_status: ExecutionStatus | None = None
        blocker: ActiveRun | None = None

        if self._state.update_in_progress:
            skip_status = "skipped_update_in_progress"
            blocker = self._state.active_run
        elif self._state.active_run is not None:
            if self._state.active_run.origin == "manual":
                skip_status = "skipped_busy_manual"
            else:
                skip_status = "skipped_busy_scheduled"
            blocker = self._state.active_run
        else:
            self._state.active_run = ActiveRun(
                run_id=run_id,
                origin=origin,
                task_name=task.name,
                occurrence_id=occurrence_id,
            )

        if skip_status is not None:
            skip_now = _utc_now()
            await asyncio.to_thread(
                self._store.add,
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
                ),
            )
            return Admission(
                accepted=False,
                run_id=run_id,
                skip_status=skip_status,
            )

        try:
            await asyncio.to_thread(
                self._store.add,
                TaskExecution(
                    id=run_id,
                    task_id=task.id,
                    task_name=task.name,
                    origin=origin,
                    occurrence_id=occurrence_id,
                    scheduled_for=scheduled_for_utc,
                    status="running",
                    started_at=_utc_now(),
                ),
            )
        except Exception:
            self._state.active_run = None
            raise

        req = RunRequest(
            run_id=run_id,
            task_list=task.task_list,
            task_options=task.task_options,
            pre_tasks=task.preTasks,
            controller_name=task.controller_name,
            device=task.device,
            resource_name=task.resource_name,
            log_label=task.id,
        )
        self._state.active_execution_task = asyncio.create_task(
            self._complete_run(req=req)
        )
        return Admission(accepted=True, run_id=run_id)

    async def stop_active(self) -> bool:
        """请求停止并等待后台完成协程清理 active 槽位。"""
        active = self._state.active_run
        if active is None:
            return False
        active.stop_requested = True
        worker = self._state.worker
        completion = self._state.active_execution_task
        if worker is not None:
            await asyncio.to_thread(worker.tasks.stop)
        if completion is not None:
            # shield 防止调用方（main.py wait_for）超时取消传播到 completion 本身，
            # 避免提前写 stopped 并释放 active_run，而底层 MAA 线程仍活。
            await asyncio.shield(completion)
        return True

    def _normalize_task_payload(
        self,
        task_list: Any,
        task_options: Any,
        pre_tasks: Any = None,
    ) -> tuple[list[str], TaskOptionsByTask, list]:
        """始终走完整规范化：去重 task_id 并透传 options 与 pre_tasks。

        worker.interface 在生产中恒为有效 InterfaceModel（main.py 启动期已校验，
        load_interface_model 失败即 exit(1)）。若 interface 缺失则 normalizer 内部
        抛出 AttributeError，由 _prepare_and_run 的外层异常处理转为 "failed" 终态——
        优于静默以空 options 执行任务（旧 fallback 会无条件丢弃 options/pre_tasks）。
        """
        worker = self._state.worker
        # _prepare_and_run 入口已 `if not worker: return "failed"`，此处仅为类型收窄。
        if worker is None:  # pragma: no cover - 调用方契约保证
            raise RuntimeError("worker 未就绪")
        return normalize_task_execution_payload(
            task_list,
            task_options,
            worker.interface,
            pre_tasks,
        )

    async def _prepare_and_run(self, *, req: RunRequest) -> tuple[str, str | None]:
        """连接设备 → 启动任务 → 轮询结束；返回 (status, error_message)，不碰 ActiveRun。"""
        run_id = req.run_id
        task_list = req.task_list
        task_options = req.task_options
        pre_tasks = req.pre_tasks
        controller_name = req.controller_name
        device = req.device
        resource_name = req.resource_name
        log_label = req.log_label
        worker = self._state.worker
        if not worker:
            logger.error("Worker 未就绪，无法执行任务 %s", log_label)
            return "failed", "Worker 未就绪"

        if self._is_stop_requested(run_id):
            return "stopped", "任务已终止"

        device_dict = _device_as_dict(device)
        device_state = self._state.device
        task_state = self._state.task

        try:
            # 准备路径要求设备与资源齐全
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

            if self._is_stop_requested(run_id):
                return "stopped", "任务已终止"

            # 已锁定且控制器/资源匹配则可复用连接
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

            if need_connect:
                # 重连前无条件清干净：connected=True 但 locked=False 的残留状态
                # （上次 run 在 stop 路径提前返回，或只调过 connect 未调 set_resource）
                # 同样会让下面的 connect 留下未注册 sink 的 controller。
                # 无 reason 调用是幂等且静默的（device_service.reset_connection_state）。
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
                    if self._is_stop_requested(run_id):
                        return "stopped", "任务已终止"
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
                        # 每次尝试必须独立：connect 成功但 set_resource 失败/抛错会
                        # 残留 connected=True + 活的 controller（sink 已注册）。下次
                        # connect 会新建 controller，而 register_controller_sink 因
                        # _controller_sink_id 已占用提前返回 → 新 controller 无 sink，
                        # 控制器侧事件静默丢失，且旧 sink id 会被错误地从新 controller 摘除。
                        await asyncio.to_thread(worker.device.reset_connection_state)
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
                    if self._is_stop_requested(run_id):
                        return "stopped", "任务已终止"
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

            if self._is_stop_requested(run_id):
                return "stopped", "任务已终止"

            normalized_task_list, normalized_task_options, normalized_pre_tasks = (
                self._normalize_task_payload(task_list, task_options, pre_tasks)
            )
            if not normalized_task_list:
                return "failed", "任务列表为空"

            if self._is_stop_requested(run_id):
                return "stopped", "任务已终止"

            if not worker.tasks.start(
                normalized_task_list,
                normalized_task_options,
                task_name=log_label,
                pre_tasks=normalized_pre_tasks,
            ):
                worker.events.send_log(f"任务 {log_label} 已被跳过：任务已在运行")
                return "stopped", "任务已在运行"

            while task_state.running:
                # 活线程：继续等待；stop_requested 仅是停止意图，不等于任务已停止。
                thread = task_state.thread
                if thread is not None and thread.is_alive():
                    await asyncio.sleep(1)
                    continue
                # 死/缺失线程：收敛 stale 残留（running=True 但线程已死）为终态，清 running/thread。
                last_status = task_state.last_status
                if last_status not in ("success", "stopped", "failed"):
                    if self._is_stop_requested(run_id):
                        task_state.last_status = "stopped"
                        task_state.last_error = "任务已终止"
                    else:
                        task_state.last_status = "failed"
                        task_state.last_error = "任务执行线程异常退出"
                task_state.running = False
                task_state.thread = None
                break

            task_status = task_state.last_status
            task_error = task_state.last_error

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
