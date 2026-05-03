import re
from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationInfo,
    field_validator,
    model_validator,
)

DocumentContent = Union[str, List[str]]
PipelineOverride = Dict[str, Any]
PresetOptionValue = Union[str, List[str], Dict[str, str]]


def validate_regex(v: Any, info: ValidationInfo) -> Any:
    if v is None or isinstance(v, re.Pattern):
        return v
    try:
        return re.compile(v)
    except (re.error, TypeError):
        raise ValueError(f"{info.field_name} 无法编译为正则表达式")


def _pipeline_override_contains_attach_option(value: Any, option_name: str) -> bool:
    if isinstance(value, dict):
        attach_value = value.get("attach")
        if isinstance(attach_value, dict) and option_name in attach_value:
            return True
        for nested_value in value.values():
            if _pipeline_override_contains_attach_option(nested_value, option_name):
                return True
        return False
    if isinstance(value, list):
        return any(
            _pipeline_override_contains_attach_option(item, option_name)
            for item in value
        )
    return False


class AdbController(BaseModel):
    """Adb 控制器配置，V2 协议中 input/screencap 由 MaaFramework 自动检测"""

    model_config = ConfigDict(extra="allow")


class Win32Controller(BaseModel):
    class_regex: Optional[re.Pattern] = None
    window_regex: Optional[re.Pattern] = None
    mouse: Optional[
        Literal[
            "Seize",
            "SendMessage",
            "PostMessage",
            "LegacyEvent",
            "SendMessageWithCursorPos",
            "PostMessageWithCursorPos",
            "SendMessageWithWindowPos",
            "PostMessageWithWindowPos",
        ]
    ] = None
    keyboard: Optional[
        Literal[
            "Seize",
            "SendMessage",
            "PostMessage",
            "LegacyEvent",
            "SendMessageWithCursorPos",
            "PostMessageWithCursorPos",
            "SendMessageWithWindowPos",
            "PostMessageWithWindowPos",
        ]
    ] = None
    screencap: Optional[
        Literal[
            "GDI",
            "FramePool",
            "DXGI_DesktopDup",
            "DXGI_DesktopDup_Window",
            "PrintWindow",
            "ScreenDC",
            "Foreground",
            "Background",
        ]
    ] = None

    @field_validator("class_regex", "window_regex", mode="before")
    @classmethod
    def check_regex(cls, v: Any, info: ValidationInfo):
        return validate_regex(v, info)

    @model_validator(mode="after")
    def method_to_int(self):
        maps = {
            "screencap": {
                "GDI": 1,
                "FramePool": 2,
                "DXGI_DesktopDup": 4,
                "DXGI_DesktopDup_Window": 8,
                "PrintWindow": 16,
                "ScreenDC": 32,
                "Foreground": 64,
                "Background": 128,
            },
            "keyboard": {
                "Seize": 1,
                "SendMessage": 2,
                "PostMessage": 4,
                "LegacyEvent": 8,
                "SendMessageWithCursorPos": 32,
                "PostMessageWithCursorPos": 64,
                "SendMessageWithWindowPos": 128,
                "PostMessageWithWindowPos": 256,
            },
            "mouse": {
                "Seize": 1,
                "SendMessage": 2,
                "PostMessage": 4,
                "LegacyEvent": 8,
                "SendMessageWithCursorPos": 32,
                "PostMessageWithCursorPos": 64,
                "SendMessageWithWindowPos": 128,
                "PostMessageWithWindowPos": 256,
            },
        }
        # 将输入的字符串方法转换为对应的整数值
        for field, mapping in maps.items():
            value = getattr(self, field, None)
            if isinstance(value, str):
                if value in mapping:
                    setattr(self, field, mapping[value])
                else:
                    raise ValueError(f"无效的 {field} 方法: {value}")
        return self


class PlayCoverController(BaseModel):
    """PlayCover 控制器配置（仅 macOS）"""

    uuid: Optional[str] = None


class MacOSController(BaseModel):
    """MacOS 控制器配置"""

    title_regex: Optional[re.Pattern] = None
    input: Optional[Literal["GlobalEvent", "PostToPid"]] = None
    screencap: Optional[Literal["ScreenCaptureKit"]] = None

    @field_validator("title_regex", mode="before")
    @classmethod
    def check_regex(cls, v: Any, info: ValidationInfo):
        return validate_regex(v, info)


class GamepadController(BaseModel):
    """虚拟游戏手柄控制器配置（仅 Windows）"""

    class_regex: Optional[re.Pattern] = None
    window_regex: Optional[re.Pattern] = None
    gamepad_type: Optional[Literal["Xbox360", "DualShock4", "DS4"]] = "Xbox360"
    screencap: Optional[
        Literal[
            "GDI",
            "FramePool",
            "DXGI_DesktopDup",
            "DXGI_DesktopDup_Window",
            "PrintWindow",
            "ScreenDC",
        ]
    ] = None

    @field_validator("class_regex", "window_regex", mode="before")
    @classmethod
    def check_regex(cls, v: Any, info: ValidationInfo):
        return validate_regex(v, info)

    @model_validator(mode="after")
    def method_to_int(self):
        maps = {
            "screencap": {
                "GDI": 1,
                "FramePool": 2,
                "DXGI_DesktopDup": 4,
                "DXGI_DesktopDup_Window": 8,
                "PrintWindow": 16,
                "ScreenDC": 32,
            },
            "gamepad_type": {"Xbox360": 0, "DualShock4": 1, "DS4": 1},
        }
        # 将输入的字符串方法转换为对应的整数值
        for field, mapping in maps.items():
            value = getattr(self, field, None)
            if isinstance(value, str):
                if value in mapping:
                    setattr(self, field, mapping[value])
                else:
                    raise ValueError(f"无效的 {field} 方法: {value}")
        return self


class Controller(BaseModel):
    name: str
    label: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    type: Literal["Adb", "Win32", "MacOS", "PlayCover", "Gamepad"]
    display_short_side: Optional[int] = 720
    display_long_side: Optional[int] = None
    display_raw: Optional[bool] = False
    permission_required: Optional[bool] = False
    attach_resource_path: Optional[List[str]] = None
    option: Optional[List[str]] = None
    adb: Optional[AdbController] = None
    win32: Optional[Win32Controller] = None
    macos: Optional[MacOSController] = None
    playcover: Optional[PlayCoverController] = None
    gamepad: Optional[GamepadController] = None

    @model_validator(mode="after")
    def check_display_fields_mutual_exclusive(self):
        # 检查是否设置了多个互斥字段（非默认值）
        fields_set = []
        if self.display_short_side is not None and self.display_short_side != 720:
            fields_set.append("display_short_side")
        if self.display_long_side is not None:
            fields_set.append("display_long_side")
        if self.display_raw is True:
            fields_set.append("display_raw")
        if len(fields_set) > 1:
            raise ValueError(
                "display_short_side, display_long_side 和 display_raw 必须互斥"
            )
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
    embedded: Optional[bool] = True


class Task(BaseModel):
    name: str
    label: Optional[str] = None
    entry: str
    default_check: Optional[bool] = False
    description: Optional[str] = None
    doc: Optional[DocumentContent] = None
    desc: Optional[DocumentContent] = None
    icon: Optional[str] = None
    group: Optional[List[str]] = None
    resource: Optional[List[str]] = None
    controller: Optional[List[str]] = None
    pipeline_override: Optional[PipelineOverride] = None
    option: Optional[List[str]] = None


class Group(BaseModel):
    name: str
    label: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    default_expand: Optional[bool] = True


class OptionCase(BaseModel):
    name: str
    label: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    option: Optional[List[str]] = None
    pipeline_override: Optional[PipelineOverride] = None


class InputCase(BaseModel):
    name: str
    label: Optional[str] = None
    description: Optional[str] = None
    default: Optional[str] = None
    pipeline_type: Optional[Literal["string", "int", "bool"]] = None
    verify: Optional[str] = None
    pattern_msg: Optional[str] = None


class Option(BaseModel):
    type: Literal["select", "input", "checkbox", "switch", "scan_select"] = "select"
    label: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    controller: Optional[List[str]] = None
    resource: Optional[List[str]] = None
    cases: Optional[List[OptionCase]] = None
    inputs: Optional[List[InputCase]] = None
    scan_dir: Optional[str] = None
    scan_filter: Optional[str] = None
    pipeline_override: Optional[PipelineOverride] = None
    default_case: Optional[Union[str, List[str]]] = None

    @model_validator(mode="after")
    def check_type_fields(self):
        if self.type == "select":
            if not self.cases:
                raise ValueError("当 type 为 select 时，cases 不能为空")
        if self.type == "switch":
            if not self.cases:
                raise ValueError("当 type 为 switch 时，cases 不能为空")
            if len(self.cases) != 2:
                raise ValueError("当 type 为 switch 时，cases 必须有且仅有 2 个元素")
        if self.type == "checkbox":
            if not self.cases:
                raise ValueError("当 type 为 checkbox 时，cases 不能为空")
            if self.default_case is not None and not isinstance(
                self.default_case, list
            ):
                raise ValueError(
                    "当 type 为 checkbox 时，default_case 必须为字符串数组"
                )
        if self.type == "input":
            if not self.inputs:
                raise ValueError("当 type 为 input 时，inputs 不能为空")
        if self.type == "scan_select":
            if not self.scan_dir:
                raise ValueError("当 type 为 scan_select 时，scan_dir 不能为空")
            if not self.scan_filter:
                raise ValueError("当 type 为 scan_select 时，scan_filter 不能为空")
            if not self.pipeline_override:
                raise ValueError(
                    "当 type 为 scan_select 时，pipeline_override 不能为空"
                )
        if self.type in {"select", "switch", "scan_select"}:
            if self.default_case is not None and not isinstance(self.default_case, str):
                raise ValueError(
                    "当 type 为 select、switch 或 scan_select 时，default_case 必须为字符串"
                )
        return self


class PresetTask(BaseModel):
    name: str
    enabled: Optional[bool] = True
    option: Optional[Dict[str, PresetOptionValue]] = None


class Preset(BaseModel):
    name: str
    label: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    task: Optional[List[PresetTask]] = None


class InterfaceModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

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
    group: Optional[List[Group]] = None
    agent: Optional[Union[Agent, List[Agent]]] = None
    task: Optional[List[Task]] = None
    option: Optional[Dict[str, Option]] = None
    global_option: Optional[List[str]] = None
    import_: Optional[List[str]] = Field(None, alias="import")
    preset: Optional[List[Preset]] = None

    @model_validator(mode="after")
    def set_variable_if_none(self):
        if self.label is None:
            self.label = self.name
        if self.title is None and self.label and self.version:
            self.title = f"{self.label} {self.version}"
        return self

    @model_validator(mode="after")
    def check_scan_select_pipeline_override_placeholder(self):
        if not self.option:
            return self

        for option_name, option in self.option.items():
            if option.type != "scan_select" or option.pipeline_override is None:
                continue

            if not _pipeline_override_contains_attach_option(
                option.pipeline_override,
                option_name,
            ):
                raise ValueError(
                    f"scan_select 选项 {option_name} 的 pipeline_override 必须在任意层级的 attach 中至少包含一次键 {option_name}"
                )
        return self
