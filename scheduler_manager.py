"""APS 任务 CRUD 与生命周期；准入控制在 ExecutionCoordinator。"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import tzlocal
from apscheduler.jobstores.base import JobLookupError
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from models.task_config import normalize_task_execution_payload
from models.scheduler import (
    ScheduledTask,
    ScheduledTaskCreate,
    ScheduledTaskDeviceConfig,
    ScheduledTaskUpdate,
    TaskOptionsByTask,
)
from scheduler_job_codec import (
    SchedulerJobDecodeError,
    build_trigger,
    decode_job_to_scheduled_task,
    decode_pre_tasks_from_job_kwargs,
    decode_scheduled_task_from_kwargs,
    decode_trigger,
    encode_execution_kwargs,
)
from services.system_scheduler import SystemScheduler

logger = logging.getLogger(__name__)

# APS 持久化回调只能序列化全局可导入 callable；运行时绑定规范 AppState
_callback_runtime_state: Any | None = None


def _bind_callback_runtime(state: Any) -> None:
    """绑定回调用的规范 AppState 引用（非所有权）。"""
    global _callback_runtime_state
    _callback_runtime_state = state


def _clear_callback_runtime() -> None:
    """关闭调度器时清空回调运行时引用。"""
    global _callback_runtime_state
    _callback_runtime_state = None


async def scheduled_job_fired(**kwargs: Any) -> None:
    """APS 任务入口：从 kwargs 解码后交给 ExecutionCoordinator。

    不 import main；不依赖 manager.get_task（DateTrigger 到期后 job 可能已删除）。
    wakeup 任务由系统原生调度负责，应用内触发直接跳过。
    """
    app_state = _callback_runtime_state
    if app_state is None:
        logger.error("scheduled_job_fired: 回调运行时 state 未绑定，跳过派发")
        return

    coordinator = getattr(app_state, "execution_coordinator", None)
    if coordinator is None:
        logger.error("scheduled_job_fired: execution_coordinator 未初始化，跳过")
        return

    try:
        task = decode_scheduled_task_from_kwargs(kwargs)
    except Exception as e:
        logger.error("scheduled_job_fired: 解码 kwargs 失败: %s", e)
        return

    # 原生唤醒任务不在此路径执行，避免与 OS 调度重复派发
    if task.wakeup_enabled:
        logger.info(
            "scheduled_job_fired: skip in-app dispatch for wakeup task %s "
            "(native owns execution)",
            task.id,
        )
        return

    try:
        await coordinator.submit_scheduled(task, origin="in_app")
    except Exception as e:
        logger.error("scheduled_job_fired: 提交执行失败 %s: %s", task.id, e)


class SchedulerManager:
    """APS 任务 CRUD/生命周期；系统唤醒经 SystemScheduler 注册。"""

    def __init__(
        self,
        state: Any,
        db_path: Path,
        system_scheduler: SystemScheduler | None = None,
    ) -> None:
        # 构造契约：SchedulerManager(state, db_path, system_scheduler=None)
        self._state = state
        self.scheduler: Optional[AsyncIOScheduler] = None
        self._db_path = Path(db_path)
        self._system_scheduler = system_scheduler
        # 构造时即绑定，供持久化 job 反序列化后回调使用
        _bind_callback_runtime(state)

    @property
    def _worker(self):
        """从规范 AppState 取 worker（main 不再单独 set_worker）。"""
        return getattr(self._state, "worker", None)

    def set_system_scheduler(self, system_scheduler: SystemScheduler | None) -> None:
        """注入跨平台系统调度后端（可为空）。"""
        self._system_scheduler = system_scheduler

    async def initialize(self, *, paused: bool = True) -> None:
        """启动 APS；db_path 由 main 注入，paused 时先不派发。"""
        _bind_callback_runtime(self._state)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        db_url = f"sqlite:///{self._db_path.resolve().as_posix()}"
        self.scheduler = AsyncIOScheduler(
            jobstores={"default": SQLAlchemyJobStore(url=db_url)},
            job_defaults={
                "misfire_grace_time": 900,
                "coalesce": True,
            },
            timezone=tzlocal.get_localzone(),
        )
        self.scheduler.start(paused=paused)
        self.scheduler.get_jobs()
        if paused:
            logger.info("调度器已启动（paused）")
        else:
            logger.info("调度器已启动")

    def resume(self) -> None:
        """从 paused 恢复 APS 派发。"""
        if self.scheduler is not None:
            self.scheduler.resume()
            logger.info("调度器已恢复派发")

    async def shutdown(self) -> None:
        """关闭 APS 并清空回调运行时引用。"""
        if self.scheduler:
            self.scheduler.shutdown()
            logger.info("调度器已关闭")
            self.scheduler = None
        _clear_callback_runtime()

    def _normalize_task_payload(
        self,
        task_list: Any,
        task_options: Any,
        pre_tasks: Any = None,
    ) -> tuple[list[str], TaskOptionsByTask, list]:
        """按 interface 规范化任务载荷；接口不可用时仅去重 task_list，透传 options 与 pre_tasks。"""
        worker = self._worker
        if not worker or not getattr(worker, "interface", None):
            normalized_task_list: list[str] = []
            if isinstance(task_list, list):
                seen_task_ids: set[str] = set()
                for task_id in task_list:
                    if not isinstance(task_id, str) or task_id in seen_task_ids:
                        continue
                    normalized_task_list.append(task_id)
                    seen_task_ids.add(task_id)
            # 接口缺失时透传 options/pre_tasks，仅去重 task_list；
            # 仅当值确实不可用（非 dict / None）才回退到空容器
            if isinstance(task_options, dict):
                passthrough_options = {
                    tid: task_options[tid]
                    for tid in normalized_task_list
                    if tid in task_options
                }
            else:
                passthrough_options = {}
            if isinstance(pre_tasks, list):
                passthrough_pre_tasks = pre_tasks
            else:
                passthrough_pre_tasks = []
            return (
                normalized_task_list,
                passthrough_options,
                passthrough_pre_tasks,
            )
        return normalize_task_execution_payload(
            task_list,
            task_options,
            worker.interface,
            pre_tasks,
        )

    def _decode_job(self, job) -> ScheduledTask:
        """将 APS job 解码为 ScheduledTask。"""
        return decode_job_to_scheduled_task(
            job,
            normalize=self._normalize_task_payload,
        )

    def _desired_wakeup(self, wakeup_enabled: bool, enabled: bool) -> bool:
        """仅当唤醒开启且任务启用时才注册原生调度。"""
        return bool(wakeup_enabled) and bool(enabled)

    def _register_native(self, task: ScheduledTask) -> None:
        """向系统调度注册原生唤醒（后端未注入则跳过）。"""
        if self._system_scheduler is None:
            return
        self._system_scheduler.register(task)

    def _unregister_native(self, task_id: str) -> None:
        """取消系统原生唤醒注册。"""
        if self._system_scheduler is None:
            return
        self._system_scheduler.unregister(task_id)

    async def create_task(self, task_create: ScheduledTaskCreate) -> ScheduledTask:
        """创建定时任务；需唤醒时先注册原生再写入 APS。"""
        if not self.scheduler:
            raise RuntimeError("调度器未初始化")

        task_id = str(uuid.uuid4())
        normalized_task_list, normalized_task_options, normalized_pre_tasks = (
            self._normalize_task_payload(
                task_create.task_list,
                task_create.task_options,
                task_create.preTasks,
            )
        )
        if not normalized_task_list:
            raise ValueError("任务列表不能为空")

        now = datetime.now()
        task = ScheduledTask(
            id=task_id,
            name=task_create.name,
            description=task_create.description,
            enabled=task_create.enabled,
            trigger_config=task_create.trigger_config,
            controller_name=task_create.controller_name,
            device=task_create.device,
            resource_name=task_create.resource_name,
            task_list=normalized_task_list,
            task_options=normalized_task_options,
            preTasks=normalized_pre_tasks,
            wakeup_enabled=task_create.wakeup_enabled,
            created_at=now,
            updated_at=now,
        )

        # 先原生后 APS，避免注册失败时 APS 已写入
        if self._desired_wakeup(task.wakeup_enabled, task.enabled):
            self._register_native(task)

        trigger = build_trigger(task_create.trigger_config)
        self.scheduler.add_job(
            scheduled_job_fired,
            trigger,
            id=task_id,
            kwargs=encode_execution_kwargs(
                task_id=task_id,
                task_name=task_create.name,
                task_description=task_create.description,
                task_list=normalized_task_list,
                task_options=normalized_task_options,
                pre_tasks=normalized_pre_tasks,
                controller_name=task_create.controller_name,
                device=task_create.device,
                resource_name=task_create.resource_name,
                wakeup_enabled=task_create.wakeup_enabled,
                trigger_config=task_create.trigger_config,
            ),
        )
        if not task_create.enabled:
            self.scheduler.pause_job(task_id)

        job = self.scheduler.get_job(task_id)
        if job is None:
            raise RuntimeError(f"创建后无法读取任务: {task_id}")

        decoded = self._decode_job(job)
        logger.info("创建定时任务: %s (%s)", decoded.name, task_id)
        return decoded

    async def get_task(self, task_id: str) -> Optional[ScheduledTask]:
        """按 id 读取并解码单个 APS 任务。"""
        if not self.scheduler:
            return None
        job = self.scheduler.get_job(task_id)
        if not job:
            return None
        return self._decode_job(job)

    async def get_all_tasks(self) -> list[ScheduledTask]:
        """列出全部任务；无法解码的旧/坏 job 跳过（只读路径不删除）。"""
        if not self.scheduler:
            return []
        tasks: list[ScheduledTask] = []
        for job in self.scheduler.get_jobs():
            try:
                tasks.append(self._decode_job(job))
            except Exception:
                # 只读路径不删除 job，避免误删；返回列表直接跳过坏 job
                logger.warning("跳过无法解码的调度任务 %s", job.id, exc_info=True)
                continue
        return tasks

    async def update_task(
        self, task_id: str, task_update: ScheduledTaskUpdate
    ) -> Optional[ScheduledTask]:
        """合并更新；原生注册变更优先于 APS 修改。"""
        if not self.scheduler:
            return None
        job = self.scheduler.get_job(task_id)
        if not job:
            return None

        try:
            current = self._decode_job(job)
            current_kwargs = job.kwargs or {}

            if task_update.trigger_config is not None:
                new_trigger_config = task_update.trigger_config
                trigger_changed = True
            else:
                try:
                    _, new_trigger_config = decode_trigger(job.trigger)
                except Exception as exc:
                    raise SchedulerJobDecodeError(
                        f"trigger decode failed: {exc}",
                        job_id=task_id,
                        cause=exc,
                    ) from exc
                trigger_changed = False

            new_name = (
                task_update.name
                if task_update.name is not None
                else current_kwargs.get("task_name", current.name)
            )
            new_description = (
                task_update.description
                if task_update.description is not None
                else current_kwargs.get("task_description", current.description)
            )
            new_task_list = (
                task_update.task_list
                if task_update.task_list is not None
                else current_kwargs.get("task_list", current.task_list)
            )
            new_options = (
                task_update.task_options
                if task_update.task_options is not None
                else current_kwargs.get("task_options", current.task_options)
            )
            new_pre_tasks = (
                task_update.preTasks
                if task_update.preTasks is not None
                else decode_pre_tasks_from_job_kwargs(current_kwargs)
            )
            updated_fields = task_update.model_fields_set
            new_controller_name = (
                task_update.controller_name
                if "controller_name" in updated_fields
                else current_kwargs.get("controller_name", current.controller_name)
            )
            if "device" in updated_fields:
                new_device = task_update.device
            else:
                new_device = current_kwargs.get("device", current.device)
            new_resource_name = (
                task_update.resource_name
                if "resource_name" in updated_fields
                else current_kwargs.get("resource_name", current.resource_name)
            )
            if "wakeup_enabled" in updated_fields:
                new_wakeup = bool(task_update.wakeup_enabled)
            else:
                new_wakeup = current.wakeup_enabled

            if task_update.enabled is not None:
                new_enabled = bool(task_update.enabled)
            else:
                # 暂停时 next_run_time 为 None
                new_enabled = job.next_run_time is not None

            normalized_task_list, normalized_task_options, normalized_pre_tasks = (
                self._normalize_task_payload(
                    new_task_list,
                    new_options,
                    new_pre_tasks,
                )
            )
            if not normalized_task_list:
                raise ValueError("任务列表不能为空")

            old_desired = self._desired_wakeup(current.wakeup_enabled, current.enabled)
            new_desired = self._desired_wakeup(new_wakeup, new_enabled)
            native_relevant = (
                trigger_changed
                or ("wakeup_enabled" in updated_fields)
                or (task_update.enabled is not None)
            )

            if isinstance(new_device, ScheduledTaskDeviceConfig):
                device_obj: ScheduledTaskDeviceConfig | None = new_device
            elif isinstance(new_device, dict):
                device_obj = ScheduledTaskDeviceConfig(**new_device)
            else:
                device_obj = None

            tentative = ScheduledTask(
                id=task_id,
                name=new_name,
                description=new_description,
                enabled=new_enabled,
                trigger_config=new_trigger_config,
                controller_name=new_controller_name,
                device=device_obj,
                resource_name=new_resource_name,
                task_list=normalized_task_list,
                task_options=normalized_task_options,
                preTasks=normalized_pre_tasks,
                wakeup_enabled=new_wakeup,
            )

            if native_relevant and self._system_scheduler is not None:
                if new_desired and (not old_desired or trigger_changed):
                    # 先改原生再改 APS，保证冷启动与触发一致
                    self._register_native(tentative)
                elif old_desired and not new_desired:
                    self._unregister_native(task_id)

            trigger = build_trigger(new_trigger_config)
            modify_kwargs: dict[str, Any] = {
                "trigger": trigger,
                "kwargs": encode_execution_kwargs(
                    task_id=task_id,
                    task_name=new_name,
                    task_description=new_description,
                    task_list=normalized_task_list,
                    task_options=normalized_task_options,
                    pre_tasks=normalized_pre_tasks,
                    controller_name=new_controller_name,
                    device=new_device,
                    resource_name=new_resource_name,
                    wakeup_enabled=new_wakeup,
                    trigger_config=new_trigger_config,
                ),
            }
            # modify_job(trigger=...) 不会重算 next_run_time，需手动设定；
            # 仅当任务处于启用态（next_run_time 非 None）时设定，避免误反暂停
            if job.next_run_time is not None:
                modify_kwargs["next_run_time"] = trigger.get_next_fire_time(
                    None, datetime.now(self.scheduler.timezone)
                )
            self.scheduler.modify_job(task_id, **modify_kwargs)

            if task_update.enabled is not None:
                if task_update.enabled:
                    self.scheduler.resume_job(task_id)
                else:
                    self.scheduler.pause_job(task_id)

            return await self.get_task(task_id)
        except SchedulerJobDecodeError:
            raise
        except (ValueError, RuntimeError):
            raise
        except Exception as e:
            logger.error("更新任务失败: %s", e)
            worker = self._worker
            if worker:
                worker.events.send_log(f"更新任务失败: {e}")
            return None

    async def delete_task(self, task_id: str) -> bool:
        """删除任务：若在原生注册中则先注销，再移除 APS job。

        解码失败不得阻断删除——否则会留下「不可见、不可删、仍触发」的僵尸任务。
        解码仅为决定是否需要注销原生唤醒；解码失败时防御性尝试注销（无法判断
        是否存在原生注册，若残留则机器会持续唤醒），再移除 APS job。
        """
        if not self.scheduler:
            return False
        try:
            job = self.scheduler.get_job(task_id)
            if job is None:
                return False
            try:
                task = self._decode_job(job)
            except Exception:
                logger.warning(
                    "delete_task: 解码 job 失败，仍尝试注销原生并移除 APS job: %s",
                    task_id,
                    exc_info=True,
                )
                try:
                    self._unregister_native(task_id)
                except Exception:
                    logger.warning(
                        "delete_task: 注销原生唤醒失败（job 不可解码）: %s",
                        task_id,
                        exc_info=True,
                    )
                self.scheduler.remove_job(task_id)
                logger.info("删除无法解码的定时任务: %s", task_id)
                return True
            if self._desired_wakeup(task.wakeup_enabled, task.enabled):
                self._unregister_native(task_id)
            self.scheduler.remove_job(task_id)
            logger.info("删除定时任务: %s", task_id)
            return True
        except JobLookupError:
            return False
        except Exception as e:
            logger.error("删除任务失败: %s", e)
            worker = self._worker
            if worker:
                worker.events.send_log(f"删除任务失败: {e}")
            return False

    async def pause_task(self, task_id: str) -> bool:
        """暂停任务；当前需要原生唤醒时先注销再 pause。

        解码失败不得阻断暂停——否则暂停态的 job 仍可能被 OS 唤醒。
        解码失败时防御性尝试注销原生（无法判断是否存在，残留则 OS 会绕过
        暂停继续唤醒），再 pause APS job。
        """
        if not self.scheduler:
            return False
        try:
            job = self.scheduler.get_job(task_id)
            if job is None:
                return False
            try:
                task = self._decode_job(job)
            except Exception:
                logger.warning(
                    "pause_task: 解码 job 失败，仍尝试注销原生并暂停 APS job: %s",
                    task_id,
                    exc_info=True,
                )
                try:
                    self._unregister_native(task_id)
                except Exception:
                    logger.warning(
                        "pause_task: 注销原生唤醒失败（job 不可解码）: %s",
                        task_id,
                        exc_info=True,
                    )
                self.scheduler.pause_job(task_id)
                logger.info("暂停无法解码的定时任务: %s", task_id)
                return True
            # 暂停后不应再被 OS 唤醒
            if self._desired_wakeup(task.wakeup_enabled, task.enabled):
                self._unregister_native(task_id)
            self.scheduler.pause_job(task_id)
            logger.info("暂停定时任务: %s", task_id)
            return True
        except JobLookupError:
            return False
        except Exception as e:
            logger.error("暂停任务失败: %s", e)
            worker = self._worker
            if worker:
                worker.events.send_log(f"暂停任务失败: {e}")
            return False

    async def resume_task(self, task_id: str) -> bool:
        """恢复任务；开启唤醒时先注册原生再 resume。

        解码失败不得阻断恢复，但无法判断 wakeup_enabled——为安全起见跳过原生
        注册（避免给本不该唤醒的任务挂上系统唤醒），仅恢复 APS job 并记录警告。
        """
        if not self.scheduler:
            return False
        try:
            job = self.scheduler.get_job(task_id)
            if job is None:
                return False
            try:
                task = self._decode_job(job)
            except Exception:
                logger.warning(
                    "resume_task: 解码 job 失败，原生唤醒未恢复（wakeup_enabled 未知），"
                    "仅恢复 APS job: %s",
                    task_id,
                    exc_info=True,
                )
                self.scheduler.resume_job(task_id)
                logger.info("恢复无法解码的定时任务（原生唤醒未恢复）: %s", task_id)
                return True
            # 恢复后需重新挂上系统唤醒
            if task.wakeup_enabled:
                self._register_native(task)
            self.scheduler.resume_job(task_id)
            logger.info("恢复定时任务: %s", task_id)
            return True
        except JobLookupError:
            return False
        except Exception as e:
            logger.error("恢复任务失败: %s", e)
            worker = self._worker
            if worker:
                worker.events.send_log(f"恢复任务失败: {e}")
            return False
