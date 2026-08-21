from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ConnectionSettings(BaseModel):
    ssh_login: str = "tc"
    ssh_passwords_encrypted: list[str] = Field(default_factory=list)
    ssh_port: int = 22
    db_login: str = "postgres"
    db_passwords_encrypted: list[str] = Field(default_factory=list)
    db_port: int = 5432
    vnc_port: int = 5900
    timeout: float = 10.0
    ping_interval: float = 5.0
    connect_timeout: float = 15.0
    ssh_timeout: float = 10.0


class ProgramsSettings(BaseModel):
    ssh_client_path: str | None = None
    vnc_client_path: str | None = None
    winscp_path: str | None = None
    db_client_path: str | None = None
    ssh_args_template: str = (
        "-- ssh -o StrictHostKeyChecking=no -o PasswordAuthentication=yes -p {port} {login}@{host}"
    )
    vnc_args_template: str = "{host}:{display}"
    winscp_args_template: str = "/open scp://{login}@{host}:{port}"
    db_args_template: str = "-h {host} -p {db_port} -U {db_login}"

    def _default_client(self, field: str | None, exe: str) -> str:
        if field and field.strip():
            return field
        from cashcontrol.infrastructure.path_resolver import get_soft_dir
        return str(get_soft_dir() / exe)

    def get_ssh_client(self) -> str:
        return self._default_client(self.ssh_client_path, "kitty.exe")

    def get_vnc_client(self) -> str:
        return self._default_client(self.vnc_client_path, "vncviewer_new.exe")

    def get_winscp(self) -> str:
        return self._default_client(self.winscp_path, "WinSCP.exe")


class GeneralSettings(BaseModel):
    max_tabs: int = 10
    info_cache_ttl: int = 300
    use_builtin_terminal: bool = False
    use_builtin_db_viewer: bool = False
    theme: str = "auto"
    language: str = "ru"
    history_mode: str = "session"
    log_level: str = "INFO"
    setup_completed: bool = False


class VncPreviewSettings(BaseModel):
    quality: str = "Auto"
    color_level: str = "rgb222"


class UpdateSettings(BaseModel):
    network_path: str | None = None
    enabled: bool = True
    check_on_startup: bool = True
    check_interval_h: int = 24


class Settings(BaseModel):
    connection: ConnectionSettings = Field(default_factory=ConnectionSettings)
    programs: ProgramsSettings = Field(default_factory=ProgramsSettings)
    general: GeneralSettings = Field(default_factory=GeneralSettings)
    vnc_preview: VncPreviewSettings = Field(default_factory=VncPreviewSettings)
    update: UpdateSettings = Field(default_factory=UpdateSettings)


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

    @property
    def is_first_launch(self) -> bool:
        return not self._settings.general.setup_completed

    def reload(self) -> None:
        self._settings = self._load()

    def update(self, section: str, **fields: Any) -> None:
        """Update fields of a settings section and persist."""
        section_obj = getattr(self._settings, section)
        for key, value in fields.items():
            setattr(section_obj, key, value)
        self.save()

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
