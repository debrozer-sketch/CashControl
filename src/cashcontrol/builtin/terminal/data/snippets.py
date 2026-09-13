"""Хранилище сниппетов: имя, команда, описание, теги (JSON)."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Optional

from data.profiles import _JsonStore


@dataclass
class Snippet:
    name: str
    command: str
    description: str = ""
    tags: list[str] = field(default_factory=list)
    send_with_enter: bool = True
    scope: str = "global"  # "global" | "profile:user@host:port"


class SnippetStore:
    """CRUD сниппетов + поиск по имени/тегам/телу команды."""

    def __init__(self) -> None:
        self._store = _JsonStore("snippets.json")

    @property
    def _items(self) -> list[dict]:
        return self._store.get("snippets", [])

    def all(self) -> list[Snippet]:
        # фильтруем неизвестные ключи (миграция старых форматов)
        valid = set(Snippet.__dataclass_fields__)
        return [Snippet(**{k: v for k, v in s.items() if k in valid}) for s in self._items]

    def upsert(self, snippet: Snippet) -> None:
        items = [dict(s) for s in self._items]
        for i, s in enumerate(items):
            if s.get("name") == snippet.name:
                items[i] = asdict(snippet)
                break
        else:
            items.append(asdict(snippet))
        self._store.set("snippets", items)

    def delete(self, name: str) -> None:
        items = [s for s in self._items if s.get("name") != name]
        self._store.set("snippets", items)

    def search(self, query: str, scope: Optional[str] = None) -> list[Snippet]:
        """Поиск по подстроке: имя > теги > тело команды."""
        q = query.lower().strip()
        result_name: list[Snippet] = []
        result_tag: list[Snippet] = []
        result_body: list[Snippet] = []
        for s in self.all():
            if scope is not None and s.scope not in ("global", scope):
                continue
            if not q:
                result_name.append(s)
            elif q in s.name.lower():
                result_name.append(s)
            elif any(q in t.lower() for t in s.tags):
                result_tag.append(s)
            elif q in s.command.lower():
                result_body.append(s)
        return result_name + result_tag + result_body
