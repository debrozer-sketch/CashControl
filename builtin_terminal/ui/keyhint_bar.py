"""Тонкая строка хоткеев внизу окна в терминальном стиле (как в mc/FAR)."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontMetrics, QMouseEvent, QPainter, QPaintEvent, QPen
from PySide6.QtWidgets import QWidget


class KeyHintBar(QWidget):
    """Полоса подсказок: 'Ctrl+N Подключить │ Ctrl+Shift+V Вставить │ …'."""

    STYLE_FLAT = "flat"      # просто текст
    STYLE_KEYS = "keys"      # ^N-стиль: ^N Подключить

    def __init__(self, parent: Optional[QWidget] = None, style: str = STYLE_KEYS) -> None:
        super().__init__(parent)
        self._items: list[tuple[str, str]] = []
        self._style = style
        self._hover_index: Optional[int] = None
        self._click_handlers: list = []

        font = QFont()
        font.setPointSizeF(8.0)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._font = font

        self.setMouseTracking(True)
        self.setFixedHeight(self._compute_height())

    # ---- API ----

    def set_items(self, items: list[tuple[str, str]]) -> None:
        """items: [(key, label), ...] — key может быть пустым (текст-подсказка)."""
        self._items = list(items)
        self._click_handlers = [None] * len(items)
        self.updateGeometry()
        self.update()

    def set_handler(self, index: int, handler) -> None:
        if 0 <= index < len(self._click_handlers):
            self._click_handlers[index] = handler

    def _compute_height(self) -> int:
        fm = QFontMetrics(self._font)
        return fm.height() + 6

    # ---- рендер ----

    def paintEvent(self, event: QPaintEvent) -> None:
        p = QPainter(self)
        p.setFont(self._font)
        p.fillRect(self.rect(), Qt.GlobalColor.transparent)

        fg = self.palette().color(self.palette().ColorRole.WindowText)
        dim = fg.darker(150) if fg.lightness() > 128 else fg.lighter(150)
        accent = Qt.GlobalColor.white if fg.lightness() > 128 else Qt.GlobalColor.black
        pen_dim = QPen(dim)
        pen_accent = QPen(fg)

        x = 8
        fm = QFontMetrics(self._font)
        for i, (key, label) in enumerate(self._items):
            if key:
                # клавиша чуть ярче, подпись тусклее
                key_text = self._fmt_key(key)
                p.setPen(pen_accent if i == self._hover_index else pen_dim)
                p.drawText(x, self._text_y(fm), key_text)
                x += fm.horizontalAdvance(key_text) + 3
                if label:
                    p.setPen(pen_dim)
                    p.drawText(x, self._text_y(fm), label)
                    x += fm.horizontalAdvance(label) + 3
            else:
                p.setPen(pen_dim)
                p.drawText(x, self._text_y(fm), label)
                x += fm.horizontalAdvance(label) + 3
            x += 8  # разделитель между группами
        p.end()

    def _fmt_key(self, key: str) -> str:
        if self._style == self.STYLE_KEYS:
            # 'Ctrl+N' -> '^N', 'Ctrl+Shift+V' -> '^SV', 'F10' -> 'F10'
            if key.startswith("Ctrl+"):
                rest = key[len("Ctrl+"):]
                return "^" + rest.replace("Shift+", "S")
            return key
        return key

    def _text_y(self, fm: QFontMetrics) -> int:
        return (self.height() - fm.descent() - (self.height() - fm.height()) // 2) - 2

    # ---- мышь ----

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        new_hover = self._item_at(event.position().x())
        if new_hover != self._hover_index:
            self._hover_index = new_hover
            self.update()
            self.setCursor(
                Qt.CursorShape.PointingHandCursor if new_hover is not None else Qt.CursorShape.ArrowCursor
            )

    def mousePressEvent(self, event: QMouseEvent) -> None:
        idx = self._item_at(event.position().x())
        if idx is not None and self._click_handlers[idx] is not None:
            self._click_handlers[idx]()

    def _item_at(self, x_pos: float) -> Optional[int]:
        fm = QFontMetrics(self._font)
        x = 8
        for i, (key, label) in enumerate(self._items):
            text_w = 0
            if key:
                key_text = self._fmt_key(key)
                text_w += fm.horizontalAdvance(key_text) + 3
            if label:
                text_w += fm.horizontalAdvance(label) + 3
            if x <= x_pos <= x + text_w:
                return i
            x += text_w + 8
        return None
