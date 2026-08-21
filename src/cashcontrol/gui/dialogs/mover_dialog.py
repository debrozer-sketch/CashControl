"""
mover_dialog.py — Диалог Mover: доставка файлов и команд на кассы.

Базовый UI (подэтап 1A):
- Выбор сценария из mover/scenarios/
- Предпросмотр шагов сценария
- Поле COM-порта (для POS)
- Кнопка «Запустить» → подтверждение → MoverProgressDialog

Полный конструктор drag-drop будет добавлен в следующем подэтапе (1B).

Открывается кнопкой «Mover» в тулбаре.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CardWidget,
    FluentIcon,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    ToolButton,
)

from cashcontrol.core.mover.executor import MoverParams
from cashcontrol.core.mover.scenario import (
    STEP_TYPE_ICONS,
    Scenario,
    ScenarioManager,
)
from cashcontrol.gui.theme_helper import color as _tc
from cashcontrol.infrastructure.audit_logger import get_logger
from cashcontrol.infrastructure.path_resolver import (
    ensure_mover_dirs,
    get_mover_data_dir,
)

logger = get_logger()


class _StepCard(CardWidget):
    """Card displaying a single step in the scenario preview."""

    def __init__(
        self,
        icon: str,
        label: str,
        step_type: str,
        enabled: bool,
        applies: bool,
        details: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setFixedHeight(56)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        # Icon
        icon_lbl = QLabel(icon, self)
        icon_lbl.setFixedWidth(24)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("font-size: 16px;")
        layout.addWidget(icon_lbl)

        # Label + details
        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        text_col.setContentsMargins(0, 0, 0, 0)

        name_lbl = QLabel(label, self)
        name_style = "font-size: 13px; font-weight: 500;"
        if not applies or not enabled:
            name_style += f" color: {_tc('text_secondary')};"
        name_lbl.setStyleSheet(name_style)
        text_col.addWidget(name_lbl)

        if details:
            det_lbl = QLabel(details, self)
            det_lbl.setStyleSheet(
                f"font-size: 11px; color: {_tc('text_secondary')};"
            )
            text_col.addWidget(det_lbl)

        layout.addLayout(text_col, stretch=1)

        # Status badge
        if not applies:
            badge = QLabel("пропуск", self)
            badge.setStyleSheet(
                f"color: {_tc('text_secondary')}; font-size: 11px; "
                "font-style: italic;"
            )
            layout.addWidget(badge)
        elif not enabled:
            badge = QLabel("выкл", self)
            badge.setStyleSheet(
                "color: #e67e22; font-size: 11px; font-style: italic;"
            )
            layout.addWidget(badge)


class MoverDialog(QDialog):
    """Диалог Mover — доставка файлов и команд на кассы."""

    def __init__(
        self,
        active_session=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._active_session = active_session
        self._manager = ScenarioManager()
        self._current_scenario: Scenario | None = None

        self.setWindowTitle("Mover — доставка файлов")
        self.setMinimumSize(650, 500)
        self.resize(720, 580)

        ensure_mover_dirs()
        self._init_ui()
        self._load_scenarios()

    # ── UI ────────────────────────────────────────────────────

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Title
        title = SubtitleLabel("📦 Mover — доставка файлов и команд", self)
        root.addWidget(title)

        # Connection info
        self._info_label = QLabel("", self)
        self._info_label.setStyleSheet(
            f"color: {_tc('text_secondary')}; font-size: 12px;"
        )
        root.addWidget(self._info_label)
        self._update_info_label()

        # ── Scenario selection ──
        scenario_row = QHBoxLayout()
        scenario_row.setSpacing(8)

        scenario_row.addWidget(QLabel("Сценарий:", self))

        self._scenario_combo = QComboBox(self)
        self._scenario_combo.setMinimumWidth(300)
        self._scenario_combo.currentIndexChanged.connect(
            self._on_scenario_changed
        )
        scenario_row.addWidget(self._scenario_combo, stretch=1)

        self._btn_reload = ToolButton(FluentIcon.SYNC, self)
        self._btn_reload.setFixedSize(30, 30)
        self._btn_reload.setToolTip("Перечитать сценарии")
        self._btn_reload.clicked.connect(self._load_scenarios)
        scenario_row.addWidget(self._btn_reload)

        self._btn_edit = ToolButton(FluentIcon.EDIT, self)
        self._btn_edit.setFixedSize(30, 30)
        self._btn_edit.setToolTip("Редактировать сценарий")
        self._btn_edit.clicked.connect(self._on_edit_scenario)
        scenario_row.addWidget(self._btn_edit)

        self._btn_new = ToolButton(FluentIcon.ADD, self)
        self._btn_new.setFixedSize(30, 30)
        self._btn_new.setToolTip("Создать новый сценарий")
        self._btn_new.clicked.connect(self._on_new_scenario)
        scenario_row.addWidget(self._btn_new)

        root.addLayout(scenario_row)

        # ── Description ──
        self._desc_label = QLabel("", self)
        self._desc_label.setWordWrap(True)
        self._desc_label.setStyleSheet(
            f"color: {_tc('text_secondary')}; font-size: 12px; "
            f"padding: 4px 0;"
        )
        root.addWidget(self._desc_label)

        # ── Steps preview ──
        steps_group = QGroupBox("Шаги сценария", self)
        steps_layout = QVBoxLayout(steps_group)
        steps_layout.setContentsMargins(8, 12, 8, 8)
        steps_layout.setSpacing(0)

        self._steps_scroll = QScrollArea(self)
        self._steps_scroll.setWidgetResizable(True)
        self._steps_scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        self._steps_container = QWidget()
        self._steps_vlayout = QVBoxLayout(self._steps_container)
        self._steps_vlayout.setContentsMargins(0, 0, 0, 0)
        self._steps_vlayout.setSpacing(4)
        self._steps_vlayout.addStretch()

        self._steps_scroll.setWidget(self._steps_container)
        steps_layout.addWidget(self._steps_scroll)

        root.addWidget(steps_group, stretch=1)

        # ── Parameters ──
        params_grid = QVBoxLayout()
        params_grid.setSpacing(6)

        # Row 1: shop name + cash number (for Loymax/QRID)
        shop_row = QHBoxLayout()
        shop_row.setSpacing(8)

        self._shop_label = QLabel("Магазин:", self)
        shop_row.addWidget(self._shop_label)

        self._shop_edit = QLineEdit(self)
        self._shop_edit.setPlaceholderText("КЯ-3 или Д-15")
        self._shop_edit.setFixedWidth(120)
        self._shop_edit.setToolTip(
            "Название магазина для поиска Loymax и QRID.\n"
            "Формат: КЯ-номер или Д-номер.\n"
            "Если касса настроена — определяется автоматически из БД."
        )
        shop_row.addWidget(self._shop_edit)

        self._cash_num_label = QLabel("Касса:", self)
        shop_row.addWidget(self._cash_num_label)

        self._cash_num_edit = QLineEdit(self)
        self._cash_num_edit.setPlaceholderText("1")
        self._cash_num_edit.setFixedWidth(60)
        self._cash_num_edit.setToolTip("Номер кассы в магазине")
        shop_row.addWidget(self._cash_num_edit)

        # Row 2: COM port
        self._com_port_label = QLabel("COM-порт:", self)
        shop_row.addWidget(self._com_port_label)

        self._com_port_edit = QLineEdit(self)
        self._com_port_edit.setPlaceholderText("Номер")
        self._com_port_edit.setFixedWidth(80)
        self._com_port_edit.setToolTip(
            "COM-порт банковского терминала (pinpad.ini)\n"
            "Только для POS-касс. Введите цифры."
        )
        shop_row.addWidget(self._com_port_edit)
        shop_row.addStretch()

        params_grid.addLayout(shop_row)

        root.addLayout(params_grid)

        # ── Directories info ──
        dirs_label = QLabel(
            "Файлы: mover/files/  •  Данные: mover/data/  •  "
            "Сценарии: mover/scenarios/",
            self,
        )
        dirs_label.setStyleSheet(
            f"color: {_tc('text_secondary')}; font-size: 11px;"
        )
        root.addWidget(dirs_label)

        # ── Bottom buttons ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        btn_close = PushButton("Закрыть", self)
        btn_close.clicked.connect(self.reject)
        btn_row.addWidget(btn_close)

        btn_row.addStretch()

        self._btn_run = PrimaryPushButton("Запустить", self)
        self._btn_run.setIcon(FluentIcon.PLAY)
        self._btn_run.setEnabled(False)
        self._btn_run.clicked.connect(self._on_run)
        btn_row.addWidget(self._btn_run)

        root.addLayout(btn_row)

    # ── Data loading ──────────────────────────────────────────

    def _update_info_label(self) -> None:
        """Update connection info label."""
        if self._active_session and self._active_session.is_connected:
            host = self._active_session.host
            cash_type = getattr(self._active_session, "cash_type", "?")
            self._info_label.setText(
                f"Касса: {host}  •  Тип: {cash_type}"
            )
        else:
            self._info_label.setText(
                "⚠ Нет активного подключения к кассе"
            )

    def _load_scenarios(self) -> None:
        """Load scenario list from mover/scenarios/."""
        self._scenario_combo.blockSignals(True)
        self._scenario_combo.clear()

        scenarios = self._manager.list_scenarios()
        if not scenarios:
            self._scenario_combo.addItem("(нет сценариев)", None)
            self._btn_run.setEnabled(False)
        else:
            for name, path in scenarios:
                self._scenario_combo.addItem(name, str(path))

        self._scenario_combo.blockSignals(False)

        if scenarios:
            self._scenario_combo.setCurrentIndex(0)
            self._on_scenario_changed(0)

    def _on_scenario_changed(self, index: int) -> None:
        """Handle scenario selection change."""
        path_str = self._scenario_combo.currentData()
        if not path_str:
            self._current_scenario = None
            self._desc_label.setText("")
            self._clear_steps()
            self._btn_run.setEnabled(False)
            return

        try:
            self._current_scenario = self._manager.load(Path(path_str))
            self._desc_label.setText(
                self._current_scenario.description or "(без описания)"
            )
            self._refresh_steps_preview()
            self._update_com_port_visibility()
            self._btn_run.setEnabled(
                self._active_session is not None
                and self._active_session.is_connected
            )
        except Exception as e:
            logger.error(f"Failed to load scenario: {e}")
            self._desc_label.setText(f"Ошибка загрузки: {e}")
            self._current_scenario = None
            self._btn_run.setEnabled(False)

    def _clear_steps(self) -> None:
        """Clear steps preview."""
        while self._steps_vlayout.count() > 1:  # keep stretch
            item = self._steps_vlayout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _refresh_steps_preview(self) -> None:
        """Refresh the steps preview cards."""
        self._clear_steps()

        if not self._current_scenario:
            return

        cash_type = "?"
        if self._active_session:
            cash_type = getattr(self._active_session, "cash_type", "?")

        for step in self._current_scenario.steps:
            icon = STEP_TYPE_ICONS.get(step.type, "❓")
            applies = (
                step.applies_to_cash_type(cash_type) if cash_type != "?" else True
            )

            details = self._step_details(step, cash_type)

            card = _StepCard(
                icon=icon,
                label=step.label,
                step_type=step.type,
                enabled=step.enabled,
                applies=applies,
                details=details,
                parent=self._steps_container,
            )
            # Insert before the stretch
            self._steps_vlayout.insertWidget(
                self._steps_vlayout.count() - 1, card
            )

    def _step_details(self, step, cash_type: str) -> str:
        """Generate details string for a step card."""
        config = step.config

        if step.type == "upload_files":
            files = config.get(cash_type, [])
            if files:
                return f"{len(files)} файлов"
            return "нет файлов для этого типа"

        elif step.type == "run_commands":
            raw = config.get(cash_type)
            if isinstance(raw, list):
                return f"{len(raw)} команд"
            elif isinstance(raw, dict):
                total = sum(
                    len(v) for v in raw.values() if isinstance(v, list)
                )
                return f"{len(raw)} подтипов, ~{total} команд"
            return "нет команд для этого типа"

        elif step.type == "loymax":
            csv_file = config.get("csv_file", "loymax_cashes.csv")
            exists = (get_mover_data_dir() / csv_file).exists()
            return f"CSV: {csv_file}" + ("" if exists else " ⚠ не найден")

        elif step.type == "qrid":
            csv_file = config.get("csv_file", "qrid.csv")
            exists = (get_mover_data_dir() / csv_file).exists()
            return f"CSV: {csv_file}" + ("" if exists else " ⚠ не найден")

        elif step.type == "set_com_port":
            return "Ввод перед запуском"

        return ""

    def _update_com_port_visibility(self) -> None:
        """Show/hide parameter fields based on cash type and scenario steps."""
        show_com = False
        show_shop = False

        if self._current_scenario and self._active_session:
            cash_type = getattr(self._active_session, "cash_type", "")
            for step in self._current_scenario.steps:
                if not step.enabled:
                    continue
                if not step.applies_to_cash_type(cash_type):
                    continue
                if step.type == "set_com_port":
                    show_com = True
                if step.type in ("loymax", "qrid"):
                    show_shop = True

        self._com_port_label.setVisible(show_com)
        self._com_port_edit.setVisible(show_com)
        self._shop_label.setVisible(show_shop)
        self._shop_edit.setVisible(show_shop)
        self._cash_num_label.setVisible(show_shop)
        self._cash_num_edit.setVisible(show_shop)

    # ── Run ───────────────────────────────────────────────────

    def _on_run(self) -> None:
        """Handle Run button click."""
        if not self._current_scenario:
            return
        if not self._active_session or not self._active_session.is_connected:
            QMessageBox.warning(
                self, "Mover", "Нет активного подключения к кассе."
            )
            return

        cash_type = getattr(self._active_session, "cash_type", "unknown")

        # Validate COM port if needed
        com_port = self._com_port_edit.text().strip()
        if self._com_port_edit.isVisible() and not com_port:
            QMessageBox.warning(
                self, "Mover",
                "Введите COM-порт банковского терминала.",
            )
            self._com_port_edit.setFocus()
            return

        if com_port and not com_port.isdigit():
            QMessageBox.warning(
                self, "Mover",
                "COM-порт должен содержать только цифры.",
            )
            self._com_port_edit.setFocus()
            return

        # Confirmation
        steps = self._current_scenario.get_steps_for_cash_type(cash_type)
        step_names = "\n".join(
            f"  {i}. {s.label}" for i, s in enumerate(steps, 1)
        )

        reply = QMessageBox.question(
            self,
            "Подтверждение запуска Mover",
            (
                f"Запустить сценарий «{self._current_scenario.name}» "
                f"на кассе {self._active_session.host}?\n\n"
                f"Тип кассы: {cash_type}\n"
                f"Шаги ({len(steps)}):\n{step_names}\n\n"
                f"Продолжить?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        # Build params
        params = MoverParams(
            com_port=com_port,
            shop_name=self._shop_edit.text().strip(),
            cash_number=self._cash_num_edit.text().strip(),
        )

        # Open progress dialog
        # IMPORTANT: use show() + setModal(True), NOT exec()
        # exec() blocks qasync event loop → freezes async operations
        from cashcontrol.gui.dialogs.mover_progress_dialog import (
            MoverProgressDialog,
        )

        dialog = MoverProgressDialog(
            session=self._active_session,
            scenario=self._current_scenario,
            params=params,
            parent=self,
        )
        dialog.setModal(True)
        dialog.show()

    # ── Editor ────────────────────────────────────────────────

    def _on_edit_scenario(self) -> None:
        """Open editor for the currently selected scenario."""
        if not self._current_scenario:
            return

        from cashcontrol.gui.dialogs.mover_editor_dialog import (
            MoverEditorDialog,
        )

        editor = MoverEditorDialog(
            scenario=self._current_scenario,
            parent=self,
        )
        editor.scenario_saved.connect(self._load_scenarios)
        editor.setModal(True)
        editor.show()

    def _on_new_scenario(self) -> None:
        """Open editor for a new scenario."""
        from cashcontrol.gui.dialogs.mover_editor_dialog import (
            MoverEditorDialog,
        )

        editor = MoverEditorDialog(
            scenario=None,
            parent=self,
        )
        editor.scenario_saved.connect(self._load_scenarios)
        editor.setModal(True)
        editor.show()