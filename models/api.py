from pydantic import BaseModel
from typing import List, Optional, Dict


class DeviceModel(BaseModel):
    name: str
    adb_path: str
    address: str
    screencap_methods: int
    input_methods: int
    config: dict

class PostTaskModel(BaseModel):
    tasklist: List[Dict[str, str]]