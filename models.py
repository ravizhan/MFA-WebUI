from pydantic import BaseModel
from typing import List, Optional, Dict, Any


class Controller(BaseModel):
    name: str
    type: str


class Resource(BaseModel):
    name: str
    path: List[str]


class Agent(BaseModel):
    child_exec: str
    child_args: List[str]


class TaskPipelineOverride(BaseModel):
    input_text: Optional[str] = None
    template: Optional[str] = None


class Task(BaseModel):
    name: str
    entry: str
    doc: Optional[str | List[str]] = None
    option: Optional[List[str]] = None
    pipeline_override: Optional[Dict[str, TaskPipelineOverride]] = None
    repeatable: Optional[bool] = None
    repeat_count: Optional[int] = None


class OptionCasePipelineOverride(BaseModel):
    enabled: Optional[bool] = None
    next: Optional[str] = None
    expected: Optional[List[str] | str] = None
    custom_action_param: Optional[Dict[str, Any]] = None


class OptionCase(BaseModel):
    name: str
    pipeline_override: Dict[str, OptionCasePipelineOverride]


class Option(BaseModel):
    default_case: Optional[str] = None
    cases: List[OptionCase]


class InterfaceModel(BaseModel):
    name: str
    url: str
    mirrorchyan_rid: Optional[str] = None
    mirrorchyan_multiplatform: Optional[bool] = None
    controller: List[Controller]
    resource: List[Resource]
    agent: Agent = None
    task: List[Task]
    option: Dict[str, Option]
    version: str

class DeviceModel(BaseModel):
    name: str
    adb_path: str
    address: str
    # 会自动转换为int，不用处理
    screencap_methods: int
    input_methods: int
    config: dict

class PostTaskModel(BaseModel):
    tasklist: List[Dict[str, str]]