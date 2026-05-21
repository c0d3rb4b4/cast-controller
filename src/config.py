from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    default_device_name: str | None = None
    default_device_host: str | None = None
    default_stream_url: str | None = None
    default_volume: float = Field(default=0.1, ge=0, le=1)
    reconcile_interval_s: float = Field(default=30, gt=0)
    min_recast_interval_s: float = Field(default=60, ge=0)
    cast_start_grace_s: float = Field(default=5, ge=0)
    port: int = Field(default=8091, gt=0, le=65535)
    state_path: Path = Path("/data/state.json")
    log_level: str = "info"
    noise_stream_base_url: str | None = "http://192.168.68.84:8081"
    default_noise_type: Literal["white", "pink", "brown"] = "white"

    model_config = SettingsConfigDict(
        env_file=("config/app.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator(
        "default_device_name",
        "default_device_host",
        "default_stream_url",
        "noise_stream_base_url",
        mode="before",
    )
    @classmethod
    def empty_string_to_none(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    def stream_url_for(self, noise_type: str | None = None) -> str | None:
        if noise_type is None and self.default_stream_url:
            return self.default_stream_url

        selected_noise_type = noise_type or self.default_noise_type
        if self.noise_stream_base_url:
            base_url = self.noise_stream_base_url.rstrip("/")
            return f"{base_url}/hls/noise_{selected_noise_type}/stream.m3u8"

        return self.default_stream_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
