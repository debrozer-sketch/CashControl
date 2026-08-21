from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class PingSettings(BaseModel):
    interval: float = 5.0


class ConnectionSettings(BaseModel):
    ping_interval: float = 5.0
    ssh_timeout: float = 10.0
    connect_timeout: float = 15.0


class GeneralSettings(BaseModel):
    max_tabs: int = 10
    language: str = "ru"


class ThemeSettings(BaseModel):
    mode: str = "dark"


class Settings(BaseModel):
    connection: ConnectionSettings = Field(default_factory=ConnectionSettings)
    general: GeneralSettings = Field(default_factory=GeneralSettings)
    theme: ThemeSettings = Field(default_factory=ThemeSettings)


class ConfigManager:
    _instance: ConfigManager | None = None

    def __new__(cls) -> ConfigManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._path = self._resolve_path()
        self._settings = self._load()

    @property
    def settings(self) -> Settings:
        return self._settings

    @staticmethod
    def _resolve_path() -> Path:
        from cashcontrol.infrastructure.path_resolver import get_config_file
        return get_config_file()

    def _load(self) -> Settings:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
                return Settings.model_validate(data)
            except Exception:
                pass
        return Settings()

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(
            self._settings.model_dump_json(indent=2, exclude_none=True),
            encoding="utf-8",
        )
