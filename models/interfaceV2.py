from pydantic import BaseModel, model_validator
from typing import List, Optional, Dict, Literal


class AdbController(BaseModel):
    input: Optional[int] = None
    screencap: Optional[int] = None
    config: Optional[Dict[str, str]] = None

class Win32Controller(BaseModel):
    class_regex: Optional[str] = None
    window_regex: Optional[str] = None
    mouse: Optional[int] = None
    keyboard: Optional[int] = None
    screencap: Optional[int] = None


class Controller(BaseModel):
    name: str
    label: str
    description: Optional[str] = None
    icon: str
    type: str
    display_short_side: Optional[int] = 720
    display_long_side: Optional[int] = 1280
    display_raw: Optional[bool] = False
    adb: Optional[AdbController] = None
    win32: Optional[Win32Controller] = None

    @model_validator(mode='after')
    def check_display_fields_mutual_exclusive(self):
        fields = [self.display_short_side, self.display_long_side, self.display_raw]
        non_none_count = sum(f is not None for f in fields)
        if non_none_count > 1:
            raise ValueError('display_short_side, display_long_side 和 display_raw 必须互斥')
        return self

class Resource(BaseModel):
    name: str
    label: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    path: List[str]
    controller: Optional[List[str]] = None


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
    icon: Optional[str] = None
    resource: Optional[List[str]] = None
    pipeline_override: Optional[Dict[str, dict]] = None
    option: Optional[List[str]] = None


class OptionCase(BaseModel):
    name: str
    label: Optional[str] = None
    description: Optional[str] = None
    icon: Optional[str] = None
    options: Optional[Dict[str,str]] = None
    pipeline_override: Dict[str, dict]

class InputCase(BaseModel):
    name: str
    label: Optional[str] = None
    description: Optional[str] = None
    default: Optional[str] = None
    pipeline_type: Literal["str", "int", "float"] = "str"
    verify: Optional[str] = None

class Option(BaseModel):
    key: str
    type: Literal["select", "input"] = "select"
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
            if self.pipeline_override:
                raise ValueError('当 type 为 select 时，pipeline_override 不应存在')
        if self.type == "input":
            if not self.inputs:
                raise ValueError('当 type 为 input 时，inputs 不能为空')
            if self.default_case:
                raise ValueError('当 type 为 input 时，default_case 不应存在')
        return self


class InterfaceModel(BaseModel):
    interface_version: int
    languages: Optional[Dict[str, str]]
    name: str
    label: Optional[str] = None
    title: Optional[str] = None
    icon: Optional[str] = None
    mirrorchyan_rid: Optional[str] = None
    mirrorchyan_multiplatform: Optional[bool] = None
    auto_update_ui: bool
    auto_update_maafw: bool
    github: str
    version: str
    contact: str
    license: str
    welcome: str
    description: str
    controller: List[Controller]
    resource: List[Resource]
    agent: Optional[Agent] = None
    task: List[Task]
    option: Dict[str, Option]

    @model_validator(mode='after')
    def set_variable_if_none(self):
        if self.label is None:
            self.label = self.name
        if self.title is None and self.label:
            self.title = f"{self.label} {self.version}"
        return self