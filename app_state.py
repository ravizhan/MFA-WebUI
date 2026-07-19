from __future__ import annotations

import asyncio
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from queue import SimpleQueue
from typing import TYPE_CHECKING, Any

from models.api import RealtimeEvent, RealtimeEventLevel
from models.scheduler import ExecutionOrigin
from models.settings import SettingsModel

if TYPE_CHECKING:
    from maa.agent_client import AgentClient
    from maa_utils import MaaWorker
    from scheduler_manager import SchedulerManager
    from services.execution_coordinator import ExecutionCoordinator
    from services.execution_store import ExecutionStore
    from services.system_scheduler import SystemScheduler


_HISTORY_MAXLEN = 2000


@dataclass
class WorkerContext:
    interface_base_dir: Path
    i18n_text_mapping: dict[str, Any] | None = None


@dataclass
class DeviceRuntimeState:
    controller: Any = None
    controller_type: str | None = None
    controller_name: str | None = None
    current_resource_name: str | None = None
    connected: bool = False
    configuration_locked: bool = False
    last_device_error: str | None = None
    last_resource_error: str | None = None


@dataclass
class TaskRuntimeState:
    stop_flag: bool = False
    running: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)
    thread: threading.Thread | None = None
    last_status: str = "idle"
    last_error: str | None = None
    current_task_name: str | None = None
    pre_tasks: list | None = None
    current_pre_task_process: subprocess.Popen | None = None


@dataclass
class AgentRuntimeState:
    start_lock: threading.Lock = field(default_factory=threading.Lock)
    started_once: bool = False
    start_succeeded: bool = False
    start_error: str | None = None
    pi_env: dict[str, str] | None = None
    processes: list[subprocess.Popen] = field(default_factory=list)
    agent_client: AgentClient | None = None


@dataclass
class ActiveRun:
    run_id: str
    origin: ExecutionOrigin
    task_name: str
    occurrence_id: str | None


class LogBroadcaster:
    def __init__(self):
        self._queues: list[asyncio.Queue] = []

    def add_client(self, history: deque[RealtimeEvent]) -> asyncio.Queue:
        q = asyncio.Queue()
        for message in history:
            q.put_nowait(message.model_copy(update={"notify": []}))
        self._queues.append(q)
        return q

    def remove_client(self, q: asyncio.Queue):
        if q in self._queues:
            self._queues.remove(q)

    async def broadcast(self, message: RealtimeEvent):
        for q in self._queues:
            await q.put(message)


def build_log_event(msg: str, level: RealtimeEventLevel = "info") -> RealtimeEvent:
    return RealtimeEvent(
        event="log",
        level=level,
        message=msg,
        time=time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
        notify=[],
    )


def normalize_event(payload: RealtimeEvent | dict[str, Any] | str) -> RealtimeEvent:
    if isinstance(payload, RealtimeEvent):
        return payload
    if isinstance(payload, dict):
        return RealtimeEvent(**payload)
    return RealtimeEvent(
        event="log",
        level="info",
        message=payload,
        time="",
        notify=[],
    )


class AppState:
    def __init__(self, app_root_dir: Path):
        self.message_conn: SimpleQueue = SimpleQueue()
        self.worker: MaaWorker | None = None
        self.is_shutting_down = False
        self.history_message: deque[RealtimeEvent] = deque(maxlen=_HISTORY_MAXLEN)
        self.broadcaster: LogBroadcaster | None = None
        self.scheduler_manager: SchedulerManager | None = None
        self.system_scheduler: SystemScheduler | None = None
        self.execution_store: ExecutionStore | None = None
        self.execution_coordinator: ExecutionCoordinator | None = None
        self.native_token: str | None = None
        self.settings: SettingsModel | None = None
        self.update_status: dict | None = None
        self.update_info: dict | None = None
        # Runtime ownership (kernel advisory lock); only for real CLI process lifetime
        self.runtime_ownership: Any | None = None
        # CLI: --scheduled-task uuid (set before uvicorn starts)
        self.pending_scheduled_task_id: str | None = None

        self.context = WorkerContext(interface_base_dir=app_root_dir.resolve())
        self.device = DeviceRuntimeState()
        self.task = TaskRuntimeState()
        self.agent = AgentRuntimeState()
        self.active_run: ActiveRun | None = None
        self.update_in_progress = False

    def send_event(self, event: RealtimeEvent):
        self.message_conn.put(event)

    def send_log(self, msg: str):
        self.send_event(build_log_event(msg))
