"""
command_editor.py — Конструктор команд CashControl.

Левая панель: список команд (JSON и Python) + кнопки + / удалить.
Правая панель: форма редактирования с выбором типа SSH / Python.
"""
from __future__ import annotations

import contextlib
import json

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CardWidget,
    ComboBox,
    FluentIcon,
    LineEdit,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    ToolButton,
)

from cashcontrol.infrastructure.audit_logger import get_logger
from cashcontrol.infrastructure.path_resolver import get_commands_dir

logger = get_logger()
_LABEL_W = 150
_PY_TEMPLATE = """\
# description: Описание команды
# requires_confirmation: false
# timeout: 30

# Ввод от пользователя — раскомментируй INPUT_PROMPT:
# INPUT_PROMPT = "Введите значение:"
# Значение будет доступно в kwargs["user_input"]

async def execute(session, **kwargs):
    # session.host               — IP кассы
    # session.ssh.execute("cmd") — выполнить SSH команду
    # session.cash_type          — тип кассы (pos, sco, sco3)
    result = await session.ssh.execute("uptime")
    return result.stdout.strip()
"""

# ── Форма редактирования ─────────────────────────────────────────────────────

class _CommandForm(QWidget):
    """Форма просмотра/редактирования одной команды."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()
        self._set_edit(False)

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 8)
        root.setSpacing(8)

        # Имя
        self._name = LineEdit(self)
        self._name.setPlaceholderText("my_command")
        self._name.textChanged.connect(self.changed)
        root.addLayout(self._row("Имя (ID):", self._name))

        # Описание
        self._desc = LineEdit(self)
        self._desc.setPlaceholderText("Краткое описание")
        self._desc.textChanged.connect(self.changed)
        root.addLayout(self._row("Описание:", self._desc))

        # Тип
        self._type = ComboBox(self)
        self._type.addItem("SSH-команды", userData="ssh")
        self._type.addItem("Python-скрипт", userData="python")
        self._type.currentIndexChanged.connect(self._switch)
        self._type.currentIndexChanged.connect(self.changed)
        root.addLayout(self._row("Тип:", self._type))

        # Таймаут
        self._timeout = QSpinBox(self)
        self._timeout.setRange(5, 600)
        self._timeout.setValue(30)
        self._timeout.setSuffix(" сек")
        self._timeout.setFixedWidth(110)
        self._timeout.valueChanged.connect(self.changed)
        tr = QHBoxLayout()
        tr.addLayout(self._row("Таймаут:", self._timeout))
        tr.addStretch()
        root.addLayout(tr)

        # Чекбоксы
        self._confirm = QCheckBox("Требует подтверждения", self)
        self._confirm.stateChanged.connect(self.changed)
        self._show_out = QCheckBox("Показывать вывод после выполнения", self)
        self._show_out.setChecked(True)
        self._show_out.stateChanged.connect(self.changed)
        root.addWidget(self._confirm)
        root.addWidget(self._show_out)

        sep = QFrame(self)
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(sep)

        # SSH-блок
        self._ssh_box = QGroupBox("Команды (по одной на строку):", self)
        sl = QVBoxLayout(self._ssh_box)
        sl.setContentsMargins(6, 6, 6, 6)
        hint = QLabel("Выполняются последовательно по SSH. Остановка при первой ошибке.", self)
        from cashcontrol.gui.theme_helper import color as _tc
        hint.setStyleSheet(f"color:{_tc('text_secondary')};font-size:11px;")
        hint.setWordWrap(True)
        sl.addWidget(hint)
        self._cmds = QPlainTextEdit(self)
        self._cmds.setPlaceholderText("cd /tmp\nls -la\necho done")
        self._cmds.setMinimumHeight(160)
        self._cmds.setStyleSheet("font-family:Consolas,monospace;font-size:12px;")
        self._cmds.textChanged.connect(self.changed)
        sl.addWidget(self._cmds)
        root.addWidget(self._ssh_box)

        # Python-блок
        self._py_box = QGroupBox("Python-скрипт:", self)
        pl = QVBoxLayout(self._py_box)
        pl.setContentsMargins(6, 6, 6, 6)
        ph = QLabel("Обязательно: async def execute(session, **kwargs)\nДоступно: session.ssh.execute(), session.host", self)
        from cashcontrol.gui.theme_helper import color as _tc
        ph.setStyleSheet(f"color:{_tc('text_secondary')};font-size:11px;")
        ph.setWordWrap(True)
        pl.addWidget(ph)
        self._py = QPlainTextEdit(self)
        self._py.setPlainText(_PY_TEMPLATE)
        self._py.setMinimumHeight(160)
        self._py.setStyleSheet("font-family:Consolas,monospace;font-size:12px;")
        self._py.textChanged.connect(self.changed)
        pl.addWidget(self._py)
        root.addWidget(self._py_box)
        self._py_box.setVisible(False)

        root.addStretch()

    def _row(self, label, widget):
        row = QHBoxLayout()
        row.setSpacing(8)
        lbl = QLabel(label, self)
        lbl.setFixedWidth(85)
        lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(lbl)
        row.addWidget(widget)
        return row

    def _switch(self, index):
        is_py = (index == 1)
        self._ssh_box.setVisible(not is_py)
        self._py_box.setVisible(is_py)
        if is_py and not self._py.toPlainText().strip():
            self._py.setPlainText(_PY_TEMPLATE)

    def _set_edit(self, on):
        self._name.setReadOnly(not on)
        self._desc.setReadOnly(not on)
        self._type.setEnabled(on)
        self._timeout.setEnabled(on)
        self._confirm.setEnabled(on)
        self._show_out.setEnabled(on)
        self._cmds.setReadOnly(not on)
        self._py.setReadOnly(not on)
        from cashcontrol.gui.theme_helper import color as _tc
        bg = "" if on else f"background:{_tc('bg_secondary')};color:{_tc('text_tertiary')};"
        self._name.setStyleSheet(bg)
        self._desc.setStyleSheet(bg)
        self._cmds.setStyleSheet(f"font-family:Consolas,monospace;font-size:12px;{bg}")
        self._py.setStyleSheet(f"font-family:Consolas,monospace;font-size:12px;{bg}")

    # Публичный API
    def set_edit_mode(self, on): self._set_edit(on)
    def load(self, data):
        self._name.setText(data.get("name", ""))
        self._desc.setText(data.get("description", ""))
        self._timeout.setValue(data.get("timeout", 30))
        self._confirm.setChecked(bool(data.get("requires_confirmation", False)))
        self._show_out.setChecked(bool(data.get("show_output", True)))
        idx = 1 if data.get("command_type") == "python" else 0
        self._type.setCurrentIndex(idx)
        self._switch(idx)
        if idx == 1:
            self._py.setPlainText(data.get("py_source", _PY_TEMPLATE))
        else:
            self._cmds.setPlainText("\n".join(data.get("commands", [])))

    def to_dict(self):
        is_py = self._type.currentIndex() == 1
        d = {
            "name":                  self._name.text().strip(),
            "description":           self._desc.text().strip(),
            "timeout":               self._timeout.value(),
            "requires_confirmation": self._confirm.isChecked(),
            "show_output":           self._show_out.isChecked(),
            "command_type":          "python" if is_py else "ssh",
        }
        if is_py:
            d["commands"] = []
            d["py_source"] = self._py.toPlainText()
        else:
            d["commands"] = [line.rstrip() for line in self._cmds.toPlainText().splitlines() if line.strip()]
        return d

    def clear(self):
        self._name.clear()
        self._desc.clear()
        self._timeout.setValue(30)
        self._confirm.setChecked(False)
        self._show_out.setChecked(True)
        self._type.setCurrentIndex(0)
        self._switch(0)
        self._cmds.clear()
        self._py.setPlainText(_PY_TEMPLATE)

    def validate(self):
        name = self._name.text().strip()
        if not name:
            return "Поле «Имя (ID)» обязательно"
        if self._type.currentIndex() == 1:
            if "async def execute(session" not in self._py.toPlainText():
                return "Скрипт должен содержать: async def execute(session, **kwargs)"
        else:
            if not any(line.strip() for line in self._cmds.toPlainText().splitlines()):
                return "Список команд не может быть пустым"
        return None


# ── Главный диалог ───────────────────────────────────────────────────────────

class CommandEditorDialog(QDialog):
    """Диалог управления командами — список слева, форма справа."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Конструктор команд")
        self.setMinimumSize(880, 600)
        self.setWindowModality(Qt.WindowModality.ApplicationModal)
        self._dir = get_commands_dir()
        self._dir.mkdir(parents=True, exist_ok=True)
        self._file = None
        self._orig_name = None
        self._is_new = False
        self._mode = "idle"
        self._build()
        self._refresh()
        self._set_mode("idle")

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 12, 16, 12)
        root.setSpacing(10)
        root.addWidget(SubtitleLabel("Конструктор команд", self))

        body = QHBoxLayout()
        body.setSpacing(10)

        # Левая панель
        left = CardWidget(self)
        left.setFixedWidth(210)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(8, 8, 8, 8)
        ll.setSpacing(6)
        ll.addWidget(QLabel("<b>Команды</b>", self))
        self._list = QListWidget(self)
        self._list.currentItemChanged.connect(self._on_select)
        ll.addWidget(self._list, stretch=1)
        row_b = QHBoxLayout()
        row_b.setSpacing(4)
        self._btn_new = PushButton("+ Новая", self)
        self._btn_new.clicked.connect(self._on_new)
        row_b.addWidget(self._btn_new)
        self._btn_del = ToolButton(FluentIcon.DELETE, self)
        self._btn_del.setToolTip("Удалить")
        self._btn_del.clicked.connect(self._on_delete)
        row_b.addWidget(self._btn_del)
        ll.addLayout(row_b)
        body.addWidget(left)

        # Правая панель
        right = CardWidget(self)
        right.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        rl = QVBoxLayout(right)
        rl.setContentsMargins(8, 8, 8, 8)
        rl.setSpacing(6)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._form = _CommandForm()
        scroll.setWidget(self._form)
        rl.addWidget(scroll, stretch=1)

        act = QHBoxLayout()
        act.addStretch()
        self._btn_edit = PushButton("✏ Редактировать", self)
        self._btn_edit.clicked.connect(self._on_edit)
        act.addWidget(self._btn_edit)
        self._btn_cancel = PushButton("Отмена", self)
        self._btn_cancel.clicked.connect(self._on_cancel)
        act.addWidget(self._btn_cancel)
        self._btn_save = PrimaryPushButton("💾 Сохранить", self)
        self._btn_save.clicked.connect(self._on_save)
        act.addWidget(self._btn_save)
        rl.addLayout(act)
        body.addWidget(right, stretch=1)
        root.addLayout(body, stretch=1)

        cr = QHBoxLayout()
        cr.addStretch()
        btn_close = PushButton("Close", self)
        btn_close.clicked.connect(self.accept)
        cr.addWidget(btn_close)
        root.addLayout(cr)

    def _set_mode(self, mode):
        self._mode = mode
        self._form.set_edit_mode(mode in ("edit", "new"))
        self._btn_new.setEnabled(mode in ("idle", "view"))
        self._btn_del.setEnabled(mode == "view")
        self._list.setEnabled(mode in ("idle", "view"))
        self._btn_edit.setVisible(mode == "view")
        self._btn_cancel.setVisible(mode in ("edit", "new"))
        self._btn_save.setVisible(mode in ("edit", "new"))

    def _refresh(self):
        cur = self._list.currentItem()
        cur_text = cur.text() if cur else None
        self._list.blockSignals(True)
        self._list.clear()
        for f in sorted(self._dir.glob("*.json")):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                name = data.get("name", f.stem)
            except Exception:
                name = f.stem
            item = QListWidgetItem(name)
            item.setData(Qt.ItemDataRole.UserRole, f)
            self._list.addItem(item)
        for f in sorted(self._dir.glob("*.py")):
            item = QListWidgetItem(f"[py] {f.stem}")
            item.setData(Qt.ItemDataRole.UserRole, f)
            self._list.addItem(item)
        self._list.blockSignals(False)
        if cur_text:
            for i in range(self._list.count()):
                if self._list.item(i).text() == cur_text:
                    self._list.setCurrentRow(i)
                    return

    def _load_file(self, f):
        if f.suffix == ".py":
            src = f.read_text(encoding="utf-8")
            desc, req, timeout = "", False, 30
            for line in src.splitlines():
                line = line.strip()
                if not line.startswith("#"):
                    break
                if line.startswith("# description:"):
                    desc = line[len("# description:"):].strip()
                elif line.startswith("# requires_confirmation:"):
                    req = line[len("# requires_confirmation:"):].strip().lower() == "true"
                elif line.startswith("# timeout:"):
                    with contextlib.suppress(ValueError):
                        timeout = int(line[len("# timeout:"):].strip())
            return {"name": f.stem, "description": desc, "timeout": timeout,
                    "requires_confirmation": req, "command_type": "python", "py_source": src}
        else:
            return json.loads(f.read_text(encoding="utf-8"))

    def _on_select(self, item, _):
        if item is None or self._mode not in ("idle", "view"):
            return
        f = item.data(Qt.ItemDataRole.UserRole)
        self._file = f
        try:
            data = self._load_file(f)
            self._form.load(data)
            self._orig_name = data.get("name", f.stem)
        except Exception as e:
            QMessageBox.warning(self, "Ошибка", f"Не удалось загрузить:\n{e}")
            return
        self._set_mode("view")

    def _on_new(self):
        self._list.clearSelection()
        self._file = None
        self._orig_name = None
        self._is_new = True
        self._form.clear()
        self._set_mode("new")

    def _on_edit(self):
        self._set_mode("edit")

    def _on_cancel(self):
        if self._is_new:
            self._is_new = False
            self._form.clear()
            self._file = None
            self._set_mode("idle")
        else:
            if self._file:
                try:
                    data = self._load_file(self._file)
                    self._form.load(data)
                except Exception:
                    # ожидаемо: файл может быть повреждён, показываем пустую форму
                    pass
            self._set_mode("view")

    def _on_save(self):
        err = self._form.validate()
        if err:
            QMessageBox.warning(self, "Ошибка", err)
            return
        data = self._form.to_dict()
        name = data["name"]
        file_stem = name.replace(" ", "_")
        is_py = data.get("command_type") == "python"
        ext = ".py" if is_py else ".json"

        if self._file and not self._is_new:
            if (self._orig_name and self._orig_name != name) or self._file.suffix != ext:
                with contextlib.suppress(Exception):
                    self._file.unlink(missing_ok=True)
                target = self._dir / f"{file_stem}{ext}"
            else:
                target = self._file
        else:
            target = self._dir / f"{file_stem}{ext}"

        try:
            if is_py:
                src = data.get("py_source", "")
                header = "\n".join([
                    f"# description: {data.get('description', '')}",
                    f"# requires_confirmation: {str(data.get('requires_confirmation', False)).lower()}",
                    f"# timeout: {data.get('timeout', 30)}",
                ])
                lines = src.splitlines()
                body_start = next((i for i, ln in enumerate(lines) if not ln.strip().startswith("#")), 0)
                body = "\n".join(lines[body_start:]).lstrip("\n")
                target.write_text(header + "\n\n" + body, encoding="utf-8")
            else:
                data.pop("py_source", None)
                target.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")
            logger.info(f"Command saved: {target.name}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить:\n{e}")
            return

        self._file = target
        self._orig_name = name
        self._is_new = False
        self._refresh()
        display = f"[py] {name}" if is_py else name
        for i in range(self._list.count()):
            if self._list.item(i).text() == display:
                self._list.blockSignals(True)
                self._list.setCurrentRow(i)
                self._list.blockSignals(False)
                break
        self._set_mode("view")

    def _on_delete(self):
        item = self._list.currentItem()
        if not item:
            return
        f = item.data(Qt.ItemDataRole.UserRole)
        reply = QMessageBox.question(
            self, "Удалить", f"Удалить «{item.text()}»?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            f.unlink(missing_ok=True)
            logger.info(f"Command deleted: {f.name}")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось удалить:\n{e}")
            return
        self._file = None
        self._orig_name = None
        self._form.clear()
        self._refresh()
        self._set_mode("idle")