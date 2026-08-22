"""Logs settings tab — log level, open folder, clear logs."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    ComboBox,
    FluentIcon,
    MessageBox,
    PushButton,
    SubtitleLabel,
)

from cashcontrol.gui.theme_helper import color as _tc
from cashcontrol.infrastructure.audit_logger import get_logger
from cashcontrol.infrastructure.path_resolver import get_logs_dir

if TYPE_CHECKING:
    from cashcontrol.infrastructure.config_manager import ConfigManager

logger = get_logger()
_LABEL_W = 220


class TabLogs(QWidget):
    """Log level, open folder, clear logs."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._config: ConfigManager | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(4, 4, 8, 4)
        inner_layout.setSpacing(10)
        inner_layout.addWidget(self._make_card())
        inner_layout.addStretch()
        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)

    def _hint(self, parent, text: str) -> BodyLabel:
        lbl = BodyLabel(text, parent)
        lbl.setStyleSheet(f"color: {_tc('text_secondary')}; font-size: 11px;")
        lbl.setWordWrap(True)
        return lbl

    def _make_card(self) -> CardWidget:
        card = CardWidget(self)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addWidget(SubtitleLabel("Управление логами", card))

        level_row = QHBoxLayout()
        level_row.setSpacing(8)
        level_lbl = BodyLabel("Уровень логирования:", card)
        level_lbl.setFixedWidth(_LABEL_W)
        level_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self.log_level_combo = ComboBox(card)
        self.log_level_combo.addItems(["DEBUG", "INFO", "WARNING", "ERROR"])
        self.log_level_combo.setFixedWidth(130)
        level_row.addWidget(level_lbl)
        level_row.addWidget(self.log_level_combo)
        level_row.addStretch()
        layout.addLayout(level_row)

        layout.addWidget(self._hint(
            card, "Изменение уровня вступит в силу после перезапуска программы"
        ))

        open_row = QHBoxLayout()
        open_row.setSpacing(8)
        open_lbl = BodyLabel("", card)
        open_lbl.setFixedWidth(_LABEL_W)
        open_row.addWidget(open_lbl)
        self.btn_open_logs = PushButton("Открыть папку логов", card, FluentIcon.FOLDER)
        self.btn_open_logs.setFixedWidth(220)
        self.btn_open_logs.clicked.connect(self._open_logs_folder)
        open_row.addWidget(self.btn_open_logs)
        open_row.addStretch()
        layout.addLayout(open_row)

        clear_row = QHBoxLayout()
        clear_row.setSpacing(8)
        clear_lbl = BodyLabel("", card)
        clear_lbl.setFixedWidth(_LABEL_W)
        clear_row.addWidget(clear_lbl)
        self.btn_clear_logs = PushButton("Очистить логи", card, FluentIcon.DELETE)
        self.btn_clear_logs.setFixedWidth(220)
        self.btn_clear_logs.clicked.connect(self._clear_logs)
        clear_row.addWidget(self.btn_clear_logs)
        clear_row.addStretch()
        layout.addLayout(clear_row)

        return card

    def _open_logs_folder(self) -> None:
        logs_dir = get_logs_dir()
        if logs_dir.exists():
            os.startfile(str(logs_dir))
        else:
            MessageBox("Папка логов", f"Папка не найдена:\n{logs_dir}", self).exec()

    def _clear_logs(self) -> None:
        dlg = MessageBox(
            "Очистить логи",
            "Удалить все файлы логов?\nЭто действие нельзя отменить.", self)
        dlg.yesButton.setText("Удалить")
        if not dlg.exec():
            return

        logs_dir = get_logs_dir()
        if not logs_dir.exists():
            return

        count = 0
        for f in logs_dir.iterdir():
            if f.is_file() and f.suffix in (".log", ".txt"):
                try:
                    f.unlink()
                    count += 1
                except Exception as e:
                    logger.warning(f"Failed to delete {f}: {e}")


        from qfluentwidgets import InfoBar, InfoBarPosition
        InfoBar.success(title="Готово", content=f"Удалено файлов: {count}",
                        parent=self, position=InfoBarPosition.TOP_RIGHT,
                        duration=2500)
        logger.info(f"Cleared {count} log files by user request")

    def load(self, config: ConfigManager) -> None:
        self._config = config
        current_level = config.settings.general.log_level.upper()
        levels = ["DEBUG", "INFO", "WARNING", "ERROR"]
        self.log_level_combo.setCurrentIndex(levels.index(current_level) if current_level in levels else 1)

    def save(self, config: ConfigManager) -> None:
        level = self.log_level_combo.currentText()
        config.update("general", log_level=level)
