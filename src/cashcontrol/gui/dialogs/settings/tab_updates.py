"""Updates settings tab — network share path, interval, manual check."""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    CheckBox,
    FluentIcon,
    LineEdit,
    MessageBox,
    PrimaryPushButton,
    SubtitleLabel,
    ToolButton,
)

from cashcontrol.gui.theme_helper import color as _tc
from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from cashcontrol.infrastructure.config_manager import ConfigManager

logger = get_logger()
_LABEL_W = 220


class TabUpdates(QWidget):
    """Update settings — UNC path, interval, manual check."""

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
        layout.addWidget(SubtitleLabel("Обновления", card))

        self.updates_enabled_cb = CheckBox("Включить автоматические обновления", card)
        self.updates_enabled_cb.stateChanged.connect(lambda _: self._on_updates_toggle())
        layout.addWidget(self.updates_enabled_cb)

        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        path_lbl = BodyLabel("Путь к обновлениям:", card)
        path_lbl.setFixedWidth(_LABEL_W)
        path_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self.updates_path_edit = LineEdit(card)
        self.updates_path_edit.setMinimumWidth(280)
        path_row.addWidget(path_lbl)
        path_row.addWidget(self.updates_path_edit, stretch=1)

        browse_btn = ToolButton(FluentIcon.FOLDER, card)
        browse_btn.setToolTip("Выбрать папку")
        browse_btn.setFixedSize(32, 32)
        browse_btn.clicked.connect(self._browse)
        path_row.addWidget(browse_btn)
        layout.addLayout(path_row)

        layout.addWidget(self._hint(
            card, "UNC-путь к папке с мастер-образом программы на сетевом диске"
        ))

        startup_row = QHBoxLayout()
        startup_row.setSpacing(8)
        startup_lbl = BodyLabel("Проверять при запуске:", card)
        startup_lbl.setFixedWidth(_LABEL_W)
        startup_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self.updates_startup_cb = CheckBox("", card)
        startup_row.addWidget(startup_lbl)
        startup_row.addWidget(self.updates_startup_cb)
        startup_row.addStretch()
        layout.addLayout(startup_row)

        interval_row = QHBoxLayout()
        interval_row.setSpacing(8)
        interval_lbl = BodyLabel("Проверять каждые (ч):", card)
        interval_lbl.setFixedWidth(_LABEL_W)
        interval_lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        self.updates_interval_edit = LineEdit(card)
        self.updates_interval_edit.setFixedWidth(90)
        self.updates_interval_edit.setValidator(QIntValidator(0, 168))
        interval_row.addWidget(interval_lbl)
        interval_row.addWidget(self.updates_interval_edit)
        interval_row.addWidget(self._hint(card, "(0 \u2014 только по расписанию запуска)"))
        interval_row.addStretch()
        layout.addLayout(interval_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_lbl = BodyLabel("", card)
        btn_lbl.setFixedWidth(_LABEL_W)
        btn_row.addWidget(btn_lbl)
        self.btn_check_now = PrimaryPushButton("Проверить сейчас", card)
        self.btn_check_now.setFixedWidth(160)
        self.btn_check_now.clicked.connect(self._check_updates_now)
        btn_row.addWidget(self.btn_check_now)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        return card

    def _on_updates_toggle(self) -> None:
        enabled = self.updates_enabled_cb.isChecked()
        self.updates_path_edit.setEnabled(enabled)
        self.updates_startup_cb.setEnabled(enabled)
        self.updates_interval_edit.setEnabled(enabled)
        self.btn_check_now.setEnabled(enabled)

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Выберите папку с обновлениями",
            self.updates_path_edit.text() or "",
        )
        if folder:
            self.updates_path_edit.setText(folder)

    def _check_updates_now(self) -> None:
        path = self.updates_path_edit.text().strip()
        if not path:
            MessageBox("Ошибка", "Укажите путь к папке с обновлениями.", self).exec()
            return

        with contextlib.suppress(Exception):
            self._config.update("update", enabled=True, network_path=path)

        mw = self._get_main_window()
        if mw and hasattr(mw, "update_client"):
            uc = mw.update_client
            self.btn_check_now.setEnabled(False)
            self.btn_check_now.setText("Проверяю\u2026")

            def _on_done() -> None:
                with contextlib.suppress(RuntimeError):
                    uc.check_finished.disconnect(_on_done)
                if not self.btn_check_now.isVisible():
                    return
                self.btn_check_now.setEnabled(True)
                self.btn_check_now.setText("Проверить сейчас")

            uc.check_finished.connect(_on_done)
            uc.check_now()
        else:
            self._check_fallback(path)

    def _check_fallback(self, path: str) -> None:
        import json
        from pathlib import Path

        from cashcontrol import __version__

        net_path = Path(path)
        if not net_path.exists():
            MessageBox("Папка недоступна",
                       f"Не удалось открыть:\n{path}\n\n"
                       "Проверьте путь и сетевое подключение.", self).exec()
            return

        manifest_file = net_path / "manifest.json"
        remote_ver = ""
        if manifest_file.exists():
            try:
                with open(manifest_file, encoding="utf-8") as f:
                    data = json.load(f)
                remote_ver = data.get("version", "")
            except Exception:
                pass

        if not remote_ver:
            ver_file = net_path / "version.txt"
            remote_ver = ver_file.read_text(encoding="utf-8").strip() if ver_file.exists() else ""

        if not remote_ver:
            MessageBox("Нет данных",
                       f"В папке не найден manifest.json или version.txt:\n{path}", self).exec()
            return

        if remote_ver != __version__:
            MessageBox("Доступно обновление",
                       f"Текущая версия: {__version__}\n"
                       f"Версия в образе: {remote_ver}\n\n"
                       "Сохраните настройки и нажмите «Проверить сейчас» повторно,\n"
                       "либо перезапустите программу.", self).exec()
        else:
            MessageBox("Обновлений нет",
                       f"Версия {__version__} актуальна.", self).exec()

    def _get_main_window(self):
        from cashcontrol.gui.main_window import MainWindow
        w = self.parent()
        while w is not None:
            if isinstance(w, MainWindow):
                return w
            w = w.parent()
        return None

    def load(self, config: ConfigManager) -> None:
        self._config = config
        upd = config.settings.update

        self.updates_enabled_cb.setChecked(upd.enabled)
        self.updates_path_edit.setText(upd.network_path)
        self.updates_startup_cb.setChecked(upd.check_on_startup)
        self.updates_interval_edit.setText(str(upd.check_interval_h))
        self._on_updates_toggle()

    def save(self, config: ConfigManager) -> None:
        interval_h = max(0, min(168, int(self.updates_interval_edit.text() or 24)))
        config.update(
            "update",
            enabled=self.updates_enabled_cb.isChecked(),
            network_path=self.updates_path_edit.text().strip() or "",
            check_on_startup=self.updates_startup_cb.isChecked(),
            check_interval_h=interval_h,
        )