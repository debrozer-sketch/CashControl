from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QWidget
from qfluentwidgets import TabBar, TabCloseButtonDisplayMode

_DOT_COLORS: dict[str, QColor] = {
    "ok": QColor("#2ecc71"),
    "slow": QColor("#f1c40f"),
    "timeout": QColor("#e74c3c"),
    "unknown": QColor("#95a5a6"),
}


def _make_dot_icon(color: QColor, size: int = 12) -> QIcon:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QBrush(color))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(1, 1, size - 2, size - 2)
    painter.end()
    return QIcon(pixmap)


class _ScrollableTabBar(TabBar):
    def wheelEvent(self, event) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            delta = -event.angleDelta().x()
        if delta > 0:
            idx = max(0, self.currentIndex() - 1)
        else:
            idx = min(self.count() - 1, self.currentIndex() + 1)
        if idx != self.currentIndex():
            self.setCurrentIndex(idx)
        event.accept()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            pos = event.position().toPoint()
            for i in range(self.count()):
                item = self.tabItem(i)
                if item and item.geometry().contains(pos):
                    self.tabCloseRequested.emit(i)
                    event.accept()
                    return
        super().mousePressEvent(event)


class CashTabBar(QWidget):
    tab_add_requested = Signal()
    tab_close_requested = Signal(str)
    tab_selected = Signal(str)
    tab_ip_changed = Signal(str, str)
    tab_refresh_requested = Signal(str)
    tab_copy_ip_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._bar = _ScrollableTabBar(self)
        self._bar.setMovable(True)
        self._bar.setTabMaximumWidth(220)
        self._bar.setTabShadowEnabled(False)
        self._bar.setAddButtonVisible(True)
        self._bar.setCloseButtonDisplayMode(TabCloseButtonDisplayMode.ON_HOVER)
        self._bar.tabAddRequested.connect(self.tab_add_requested.emit)
        self._bar.tabCloseRequested.connect(self._on_tab_close_requested)
        self._bar.currentChanged.connect(self._on_current_changed)
        self._bar.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._bar.customContextMenuRequested.connect(self._on_tab_context_menu)
        self._bar.tabBarDoubleClicked.connect(self._on_tab_double_clicked)

        from PySide6.QtWidgets import QVBoxLayout
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._bar)

    def add_tab(self, ip: str) -> None:
        self._bar.addTab(ip, ip, _make_dot_icon(_DOT_COLORS["unknown"]))

    def remove_tab(self, ip: str) -> None:
        idx = self._find_tab_index(ip)
        if idx >= 0:
            self._bar.removeTab(idx)

    def set_active(self, ip: str) -> None:
        idx = self._find_tab_index(ip)
        if idx >= 0:
            self._bar.setCurrentIndex(idx)

    def get_active_ip(self) -> str | None:
        idx = self._bar.currentIndex()
        if idx < 0:
            return None
        item = self._bar.tabItem(idx)
        return item.routeKey() if item else None

    def set_ping_status(self, ip: str, status: str) -> None:
        color = _DOT_COLORS.get(status, _DOT_COLORS["unknown"])
        idx = self._find_tab_index(ip)
        if idx >= 0:
            item = self._bar.tabItem(idx)
            if item:
                item.setIcon(_make_dot_icon(color))

    def get_all_ips(self) -> list[str]:
        result: list[str] = []
        for i in range(self._bar.count()):
            item = self._bar.tabItem(i)
            if item:
                result.append(item.routeKey())
        return result

    def update_route_key(self, old_ip: str, new_ip: str) -> None:
        idx = self._find_tab_index(old_ip)
        if idx < 0:
            return
        self._bar.setTabText(idx, new_ip)
        item = self._bar.tabItem(idx)
        if item and hasattr(self._bar, "itemMap"):
            self._bar.itemMap.pop(old_ip, None)
            self._bar.itemMap[new_ip] = item
            item.setRouteKey(new_ip)

    def count(self) -> int:
        return self._bar.count()

    def _find_tab_index(self, ip: str) -> int:
        for i in range(self._bar.count()):
            item = self._bar.tabItem(i)
            if item and item.routeKey() == ip:
                return i
        return -1

    def _on_tab_close_requested(self, index: int) -> None:
        item = self._bar.tabItem(index)
        if item:
            self.tab_close_requested.emit(item.routeKey())

    def _on_current_changed(self, index: int) -> None:
        if index < 0:
            self.tab_selected.emit("")
            return
        item = self._bar.tabItem(index)
        if item:
            self.tab_selected.emit(item.routeKey())

    def _on_tab_context_menu(self, pos: QPoint) -> None:
        tab_idx = -1
        for i in range(self._bar.count()):
            item = self._bar.tabItem(i)
            if item and item.geometry().contains(pos):
                tab_idx = i
                break
        if tab_idx < 0:
            tab_idx = self._bar.currentIndex()
        if tab_idx < 0:
            return
        item = self._bar.tabItem(tab_idx)
        if not item:
            return
        ip = item.routeKey()

        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        action_close = menu.addAction(f"\u2715  \u0417\u0430\u043a\u0440\u044b\u0442\u044c \u0432\u043a\u043b\u0430\u0434\u043a\u0443  {ip}")
        action_close.setToolTip("\u0417\u0430\u043a\u0440\u044b\u0442\u044c \u0432\u043a\u043b\u0430\u0434\u043a\u0443 \u0438 \u043e\u0442\u043a\u043b\u044e\u0447\u0438\u0442\u044c\u0441\u044f \u043e\u0442 \u043a\u0430\u0441\u0441\u044b")
        menu.addSeparator()
        action_change_ip = menu.addAction("\u270f\ufe0f  \u0418\u0437\u043c\u0435\u043d\u0438\u0442\u044c IP")
        menu.addSeparator()
        action_refresh = menu.addAction("\U0001f504  \u041e\u0431\u043d\u043e\u0432\u0438\u0442\u044c \u0434\u0430\u043d\u043d\u044b\u0435")
        action_copy = menu.addAction("\U0001f4cb  \u041a\u043e\u043f\u0438\u0440\u043e\u0432\u0430\u0442\u044c IP")
        chosen = menu.exec(self._bar.mapToGlobal(pos))
        if chosen == action_close:
            self.tab_close_requested.emit(ip)
        elif chosen == action_change_ip:
            self.tab_ip_changed.emit(ip, "")
        elif chosen == action_refresh:
            self.tab_refresh_requested.emit(ip)
        elif chosen == action_copy:
            from PySide6.QtWidgets import QApplication
            QApplication.clipboard().setText(ip)
            self.tab_copy_ip_requested.emit(ip)

    def _on_tab_double_clicked(self, index: int) -> None:
        if index < 0:
            return
        item = self._bar.tabItem(index)
        if not item:
            return
        self.tab_ip_changed.emit(item.routeKey(), "")
