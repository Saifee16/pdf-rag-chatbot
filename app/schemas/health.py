from typing import Literal

from pydantic import BaseModel


class HealthData(BaseModel):
    status: Literal["ok"] = "ok"
    app: str
    environment: str


class ComponentStatus(BaseModel):
    name: str
    ready: bool
    detail: str


class ReadinessData(BaseModel):
    ready: bool
    components: list[ComponentStatus]
