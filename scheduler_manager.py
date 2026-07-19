"""APS job CRUD + lifecycle. Execution admission lives in ExecutionCoordinator."""

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
    """APS job entry: decode task and hand off to ExecutionCoordinator."""
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

    try:
        await coordinator.submit_scheduled(task, origin="in_app")
    except Exception as e:
        logger.error("scheduled_job_fired: 提交执行失败 %s: %s", task_id, e)


class SchedulerManager:
    """APScheduler CRUD and lifecycle; native wakeup via SystemScheduler."""

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
        self._system_scheduler = system_scheduler

    async def initialize(self, *, paused: bool = True) -> None:
        """Start APS (optionally paused). Absolute db_path is injected by main."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        db_url = f"sqlite:///{self._db_path.resolve().as_posix()}"
        self.scheduler = AsyncIOScheduler(
            jobstores={"default": SQLAlchemyJobStore(url=db_url)},
            job_defaults={
                "misfire_grace_time": 900,
                "coalesce": True,
                "max_instances": 1,
            },
            timezone=tzlocal.get_localzone(),
        )
        self.scheduler.start(paused=paused)
        # 旧格式 job 重置：反序列化失败（如旧 headless 回调引用）→ 清空，用户重建
        try:
            self.scheduler.get_jobs()
        except Exception:
            logger.warning(
                "检测到旧格式调度任务，已清空（请重建计划任务）", exc_info=True
            )
            self.scheduler.remove_all_jobs()
        if paused:
            logger.info("调度器已启动（paused）")
        else:
            logger.info("调度器已启动")

    def resume(self) -> None:
        if self.scheduler is not None:
            self.scheduler.resume()
            logger.info("调度器已恢复派发")

    async def shutdown(self) -> None:
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
        return decode_job_to_scheduled_task(
            job,
            normalize=self._normalize_task_payload,
        )

    def _desired_wakeup(self, wakeup_enabled: bool, enabled: bool) -> bool:
        return bool(wakeup_enabled) and bool(enabled)

    def _register_native(self, task: ScheduledTask) -> None:
        if self._system_scheduler is None:
            return
        self._system_scheduler.register(task)

    def _unregister_native(self, task_id: str, *, warn_only: bool = False) -> None:
        if self._system_scheduler is None:
            return
        try:
            self._system_scheduler.unregister(task_id)
        except Exception as e:
            if warn_only:
                logger.warning("native unregister 失败 %s: %s", task_id, e)
            else:
                raise

    async def create_task(self, task_create: ScheduledTaskCreate) -> ScheduledTask:
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

        # Native first so APS is untouched on register failure.
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
        if not self.scheduler:
            return None
        job = self.scheduler.get_job(task_id)
        if not job:
            return None
        return self._decode_job(job)

    async def get_all_tasks(self) -> list[ScheduledTask]:
        if not self.scheduler:
            return []
        tasks: list[ScheduledTask] = []
        for job in self.scheduler.get_jobs():
            try:
                tasks.append(self._decode_job(job))
            except SchedulerJobDecodeError:
                # 恶构/旧格式 job：删除并显式记录（不伪造兜底，用户重建）
                logger.warning("删除无法解码的调度任务 %s", job.id, exc_info=True)
                job.remove()
        return tasks

    async def update_task(
        self, task_id: str, task_update: ScheduledTaskUpdate
    ) -> Optional[ScheduledTask]:
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
                # APS: next_run_time is None when paused
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
                    # register / re-register before APS mutation
                    self._register_native(tentative)
                elif old_desired and not new_desired:
                    self._unregister_native(task_id, warn_only=False)

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
        """Remove APS job, then best-effort native unregister."""
        if not self.scheduler:
            return False
        try:
            existing = self.scheduler.get_job(task_id)
            if existing is None:
                self._unregister_native(task_id, warn_only=True)
                return True
            self.scheduler.remove_job(task_id)
        except Exception as e:
            name = type(e).__name__
            if name == "JobLookupError" or "JobLookupError" in name:
                self._unregister_native(task_id, warn_only=True)
                return True
            logger.error("删除任务失败: %s", e)
            if self._worker:
                self._worker.events.send_log(f"删除任务失败: {e}")
            return False

        self._unregister_native(task_id, warn_only=True)
        logger.info("删除定时任务: %s", task_id)
        return True

    async def pause_task(self, task_id: str) -> bool:
        if not self.scheduler:
            return False
        try:
            job = self.scheduler.get_job(task_id)
            if job is None:
                return False
            task = self._decode_job(job)
            self.scheduler.pause_job(task_id)
            if task.wakeup_enabled:
                self._unregister_native(task_id, warn_only=True)
            logger.info("暂停定时任务: %s", task_id)
            return True
        except Exception as e:
            logger.error("暂停任务失败: %s", e)
            if self._worker:
                self._worker.events.send_log(f"暂停任务失败: {e}")
            return False

    async def resume_task(self, task_id: str) -> bool:
        if not self.scheduler:
            return False
        try:
            job = self.scheduler.get_job(task_id)
            if job is None:
                return False
            task = self._decode_job(job)
            if task.wakeup_enabled:
                # Fail closed: do not resume APS if native register fails
                self._register_native(task)
            self.scheduler.resume_job(task_id)
            logger.info("恢复定时任务: %s", task_id)
            return True
        except Exception as e:
            logger.error("恢复任务失败: %s", e)
            if self._worker:
                self._worker.events.send_log(f"恢复任务失败: {e}")
            return False
