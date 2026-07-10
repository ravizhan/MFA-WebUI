from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

RealtimeEventName = Literal[
    "log",
    "focus.display",
    "task.started",
    "task.completed",
    "task.failed",
    "notification.test",
]
RealtimeEventLevel = Literal["info", "success", "error"]

DeviceType = Literal["Adb", "Win32", "Gamepad", "PlayCover"]


class DeviceModel(BaseModel):
    type: DeviceType
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


class CustomDeviceCreate(BaseModel):
    """User-entered device address to persist and merge with scan results."""

    controller_name: str = Field(..., description="interface.json controller name")
    type: DeviceType
    address: str = Field(..., description="Device address (format depends on type)")

    @field_validator("controller_name", "address", mode="before")
    @classmethod
    def strip_and_require(cls, value: Any) -> str:
        if value is None:
            raise ValueError("must not be empty")
        text = str(value).strip()
        if not text:
            raise ValueError("must not be empty")
        return text


class RealtimeEvent(BaseModel):
    event: RealtimeEventName
    level: RealtimeEventLevel = "info"
    message: str
    time: str
    notify: list[str] = Field(default_factory=list)
    title: str | None = None
    details: dict[str, Any] | None = None
    display: bool = True
