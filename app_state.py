import asyncio
import subprocess
import time
from queue import SimpleQueue
from typing import Any

from maa_utils import MaaWorker
from models.api import RealtimeEvent, RealtimeEventLevel
from models.settings import SettingsModel
from scheduler_manager import SchedulerManager


class LogBroadcaster:
    def __init__(self):
        self._queues: list[asyncio.Queue] = []

    def add_client(self, history: list[RealtimeEvent]) -> asyncio.Queue:
        q = asyncio.Queue()
        for message in history:
            q.put_nowait(message.model_copy(update={"notify": False}))
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
        notify=False,
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
        notify=False,
    )


class AppState:
    def __init__(self):
        self.message_conn = SimpleQueue()
        self.worker: MaaWorker | None = None
        self.is_shutting_down = False
        self.history_message: list[RealtimeEvent] = []
        self.current_status = None
        self.broadcaster: LogBroadcaster | None = None
        self.scheduler_manager: SchedulerManager | None = None
        self.settings: SettingsModel | None = None
        self.subprocess_pipe: subprocess.Popen | None = None
        self.update_status: dict | None = None
        self.update_info: dict | None = None

    def send_event(self, event: RealtimeEvent):
        self.message_conn.put(event)

    def send_log(self, msg: str):
        self.send_event(build_log_event(msg))
