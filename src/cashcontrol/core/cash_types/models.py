"""Cash type definitions (Pydantic) and TOML loading helpers."""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, Field


class DbConnection(BaseModel):
    enabled: bool = False
    database: str | None = None
    port: int | None = None


class Connection(BaseModel):
    db: DbConnection = Field(default_factory=DbConnection)


class CashTypeDefinition(BaseModel):
    """Role of a cash register in the network (docs/design/cash_type_system.md)."""

    id: str
    name: str = ""
    aliases: list[str] = Field(default_factory=list)
    icon: str = ""
    extends: str | None = None
    features_mode: str = "union"
    os_hints: list[str] = Field(default_factory=list)
    connection: Connection = Field(default_factory=Connection)
    features: set[str] = Field(default_factory=set)
    extra: dict[str, Any] = Field(default_factory=dict)

    def has(self, feature: str) -> bool:
        return feature in self.features

    _KNOWN_TYPE_KEYS: ClassVar[frozenset[str]] = frozenset(
        {"id", "name", "aliases", "icon", "extends", "os_hints", "features_mode"}
    )

    @classmethod
    def from_toml(cls, data: dict[str, Any], default_id: str = "") -> CashTypeDefinition:
        type_table = dict(data.get("type") or {})
        if not type_table.get("id"):
            type_table["id"] = default_id
        payload: dict[str, Any] = {
            "id": type_table.get("id") or default_id,
            "features": data.get("features", []),
            "extra": data.get("extra", {}),
            "connection": data.get("connection", {}),
        }
        for key in ("name", "aliases", "icon", "extends", "os_hints", "features_mode"):
            if key in type_table:
                payload[key] = type_table[key]
        ignored = set(type_table) - cls._KNOWN_TYPE_KEYS - {"id"}
        if ignored:
            from cashcontrol.infrastructure.audit_logger import get_logger

            get_logger().warning(
                f"Cash type '{payload['id']}': ignoring keys inside [type]: "
                f"{sorted(ignored)} (top-level keys are separate)"
            )
        return cls(**payload)

    def merged_dict(self) -> dict[str, Any]:
        return self.model_dump()
