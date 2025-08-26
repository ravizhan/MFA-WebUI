from pydantic import BaseModel
from typing import List, Optional, Dict


class Controller(BaseModel):
    name: str
    type: str


class Resource(BaseModel):
    name: str
    path: List[str]


class Agent(BaseModel):
    child_exec: str
    child_args: List[str]


class Task(BaseModel):
    name: str
    entry: str
    doc: Optional[str | List[str]] = None
    option: Optional[List[str]] = None
    pipeline_override: Optional[Dict[str, dict]] = None
    repeatable: Optional[bool] = None
    repeat_count: Optional[int] = None


class OptionCase(BaseModel):
    name: str
    pipeline_override: Dict[str, dict]


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
    agent: Optional[Agent] = None
    task: List[Task]
    option: Dict[str, Option]
    version: str

class DeviceModel(BaseModel):
    name: str
    adb_path: str
    address: str
    screencap_methods: int
    input_methods: int
    config: dict

class PostTaskModel(BaseModel):
    tasklist: List[Dict[str, str]]