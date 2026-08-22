"""General settings tab — theme, history, limits."""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import QHBoxLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CardWidget, ComboBox, LineEdit, SubtitleLabel

from cashcontrol.gui.theme_helper import color as _tc

if TYPE_CHECKING:
    from cashcontrol.infrastructure.config_manager import ConfigManager

_LABEL_W = 220
_FIELD_W = 110


class TabGeneral(QWidget):
    """Theme, language, history mode, limits."""

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
        inner_layout.addWidget(self._make_appearance_card())
        inner_layout.addWidget(self._make_limits_card())
        inner_layout.addStretch()
        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)

    def _combo_row(self, parent, label_text: str, items: list[str]) -> tuple[QHBoxLayout, ComboBox]:
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = BodyLabel(label_text, parent)
        lbl.setFixedWidth(_LABEL_W)
        lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        combo = ComboBox(parent)
        combo.addItems(items)
        combo.setFixedWidth(_FIELD_W)
        row.addWidget(lbl)
        row.addWidget(combo)
        row.addStretch()
        return row, combo

    def _int_row(self, parent, label_text: str, placeholder: str,
                 lo: int, hi: int, extra_label: str = "") -> tuple[QHBoxLayout, LineEdit]:
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = BodyLabel(label_text, parent)
        lbl.setFixedWidth(_LABEL_W)
        lbl.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight)
        edit = LineEdit(parent)
        edit.setPlaceholderText(placeholder)
        edit.setFixedWidth(_FIELD_W)
        edit.setValidator(QIntValidator(lo, hi))
        row.addWidget(lbl)
        row.addWidget(edit)
        if extra_label:
            extra = BodyLabel(extra_label, parent)
            extra.setStyleSheet(f"color: {_tc('text_secondary')}; font-size: 11px;")
            row.addWidget(extra)
        row.addStretch()
        return row, edit

    def _hint(self, parent, text: str) -> BodyLabel:
        lbl = BodyLabel(text, parent)
        lbl.setStyleSheet(f"color: {_tc('text_secondary')}; font-size: 11px;")
        lbl.setWordWrap(True)
        return lbl

    def _make_appearance_card(self) -> CardWidget:
        card = CardWidget(self)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addWidget(SubtitleLabel("Внешний вид", card))

        theme_row, self.theme_combo = self._combo_row(card, "Тема:", ["Светлая", "Тёмная", "Системная"])
        layout.addLayout(theme_row)

        lang_row, self.lang_combo = self._combo_row(card, "Язык:", ["Русский", "English"])
        layout.addLayout(lang_row)

        history_row, self.history_combo = self._combo_row(card, "История:", ["Сессия", "Постоянная"])
        layout.addLayout(history_row)

        layout.addWidget(self._hint(card, "Изменение языка вступит в силу после перезапуска"))
        return card

    def _make_limits_card(self) -> CardWidget:
        card = CardWidget(self)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)
        layout.addWidget(SubtitleLabel("Лимиты и таймауты", card))

        tabs_row, self.max_tabs_edit = self._int_row(card, "Максимум вкладок:", "1\u201350", 1, 50)
        layout.addLayout(tabs_row)

        cache_row, self.cache_ttl_edit = self._int_row(card, "Кеш информации (сек):", "10\u20133600", 10, 3600)
        layout.addLayout(cache_row)

        timeout_row, self.timeout_edit = self._int_row(card, "Таймаут команд (сек):", "5\u2013300", 5, 300)
        layout.addLayout(timeout_row)

        return card

    def load(self, config: ConfigManager) -> None:
        self._config = config
        general = config.settings.general
        conn = config.settings.connection

        self.theme_combo.setCurrentIndex({"light": 0, "dark": 1, "auto": 2}.get(general.theme, 2))
        self.lang_combo.setCurrentIndex({"ru": 0, "en": 1}.get(general.language, 0))
        self.history_combo.setCurrentIndex({"session": 0, "persistent": 1}.get(general.history_mode, 0))

        self.max_tabs_edit.setText(str(general.max_tabs))
        self.cache_ttl_edit.setText(str(general.info_cache_ttl))
        self.timeout_edit.setText(str(conn.timeout))

    def save(self, config: ConfigManager) -> None:
        theme = ["light", "dark", "auto"][self.theme_combo.currentIndex()]
        language = ["ru", "en"][self.lang_combo.currentIndex()]
        history_mode = ["session", "persistent"][self.history_combo.currentIndex()]

        max_tabs = max(1, min(50, int(float(self.max_tabs_edit.text() or 15))))
        cache_ttl = max(10, min(3600, int(float(self.cache_ttl_edit.text() or 300))))
        timeout = max(5, min(300, int(float(self.timeout_edit.text() or 10))))

        config.update("general", theme=theme, language=language, max_tabs=max_tabs,
                       info_cache_ttl=cache_ttl, history_mode=history_mode)
        config.update("connection", timeout=timeout)

        from cashcontrol.gui.theme_engine import ThemeEngine
        ThemeEngine.instance().apply(theme)