"""APS 任务 CRUD 与生命周期；准入控制在 ExecutionCoordinator。"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import tzlocal
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
    decode_trigger,
    encode_execution_kwargs,
)
from services.system_scheduler import SystemScheduler

logger = logging.getLogger(__name__)


async def scheduled_job_fired(**kwargs: Any) -> None:
    """APS 任务入口：解码后交给 ExecutionCoordinator。

    wakeup 任务由系统原生调度负责，应用内触发直接跳过。
    """
    try:
        import main as main_mod
    except Exception:
        logger.error("scheduled_job_fired: 无法导入 main，跳过派发")
        return

    app_state = getattr(main_mod, "app_state", None)
    if app_state is None:
        logger.error("scheduled_job_fired: app_state 不可用")
        return

    coordinator = getattr(app_state, "execution_coordinator", None)
    manager = getattr(app_state, "scheduler_manager", None)
    if coordinator is None or manager is None:
        logger.error("scheduled_job_fired: coordinator/manager 未初始化，跳过")
        return

    task_id = kwargs.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        logger.error("scheduled_job_fired: 缺少 task_id")
        return

    try:
        task = await manager.get_task(task_id)
    except Exception as e:
        logger.error("scheduled_job_fired: 解码任务 %s 失败: %s", task_id, e)
        return

    if task is None:
        logger.error("scheduled_job_fired: 任务不存在 %s", task_id)
        return

    # 原生唤醒任务不在此路径执行，避免与 OS 调度重复派发
    if task.wakeup_enabled:
        logger.info(
            "scheduled_job_fired: skip in-app dispatch for wakeup task %s "
            "(native owns execution)",
            task_id,
        )
        return

    try:
        await coordinator.submit_scheduled(task, origin="in_app")
    except Exception as e:
        logger.error("scheduled_job_fired: 提交执行失败 %s: %s", task_id, e)


class SchedulerManager:
    """APS 任务 CRUD/生命周期；系统唤醒经 SystemScheduler 注册。"""

    def __init__(
        self,
        db_path: Path,
        system_scheduler: SystemScheduler | None = None,
    ) -> None:
        self.scheduler: Optional[AsyncIOScheduler] = None
        self._worker = None
        self._db_path = Path(db_path)
        self._system_scheduler = system_scheduler

    def set_worker(self, worker) -> None:
        self._worker = worker

    def set_system_scheduler(self, system_scheduler: SystemScheduler | None) -> None:
        """注入跨平台系统调度后端（可为空）。"""
        self._system_scheduler = system_scheduler

    async def initialize(self, *, paused: bool = True) -> None:
        """启动 APS；db_path 由 main 注入，paused 时先不派发。"""
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
        """关闭 APS 并清空引用。"""
        if self.scheduler:
            self.scheduler.shutdown()
            logger.info("调度器已关闭")
            self.scheduler = None

    def _normalize_task_payload(
        self,
        task_list: Any,
        task_options: Any,
        pre_tasks: Any = None,
    ) -> tuple[list[str], TaskOptionsByTask, list]:
        """按 interface 规范化任务载荷；无 worker 时仅做去重。"""
        if not self._worker or not getattr(self._worker, "interface", None):
            normalized_task_list: list[str] = []
            if isinstance(task_list, list):
                seen_task_ids: set[str] = set()
                for task_id in task_list:
                    if not isinstance(task_id, str) or task_id in seen_task_ids:
                        continue
                    normalized_task_list.append(task_id)
                    seen_task_ids.add(task_id)
            return (
                normalized_task_list,
                {tid: {} for tid in normalized_task_list},
                [],
            )
        return normalize_task_execution_payload(
            task_list,
            task_options,
            self._worker.interface,
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
        """列出全部任务；无法解码的旧/坏 job 直接删除。"""
        if not self.scheduler:
            return []
        tasks: list[ScheduledTask] = []
        for job in self.scheduler.get_jobs():
            try:
                tasks.append(self._decode_job(job))
            except SchedulerJobDecodeError:
                # 不伪造兜底配置，删除后由用户重建
                logger.warning("删除无法解码的调度任务 %s", job.id, exc_info=True)
                job.remove()
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
            self.scheduler.modify_job(
                task_id,
                trigger=trigger,
                kwargs=encode_execution_kwargs(
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
            )

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
            if self._worker:
                self._worker.events.send_log(f"更新任务失败: {e}")
            return None

    async def delete_task(self, task_id: str) -> bool:
        """删除任务：若在原生注册中则先注销，再移除 APS job。"""
        if not self.scheduler:
            return False
        try:
            job = self.scheduler.get_job(task_id)
            if job is None:
                return False
            task = self._decode_job(job)
            if self._desired_wakeup(task.wakeup_enabled, task.enabled):
                self._unregister_native(task_id)
            self.scheduler.remove_job(task_id)
            logger.info("删除定时任务: %s", task_id)
            return True
        except Exception as e:
            name = type(e).__name__
            if name == "JobLookupError" or "JobLookupError" in name:
                return False
            logger.error("删除任务失败: %s", e)
            if self._worker:
                self._worker.events.send_log(f"删除任务失败: {e}")
            return False

    async def pause_task(self, task_id: str) -> bool:
        """暂停任务；当前需要原生唤醒时先注销再 pause。"""
        if not self.scheduler:
            return False
        try:
            job = self.scheduler.get_job(task_id)
            if job is None:
                return False
            task = self._decode_job(job)
            # 暂停后不应再被 OS 唤醒
            if self._desired_wakeup(task.wakeup_enabled, task.enabled):
                self._unregister_native(task_id)
            self.scheduler.pause_job(task_id)
            logger.info("暂停定时任务: %s", task_id)
            return True
        except Exception as e:
            logger.error("暂停任务失败: %s", e)
            if self._worker:
                self._worker.events.send_log(f"暂停任务失败: {e}")
            return False

    async def resume_task(self, task_id: str) -> bool:
        """恢复任务；开启唤醒时先注册原生再 resume。"""
        if not self.scheduler:
            return False
        try:
            job = self.scheduler.get_job(task_id)
            if job is None:
                return False
            task = self._decode_job(job)
            # 恢复后需重新挂上系统唤醒
            if task.wakeup_enabled:
                self._register_native(task)
            self.scheduler.resume_job(task_id)
            logger.info("恢复定时任务: %s", task_id)
            return True
        except Exception as e:
            logger.error("恢复任务失败: %s", e)
            if self._worker:
                self._worker.events.send_log(f"恢复任务失败: {e}")
            return False
