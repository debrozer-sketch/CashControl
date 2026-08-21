from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DiffResult:
    added: list[str] = field(default_factory=list)
    changed: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    @property
    def has_changes(self) -> bool:
        return bool(self.added or self.changed or self.deleted)

    @property
    def total(self) -> int:
        return len(self.added) + len(self.changed) + len(self.deleted)


def diff(current: dict[str, str], baseline: dict[str, str]) -> DiffResult:
    current_keys = set(current.keys())
    baseline_keys = set(baseline.keys())

    return DiffResult(
        added=sorted(current_keys - baseline_keys),
        changed=sorted(
            k for k in current_keys & baseline_keys if current[k] != baseline[k]
        ),
        deleted=sorted(baseline_keys - current_keys),
    )
