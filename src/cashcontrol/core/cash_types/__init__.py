"""Cash type system: TOML-defined register roles, aliases, features, detection."""

from cashcontrol.core.cash_types.detector import TypeDetector
from cashcontrol.core.cash_types.merge import ExtendsCycleError, resolve_extends
from cashcontrol.core.cash_types.models import CashTypeDefinition
from cashcontrol.core.cash_types.registry import (
    CashTypeRegistry,
    get_cash_type_registry,
    has_feature,
)

__all__ = [
    "CashTypeDefinition",
    "CashTypeRegistry",
    "ExtendsCycleError",
    "TypeDetector",
    "get_cash_type_registry",
    "has_feature",
    "resolve_extends",
]
