from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer, Signal

from cashcontrol.infrastructure.audit_logger import get_logger
from cashcontrol.infrastructure.config_manager import ConfigManager
from cashcontrol.infrastructure.path_resolver import get_data_dir

logger = get_logger()

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class HistoryEntry:
    timestamp: datetime
    action_name: str
    result: str
    details: str
    ip: str

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "action_name": self.action_name,
            "result": self.result,
            "details": self.details,
            "ip": self.ip,
        }

    @classmethod
    def from_dict(cls, d: dict) -> HistoryEntry:
        return cls(
            timestamp=datetime.fromisoformat(d["timestamp"]),
            action_name=d["action_name"],
            result=d["result"],
            details=d.get("details", ""),
            ip=d["ip"],
        )


class HistoryManager(QObject):
    entry_added = Signal(str, object)
    _instance: HistoryManager | None = None

    @classmethod
    def instance(cls) -> HistoryManager:
        if cls._instance is None:
            cls._instance = HistoryManager()
        return cls._instance

    def __init__(self) -> None:
        super().__init__()
        self._memory: dict[str, list[HistoryEntry]] = {}
        # Батч-запись: строки копятся в очереди и сбрасываются на диск
        # одним append'ом (таймер 500 мс или 10 записей — что раньше).
        self._pending_lines: dict[str, list[str]] = {}
        self._flush_timer = QTimer(self)
        self._flush_timer.setSingleShot(True)
        self._flush_timer.setInterval(500)
        self._flush_timer.timeout.connect(self.flush)

    def _mode(self) -> str:
        try:
            return ConfigManager().settings.general.history_mode
        except Exception:
            return "session"

    def _history_dir(self) -> Path:
        d = get_data_dir() / "history"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def add(self, ip: str, entry: HistoryEntry) -> None:
        if ip not in self._memory:
            self._memory[ip] = []
        self._memory[ip].append(entry)
        if self._mode() == "persistent":
            line = json.dumps(entry.to_dict(), ensure_ascii=False) + "\n"
            lines = self._pending_lines.setdefault(ip, [])
            lines.append(line)
            if len(lines) >= 10:
                self.flush()
            elif not self._flush_timer.isActive():
                self._flush_timer.start()
        self.entry_added.emit(ip, entry)

    def flush(self) -> None:
        """Сбросить очередь на диск (один append на IP)."""
        self._flush_timer.stop()
        if not self._pending_lines:
            return
        pending, self._pending_lines = self._pending_lines, {}
        for ip, lines in pending.items():
            path = self._history_dir() / f"{ip.replace(':', '_')}.jsonl"
            try:
                with path.open("a", encoding="utf-8") as f:
                    f.write("".join(lines))
            except Exception:
                logger.exception(f"History flush failed for {ip}")

    def get(self, ip: str, limit: int = 100) -> list[HistoryEntry]:
        if self._mode() == "persistent":
            return self._load_from_file(ip, limit)
        entries = self._memory.get(ip, [])
        return list(reversed(entries[-limit:]))

    def clear(self, ip: str) -> None:
        self._memory.pop(ip, None)
        self._pending_lines.pop(ip, None)
        if self._mode() == "persistent":
            f = self._history_dir() / f"{ip.replace(':', '_')}.jsonl"
            f.unlink(missing_ok=True)

    def _append_to_file(self, ip: str, entry: HistoryEntry) -> None:
        """Legacy single-entry append — kept for direct callers/tests."""
        self._pending_lines.setdefault(ip, []).append(
            json.dumps(entry.to_dict(), ensure_ascii=False) + "\n"
        )
        self.flush()

    def _load_from_file(self, ip: str, limit: int) -> list[HistoryEntry]:
        path = self._history_dir() / f"{ip.replace(':', '_')}.jsonl"
        if not path.exists():
            return self._memory.get(ip, [])[-limit:]
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        entries = []
        for line in lines[-limit:]:
            try:
                entries.append(HistoryEntry.from_dict(json.loads(line)))
            except Exception:
                continue
        return list(reversed(entries))


def get_history_manager() -> HistoryManager:
    return HistoryManager.instance()
