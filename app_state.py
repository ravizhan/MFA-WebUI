import asyncio
import subprocess
import time
from collections import deque
from queue import SimpleQueue
from typing import Any

from maa_utils import MaaWorker
from models.api import RealtimeEvent, RealtimeEventLevel
from models.settings import SettingsModel
from scheduler_manager import SchedulerManager
from services.execution_coordinator import ExecutionCoordinator
from services.execution_store import ExecutionStore
from services.system_scheduler import SystemScheduler


_HISTORY_MAXLEN = 2000


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
    def __init__(self):
        self.message_conn = SimpleQueue()
        self.worker: MaaWorker | None = None
        self.is_shutting_down = False
        self.history_message: deque[RealtimeEvent] = deque(maxlen=_HISTORY_MAXLEN)
        self.current_status = None
        self.broadcaster: LogBroadcaster | None = None
        self.scheduler_manager: SchedulerManager | None = None
        self.system_scheduler: SystemScheduler | None = None
        self.execution_store: ExecutionStore | None = None
        self.execution_coordinator: ExecutionCoordinator | None = None
        self.native_token: str | None = None
        self.settings: SettingsModel | None = None
        self.subprocess_pipe: subprocess.Popen | None = None
        self.update_status: dict | None = None
        self.update_info: dict | None = None
        # Runtime ownership (kernel advisory lock); only for real CLI process lifetime
        self.runtime_ownership: Any | None = None
        # CLI: --scheduled-task uuid (set before uvicorn starts)
        self.pending_scheduled_task_id: str | None = None

    def send_event(self, event: RealtimeEvent):
        self.message_conn.put(event)

    def send_log(self, msg: str):
        self.send_event(build_log_event(msg))
