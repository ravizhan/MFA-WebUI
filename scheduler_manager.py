import asyncio
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Literal

import aiosqlite
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from apscheduler.triggers.interval import IntervalTrigger

from models.scheduler import (
    ScheduledTask,
    ScheduledTaskCreate,
    ScheduledTaskUpdate,
    TaskExecution,
    TaskOptionValue,
    TriggerConfig,
    CronTriggerConfig,
    DateTriggerConfig,
    IntervalTriggerConfig,
)

logger = logging.getLogger(__name__)
EXECUTIONS_MAX_RECORDS = 1000
_ACTIVE_MANAGER = None


async def execute_scheduled_task(
    task_id: str,
    task_name: str,
    task_description: str,
    task_list: List[str],
    task_options: Dict[str, TaskOptionValue],
):
    """APScheduler 可持久化执行入口"""
    if _ACTIVE_MANAGER is None:
        logger.error(f"调度器管理器未就绪，跳过定时任务 {task_id}")
        return
    await _ACTIVE_MANAGER._execute_task(
        task_id=task_id,
        task_name=task_name,
        _task_description=task_description,
        task_list=task_list,
        task_options=task_options,
    )


class SchedulerManager:
    """调度器管理器"""

    def __init__(self):
        self.scheduler: Optional[AsyncIOScheduler] = None
        self._worker = None
        self._executions_lock = asyncio.Lock()
        self._db_path = Path("config") / "scheduler.sqlite"

    def set_worker(self, worker):
        """设置 MaaWorker 实例"""
        self._worker = worker

    async def initialize(self):
        """初始化调度器"""
        global _ACTIVE_MANAGER
        _ACTIVE_MANAGER = self

        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        await self._initialize_executions_table()

        db_url = f"sqlite:///{self._db_path.resolve().as_posix()}"
        self.scheduler = AsyncIOScheduler(
            jobstores={"default": SQLAlchemyJobStore(url=db_url)}
        )

        # 启动调度器
        self.scheduler.start()
        logger.info("调度器已启动")

    async def shutdown(self):
        """关闭调度器"""
        global _ACTIVE_MANAGER
        if self.scheduler:
            self.scheduler.shutdown()
            logger.info("调度器已关闭")
        if _ACTIVE_MANAGER is self:
            _ACTIVE_MANAGER = None

    async def _initialize_executions_table(self):
        """初始化执行历史数据表"""
        async with aiosqlite.connect(self._db_path) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduler_executions (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    task_name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    status TEXT NOT NULL,
                    error_message TEXT
                )
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_scheduler_executions_started_at
                ON scheduler_executions(started_at DESC)
                """
            )
            await db.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_scheduler_executions_task_id
                ON scheduler_executions(task_id)
                """
            )
            await db.commit()

    def _create_trigger(self, trigger_config: TriggerConfig):
        """根据配置创建触发器"""
        if isinstance(trigger_config, CronTriggerConfig):
            # 解析 cron 表达式
            parts = trigger_config.cron.split()
            if len(parts) != 5:
                raise ValueError(f"无效的 Cron 表达式: {trigger_config.cron}")
            minute, hour, day, month, day_of_week = parts
            return CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
            )
        elif isinstance(trigger_config, DateTriggerConfig):
            return DateTrigger(run_date=trigger_config.run_date)
        elif isinstance(trigger_config, IntervalTriggerConfig):
            return IntervalTrigger(
                weeks=trigger_config.weeks or 0,
                days=trigger_config.days or 0,
                hours=trigger_config.hours or 0,
                minutes=trigger_config.minutes or 0,
                seconds=trigger_config.seconds or 0,
                start_date=trigger_config.start_date,
                end_date=trigger_config.end_date,
            )
        else:
            raise ValueError(f"未知的触发器类型: {type(trigger_config)}")

    async def _execute_task(
        self,
        task_id: str,
        task_name: str,
        _task_description: str,
        task_list: List[str],
        task_options: Dict[str, TaskOptionValue],
    ):
        """执行定时任务"""
        logger.info(f"开始执行定时任务: {task_id}")

        # 创建执行记录
        execution_id = str(uuid.uuid4())
        execution = TaskExecution(
            id=execution_id,
            task_id=task_id,
            task_name=task_name,
            started_at=datetime.now(),
            status="running",
            finished_at=None,
            error_message=None,
        )
        await self._add_execution(execution)

        try:
            # 检查是否有任务正在运行
            if self._worker and self._worker.running:
                logger.warning(f"任务已在运行，跳过定时任务 {task_id}")
                await self._update_execution_status(
                    execution_id, "stopped", "任务已在运行"
                )
                return

            # 检查设备是否已连接
            if not self._worker or not self._worker.connected:
                logger.error(f"设备未连接，无法执行定时任务 {task_id}")
                await self._update_execution_status(
                    execution_id, "failed", "设备未连接"
                )
                return

            # 启动任务
            if not self._worker.start_task(
                task_list, task_options, task_name=task_name
            ):
                logger.warning(f"任务已在运行，跳过定时任务 {task_id}")
                await self._update_execution_status(
                    execution_id, "stopped", "任务已在运行"
                )
                return

            # 等待任务完成
            while self._worker and self._worker.running:
                await asyncio.sleep(1)

            task_status = getattr(self._worker, "last_task_status", "failed")
            task_error = getattr(self._worker, "last_task_error", None)

            if task_status == "success":
                await self._update_execution_status(execution_id, "success")
                logger.info(f"定时任务 {task_id} 执行成功")
            elif task_status == "stopped":
                await self._update_execution_status(
                    execution_id, "stopped", task_error or "任务已终止"
                )
                logger.warning(f"定时任务 {task_id} 已停止")
            else:
                await self._update_execution_status(
                    execution_id, "failed", task_error or "任务执行失败"
                )
                logger.error(f"定时任务 {task_id} 执行失败: {task_error}")

        except Exception as e:
            logger.error(f"定时任务 {task_id} 执行失败: {e}")
            await self._update_execution_status(execution_id, "failed", str(e))

    def _build_trigger_config(
        self, trigger
    ) -> tuple[Literal["cron", "date", "interval"], TriggerConfig]:
        """从 APScheduler trigger 重建触发器类型与配置"""
        if isinstance(trigger, CronTrigger):
            field_map = {field.name: str(field) for field in trigger.fields}
            cron = " ".join(
                [
                    field_map.get("minute", "*"),
                    field_map.get("hour", "*"),
                    field_map.get("day", "*"),
                    field_map.get("month", "*"),
                    field_map.get("day_of_week", "*"),
                ]
            )
            return "cron", CronTriggerConfig(cron=cron)

        if isinstance(trigger, DateTrigger):
            run_date = getattr(trigger, "run_date", None)
            if run_date is None:
                raise ValueError("DateTrigger 缺少 run_date")
            return "date", DateTriggerConfig(run_date=run_date)

        if isinstance(trigger, IntervalTrigger):
            interval = getattr(trigger, "interval", None)
            total_seconds = int(interval.total_seconds()) if interval is not None else 0

            week_seconds = 7 * 24 * 60 * 60
            day_seconds = 24 * 60 * 60

            weeks, remainder = divmod(total_seconds, week_seconds)
            days, remainder = divmod(remainder, day_seconds)
            hours, remainder = divmod(remainder, 60 * 60)
            minutes, seconds = divmod(remainder, 60)

            return "interval", IntervalTriggerConfig(
                weeks=weeks or None,
                days=days or None,
                hours=hours or None,
                minutes=minutes or None,
                seconds=seconds or None,
                start_date=getattr(trigger, "start_date", None),
                end_date=getattr(trigger, "end_date", None),
            )

        raise ValueError(f"未知的触发器类型: {type(trigger)}")

    async def _add_execution(self, execution: TaskExecution):
        """添加执行记录"""
        async with self._executions_lock:
            async with aiosqlite.connect(self._db_path) as db:
                await db.execute(
                    """
                    INSERT INTO scheduler_executions
                    (id, task_id, task_name, started_at, finished_at, status, error_message)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        execution.id,
                        execution.task_id,
                        execution.task_name,
                        execution.started_at.isoformat(),
                        execution.finished_at.isoformat()
                        if execution.finished_at
                        else None,
                        execution.status,
                        execution.error_message,
                    ),
                )
                await db.execute(
                    """
                    DELETE FROM scheduler_executions
                    WHERE id NOT IN (
                        SELECT id FROM scheduler_executions
                        ORDER BY started_at DESC, id DESC
                        LIMIT ?
                    )
                    """,
                    (EXECUTIONS_MAX_RECORDS,),
                )
                await db.commit()

    async def _update_execution_status(
        self,
        execution_id: str,
        status: Literal["running", "success", "failed", "stopped"],
        error_message: Optional[str] = None,
    ):
        """更新执行记录状态"""
        async with self._executions_lock:
            async with aiosqlite.connect(self._db_path) as db:
                finished_at = datetime.now().isoformat()
                if error_message is None:
                    await db.execute(
                        """
                        UPDATE scheduler_executions
                        SET status = ?, finished_at = ?
                        WHERE id = ?
                        """,
                        (status, finished_at, execution_id),
                    )
                else:
                    await db.execute(
                        """
                        UPDATE scheduler_executions
                        SET status = ?, finished_at = ?, error_message = ?
                        WHERE id = ?
                        """,
                        (status, finished_at, error_message, execution_id),
                    )
                await db.commit()

    async def create_task(self, task_create: ScheduledTaskCreate) -> ScheduledTask:
        """创建定时任务"""
        if not self.scheduler:
            raise RuntimeError("调度器未初始化")

        task_id = str(uuid.uuid4())
        trigger = self._create_trigger(task_create.trigger_config)

        # 添加任务到调度器，存储完整的任务信息
        self.scheduler.add_job(
            execute_scheduled_task,
            trigger,
            id=task_id,
            kwargs={
                "task_id": task_id,
                "task_name": task_create.name,
                "task_description": task_create.description or "",
                "task_list": task_create.task_list,
                "task_options": task_create.task_options,
            },
        )

        # 如果任务未启用，则暂停
        if not task_create.enabled:
            self.scheduler.pause_job(task_id)

        # 获取下次执行时间
        job = self.scheduler.get_job(task_id)
        next_run_time = job.next_run_time if job else None

        # 创建任务对象
        task = ScheduledTask(
            id=task_id,
            name=task_create.name,
            description=task_create.description,
            enabled=task_create.enabled,
            trigger_type=task_create.trigger_type,
            trigger_config=task_create.trigger_config,
            task_list=task_create.task_list,
            task_options=task_create.task_options,
            next_run_time=next_run_time,
        )

        logger.info(f"创建定时任务: {task.name} ({task_id})")
        return task

    async def get_task(self, task_id: str) -> Optional[ScheduledTask]:
        """获取定时任务"""
        if not self.scheduler:
            return None
        job = self.scheduler.get_job(task_id)
        if not job:
            return None

        # 从 kwargs 中获取任务信息
        task_name = job.kwargs.get("task_name", "")
        task_description = job.kwargs.get("task_description", "")
        task_list = job.kwargs.get("task_list", [])
        task_options = job.kwargs.get("task_options", {})
        trigger_type: Literal["cron", "date", "interval"]

        try:
            trigger_type, trigger_config = self._build_trigger_config(job.trigger)
        except Exception as e:
            logger.warning(f"重建触发器配置失败，使用默认 cron 配置: {e}")
            trigger_type = "cron"
            trigger_config = CronTriggerConfig(cron="* * * * *")

        return ScheduledTask(
            id=task_id,
            name=task_name,
            description=task_description,
            enabled=job.next_run_time is not None,
            trigger_type=trigger_type,
            trigger_config=trigger_config,
            task_list=task_list,
            task_options=task_options,
            next_run_time=job.next_run_time,
        )

    async def get_all_tasks(self) -> List[ScheduledTask]:
        """获取所有定时任务"""
        if not self.scheduler:
            return []
        tasks = []
        jobs = self.scheduler.get_jobs()

        for job in jobs:
            task_name = job.kwargs.get("task_name", "")
            task_description = job.kwargs.get("task_description", "")
            task_list = job.kwargs.get("task_list", [])
            task_options = job.kwargs.get("task_options", {})
            trigger_type: Literal["cron", "date", "interval"]

            try:
                trigger_type, trigger_config = self._build_trigger_config(job.trigger)
            except Exception as e:
                logger.warning(
                    f"重建任务 {job.id} 的触发器配置失败，使用默认 cron 配置: {e}"
                )
                trigger_type = "cron"
                trigger_config = CronTriggerConfig(cron="* * * * *")

            task = ScheduledTask(
                id=job.id,
                name=task_name,
                description=task_description,
                enabled=job.next_run_time is not None,
                trigger_type=trigger_type,
                trigger_config=trigger_config,
                task_list=task_list,
                task_options=task_options,
                next_run_time=job.next_run_time,
            )
            tasks.append(task)

        return tasks

    async def update_task(
        self, task_id: str, task_update: ScheduledTaskUpdate
    ) -> Optional[ScheduledTask]:
        """更新定时任务"""
        if not self.scheduler:
            logger.error("调度器未初始化")
            return None
        job = self.scheduler.get_job(task_id)
        if not job:
            logger.error(f"任务不存在: {task_id}")
            return None

        try:
            # 获取当前任务信息
            current_kwargs = job.kwargs

            try:
                _, current_trigger_config = self._build_trigger_config(job.trigger)
            except Exception as e:
                logger.warning(f"重建当前触发器配置失败，使用默认 cron 配置: {e}")
                current_trigger_config = CronTriggerConfig(cron="* * * * *")

            # 合并更新数据
            new_name = (
                task_update.name
                if task_update.name is not None
                else current_kwargs.get("task_name", "")
            )
            new_description = (
                task_update.description
                if task_update.description is not None
                else current_kwargs.get("task_description", "")
            )
            new_task_list = (
                task_update.task_list
                if task_update.task_list is not None
                else current_kwargs.get("task_list", [])
            )
            new_options = (
                task_update.task_options
                if task_update.task_options is not None
                else current_kwargs.get("task_options", {})
            )

            new_trigger_config = (
                task_update.trigger_config
                if task_update.trigger_config is not None
                else current_trigger_config
            )

            # 创建新的触发器
            trigger = self._create_trigger(new_trigger_config)

            # 修改任务
            self.scheduler.modify_job(
                task_id,
                trigger=trigger,
                kwargs={
                    "task_id": task_id,
                    "task_name": new_name,
                    "task_description": new_description,
                    "task_list": new_task_list,
                    "task_options": new_options,
                },
            )

            # 处理启用/暂停状态
            if task_update.enabled is not None:
                if task_update.enabled:
                    self.scheduler.resume_job(task_id)
                else:
                    self.scheduler.pause_job(task_id)

            # 获取更新后的任务
            return await self.get_task(task_id)
        except Exception as e:
            logger.error(f"更新任务失败: {e}")
            return None

    async def delete_task(self, task_id: str) -> bool:
        """删除定时任务"""
        if not self.scheduler:
            return False
        try:
            self.scheduler.remove_job(task_id)
            logger.info(f"删除定时任务: {task_id}")
            return True
        except Exception as e:
            logger.error(f"删除任务失败: {e}")
            return False

    async def pause_task(self, task_id: str) -> bool:
        """暂停定时任务"""
        if not self.scheduler:
            return False
        try:
            self.scheduler.pause_job(task_id)
            logger.info(f"暂停定时任务: {task_id}")
            return True
        except Exception as e:
            logger.error(f"暂停任务失败: {e}")
            return False

    async def resume_task(self, task_id: str) -> bool:
        """恢复定时任务"""
        if not self.scheduler:
            return False
        try:
            self.scheduler.resume_job(task_id)
            logger.info(f"恢复定时任务: {task_id}")
            return True
        except Exception as e:
            logger.error(f"恢复任务失败: {e}")
            return False

    async def get_executions(self, limit: int = 50) -> List[TaskExecution]:
        """获取执行历史"""
        async with self._executions_lock:
            async with aiosqlite.connect(self._db_path) as db:
                cursor = await db.execute(
                    """
                    SELECT id, task_id, task_name, started_at, finished_at, status, error_message
                    FROM scheduler_executions
                    ORDER BY started_at DESC, id DESC
                    LIMIT ?
                    """,
                    (limit,),
                )
                rows = await cursor.fetchall()

        executions: List[TaskExecution] = []
        for row in rows:
            started_at = datetime.fromisoformat(row[3])
            finished_at = datetime.fromisoformat(row[4]) if row[4] else None
            executions.append(
                TaskExecution(
                    id=row[0],
                    task_id=row[1],
                    task_name=row[2],
                    started_at=started_at,
                    finished_at=finished_at,
                    status=row[5],
                    error_message=row[6],
                )
            )
        return executions
