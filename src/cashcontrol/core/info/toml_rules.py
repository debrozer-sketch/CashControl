"""
Declarative problem rules from TOML files (no Python required).

Any ``*.toml`` placed in the collectors directory may carry ``[[rule]]``
entries describing what to check over the collected snapshot:

    [[rule]]
    section      = "disk"        # snapshot section (collector name)
    key          = "disk_free"   # field key inside section.data
    op           = "<"           # == != > < >= <= contains is_null not_null
    value        = 100
    severity     = "warning"     # "warning" | "error"
    message      = "мало места: {value} МБ"
    label        = "Диск"        # optional heading shown in «Проблемы»
    cash_types   = []            # empty = all; or cash type ids/aliases/features

The same file may combine ``[[fields]]`` (data collection) and ``[[rule]]``
(checks), or hold rules only. A rule's condition describes the FAULT: when
the collected value matches it, a problem is reported. ``{value}`` in the
message is replaced with the collected value.
"""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING

from cashcontrol.core.cash_types.registry import (
    get_cash_type_registry,
    has_feature,
)
from cashcontrol.core.info.rules import ProblemIssue
from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from pathlib import Path

logger = get_logger()

_ALLOWED_OPS = {"==", "!=", ">", ">=", "<", "<=", "contains", "is_null", "not_null"}
_NULLISH = {"", "-", "\u2014", "nan", "none"}


def _numeric(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _nullish(actual) -> bool:
    if actual is None:
        return True
    if isinstance(actual, str):
        return actual.strip().lower() in _NULLISH
    return False


class TomlRule:
    """One declarative check loaded from a TOML file."""

    def __init__(
        self,
        section: str,
        key: str,
        op: str,
        value: object,
        message: str,
        severity: str = "warning",
        cash_types: list[str] | None = None,
        label: str | None = None,
        source: str = "",
    ) -> None:
        if op not in _ALLOWED_OPS:
            raise ValueError(f"unsupported op {op!r}")
        self.section = section
        self.key = key
        self.op = op
        self.value = value
        self.message = message
        self.severity = "error" if severity == "error" else "warning"
        self.cash_types = list(cash_types or [])
        self.label = label or section
        self.source = source

    def applies_to(self, cash_type: str) -> bool:
        """Empty cash_types → all; otherwise match by id/alias or feature."""
        if not self.cash_types:
            return True
        registry = get_cash_type_registry()
        actual_id = registry.resolve(cash_type)
        for entry in self.cash_types:
            if actual_id and registry.resolve(entry) == actual_id:
                return True
            if has_feature(cash_type, entry):
                return True
        return False

    def check(self, snapshot, cash_type: str) -> ProblemIssue | None:
        if not self.applies_to(cash_type):
            return None
        section = snapshot.get_section(self.section)
        if section is None:
            return None
        actual = section.data.get(self.key)
        if not self._evaluate(actual):
            return None
        message = self.message.format(value=actual if actual is not None else "")
        return ProblemIssue(self.label, message, self.severity)

    def _evaluate(self, actual: object) -> bool:
        op = self.op
        if op == "is_null":
            return _nullish(actual)
        if op == "not_null":
            return not _nullish(actual)
        if actual is None:
            return False

        if op == "contains":
            return str(self.value) in str(actual)

        expected = self.value
        if isinstance(expected, bool):
            flag = str(actual).strip().lower()
            if flag in ("true", "1", "yes", "on"):
                resolved_bool = True
            elif flag in ("false", "0", "no", "off"):
                resolved_bool = False
            else:
                return False
            if op == "==":
                return resolved_bool == expected
            if op == "!=":
                return resolved_bool != expected
            return False

        left = str(actual).strip()
        right = str(expected).strip()
        left_num, right_num = _numeric(left), _numeric(right)
        use_numeric = left_num is not None and right_num is not None
        a: object = left_num if use_numeric else left
        b: object = right_num if use_numeric else right

        if op == "==":
            if use_numeric:
                return a == b
            return left.lower() == right.lower()
        if op == "!=":
            if use_numeric:
                return a != b
            return left.lower() != right.lower()
        try:
            if op == ">":
                return a > b
            if op == ">=":
                return a >= b
            if op == "<":
                return a < b
            if op == "<=":
                return a <= b
        except TypeError:
            return False
        return False

    def __repr__(self) -> str:
        return f"<TomlRule {self.section}.{self.key} {self.op} {self.value}>"


class TomlRuleChecker:
    """Loads all [[rule]] entries from *.toml files in the collectors dir."""

    def load(self, directory: Path | None = None) -> list[TomlRule]:
        from cashcontrol.infrastructure.path_resolver import get_collectors_dir

        rules: list[TomlRule] = []
        path_dir = directory or get_collectors_dir()
        if not path_dir.is_dir():
            return rules
        for path in sorted(path_dir.glob("*.toml")):
            try:
                with path.open("rb") as f:
                    data = tomllib.load(f)
            except Exception as e:
                logger.error(f"Failed to parse rules file {path}: {e}")
                continue
            default_section = None
            meta = data.get("collector")
            if isinstance(meta, dict):
                default_section = meta.get("name")
            for raw in data.get("rule") or data.get("rules") or []:
                rule = self._build_rule(raw, default_section, path)
                if rule is not None:
                    rules.append(rule)
        return rules

    @staticmethod
    def _build_rule(
        raw: dict, default_section: str | None, path: Path
    ) -> TomlRule | None:
        section = raw.get("section") or default_section
        key = raw.get("key")
        op = raw.get("op")
        if not key or not op:
            logger.warning(f"Rule in {path} is missing key/op, skipped")
            return None
        op_lower = str(op).lower()
        if op_lower not in _ALLOWED_OPS:
            logger.warning(
                f"Rule {path}:{section}.{key} uses unsupported op {op!r}, skipped"
            )
            return None
        if not section:
            logger.warning(f"Rule {path}:{key} has no section, skipped")
            return None
        try:
            return TomlRule(
                section=section,
                key=key,
                op=op_lower,
                value=raw.get("value"),
                message=raw.get("message")
                or f"не соответствует условию: {key} {op_lower} {raw.get('value', '')}",
                severity=raw.get("severity", "warning"),
                cash_types=raw.get("cash_types"),
                label=raw.get("label"),
                source=str(path),
            )
        except ValueError as e:
            logger.warning(f"Invalid rule {path}:{section}.{key}: {e}")
            return None
