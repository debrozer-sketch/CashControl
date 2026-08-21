"""
Status bar — collapsible panel at the bottom of the main window.

Two tabs inside:
  - История       — action history for the active cash tab
  - Уведомления   — system notifications (replaces Toast)

Collapsed: single row, shows last event (action or notification).
Expanded:  full panel with tabs, list, and clear button.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

if TYPE_CHECKING:
    from cashcontrol.gui.history_manager import HistoryEntry
    from cashcontrol.gui.notification_manager import Notification

_COLLAPSED_H = 28
_EXPANDED_H  = 200
_ANIM_MS     = 220


class CashStatusBar(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._expanded   = False
        self._active_ip: str | None = None
        self._anim: QPropertyAnimation | None = None

        self.setMinimumHeight(_COLLAPSED_H)
        self.setMaximumHeight(_COLLAPSED_H)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Maximum,
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sep = QFrame(self)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        sep.setFixedHeight(1)
        root.addWidget(sep)

        collapsed_bar = QWidget(self)
        collapsed_bar.setFixedHeight(_COLLAPSED_H - 1)
        cl = QHBoxLayout(collapsed_bar)
        cl.setContentsMargins(8, 0, 8, 0)
        cl.setSpacing(6)

        self._toggle_btn = QLabel("▲", collapsed_bar)
        self._toggle_btn.setFixedWidth(14)
        self._toggle_btn.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.mousePressEvent = lambda _e: self._toggle_expanded()

        self._status_lbl = QLabel("", collapsed_bar)
        self._status_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        self._status_lbl.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )

        cl.addWidget(self._toggle_btn)
        cl.addWidget(self._status_lbl, stretch=1)
        root.addWidget(collapsed_bar)

        self._expanded_panel = QWidget(self)
        self._expanded_panel.setVisible(False)
        el = QVBoxLayout(self._expanded_panel)
        el.setContentsMargins(4, 2, 4, 4)
        el.setSpacing(2)

        tab_row = QHBoxLayout()
        tab_row.setSpacing(2)

        self._btn_history = QPushButton("История", self._expanded_panel)
        self._btn_history.setFixedHeight(22)
        self._btn_history.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_history.clicked.connect(lambda: self._switch_tab(0))

        self._btn_notifs = QPushButton("Уведомления", self._expanded_panel)
        self._btn_notifs.setFixedHeight(22)
        self._btn_notifs.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_notifs.clicked.connect(lambda: self._switch_tab(1))

        tab_row.addWidget(self._btn_history)
        tab_row.addWidget(self._btn_notifs)
        tab_row.addStretch()
        el.addLayout(tab_row)

        self._stack = QStackedWidget(self._expanded_panel)

        self._history_list = QListWidget()
        self._history_list.setFrameShape(QFrame.Shape.NoFrame)
        self._stack.addWidget(self._history_list)

        self._notif_list = QListWidget()
        self._notif_list.setFrameShape(QFrame.Shape.NoFrame)
        self._stack.addWidget(self._notif_list)

        el.addWidget(self._stack, stretch=1)

        self._clear_btn = QPushButton("Очистить", self._expanded_panel)
        self._clear_btn.setFixedHeight(22)
        self._clear_btn.clicked.connect(self._on_clear)
        el.addWidget(self._clear_btn)

        root.addWidget(self._expanded_panel)
        self._switch_tab(0)

    # ── Public API ────────────────────────────────────────────────────────

    def set_active_ip(self, ip: str | None) -> None:
        self._active_ip = ip if ip else None
        self._refresh_history()

    def set_status_text(self, text: str) -> None:
        self._status_lbl.setText(text)

    def add_history_entry(self, ip: str, entry: HistoryEntry) -> None:
        if ip == self._active_ip:
            self._add_history_item(entry)
            icon = "✅" if entry.result == "success" else "❌"
            msg  = f"{icon} {entry.action_name}"
            if entry.details:
                msg += f" — {entry.details}"
            self._status_lbl.setText(msg)

    def add_notification(self, n: Notification) -> None:
        icons  = {"info": "ℹ", "success": "✅", "warning": "⚠", "error": "❌"}
        prefix = icons.get(n.level, "ℹ")
        self._add_notif_item(f"{prefix} {n.message}")
        short = n.message[:80] + "…" if len(n.message) > 80 else n.message
        self._status_lbl.setText(f"{prefix} {short}")

    # ── Tabs ──────────────────────────────────────────────────────────────

    def _switch_tab(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        active_ss   = "font-weight: bold; text-decoration: underline;"
        inactive_ss = ""
        if index == 0:
            self._btn_history.setStyleSheet(active_ss)
            self._btn_notifs.setStyleSheet(inactive_ss)
        else:
            self._btn_history.setStyleSheet(inactive_ss)
            self._btn_notifs.setStyleSheet(active_ss)

    # ── Expand / collapse ─────────────────────────────────────────────────

    def _toggle_expanded(self) -> None:
        if self._expanded:
            self._do_collapse()
        else:
            self._do_expand()

    def _do_expand(self) -> None:
        self._expanded = True
        self._expanded_panel.setVisible(True)
        self._toggle_btn.setText("▼")
        self._animate_to(_COLLAPSED_H + _EXPANDED_H)

    def _do_collapse(self) -> None:
        self._expanded = False
        self._toggle_btn.setText("▲")
        self._animate_to(_COLLAPSED_H)

    def _animate_to(self, target_h: int) -> None:
        if self._anim and self._anim.state() == QPropertyAnimation.State.Running:
            self._anim.stop()
        self._anim = QPropertyAnimation(self, b"panelHeight")
        self._anim.setDuration(_ANIM_MS)
        self._anim.setStartValue(self.maximumHeight())
        self._anim.setEndValue(target_h)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.finished.connect(self._on_anim_finished)
        self._anim.start()

    def _on_anim_finished(self) -> None:
        if not self._expanded:
            self._expanded_panel.setVisible(False)
            self._set_panel_height(_COLLAPSED_H)
        self._anim = None

    def _get_panel_height(self) -> int:
        return self.maximumHeight()

    def _set_panel_height(self, h: int) -> None:
        self.setMinimumHeight(h)
        self.setMaximumHeight(h)

    panelHeight = Property(int, _get_panel_height, _set_panel_height)

    # ── Clear ─────────────────────────────────────────────────────────────

    def _on_clear(self) -> None:
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "Очистить", "Очистить все записи?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if self._stack.currentIndex() == 0:
            self._history_list.clear()
            if self._active_ip:
                from cashcontrol.gui.history_manager import get_history_manager
                get_history_manager().clear(self._active_ip)
        else:
            self._notif_list.clear()
            from cashcontrol.gui.notification_manager import get_notification_manager
            get_notification_manager().clear()

    # ── History ───────────────────────────────────────────────────────────

    def _refresh_history(self) -> None:
        self._history_list.clear()
        if not self._active_ip:
            return
        from cashcontrol.gui.history_manager import get_history_manager
        for entry in get_history_manager().get(self._active_ip):
            self._add_history_item(entry)

    def _add_history_item(self, entry: HistoryEntry) -> None:
        icon = "✅" if entry.result == "success" else "❌"
        ts   = entry.timestamp.strftime("%H:%M:%S")
        text = f"{ts}  {icon}  {entry.action_name}"
        if entry.details:
            text += f" — {entry.details}"
        self._history_list.insertItem(0, QListWidgetItem(text))

    def _add_notif_item(self, text: str) -> None:
        self._notif_list.insertItem(0, QListWidgetItem(text))