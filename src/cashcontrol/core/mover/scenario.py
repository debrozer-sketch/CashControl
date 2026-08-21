"""
scenario.py — Mover scenario model: load, save, validate JSON scenarios.

A scenario is an ordered list of steps to execute on a cash register.
Each step has a type, configuration, and optional applicability filter.

Scenario JSON format:
    {
        "name": "...",
        "description": "...",
        "version": 1,
        "steps": [
            {
                "id": "unique_id",
                "type": "upload_files | run_commands | loymax | qrid | set_com_port",
                "enabled": true,
                "label": "Human-readable label",
                "applies_to": ["pos", "touch", "sco3"],   // optional, default=all
                "config": { ... }                           // type-specific
            }
        ]
    }
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cashcontrol.infrastructure.audit_logger import get_logger
from cashcontrol.infrastructure.path_resolver import (
    MOVER_CASH_TYPES,
    get_mover_scenarios_dir,
)

logger = get_logger()

# All known step types
STEP_TYPES = ("upload_files", "run_commands", "loymax", "qrid", "set_com_port")

# Human-readable labels for step types (defaults)
STEP_TYPE_LABELS: dict[str, str] = {
    "upload_files": "Загрузка файлов",
    "run_commands": "Выполнение команд",
    "loymax": "Настройка Loymax",
    "qrid": "Настройка QRID",
    "set_com_port": "Настройка COM-порта",
}

# Default applies_to per step type (which cash types the step applies to)
STEP_TYPE_DEFAULT_APPLIES_TO: dict[str, list[str]] = {
    "upload_files": list(MOVER_CASH_TYPES),
    "run_commands": list(MOVER_CASH_TYPES),
    "loymax": list(MOVER_CASH_TYPES),
    "qrid": ["pos"],
    "set_com_port": ["pos"],
}

# Icons for step types (emoji)
STEP_TYPE_ICONS: dict[str, str] = {
    "upload_files": "📤",
    "run_commands": "⚡",
    "loymax": "🔑",
    "qrid": "📱",
    "set_com_port": "🔌",
}

CURRENT_SCHEMA_VERSION = 1


@dataclass
class StepDefinition:
    """A single step in a Mover scenario."""

    id: str
    type: str
    enabled: bool = True
    label: str = ""
    applies_to: list[str] = field(default_factory=list)
    config: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.label:
            self.label = STEP_TYPE_LABELS.get(self.type, self.type)
        if not self.applies_to:
            self.applies_to = list(STEP_TYPE_DEFAULT_APPLIES_TO.get(
                self.type, list(MOVER_CASH_TYPES)
            ))

    def applies_to_cash_type(self, cash_type: str) -> bool:
        """Check if this step applies to the given cash type."""
        return cash_type.lower() in [ct.lower() for ct in self.applies_to]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON."""
        return {
            "id": self.id,
            "type": self.type,
            "enabled": self.enabled,
            "label": self.label,
            "applies_to": self.applies_to,
            "config": self.config,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StepDefinition:
        """Deserialize from dictionary."""
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            type=data["type"],
            enabled=data.get("enabled", True),
            label=data.get("label", ""),
            applies_to=data.get("applies_to", []),
            config=data.get("config", {}),
        )


@dataclass
class Scenario:
    """A complete Mover scenario — ordered list of steps."""

    name: str
    description: str = ""
    version: int = CURRENT_SCHEMA_VERSION
    steps: list[StepDefinition] = field(default_factory=list)
    file_path: Path | None = field(default=None, repr=False)

    def get_steps_for_cash_type(self, cash_type: str) -> list[StepDefinition]:
        """Return only enabled steps that apply to the given cash type."""
        return [
            step for step in self.steps
            if step.enabled and step.applies_to_cash_type(cash_type)
        ]

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON."""
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], file_path: Path | None = None) -> Scenario:
        """Deserialize from dictionary."""
        steps = [StepDefinition.from_dict(s) for s in data.get("steps", [])]
        return cls(
            name=data.get("name", "Без названия"),
            description=data.get("description", ""),
            version=data.get("version", CURRENT_SCHEMA_VERSION),
            steps=steps,
            file_path=file_path,
        )

    def save(self, path: Path | None = None) -> Path:
        """
        Save scenario to JSON file.

        Args:
            path: Target path. If None, uses self.file_path or generates one.

        Returns:
            Path where scenario was saved.
        """
        if path is None:
            path = self.file_path
        if path is None:
            safe_name = self.name.replace(" ", "_").lower()
            path = get_mover_scenarios_dir() / f"{safe_name}.json"

        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=4)

        self.file_path = path
        logger.info(f"Scenario saved: {path}")
        return path


class ScenarioManager:
    """
    Manages Mover scenarios — list, load, save, delete.

    Scans mover/scenarios/ directory for JSON files.
    """

    def __init__(self) -> None:
        self._scenarios_dir = get_mover_scenarios_dir()

    def list_scenarios(self) -> list[tuple[str, Path]]:
        """
        List all available scenarios.

        Returns:
            List of (scenario_name, file_path) tuples, sorted by name.
        """
        result: list[tuple[str, Path]] = []
        if not self._scenarios_dir.exists():
            return result

        for json_file in sorted(self._scenarios_dir.glob("*.json")):
            try:
                with open(json_file, encoding="utf-8") as f:
                    data = json.load(f)
                name = data.get("name", json_file.stem)
                result.append((name, json_file))
            except Exception as e:
                logger.warning(f"Cannot read scenario {json_file}: {e}")
                result.append((json_file.stem, json_file))

        return result

    def load(self, path_or_name: str | Path) -> Scenario:
        """
        Load a scenario by path or name.

        Args:
            path_or_name: Full path to JSON file, or scenario name (without extension).

        Returns:
            Loaded Scenario object.

        Raises:
            FileNotFoundError: If scenario file not found.
            ValueError: If scenario JSON is invalid.
        """
        if isinstance(path_or_name, Path):
            path = path_or_name
        else:
            # Try as absolute/relative path first
            candidate = Path(path_or_name)
            if candidate.exists():
                path = candidate
            else:
                # Try as name in scenarios dir
                path = self._scenarios_dir / f"{path_or_name}.json"

        if not path.exists():
            raise FileNotFoundError(f"Scenario not found: {path}")

        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in scenario {path}: {e}")

        scenario = Scenario.from_dict(data, file_path=path)
        logger.info(f"Scenario loaded: {scenario.name} ({len(scenario.steps)} steps)")
        return scenario

    def save(self, scenario: Scenario, path: Path | None = None) -> Path:
        """Save a scenario. Delegates to Scenario.save()."""
        return scenario.save(path)

    def delete(self, path: Path) -> bool:
        """
        Delete a scenario file.

        Args:
            path: Path to scenario JSON file.

        Returns:
            True if deleted, False if not found.
        """
        if path.exists():
            path.unlink()
            logger.info(f"Scenario deleted: {path}")
            return True
        return False