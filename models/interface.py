from pydantic import BaseModel, model_validator, ConfigDict
from typing import List, Optional, Dict, Literal, Union


class AdbController(BaseModel):
    """Adb 控制器配置，V2 协议中 input/screencap 由 MaaFramework 自动检测"""
    model_config = ConfigDict(extra='allow')


class Win32Controller(BaseModel):
    class_regex: Optional[str] = None
    window_regex: Optional[str] = None
    mouse: Optional[Literal["Seize", "SendMessage", "PostMessage", "LegacyEvent", "PostThreadMessage", "SendMessageWithCursorPos", "PostMessageWithCursorPos"]] = None
    keyboard: Optional[Literal["Seize", "SendMessage", "PostMessage", "LegacyEvent", "PostThreadMessage", "SendMessageWithCursorPos", "PostMessageWithCursorPos"]] = None
    screencap: Optional[Literal["GDI", "FramePool", "DXGI_DesktopDup", "DXGI_DesktopDup_Window", "PrintWindow", "ScreenDC"]] = None


class PlayCoverController(BaseModel):
    """PlayCover 控制器配置（仅 macOS）"""
    uuid: Optional[str] = None


class GamepadController(BaseModel):
    """虚拟游戏手柄控制器配置（仅 Windows）"""
    class_regex: Optional[str] = None
    window_regex: Optional[str] = None
    gamepad_type: Optional[Literal["Xbox360", "DualShock4", "DS4"]] = "Xbox360"
    screencap: Optional[Literal["GDI", "FramePool", "DXGI_DesktopDup", "DXGI_DesktopDup_Window", "PrintWindow", "ScreenDC"]] = None


class Controller(BaseModel):
    name: str
    label: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    type: Literal["Adb", "Win32", "PlayCover", "Gamepad"]
    display_short_side: Optional[int] = 720
    display_long_side: Optional[int] = None
    display_raw: Optional[bool] = False
    permission_required: Optional[bool] = False
    adb: Optional[AdbController] = None
    win32: Optional[Win32Controller] = None
    playcover: Optional[PlayCoverController] = None
    gamepad: Optional[GamepadController] = None

    @model_validator(mode='after')
    def check_display_fields_mutual_exclusive(self):
        # 检查是否设置了多个互斥字段（非默认值）
        fields_set = []
        if self.display_short_side is not None and self.display_short_side != 720:
            fields_set.append('display_short_side')
        if self.display_long_side is not None:
            fields_set.append('display_long_side')
        if self.display_raw is True:
            fields_set.append('display_raw')
        if len(fields_set) > 1:
            raise ValueError('display_short_side, display_long_side 和 display_raw 必须互斥')
        return self

class Resource(BaseModel):
    name: str
    label: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    path: List[str]
    controller: Optional[List[str]] = None
    option: Optional[List[str]] = None


class Agent(BaseModel):
    child_exec: str
    child_args: Optional[List[str]] = None
    identifier: Optional[str] = None


class Task(BaseModel):
    name: str
    label: Optional[str] = None
    entry: str
    default_check: Optional[bool] = False
    description: Optional[str] = None
    doc: Optional[Union[str, List[str]]] = None
    icon: Optional[str] = None
    resource: Optional[List[str]] = None
    controller: Optional[List[str]] = None
    pipeline_override: Optional[Dict[str, dict]] = None
    option: Optional[List[str]] = None


class OptionCase(BaseModel):
    name: str
    label: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    option: Optional[List[str]] = None
    pipeline_override: Optional[Dict[str, dict]] = None


class InputCase(BaseModel):
    name: str
    label: Optional[str] = None
    description: Optional[str] = None
    default: Optional[str] = None
    pipeline_type: Optional[Literal["string", "int", "bool"]] = None
    verify: Optional[str] = None
    pattern_msg: Optional[str] = None


class Option(BaseModel):
    type: Literal["select", "input", "switch"] = "select"
    label: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    cases: Optional[List[OptionCase]] = None
    inputs: Optional[List[InputCase]] = None
    pipeline_override: Optional[Dict[str, dict]] = None
    default_case: Optional[str] = None

    @model_validator(mode='after')
    def check_type_fields(self):
        if self.type == "select":
            if not self.cases:
                raise ValueError('当 type 为 select 时，cases 不能为空')
        if self.type == "switch":
            if not self.cases:
                raise ValueError('当 type 为 switch 时，cases 不能为空')
            if len(self.cases) != 2:
                raise ValueError('当 type 为 switch 时，cases 必须有且仅有 2 个元素')
        if self.type == "input":
            if not self.inputs:
                raise ValueError('当 type 为 input 时，inputs 不能为空')
        return self


class InterfaceModel(BaseModel):
    interface_version: Literal[2]
    languages: Optional[Dict[str, str]] = None
    name: str
    label: Optional[str] = None
    title: Optional[str] = None
    icon: Optional[str] = None
    mirrorchyan_rid: Optional[str] = None
    mirrorchyan_multiplatform: Optional[bool] = None
    github: Optional[str] = None
    version: Optional[str] = None
    contact: Optional[str] = None
    license: Optional[str] = None
    welcome: Optional[str] = None
    description: Optional[str] = None
    controller: List[Controller]
    resource: List[Resource]
    agent: Optional[Agent] = None
    task: List[Task]
    option: Optional[Dict[str, Option]] = None

    @model_validator(mode='after')
    def set_variable_if_none(self):
        if self.label is None:
            self.label = self.name
        if self.title is None and self.label and self.version:
            self.title = f"{self.label} {self.version}"
        return self

