from pydantic import BaseModel
from typing import List, Optional, Dict


class DeviceModel(BaseModel):
    name: str
    adb_path: str
    address: str
    screencap_methods: int
    input_methods: int
    config: dict

class UserConfig(BaseModel):
    taskOrder: Optional[List[str]] = None
    taskChecked: Optional[Dict[str, bool]] = None
    taskOptions: Optional[Dict[str, str]] = None