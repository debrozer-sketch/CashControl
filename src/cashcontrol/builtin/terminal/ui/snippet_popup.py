"""Popup автодополнения сниппетов в самом терминале (Termius-стиль).

Появляется под курсором при вводе, фильтруется по подстроке (имя > теги > тело),
Tab/Enter — применить, ↑↓ — выбор, Esc — закрыть. Пункты: имя (жирно),
теги (акцент), команда (моно, тускло).
"""

from __future__ import annotations

import html
from typing import Optional

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QFont, QKeyEvent
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)


class SnippetPopup(QFrame):
    """Выпадающий список сниппетов под курсором терминала."""

    activated = Signal(object)  # выбранный Snippet
    dismissed = Signal()

    MAX_ITEMS = 8
    MAX_WIDTH = 420

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        # Qt.Tool: получает mouse events (в отличие от ToolTip) и не крадёт
        # фокус у терминала при show с WA_ShowWithoutActivating
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)  # noqa: B104 — macOS
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._items: list = []  # Snippet-объекты
        self._selected_index = 0

        self.list_widget = QListWidget(self)
        self.list_widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.list_widget.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        self.list_widget.setMouseTracking(True)
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list_widget.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # hover-подсветка через QSS (dynamic property), выбор рисуем сами
        self.list_widget.setStyleSheet(
            "QListWidget { background: #262636; border: none; outline: none; }"
            "QListWidget::item { padding: 4px 10px; border-radius: 4px; }"
            "QListWidget::item:hover { background: #33334a; }"
        )
        self.list_widget.itemPressed.connect(self._on_item_clicked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.addWidget(self.list_widget)

        self.setFrameShape(QFrame.Shape.Box)
        self.setStyleSheet(
            "SnippetPopup { background: #20202e; border: 1px solid #4a4a6a;"
            "  border-radius: 6px; }"
        )

    # ---- публичное API ----

    def update_items(self, snippets: list) -> None:
        """Показать/обновить список. Пустой список = скрыться."""
        self._items = list(snippets)
        self._selected_index = 0
        self.list_widget.clear()
        if not self._items:
            self.hide()
            return
        shown = self._items[: self.MAX_ITEMS]
        for s in shown:
            item = QListWidgetItem()
            label = QLabel(self._render_item(s))
            label.setWordWrap(False)
            label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            # запас по высоте: у подсвеченного пункта padding+radius отъедают
            # пиксели, иначе нижняя строка (команда) срезается
            hint = label.sizeHint()
            from PySide6.QtCore import QSize

            item.setSizeHint(QSize(hint.width() + 8, hint.height() + 6))
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, label)
        self._apply_selection()
        self._fit_size()
        if not self.isVisible():
            self.show()

    def _render_item(self, s) -> str:
        """HTML-представление сниппета в две строки."""
        name = html.escape(s.name)
        cmd = html.escape(s.command)
        if len(cmd) > 56:
            cmd = cmd[:56] + "…"
        tags_html = ""
        if s.tags:
            pill = " ".join(html.escape(t) for t in s.tags[:3])
            tags_html = f' <span style="color:#7aa2f7; font-size:8pt;">[{pill}]</span>'
        desc_html = ""
        if s.description:
            desc_html = (
                f'<br><span style="color:#787890; font-size:8pt;">'
                f'{html.escape(s.description[:56])}</span>'
            )
        return (
            f'<div style="color:#ffffff;"><b>{name}</b>{tags_html}</div>'
            f'<div style="color:#9a9ab0; font-family:Consolas, monospace; font-size:8pt;">'
            f'{cmd}</div>{desc_html}'
        )

    def _fit_size(self) -> None:
        """Подстроиться под контент: высота по пунктам, ширина по самому длинному."""
        # высота: сумма sizeHint'ов + рамка
        total_h = sum(self.list_widget.item(i).sizeHint().height() for i in range(self.list_widget.count()))
        self.list_widget.setFixedHeight(total_h)
        # ширина: максимум по label'ам, с ограничением
        max_w = 0
        mono = QFont("Consolas")
        mono.setPointSizeF(8.5)
        for s in self._items[: self.MAX_ITEMS]:
            name_w = 30 + len(s.name) * 8 + (sum(len(t) + 3 for t in s.tags[:3]) + 4) * 6
            cmd_w = 30 + min(len(s.command), 56) * 7
            max_w = max(max_w, name_w, cmd_w)
        w = max(180, min(self.MAX_WIDTH, max_w))
        self.setFixedWidth(w)

    def is_active(self) -> bool:
        return self.isVisible()

    def handle_key(self, event: QKeyEvent) -> bool:
        """Клавиша при активном попапе. True = обработано (не слать в PTY)."""
        key = event.key()
        if key == Qt.Key.Key_Up:
            self._selected_index = max(0, self._selected_index - 1)
            self._apply_selection()
            return True
        if key == Qt.Key.Key_Down:
            self._selected_index = min(len(self._items) - 1, self._selected_index + 1)
            self._apply_selection()
            return True
        if key in (Qt.Key.Key_Tab, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if self._items:
                self._emit_selected()
            return True
        if key == Qt.Key.Key_Escape:
            self.hide_popup()
            return True
        return False

    def hide_popup(self) -> None:
        self.hide()
        self.dismissed.emit()

    # ---- выбор: рисуем рамку сами (QSS-псевдосостояния не для itemWidget) ----

    def _apply_selection(self) -> None:
        for i in range(self.list_widget.count()):
            label = self.list_widget.itemWidget(self.list_widget.item(i))
            if label is None:
                continue
            if i == self._selected_index:
                label.setStyleSheet(
                    "background:#0078d4; border-radius:4px;"
                )
            else:
                label.setStyleSheet("")

    def _emit_selected(self) -> None:
        if 0 <= self._selected_index < len(self._items):
            snippet = self._items[self._selected_index]
            self._items = []  # предохранитель: скрытый попап больше не выбирает
            self.hide()
            self.activated.emit(snippet)

    # ---- мышь ----

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        self._selected_index = self.list_widget.row(item)
        self._emit_selected()

    def mouseMoveEvent(self, event: QEvent) -> None:  # noqa: N802
        # hover мышью: подсветить пункт под курсором
        pos = self.list_widget.viewport().mapFromGlobal(event.globalPosition().toPoint())
        item = self.list_widget.itemAt(pos)
        if item is not None:
            new_index = self.list_widget.row(item)
            if new_index != self._selected_index:
                self._selected_index = new_index
                self._apply_selection()
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QEvent) -> None:  # noqa: N802
        # клик мимо пунктов — закрыть
        pos = self.list_widget.viewport().mapFromGlobal(event.globalPosition().toPoint())
        if self.list_widget.itemAt(pos) is None:
            self.hide_popup()
        super().mousePressEvent(event)
