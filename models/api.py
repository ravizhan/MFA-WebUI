from typing import Literal

from pydantic import BaseModel

RealtimeEventName = Literal[
    "log",
    "task.started",
    "task.completed",
    "task.failed",
    "notification.test",
]
RealtimeEventLevel = Literal["info", "success", "error"]


class DeviceModel(BaseModel):
    type: Literal["Adb", "Win32", "Gamepad", "PlayCover"]
    controller_name: str = ""
    name: str = ""
    adb_path: str = ""
    address: str = ""
    screencap_methods: int | str = 0
    input_methods: int | str = 0
    hWnd: int = 0
    gamepad_type: int = 0
    uuid: str = ""
    config: dict = {}


class RealtimeEvent(BaseModel):
    event: RealtimeEventName
    level: RealtimeEventLevel = "info"
    message: str
    time: str
    notify: bool = False
    title: str | None = None
