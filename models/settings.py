from pydantic import BaseModel
from typing import Optional, Literal

class Update(BaseModel):
    autoUpdate: bool
    updateChannel: Literal["stable", "beta"]
    proxy: str

class Notification(BaseModel):
    enabled: bool
    webhook: str
    notifyOnComplete: bool
    notifyOnError: bool

class UI(BaseModel):
    darkMode: Optional[bool|str] = "auto"

class Runtime(BaseModel):
    timeout: int
    reminderInterval: int
    autoRetry: bool
    maxRetryCount: int

class About(BaseModel):
    version: str
    author: str
    github: str
    license: str
    description: str
    contact: str
    issueUrl: str

class SettingsModel(BaseModel):
    update: Update
    notification: Notification
    ui: UI
    runtime: Runtime
    about: About
