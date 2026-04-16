import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from maa.agent_client import AgentClient


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


@dataclass
class AgentRuntimeState:
    start_lock: threading.Lock = field(default_factory=threading.Lock)
    started_once: bool = False
    start_succeeded: bool = False
    start_error: str | None = None
    pi_env: dict[str, str] | None = None
    processes: list[subprocess.Popen] = field(default_factory=list)
    agent_client: "AgentClient" = None
