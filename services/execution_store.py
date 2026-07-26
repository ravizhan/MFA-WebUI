"""调度执行记录的 SQLite 持久化"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List

from sqlalchemy import (
    String,
    create_engine,
    delete,
    func,
    select,
    update,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    sessionmaker,
)
from sqlalchemy.schema import Index

from models.scheduler import TaskExecution

logger = logging.getLogger(__name__)

EXECUTIONS_MAX_RECORDS = 1000


class _Base(DeclarativeBase):
    pass


class SchedulerExecution(_Base):
    """``scheduler_executions`` 历史表 ORM 实体。"""

    __tablename__ = "scheduler_executions"
    __table_args__ = (
        Index("idx_scheduler_executions_started_at", "started_at"),
        Index("idx_scheduler_executions_task_id", "task_id"),
    )

    id: Mapped[str] = mapped_column(String, primary_key=True)
    task_id: Mapped[str | None] = mapped_column(String, nullable=True)
    task_name: Mapped[str] = mapped_column(String, nullable=False)
    origin: Mapped[str] = mapped_column(String, nullable=False)
    occurrence_id: Mapped[str | None] = mapped_column(String, nullable=True)
    scheduled_for: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    blocker_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    blocker_task_name: Mapped[str | None] = mapped_column(String, nullable=True)
    error_message: Mapped[str | None] = mapped_column(String, nullable=True)
    started_at: Mapped[str] = mapped_column(String, nullable=False)
    finished_at: Mapped[str | None] = mapped_column(String, nullable=True)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _from_iso(value: str | None) -> datetime | None:
    if value is None:
        return None
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _orm_to_execution(row: SchedulerExecution) -> TaskExecution:
    return TaskExecution(
        id=row.id,
        task_id=row.task_id,
        task_name=row.task_name,
        origin=row.origin,  # type: ignore[arg-type]
        occurrence_id=row.occurrence_id,
        scheduled_for=_from_iso(row.scheduled_for),
        status=row.status,  # type: ignore[arg-type]
        blocker_run_id=row.blocker_run_id,
        blocker_task_name=row.blocker_task_name,
        error_message=row.error_message,
        started_at=_from_iso(row.started_at) or _utc_now(),
        finished_at=_from_iso(row.finished_at),
    )


def _execution_to_orm(execution: TaskExecution) -> SchedulerExecution:
    return SchedulerExecution(
        id=execution.id,
        task_id=execution.task_id,
        task_name=execution.task_name,
        origin=execution.origin,
        occurrence_id=execution.occurrence_id,
        scheduled_for=_to_iso(execution.scheduled_for),
        status=execution.status,
        blocker_run_id=execution.blocker_run_id,
        blocker_task_name=execution.blocker_task_name,
        error_message=execution.error_message,
        started_at=_to_iso(execution.started_at),
        finished_at=_to_iso(execution.finished_at),
    )


class ExecutionStore:
    """scheduler.sqlite 执行历史表的同步读写封装。"""

    def __init__(self, db_path: Path) -> None:
        self._db_path = Path(db_path)
        # check_same_thread=False：允许 asyncio.to_thread 跨线程共享 engine
        self._engine = create_engine(
            f"sqlite:///{self._db_path.resolve().as_posix()}",
            connect_args={"check_same_thread": False},
        )
        self._session_factory = sessionmaker(self._engine)

    def init(self) -> None:
        """创建表与索引，并崩溃恢复残留的 running 记录为 failed。

        进程异常退出（崩溃 / kill / 断电）后，残留的 ``status='running'`` 且
        ``finished_at IS NULL`` 的行会让后续入场永远 busy，故在此归档为
        ``failed`` 终态；仅在 ``error_message`` 当前为 NULL 时写入
        ``应用异常退出``，避免覆盖既有错误信息。
        """
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        _Base.metadata.create_all(self._engine)
        # 崩溃恢复：上次进程异常退出后，残留 running 行（finished_at IS NULL）
        # 会让后续入场永远 busy；归档为 failed 终态。
        finished_at = _to_iso(_utc_now())
        with self._session_factory() as session:
            result = session.execute(
                update(SchedulerExecution)
                .where(SchedulerExecution.finished_at.is_(None))
                .values(
                    status="failed",
                    finished_at=finished_at,
                    error_message=func.coalesce(
                        SchedulerExecution.error_message, "应用异常退出"
                    ),
                )
            )
            reconciled = result.rowcount  # type: ignore[attr-defined]
            session.commit()
        if reconciled > 0:
            logger.info(
                "execution_store: 崩溃恢复归档 %d 条残留 running 记录", reconciled
            )

    def add(self, execution: TaskExecution) -> None:
        """插入一条记录，并在同一事务内裁剪至最多 EXECUTIONS_MAX_RECORDS 条。"""
        with self._session_factory() as session:
            session.add(_execution_to_orm(execution))
            # 同事务插入+裁剪；autoflush 使新行参与 keep 子集计算
            keep_ids = (
                select(SchedulerExecution.id)
                .order_by(
                    SchedulerExecution.started_at.desc(),
                    SchedulerExecution.id.desc(),
                )
                .limit(EXECUTIONS_MAX_RECORDS)
                .scalar_subquery()
            )
            session.execute(
                delete(SchedulerExecution)
                .where(SchedulerExecution.id.not_in(keep_ids))
                .execution_options(synchronize_session=False)
            )
            session.commit()

    def finish(self, run_id: str, status: str, error: str | None = None) -> None:
        """按 run_id 收尾：写 status / finished_at / 可选 error_message。"""
        finished_at = _to_iso(_utc_now())
        values: dict[str, object] = {"status": status, "finished_at": finished_at}
        if error is not None:
            values["error_message"] = error
        with self._session_factory() as session:
            result = session.execute(
                update(SchedulerExecution)
                .where(SchedulerExecution.id == run_id)
                .values(**values)
            )
            reconciled = result.rowcount  # type: ignore[attr-defined]
            session.commit()
        if reconciled == 0:
            logger.warning("finish: 未找到 run_id=%s，未更新任何执行记录", run_id)

    def list(self, limit: int = 50) -> List[TaskExecution]:
        """按 started_at/id 倒序取最近 limit 条。"""
        with self._session_factory() as session:
            rows = (
                session.execute(
                    select(SchedulerExecution)
                    .order_by(
                        SchedulerExecution.started_at.desc(),
                        SchedulerExecution.id.desc(),
                    )
                    .limit(limit)
                )
                .scalars()
                .all()
            )
            return [_orm_to_execution(row) for row in rows]
