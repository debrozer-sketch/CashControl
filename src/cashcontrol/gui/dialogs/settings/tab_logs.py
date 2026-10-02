"""Logs settings tab — log level, open folder, clear logs."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
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
    PushButton,
    SubtitleLabel,
)

from cashcontrol.gui import feedback
from cashcontrol.gui.notification_manager import Level
from cashcontrol.gui.theme_helper import color as _tc
from cashcontrol.gui.theme_helper import font_size, label_width
from cashcontrol.infrastructure.audit_logger import get_logger
from cashcontrol.infrastructure.path_resolver import get_logs_dir

if TYPE_CHECKING:
    from cashcontrol.infrastructure.config_manager import ConfigManager

logger = get_logger()
# Минимум ширины колонки подписей, а не фиксированная ширина.
# Фиксированная режет текст: «Глубина цвета» не помещалась в 120,
# «Кеш информации (сек):» — даже в 220. Колонка растёт под содержимое
# и ничего не обрезает.
_LABEL_W = label_width("wide")


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
        lbl.setStyleSheet(f"color: {_tc('text_secondary')}; font-size: {font_size('hint')}px;")
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
        level_lbl.setMinimumWidth(_LABEL_W)
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
        open_lbl.setMinimumWidth(_LABEL_W)
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
        clear_lbl.setMinimumWidth(_LABEL_W)
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
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(logs_dir)))
        else:
            feedback.notify(
                f"Папка не найдена:\n{logs_dir}",
                Level.WARNING,
                title="Папка логов",
                parent=self,
            )

    def _clear_logs(self) -> None:
        if not feedback.confirm(
            "Очистить логи",
            "Удалить все файлы логов?\nЭто действие нельзя отменить.",
            parent=self,
            destructive=True,
        ):
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


        if count:
            feedback.notify(
                f"Удалено файлов: {count}",
                Level.SUCCESS,
                title="Готово",
                parent=self,
            )
        else:
            # Зелёное «удалено файлов: 0» читается как подтверждение успеха,
            # хотя ничего не удалено: файлов логов не было либо удалить их
            # не получилось. Причина в обоих случаях одна и та же с точки
            # зрения оператора — итога нет, поэтому уровень ниже успеха, а
            # текст не указывает причину, которой здесь не видно.
            feedback.notify(
                "Ничего не удалено",
                Level.INFO,
                title="Готово",
                parent=self,
            )
        logger.info(f"Cleared {count} log files by user request")

    def load(self, config: ConfigManager) -> None:
        self._config = config
        current_level = config.settings.general.log_level.upper()
        levels = ["DEBUG", "INFO", "WARNING", "ERROR"]
        self.log_level_combo.setCurrentIndex(levels.index(current_level) if current_level in levels else 1)

    def save(self, config: ConfigManager) -> None:
        level = self.log_level_combo.currentText()
        config.update("general", log_level=level)
