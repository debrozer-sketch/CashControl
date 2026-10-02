"""Ввод IP-адреса: запятая превращается в точку.

С русской раскладкой адрес набирают как ``192,168,1,10``. Запятая заменяется
на точку прямо во время ввода, без участия пользователя и без потери позиции
курсора.

Подключать через ``textEdited``, а не ``textChanged``: при ``setText`` сигнал
тоже приходит, и нормализация вызывала бы себя рекурсивно.
"""

from __future__ import annotations

from typing import Protocol


class _HasCursor(Protocol):
    def text(self) -> str: ...

    def setText(self, text: str) -> None: ...

    def cursorPosition(self) -> int: ...

    def setCursorPosition(self, pos: int) -> None: ...


__all__ = ["install_comma_to_dot", "normalize_ip_text"]


def normalize_ip_text(text: str) -> str:
    return text.replace(",", ".")


def install_comma_to_dot(edit: _HasCursor) -> None:
    """Подключить замену запятой на точку к полю ввода.

    Схема с сохранением позиции курсора: замена символа на символ не меняет
    длину, поэтому позиция остаётся корректной без поправок.
    """

    def _on_text_edited(text: str) -> None:
        if "," not in text:
            return
        pos = edit.cursorPosition()
        edit.setText(normalize_ip_text(text))
        edit.setCursorPosition(pos)

    edit.textEdited.connect(_on_text_edited)
