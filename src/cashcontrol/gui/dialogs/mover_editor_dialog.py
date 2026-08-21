"""
mover_editor_dialog.py — Конструктор Mover-сценариев.

Три панели:
  ┌──────────┬──────────────────────┬──────────────────────┐
  │ Палитра  │   Шаги сценария      │  Настройки шага      │
  │ блоков   │   (drag-drop список) │  (зависят от типа)   │
  │          │                      │                      │
  └──────────┴──────────────────────┴──────────────────────┘
  │  Имя сценария / Описание               [Сохранить] [Отмена] │
  └─────────────────────────────────────────────────────────────┘

Палитра: перетаскивание типов шагов в список.
Список: drag-drop для перестановки, чекбокс вкл/выкл, кнопка удалить.
Настройки: параметры выбранного шага (файлы, команды, CSV, пути).
"""

from __future__ import annotations

import copy
import uuid

from PySide6.QtCore import (
    QMimeData,
    Qt,
    Signal,
)
from PySide6.QtGui import QDrag, QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CardWidget,
    FluentIcon,
    PrimaryPushButton,
    PushButton,
    ToolButton,
)
from qfluentwidgets import (
    LineEdit as FluentLineEdit,
)

from cashcontrol.core.mover.scenario import (
    MOVER_CASH_TYPES,
    STEP_TYPE_ICONS,
    STEP_TYPE_LABELS,
    STEP_TYPES,
    Scenario,
    ScenarioManager,
    StepDefinition,
)
from cashcontrol.gui.theme_helper import color as _tc
from cashcontrol.infrastructure.audit_logger import get_logger
from cashcontrol.infrastructure.path_resolver import (
    get_mover_scenarios_dir,
)

logger = get_logger()

_MIME_STEP_TYPE = "application/x-mover-step-type"

# ── Step type descriptions for palette ──────────────────────

_STEP_TYPE_DESCRIPTIONS: dict[str, str] = {
    "upload_files": "Загрузка файлов на кассу по типу",
    "run_commands": "SSH-команды по типу кассы",
    "loymax": "Loymax логин/пароль из CSV",
    "qrid": "QRID Газпром СБП из CSV",
    "set_com_port": "COM-порт банковского терминала",
}


# ═══════════════════════════════════════════════════════════════
#  PALETTE — left panel with draggable step types
# ═══════════════════════════════════════════════════════════════

class _PaletteItem(CardWidget):
    """Draggable step type in the palette."""

    def __init__(self, step_type: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._step_type = step_type
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setFixedHeight(54)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(8)

        icon = QLabel(STEP_TYPE_ICONS.get(step_type, "❓"), self)
        icon.setFixedWidth(22)
        icon.setStyleSheet("font-size: 15px;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(icon)

        col = QVBoxLayout()
        col.setSpacing(1)
        col.setContentsMargins(0, 0, 0, 0)

        name = QLabel(STEP_TYPE_LABELS.get(step_type, step_type), self)
        name.setStyleSheet("font-size: 12px; font-weight: 600;")
        col.addWidget(name)

        desc = QLabel(
            _STEP_TYPE_DESCRIPTIONS.get(step_type, ""), self
        )
        desc.setStyleSheet(
            f"font-size: 10px; color: {_tc('text_secondary')};"
        )
        col.addWidget(desc)

        lay.addLayout(col, stretch=1)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            drag = QDrag(self)
            mime = QMimeData()
            mime.setData(_MIME_STEP_TYPE, self._step_type.encode("utf-8"))
            drag.setMimeData(mime)
            drag.exec(Qt.DropAction.CopyAction)
        else:
            super().mousePressEvent(event)


class _PalettePanel(QWidget):
    """Left panel — palette of draggable step types."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(200)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        lbl = QLabel("Блоки", self)
        lbl.setStyleSheet("font-size: 13px; font-weight: 600; padding: 4px 0;")
        lay.addWidget(lbl)

        for st in STEP_TYPES:
            lay.addWidget(_PaletteItem(st, self))

        lay.addStretch()

        hint = QLabel("Перетащите блок\nв список шагов →", self)
        hint.setStyleSheet(
            f"color: {_tc('text_secondary')}; font-size: 11px; "
            "font-style: italic; padding: 8px;"
        )
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(hint)


# ═══════════════════════════════════════════════════════════════
#  STEP LIST — central panel with drag-drop reordering
# ═══════════════════════════════════════════════════════════════

class _StepListWidget(QListWidget):
    """
    List of scenario steps with:
    - Drop from palette (add new step)
    - Internal drag-drop (reorder)
    """

    step_added = Signal(str)     # emits step_type when dropped from palette
    step_selected = Signal(int)  # emits index when selection changes
    order_changed = Signal()     # emits when items reordered

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setSpacing(2)

        self.currentRowChanged.connect(self.step_selected.emit)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(_MIME_STEP_TYPE) or event.source() is self:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(_MIME_STEP_TYPE) or event.source() is self:
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        if event.mimeData().hasFormat(_MIME_STEP_TYPE):
            step_type = bytes(event.mimeData().data(_MIME_STEP_TYPE)).decode("utf-8")
            event.acceptProposedAction()
            self.step_added.emit(step_type)
        elif event.source() is self:
            super().dropEvent(event)
            self.order_changed.emit()
        else:
            event.ignore()


# ═══════════════════════════════════════════════════════════════
#  STEP CONFIG PANELS — right panel editors per step type
# ═══════════════════════════════════════════════════════════════

class _BaseConfigPanel(QWidget):
    """Base class for step configuration panels."""

    changed = Signal()

    def load(self, step: StepDefinition) -> None:
        """Load step data into the editor."""
        raise NotImplementedError

    def save(self) -> dict:
        """Return updated config dict."""
        raise NotImplementedError

    def get_label(self) -> str:
        """Return current label text."""
        return ""

    def get_applies_to(self) -> list[str]:
        """Return current applies_to list."""
        return list(MOVER_CASH_TYPES)


class _UploadFilesConfigPanel(_BaseConfigPanel):
    """Editor for upload_files step: file list per cash type."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        lay.addWidget(QLabel("Файлы для загрузки (по одному на строку):"))

        self._tabs: dict[str, QPlainTextEdit] = {}
        self._tab_widget = QComboBox(self)
        for ct in MOVER_CASH_TYPES:
            self._tab_widget.addItem(ct)
        self._tab_widget.currentTextChanged.connect(self._switch_tab)
        lay.addWidget(self._tab_widget)

        self._stack = QStackedWidget(self)
        for ct in MOVER_CASH_TYPES:
            edit = QPlainTextEdit(self)
            edit.setFont(QFont("Consolas", 10))
            edit.setPlaceholderText(f"Файлы для {ct}...")
            edit.textChanged.connect(self.changed.emit)
            self._tabs[ct] = edit
            self._stack.addWidget(edit)
        lay.addWidget(self._stack, stretch=1)

        hint = QLabel(
            "Файлы берутся из mover/files/", self
        )
        hint.setStyleSheet(f"font-size: 11px; color: {_tc('text_secondary')};")
        lay.addWidget(hint)

    def _switch_tab(self, text: str) -> None:
        idx = list(MOVER_CASH_TYPES).index(text) if text in MOVER_CASH_TYPES else 0
        self._stack.setCurrentIndex(idx)

    def load(self, step: StepDefinition) -> None:
        for ct in MOVER_CASH_TYPES:
            files = step.config.get(ct, [])
            self._tabs[ct].setPlainText("\n".join(files))

    def save(self) -> dict:
        config = {}
        for ct in MOVER_CASH_TYPES:
            lines = self._tabs[ct].toPlainText().strip().splitlines()
            config[ct] = [l.strip() for l in lines if l.strip()]
        return config


class _RunCommandsConfigPanel(_BaseConfigPanel):
    """Editor for run_commands step: commands per cash type (with subtypes for touch)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        lay.addWidget(QLabel("SSH-команды (по одной на строку):"))

        # Cash type selector
        self._type_combo = QComboBox(self)
        self._config_keys: list[str] = []
        lay.addWidget(self._type_combo)
        self._type_combo.currentTextChanged.connect(self._switch_tab)

        self._stack = QStackedWidget(self)
        self._editors: dict[str, QPlainTextEdit] = {}
        lay.addWidget(self._stack, stretch=1)

    def load(self, step: StepDefinition) -> None:
        self._type_combo.blockSignals(True)
        self._type_combo.clear()

        # Clear old editors
        while self._stack.count() > 0:
            w = self._stack.widget(0)
            self._stack.removeWidget(w)
            w.deleteLater()
        self._editors.clear()
        self._config_keys.clear()

        config = step.config
        # Build keys: for each cash type, check if dict (subtypes) or list
        for ct in MOVER_CASH_TYPES:
            raw = config.get(ct)
            if isinstance(raw, dict):
                # Touch with subtypes
                for subtype in raw:
                    key = f"{ct}/{subtype}"
                    self._config_keys.append(key)
                    self._type_combo.addItem(key)
                    edit = QPlainTextEdit(self)
                    edit.setFont(QFont("Consolas", 10))
                    edit.setPlainText("\n".join(raw[subtype]))
                    edit.textChanged.connect(self.changed.emit)
                    self._editors[key] = edit
                    self._stack.addWidget(edit)
            else:
                key = ct
                self._config_keys.append(key)
                self._type_combo.addItem(key)
                edit = QPlainTextEdit(self)
                edit.setFont(QFont("Consolas", 10))
                cmds = raw if isinstance(raw, list) else []
                edit.setPlainText("\n".join(cmds))
                edit.textChanged.connect(self.changed.emit)
                self._editors[key] = edit
                self._stack.addWidget(edit)

        self._type_combo.blockSignals(False)
        if self._config_keys:
            self._type_combo.setCurrentIndex(0)
            self._stack.setCurrentIndex(0)

    def _switch_tab(self, text: str) -> None:
        if text in self._editors:
            idx = self._config_keys.index(text)
            self._stack.setCurrentIndex(idx)

    def save(self) -> dict:
        config: dict = {}
        for key, edit in self._editors.items():
            lines = edit.toPlainText().strip().splitlines()
            cmds = [l for l in lines if l.strip()]

            if "/" in key:
                ct, subtype = key.split("/", 1)
                if ct not in config:
                    config[ct] = {}
                config[ct][subtype] = cmds
            else:
                config[key] = cmds
        return config


class _LoymaxConfigPanel(_BaseConfigPanel):
    """Editor for loymax step."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        lay.addWidget(QLabel("CSV-файл с логинами:"))
        self._csv_edit = QLineEdit(self)
        self._csv_edit.setPlaceholderText("loymax_cashes.csv")
        self._csv_edit.textChanged.connect(self.changed.emit)
        lay.addWidget(self._csv_edit)

        lay.addWidget(QLabel("Целевой путь на кассе:"))
        self._path_edit = QLineEdit(self)
        self._path_edit.textChanged.connect(self.changed.emit)
        lay.addWidget(self._path_edit)

        lay.addStretch()

        hint = QLabel("CSV берётся из mover/data/", self)
        hint.setStyleSheet(f"font-size: 11px; color: {_tc('text_secondary')};")
        lay.addWidget(hint)

    def load(self, step: StepDefinition) -> None:
        self._csv_edit.setText(step.config.get("csv_file", "loymax_cashes.csv"))
        self._path_edit.setText(step.config.get(
            "target_path",
            "/home/tc/storage/crystal-cash/config/plugins/loymax.properties"
        ))

    def save(self) -> dict:
        return {
            "csv_file": self._csv_edit.text().strip() or "loymax_cashes.csv",
            "target_path": self._path_edit.text().strip(),
        }


class _QridConfigPanel(_BaseConfigPanel):
    """Editor for qrid step."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        lay.addWidget(QLabel("CSV-файл с QRID:"))
        self._csv_edit = QLineEdit(self)
        self._csv_edit.setPlaceholderText("qrid.csv")
        self._csv_edit.textChanged.connect(self.changed.emit)
        lay.addWidget(self._csv_edit)

        lay.addWidget(QLabel("Целевой путь на кассе:"))
        self._path_edit = QLineEdit(self)
        self._path_edit.textChanged.connect(self.changed.emit)
        lay.addWidget(self._path_edit)

        lay.addStretch()

    def load(self, step: StepDefinition) -> None:
        self._csv_edit.setText(step.config.get("csv_file", "qrid.csv"))
        self._path_edit.setText(step.config.get(
            "target_path",
            "/home/tc/storage/crystal-cash/config/plugins/bank-gazprom_sbp-config.xml"
        ))

    def save(self) -> dict:
        return {
            "csv_file": self._csv_edit.text().strip() or "qrid.csv",
            "target_path": self._path_edit.text().strip(),
        }


class _ComPortConfigPanel(_BaseConfigPanel):
    """Editor for set_com_port step."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        lay.addWidget(QLabel("Целевой файл на кассе:"))
        self._path_edit = QLineEdit(self)
        self._path_edit.textChanged.connect(self.changed.emit)
        lay.addWidget(self._path_edit)

        lay.addStretch()

        note = QLabel(
            "COM-порт вводится пользователем\nперед запуском сценария.", self
        )
        note.setStyleSheet(
            f"color: {_tc('text_secondary')}; font-size: 11px; "
            "font-style: italic;"
        )
        lay.addWidget(note)

    def load(self, step: StepDefinition) -> None:
        self._path_edit.setText(step.config.get(
            "target_path",
            "/home/tc/storage/crystal-cash/banks/sberbank/linux/pinpad.ini"
        ))

    def save(self) -> dict:
        return {"target_path": self._path_edit.text().strip()}


# Registry: step type → config panel class
_CONFIG_PANELS: dict[str, type[_BaseConfigPanel]] = {
    "upload_files": _UploadFilesConfigPanel,
    "run_commands": _RunCommandsConfigPanel,
    "loymax": _LoymaxConfigPanel,
    "qrid": _QridConfigPanel,
    "set_com_port": _ComPortConfigPanel,
}


# ═══════════════════════════════════════════════════════════════
#  MAIN EDITOR DIALOG
# ═══════════════════════════════════════════════════════════════

class MoverEditorDialog(QDialog):
    """
    Конструктор Mover-сценариев.

    Может быть открыт:
    - Для создания нового сценария (scenario=None)
    - Для редактирования существующего (scenario=Scenario)
    """

    scenario_saved = Signal()  # emitted when scenario is saved

    def __init__(
        self,
        scenario: Scenario | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._manager = ScenarioManager()
        self._original_scenario = scenario
        self._steps: list[StepDefinition] = []
        self._selected_index: int = -1
        self._config_panel: _BaseConfigPanel | None = None
        self._modified = False

        if scenario:
            self._steps = [copy.deepcopy(s) for s in scenario.steps]

        self.setWindowTitle(
            f"Редактор сценария — {scenario.name}"
            if scenario else "Новый сценарий"
        )
        self.setMinimumSize(900, 600)
        self.resize(1000, 650)

        self._init_ui()
        self._refresh_step_list()

    # ── UI ────────────────────────────────────────────────────

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        # ── Top: name + description ──
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        top_row.addWidget(QLabel("Название:", self))
        self._name_edit = FluentLineEdit(self)
        self._name_edit.setPlaceholderText("Название сценария")
        if self._original_scenario:
            self._name_edit.setText(self._original_scenario.name)
        self._name_edit.textChanged.connect(self._mark_modified)
        top_row.addWidget(self._name_edit, stretch=1)

        top_row.addWidget(QLabel("Описание:", self))
        self._desc_edit = FluentLineEdit(self)
        self._desc_edit.setPlaceholderText("Краткое описание")
        if self._original_scenario:
            self._desc_edit.setText(self._original_scenario.description)
        self._desc_edit.textChanged.connect(self._mark_modified)
        top_row.addWidget(self._desc_edit, stretch=2)

        root.addLayout(top_row)

        # ── Main 3-panel splitter ──
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setHandleWidth(2)

        # Left: palette
        self._palette = _PalettePanel(self)
        splitter.addWidget(self._palette)

        # Center: step list
        center = QWidget(self)
        center_lay = QVBoxLayout(center)
        center_lay.setContentsMargins(0, 0, 0, 0)
        center_lay.setSpacing(4)

        center_header = QHBoxLayout()
        center_header.addWidget(QLabel("Шаги сценария:", self))
        center_header.addStretch()

        self._btn_remove = ToolButton(FluentIcon.DELETE, self)
        self._btn_remove.setToolTip("Удалить выбранный шаг")
        self._btn_remove.setFixedSize(28, 28)
        self._btn_remove.setEnabled(False)
        self._btn_remove.clicked.connect(self._on_remove_step)
        center_header.addWidget(self._btn_remove)

        self._btn_up = ToolButton(FluentIcon.UP, self)
        self._btn_up.setToolTip("Переместить вверх")
        self._btn_up.setFixedSize(28, 28)
        self._btn_up.setEnabled(False)
        self._btn_up.clicked.connect(self._on_move_up)
        center_header.addWidget(self._btn_up)

        self._btn_down = ToolButton(FluentIcon.DOWN, self)
        self._btn_down.setToolTip("Переместить вниз")
        self._btn_down.setFixedSize(28, 28)
        self._btn_down.setEnabled(False)
        self._btn_down.clicked.connect(self._on_move_down)
        center_header.addWidget(self._btn_down)

        center_lay.addLayout(center_header)

        self._step_list = _StepListWidget(self)
        self._step_list.step_added.connect(self._on_step_added_from_palette)
        self._step_list.step_selected.connect(self._on_step_selected)
        self._step_list.order_changed.connect(self._on_order_changed)
        center_lay.addWidget(self._step_list, stretch=1)

        splitter.addWidget(center)

        # Right: config panel
        right = QWidget(self)
        self._right_lay = QVBoxLayout(right)
        self._right_lay.setContentsMargins(0, 0, 0, 0)
        self._right_lay.setSpacing(4)

        self._right_header = QLabel("Настройки шага", self)
        self._right_header.setStyleSheet(
            "font-size: 13px; font-weight: 600; padding: 4px 0;"
        )
        self._right_lay.addWidget(self._right_header)

        # Step-level controls: label, enabled, applies_to
        step_meta = QWidget(self)
        meta_lay = QVBoxLayout(step_meta)
        meta_lay.setContentsMargins(0, 0, 0, 0)
        meta_lay.setSpacing(6)

        lbl_row = QHBoxLayout()
        lbl_row.addWidget(QLabel("Название:", self))
        self._step_label_edit = QLineEdit(self)
        self._step_label_edit.textChanged.connect(self._on_step_meta_changed)
        lbl_row.addWidget(self._step_label_edit, stretch=1)
        meta_lay.addLayout(lbl_row)

        self._step_enabled_cb = QCheckBox("Включён", self)
        self._step_enabled_cb.stateChanged.connect(self._on_step_meta_changed)
        meta_lay.addWidget(self._step_enabled_cb)

        applies_row = QHBoxLayout()
        applies_row.addWidget(QLabel("Типы касс:", self))
        self._applies_checks: dict[str, QCheckBox] = {}
        for ct in MOVER_CASH_TYPES:
            cb = QCheckBox(ct, self)
            cb.stateChanged.connect(self._on_step_meta_changed)
            self._applies_checks[ct] = cb
            applies_row.addWidget(cb)
        applies_row.addStretch()
        meta_lay.addLayout(applies_row)

        sep = QFrame(self)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        meta_lay.addWidget(sep)

        self._right_lay.addWidget(step_meta)

        # Config panel placeholder (replaced when step selected)
        self._config_container = QWidget(self)
        self._config_container_lay = QVBoxLayout(self._config_container)
        self._config_container_lay.setContentsMargins(0, 0, 0, 0)

        self._empty_label = QLabel(
            "Выберите шаг для настройки\nили перетащите блок из палитры",
            self,
        )
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(
            f"color: {_tc('text_secondary')}; font-size: 12px; "
            "font-style: italic; padding: 40px;"
        )
        self._config_container_lay.addWidget(self._empty_label)

        self._right_lay.addWidget(self._config_container, stretch=1)

        splitter.addWidget(right)

        # Splitter proportions
        splitter.setSizes([200, 280, 420])
        root.addWidget(splitter, stretch=1)

        # ── Bottom buttons ──
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        btn_cancel = PushButton("Отмена", self)
        btn_cancel.clicked.connect(self._on_cancel)
        btn_row.addWidget(btn_cancel)

        btn_row.addStretch()

        self._btn_save_as = PushButton("Сохранить как...", self)
        self._btn_save_as.setIcon(FluentIcon.SAVE_AS)
        self._btn_save_as.clicked.connect(lambda: self._on_save(save_as=True))
        btn_row.addWidget(self._btn_save_as)

        self._btn_save = PrimaryPushButton("Сохранить", self)
        self._btn_save.setIcon(FluentIcon.SAVE)
        self._btn_save.clicked.connect(lambda: self._on_save(save_as=False))
        btn_row.addWidget(self._btn_save)

        root.addLayout(btn_row)

        # Initially hide step meta
        step_meta.setVisible(False)
        self._step_meta_widget = step_meta

    # ── Step list management ──────────────────────────────────

    def _refresh_step_list(self) -> None:
        """Rebuild QListWidget items from self._steps."""
        self._step_list.blockSignals(True)
        self._step_list.clear()

        for step in self._steps:
            icon = STEP_TYPE_ICONS.get(step.type, "❓")
            text = f"{icon} {step.label}"
            if not step.enabled:
                text += " (выкл)"
            item = QListWidgetItem(text)
            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsDragEnabled
                | Qt.ItemFlag.ItemIsDropEnabled
            )
            self._step_list.addItem(item)

        self._step_list.blockSignals(False)
        self._update_buttons()

    def _on_step_added_from_palette(self, step_type: str) -> None:
        """Handle new step dropped from palette."""
        new_step = StepDefinition(
            id=str(uuid.uuid4())[:8],
            type=step_type,
        )
        self._steps.append(new_step)
        self._refresh_step_list()
        self._step_list.setCurrentRow(len(self._steps) - 1)
        self._mark_modified()

    def _on_remove_step(self) -> None:
        """Remove selected step."""
        idx = self._step_list.currentRow()
        if 0 <= idx < len(self._steps):
            self._steps.pop(idx)
            self._refresh_step_list()
            self._selected_index = -1
            self._show_empty_config()
            self._mark_modified()

    def _on_move_up(self) -> None:
        idx = self._step_list.currentRow()
        if idx > 0:
            self._save_current_config()
            self._steps[idx], self._steps[idx - 1] = (
                self._steps[idx - 1],
                self._steps[idx],
            )
            self._refresh_step_list()
            self._step_list.setCurrentRow(idx - 1)
            self._mark_modified()

    def _on_move_down(self) -> None:
        idx = self._step_list.currentRow()
        if 0 <= idx < len(self._steps) - 1:
            self._save_current_config()
            self._steps[idx], self._steps[idx + 1] = (
                self._steps[idx + 1],
                self._steps[idx],
            )
            self._refresh_step_list()
            self._step_list.setCurrentRow(idx + 1)
            self._mark_modified()

    def _on_order_changed(self) -> None:
        """Handle drag-drop reorder in list."""
        # Rebuild self._steps from list widget order
        # Items carry text with icon prefix — match by index
        # Since internal drag-drop only swaps items, we need to
        # re-derive order. Simplest: after DnD, items in QListWidget
        # are in new visual order but _steps is stale.
        # We use item text to match back (fragile but OK for now).
        new_steps: list[StepDefinition] = []
        for i in range(self._step_list.count()):
            item_text = self._step_list.item(i).text()
            # Find matching step — match by label
            for step in self._steps:
                icon = STEP_TYPE_ICONS.get(step.type, "❓")
                expected = f"{icon} {step.label}"
                if not step.enabled:
                    expected += " (выкл)"
                if expected == item_text and step not in new_steps:
                    new_steps.append(step)
                    break

        if len(new_steps) == len(self._steps):
            self._steps = new_steps
            self._mark_modified()

    def _on_step_selected(self, index: int) -> None:
        """Handle step selection in the list."""
        # Save previous config first
        self._save_current_config()

        self._selected_index = index
        self._update_buttons()

        if 0 <= index < len(self._steps):
            step = self._steps[index]
            self._show_step_config(step)
        else:
            self._show_empty_config()

    def _update_buttons(self) -> None:
        idx = self._step_list.currentRow()
        has_sel = 0 <= idx < len(self._steps)
        self._btn_remove.setEnabled(has_sel)
        self._btn_up.setEnabled(has_sel and idx > 0)
        self._btn_down.setEnabled(has_sel and idx < len(self._steps) - 1)

    # ── Config panel switching ────────────────────────────────

    def _show_empty_config(self) -> None:
        """Show empty placeholder in config area."""
        self._step_meta_widget.setVisible(False)
        self._clear_config_container()
        self._config_container_lay.addWidget(self._empty_label)
        self._empty_label.setVisible(True)
        self._config_panel = None
        self._right_header.setText("Настройки шага")

    def _show_step_config(self, step: StepDefinition) -> None:
        """Show config panel for the given step."""
        self._step_meta_widget.setVisible(True)

        # Update meta fields
        self._step_label_edit.blockSignals(True)
        self._step_label_edit.setText(step.label)
        self._step_label_edit.blockSignals(False)

        self._step_enabled_cb.blockSignals(True)
        self._step_enabled_cb.setChecked(step.enabled)
        self._step_enabled_cb.blockSignals(False)

        for ct, cb in self._applies_checks.items():
            cb.blockSignals(True)
            cb.setChecked(ct in step.applies_to)
            cb.blockSignals(False)

        # Update header
        icon = STEP_TYPE_ICONS.get(step.type, "❓")
        self._right_header.setText(f"{icon} {step.label}")

        # Replace config panel
        self._clear_config_container()
        self._empty_label.setVisible(False)

        panel_cls = _CONFIG_PANELS.get(step.type)
        if panel_cls:
            panel = panel_cls(self._config_container)
            panel.load(step)
            panel.changed.connect(self._mark_modified)
            self._config_container_lay.addWidget(panel, stretch=1)
            self._config_panel = panel
        else:
            lbl = QLabel(f"Нет редактора для типа «{step.type}»", self)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._config_container_lay.addWidget(lbl)
            self._config_panel = None

    def _clear_config_container(self) -> None:
        """Remove all widgets from config container."""
        while self._config_container_lay.count():
            item = self._config_container_lay.takeAt(0)
            w = item.widget()
            if w and w is not self._empty_label:
                w.deleteLater()

    def _save_current_config(self) -> None:
        """Save current config panel data back to the step."""
        if self._config_panel and 0 <= self._selected_index < len(self._steps):
            step = self._steps[self._selected_index]
            step.config = self._config_panel.save()

    def _on_step_meta_changed(self) -> None:
        """Handle changes in step label, enabled, applies_to."""
        if 0 <= self._selected_index < len(self._steps):
            step = self._steps[self._selected_index]
            step.label = self._step_label_edit.text().strip() or step.label
            step.enabled = self._step_enabled_cb.isChecked()
            step.applies_to = [
                ct for ct, cb in self._applies_checks.items() if cb.isChecked()
            ]
            # Update list item text
            icon = STEP_TYPE_ICONS.get(step.type, "❓")
            text = f"{icon} {step.label}"
            if not step.enabled:
                text += " (выкл)"
            item = self._step_list.item(self._selected_index)
            if item:
                item.setText(text)

            self._right_header.setText(f"{icon} {step.label}")
            self._mark_modified()

    # ── Save / Cancel ─────────────────────────────────────────

    def _mark_modified(self) -> None:
        self._modified = True

    def _on_save(self, save_as: bool = False) -> None:
        """Save scenario to JSON."""
        self._save_current_config()

        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Mover", "Введите название сценария.")
            self._name_edit.setFocus()
            return

        if not self._steps:
            QMessageBox.warning(self, "Mover", "Добавьте хотя бы один шаг.")
            return

        scenario = Scenario(
            name=name,
            description=self._desc_edit.text().strip(),
            steps=self._steps,
        )

        # Determine save path
        if not save_as and self._original_scenario and self._original_scenario.file_path:
            path = self._original_scenario.file_path
        else:
            safe_name = name.replace(" ", "_").lower()
            # Remove problematic characters
            safe_name = "".join(
                c for c in safe_name if c.isalnum() or c in "_-"
            ) or "scenario"
            path = get_mover_scenarios_dir() / f"{safe_name}.json"

            if path.exists():
                reply = QMessageBox.question(
                    self, "Mover",
                    f"Файл «{path.name}» уже существует. Перезаписать?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                )
                if reply != QMessageBox.StandardButton.Yes:
                    return

        try:
            scenario.save(path)
            self._modified = False
            self.scenario_saved.emit()
            QMessageBox.information(
                self, "Mover",
                f"Сценарий «{name}» сохранён:\n{path.name}",
            )
            self.accept()
        except Exception as e:
            QMessageBox.critical(
                self, "Ошибка",
                f"Не удалось сохранить сценарий:\n{e}",
            )

    def _on_cancel(self) -> None:
        if self._modified:
            reply = QMessageBox.question(
                self, "Mover",
                "Есть несохранённые изменения. Выйти без сохранения?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self.reject()

    def closeEvent(self, event) -> None:
        if self._modified:
            reply = QMessageBox.question(
                self, "Mover",
                "Есть несохранённые изменения. Выйти без сохранения?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        super().closeEvent(event)