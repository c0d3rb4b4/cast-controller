from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DesiredState(str, Enum):
    ON = "on"
    OFF = "off"


class ObservedState(str, Enum):
    PLAYING = "playing"
    PAUSED = "paused"
    IDLE = "idle"
    UNKNOWN = "unknown"


class NoiseType(str, Enum):
    WHITE = "white"
    PINK = "pink"
    BROWN = "brown"


class StartRequest(BaseModel):
    device: str | None = None
    stream_url: str | None = None
    volume: float | None = Field(default=None, ge=0, le=1)
    noise_type: NoiseType | None = None


class StopRequest(BaseModel):
    device: str | None = None


class ControllerState(BaseModel):
    desired: DesiredState = DesiredState.OFF
    observed: ObservedState = ObservedState.UNKNOWN
    device: str | None = None
    device_host: str | None = None
    device_port: int | None = None
    device_uuid: str | None = None
    device_model_name: str | None = None
    stream_url: str | None = None
    volume: float | None = None
    last_action: str | None = None
    failure_count: int = 0
    last_cast_attempt_at: datetime | None = None
    last_success_at: datetime | None = None
    updated_at: datetime = Field(default_factory=utc_now)


class ActionResponse(BaseModel):
    ok: bool
    desired: DesiredState
    action: str


class HealthResponse(BaseModel):
    ok: bool
    status: str
    reconcile_running: bool
    desired: DesiredState
    observed: ObservedState


class DeviceInfo(BaseModel):
    name: str | None = None
    host: str | None = None
    port: int | None = None
    uuid: str | None = None
    model_name: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class DevicesResponse(BaseModel):
    ok: bool
    devices: list[DeviceInfo]
