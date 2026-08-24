"""Sidebar panel — vertical icon-only navigation bar."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QFrame, QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon, ToolButton

from cashcontrol.infrastructure.audit_logger import audit_log

_BTN_SIZE = 40
_ICON_SIZE = 18
_SIDEBAR_WIDTH = 48


class SidebarPanel(QWidget):
    """Vertical icon-only sidebar."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(_SIDEBAR_WIDTH)
        self.setObjectName("CashControlSidebar")
        self._init_ui()

    def _make_btn(self, icon: FluentIcon, tooltip: str) -> ToolButton:
        btn = ToolButton(icon, self)
        btn.setObjectName("SideNavButton")
        btn.setFixedSize(_BTN_SIZE, _BTN_SIZE)
        btn.setIconSize(QSize(_ICON_SIZE, _ICON_SIZE))
        btn.setToolTip(tooltip)
        return btn

    def _hline(self) -> QFrame:
        sep = QFrame(self)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        sep.setFixedWidth(_BTN_SIZE)
        return sep

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self._settings_btn = self._make_btn(FluentIcon.SETTING, "Настройки")
        self._settings_btn.clicked.connect(self._on_settings)
        layout.addWidget(self._settings_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        layout.addWidget(self._hline(), alignment=Qt.AlignmentFlag.AlignHCenter)

        self._cmd_editor_btn = self._make_btn(FluentIcon.EDIT, "Редактор команд")
        self._cmd_editor_btn.clicked.connect(self._on_command_editor)
        layout.addWidget(self._cmd_editor_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        layout.addStretch()

        layout.addWidget(self._hline(), alignment=Qt.AlignmentFlag.AlignHCenter)

        self._logs_btn = self._make_btn(FluentIcon.HISTORY, "Журнал действий")
        self._logs_btn.clicked.connect(self._on_logs)
        layout.addWidget(self._logs_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

        self._about_btn = self._make_btn(FluentIcon.INFO, "О программе")
        self._about_btn.clicked.connect(self._on_about)
        layout.addWidget(self._about_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

    def _on_settings(self) -> None:
        audit_log(action_type="ui", action_name="open_settings", result="success")
        from cashcontrol.gui.dialogs.settings.settings_dialog import SettingsDialog
        dlg = SettingsDialog(self.window())
        dlg.exec()

    def _on_command_editor(self) -> None:
        audit_log(action_type="ui", action_name="open_command_editor", result="success")
        from cashcontrol.gui.dialogs.command_editor import CommandEditorDialog
        dlg = CommandEditorDialog(self.window())
        dlg.exec()

    def _on_logs(self) -> None:
        audit_log(action_type="ui", action_name="open_logs", result="success")
        from cashcontrol.gui.dialogs.logs_viewer import LogsViewerDialog
        dlg = LogsViewerDialog(self.window())
        dlg.show()   # Non-modal — can keep open while working

    def _on_about(self) -> None:
        audit_log(action_type="ui", action_name="open_help", result="success")
        from PySide6.QtCore import Qt

        from cashcontrol.gui.dialogs.help_dialog import HelpDialog
        # Сохраняем ссылку в self чтобы GC не удалил окно
        self._help_dlg = HelpDialog(self.window())
        self._help_dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._help_dlg.destroyed.connect(lambda: setattr(self, "_help_dlg", None))
        self._help_dlg.show()
        self._help_dlg.raise_()
        self._help_dlg.activateWindow()
