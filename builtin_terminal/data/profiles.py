"""Хранение профилей и настроек прототипа.

Portable-стиль: всё в подпапке <проект>/data/app/ рядом с кодом,
система не засоряется (%LOCALAPPDATA% не используется).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional


def _app_data_dir() -> Path:
    """Папка данных: <корень проекта>/data/app (portable)."""
    # data/profiles.py -> <проект>/data/app
    app_dir = Path(__file__).resolve().parent / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


@dataclass
class HostProfile:
    name: str
    host: str
    username: str = "root"
    port: int = 22
    password: Optional[str] = None
    color_tag: str = "none"  # none | red | green | blue | yellow
    last_connected: Optional[str] = None

    @property
    def profile_id(self) -> str:
        return f"{self.host}:{self.port}:{self.username}"


@dataclass
class AppSettings:
    font_size: float = 10.0
    font_family: Optional[str] = None
    scrollback_lines: int = 10000
    copy_on_select: bool = True
    keepalive_interval: float = 15.0
    connect_timeout: float = 15.0
    theme: str = "dark"
    # режим стрелок: "auto" (по DECCKM) | "normal" (ESC[A) | "app" (ESCOA)
    cursor_keys_mode: str = "auto"
    # тип терминала: "xterm" как PuTTY (макс. совместимость, esp. урезанные
    # terminfo на кассах), "xterm-256color" для полноценных хостов
    term_type: str = "xterm"


class _JsonStore:
    def __init__(self, filename: str) -> None:
        self._path = _app_data_dir() / filename
        self._data: dict = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}

    def _save(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    # dict-like
    def get(self, key: str, default: object = None) -> object:
        return self._data.get(key, default)

    def set(self, key: str, value: object) -> None:
        self._data[key] = value
        self._save()


class ProfileStore:
    """Профили хостов + настройки + последние подключения."""

    def __init__(self) -> None:
        self._store = _JsonStore("profiles.json")
        self.settings = AppSettings()
        self._load_settings()

    # ---- settings ----

    def _load_settings(self) -> None:
        raw = self._store.get("settings", {})
        for f in self.settings.__dataclass_fields__:
            if f in raw:
                setattr(self.settings, f, raw[f])

    def save_settings(self) -> None:
        self._store.set("settings", asdict(self.settings))

    # ---- profiles ----

    @property
    def _profiles(self) -> list[dict]:
        return self._store.get("profiles", [])

    def all_profiles(self) -> list[HostProfile]:
        # фильтруем неизвестные ключи (миграция старых форматов)
        valid = set(HostProfile.__dataclass_fields__)
        return [HostProfile(**{k: v for k, v in p.items() if k in valid}) for p in self._profiles]

    def upsert(self, profile: HostProfile) -> None:
        profiles = [dict(p) for p in self._profiles]
        for i, p in enumerate(profiles):
            if p.get("profile_id") == profile.profile_id or (
                p.get("host") == profile.host and p.get("port") == profile.port
                and p.get("username") == profile.username
            ):
                profiles[i] = asdict(profile)
                profiles[i]["profile_id"] = profile.profile_id
                break
        else:
            entry = asdict(profile)
            entry["profile_id"] = profile.profile_id
            profiles.append(entry)
        self._store.set("profiles", profiles)

    def delete(self, profile: HostProfile) -> None:
        profiles = [p for p in self._profiles
                    if not (p["host"] == profile.host and p["port"] == profile.port
                            and p["username"] == profile.username)]
        self._store.set("profiles", profiles)

    # ---- recent ----

    def push_recent(self, profile: HostProfile) -> None:
        recents: list = self._store.get("recent", [])
        recents = [p for p in recents if p != profile.profile_id]
        recents.insert(0, profile.profile_id)
        self._store.set("recent", recents[:10])

    def recent_ids(self) -> list[str]:
        return list(self._store.get("recent", []))

    # ---- known hosts (TOFU) ----

    @property
    def known_hosts_path(self) -> Path:
        return _app_data_dir() / "known_hosts"
