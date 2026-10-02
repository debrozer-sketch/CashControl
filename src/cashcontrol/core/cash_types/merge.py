"""extends-chain resolution with deep merge (TOML inheritance, not OOP)."""

from __future__ import annotations

from typing import Any

from cashcontrol.core.cash_types.models import CashTypeDefinition


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class ExtendsCycleError(ValueError):
    pass


def resolve_extends(raw: dict[str, CashTypeDefinition]) -> dict[str, CashTypeDefinition]:
    """Resolve `extends` chains: parent fields are merged under the child,
    feature sets union by default (features_mode = "replace" overrides)."""
    resolved: dict[str, CashTypeDefinition] = {}

    def _resolve(type_id: str, chain: tuple[str, ...]) -> CashTypeDefinition:
        if type_id in resolved:
            return resolved[type_id]
        if type_id in chain:
            raise ExtendsCycleError(
                f"extends cycle: {' -> '.join((*chain, type_id))}"
            )
        node = raw[type_id]
        if not node.extends:
            resolved[type_id] = node
            return node
        if node.extends not in raw:
            raise ValueError(
                f"{type_id}: extends unknown type '{node.extends}'"
            )
        parent = _resolve(node.extends, (*chain, type_id))
        merged = deep_merge(parent.merged_dict(), node.merged_dict())
        features = set(parent.features)
        if node.features_mode == "replace":
            features = set(node.features)
        else:
            features |= node.features
        merged["features"] = features
        child = CashTypeDefinition(**merged)
        resolved[type_id] = child
        return child

    for type_id in raw:
        _resolve(type_id, ())
    return resolved
