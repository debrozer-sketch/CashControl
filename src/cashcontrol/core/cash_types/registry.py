"""CashTypeRegistry — loads cash_types/*.toml (bundled + user overlay)."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

from cashcontrol.core.cash_types.merge import ExtendsCycleError, resolve_extends
from cashcontrol.core.cash_types.models import CashTypeDefinition
from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Iterable

logger = get_logger()

BUNDLED_DIR = Path(__file__).parent / "bundled"


def _load_toml_files(directory: Path) -> dict[str, dict]:
    result: dict[str, dict] = {}
    if not directory.is_dir():
        return result
    for path in sorted(directory.glob("*.toml")):
        try:
            with path.open("rb") as f:
                result[path.stem] = tomllib.load(f)
        except Exception as e:
            logger.error(f"Failed to parse {path}: {e}")
    return result


class CashTypeRegistry:
    def __init__(self) -> None:
        self._types: dict[str, CashTypeDefinition] = {}
        self._aliases: dict[str, str] = {}

    def load(self) -> None:
        from cashcontrol.infrastructure.path_resolver import get_cash_types_dir

        raw = _load_toml_files(BUNDLED_DIR)
        raw.update(_load_toml_files(get_cash_types_dir()))

        definitions: dict[str, CashTypeDefinition] = {}
        for stem, data in raw.items():
            try:
                definition = CashTypeDefinition.from_toml(data, default_id=stem)
            except Exception as e:
                logger.error(f"Invalid cash type definition '{stem}': {e}")
                continue
            definitions[definition.id] = definition

        try:
            self._types = resolve_extends(definitions)
        except (ExtendsCycleError, ValueError) as e:
            logger.error(f"Cash type extends resolution failed: {e}")
            self._types = {
                t.id: t for t in definitions.values() if not t.extends
            }

        self._aliases = {}
        for definition in self._types.values():
            names = [definition.id, *definition.aliases]
            for name in names:
                self._aliases[name.strip().lower()] = definition.id

    def reload(self) -> None:
        self.load()

    @property
    def types(self) -> dict[str, CashTypeDefinition]:
        return dict(self._types)

    def all(self) -> list[CashTypeDefinition]:
        return list(self._types.values())

    def resolve(self, value: str | None) -> str | None:
        """Normalise id/alias to canonical type id (None when unknown)."""
        if not value:
            return None
        return self._aliases.get(value.strip().lower())

    def match_substring(self, value: str) -> str | None:
        """Find a type whose alias is contained in the given raw string."""
        lowered = value.strip().lower()
        for alias, type_id in self._aliases.items():
            if len(alias) > 2 and alias in lowered:
                return type_id
        return None

    def get(self, value: str | None) -> CashTypeDefinition | None:
        type_id = self.resolve(value)
        return self._types.get(type_id) if type_id else None

    def has(self, value: str | None) -> bool:
        return self.resolve(value) is not None


_registry: CashTypeRegistry | None = None


def get_cash_type_registry() -> CashTypeRegistry:
    global _registry
    if _registry is None:
        _registry = CashTypeRegistry()
        _registry.load()
    return _registry


def has_feature(source: object, feature: str) -> bool:
    """Feature check by canonical id / alias / session-like object.

    Unknown type (None/"unknown") resolves to False."""
    value = getattr(source, "cash_type", source)
    definition = get_cash_type_registry().get(value if isinstance(value, str) else None)
    return bool(definition and definition.has(feature))


def known_type_ids() -> Iterable[str]:
    return get_cash_type_registry().types.keys()
