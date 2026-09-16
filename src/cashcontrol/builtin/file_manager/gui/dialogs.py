"""Modal dialogs used by the Remote Files GUI (conflicts, prompts, info) and the
editable owner/group/permissions properties dialog."""

from __future__ import annotations

import stat as _stat
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
    QTextCursor,
    QTextDocument,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTextEdit,
    QToolBar,
    QToolButton,
    QVBoxLayout,
)

from cashcontrol.builtin.file_manager.models import FileKind

if TYPE_CHECKING:
    from cashcontrol.builtin.file_manager.models import RemoteFileInfo
    from cashcontrol.builtin.file_manager.service import ConflictInfo

_KIND_RU = {
    FileKind.FILE: "Файл",
    FileKind.DIRECTORY: "Каталог",
    FileKind.SYMLINK: "Символическая ссылка",
    FileKind.OTHER: "Другое",
}


class ConflictDialog(QDialog):
    """Asks the user how to resolve a destination-conflict during a transfer."""

    ACTIONS = (
        ("overwrite", "Перезаписать"),
        ("overwrite_if_newer", "Перезаписать, если новее"),
        ("rename", "Переименовать"),
        ("skip", "Пропустить"),
    )

    def __init__(self, conflict: ConflictInfo, parent: Any = None) -> None:
        super().__init__(parent)
        self._chosen = "skip"
        self.setWindowTitle("Файл уже существует")
        text = (
            f"{conflict.destination}\n"
            f"Источник: {self._size(conflict.source_size)}   "
            f"Назначение: {self._size(conflict.destination_size)}\n"
            f"Источник изменён: {self._time(conflict.source_mtime)}   "
            f"Назначение изменено: {self._time(conflict.destination_mtime)}"
        )
        label = QLabel(text, self)
        label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._apply_all = QCheckBox("Применить ко всем", self)
        buttons = QHBoxLayout()
        for action, caption in self.ACTIONS:
            button = QPushButton(caption, self)
            button.clicked.connect(lambda _=False, a=action: self._choose(a))
            buttons.addWidget(button)
        cancel = QPushButton("Отмена", self)
        cancel.clicked.connect(lambda: self._choose("abort"))
        buttons.addWidget(cancel)

        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addWidget(self._apply_all)
        layout.addLayout(buttons)

    @staticmethod
    def _size(value: int | None) -> str:
        return f"{value} байт" if value is not None else "н/д"

    @staticmethod
    def _time(value: object) -> str:
        return value.strftime("%Y-%m-%d %H:%M") if value is not None else "н/д"

    def _choose(self, action: str) -> None:
        self._chosen = action
        self.accept()

    def chosen_action(self) -> str:
        return self._chosen

    def apply_to_all(self) -> bool:
        return self._apply_all.isChecked()


class PathInputDialog(QDialog):
    """Single-line input for mkdir/rename actions."""

    def __init__(self, title: str, label: str, initial: str = "", parent: Any = None) -> None:
        super().__init__(parent)
        self._edit = QLineEdit(initial, self)
        self._edit.setMinimumWidth(320)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(label, self))
        layout.addWidget(self._edit)
        layout.addWidget(buttons)

    def value(self) -> str:
        return self._edit.text().strip()


class DeleteConfirmDialog(QDialog):
    """Confirms recursive deletion when directories are among the selection."""

    def __init__(self, count: int, has_dirs: bool, parent: Any = None) -> None:
        super().__init__(parent)
        self._recursive = has_dirs
        self.setWindowTitle("Подтверждение удаления")
        label = QLabel(
            f"Удалить {count} элемент(ов)?"
            + ("\nКаталоги будут удалены рекурсивно." if has_dirs else ""),
            self,
        )
        self._recursive_check = QCheckBox("Удалять каталоги рекурсивно", self)
        self._recursive_check.setChecked(has_dirs)
        if not has_dirs:
            self._recursive_check.setEnabled(False)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No,
            self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Yes).setText("Удалить")
        buttons.accepted.connect(lambda: self.accept())
        buttons.rejected.connect(lambda: self.reject())
        layout = QVBoxLayout(self)
        layout.addWidget(label)
        layout.addWidget(self._recursive_check)
        layout.addWidget(buttons)

    def recursive(self) -> bool:
        return self._recursive_check.isChecked()


class ConnectDialog(QDialog):
    """Collects connection parameters for the standalone manager."""

    def __init__(self, parent: Any = None, host: str = "", user: str = "", port: int = 22) -> None:
        super().__init__(parent)
        self._host = QLineEdit(host, self)
        self._port = QLineEdit(str(port), self)
        self._user = QLineEdit(user, self)
        self._password = QLineEdit(self)
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._protocol = QComboBox(self)
        self._protocol.addItem("Авто (SFTP, при недоступности — SCP)", "auto")
        self._protocol.addItem("SFTP", "sftp")
        self._protocol.addItem("SCP (shell)", "scp")
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form = QFormLayout()
        form.addRow("Хост:", self._host)
        form.addRow("Порт:", self._port)
        form.addRow("Пользователь:", self._user)
        form.addRow("Пароль:", self._password)
        form.addRow("Протокол:", self._protocol)
        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def result_data(self) -> dict[str, object]:
        return {
            "host": self._host.text().strip(),
            "port": int(self._port.text().strip() or "22"),
            "username": self._user.text().strip(),
            "password": self._password.text(),
            "protocol": str(self._protocol.currentData()),
        }


class ConnectErrorDialog(QDialog):
    """Technical diagnostics shown when an SSH/SFTP connection fails."""

    def __init__(
        self,
        *,
        host: str,
        port: int,
        protocol: str,
        stage: str,
        error_line: str,
        details: str,
        log_tail: list[str],
        on_open_log: Any = None,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Не удалось подключиться")
        self.resize(760, 560)

        summary = (
            f"Хост: {host}   Порт: {port}   Протокол: {_PROTOCOL_RU.get(protocol, protocol)}\n"
            f"Этап: {stage}\n\n{error_line}"
        )
        summary_label = QLabel(summary, self)
        summary_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        summary_label.setWordWrap(True)

        section_label = QLabel("Технические сведения (лог):", self)
        view = QPlainTextEdit(self)
        view.setReadOnly(True)
        view.setPlainText("\n".join(details) if isinstance(details, list) else str(details))
        if log_tail:
            view.appendPlainText("\n" + "─" * 60 + "\nПоследние записи журнала:\n" + "\n".join(log_tail))

        copy_btn = QPushButton("Копировать в буфер", self)
        copy_btn.clicked.connect(lambda: self._copy(view))
        log_btn = QPushButton("Открыть журнал", self)
        log_btn.clicked.connect(self._call(on_open_log))
        close_btn = QPushButton("Закрыть", self)
        close_btn.clicked.connect(self.accept)

        buttons = QHBoxLayout()
        buttons.addWidget(copy_btn)
        buttons.addWidget(log_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)

        layout = QVBoxLayout(self)
        layout.addWidget(summary_label)
        layout.addWidget(section_label)
        layout.addWidget(view, 1)
        layout.addLayout(buttons)

    def _copy(self, view: QPlainTextEdit) -> None:
        view.selectAll()
        view.copy()

    def _call(self, callback: Any):
        def invoke() -> None:
            if callback is not None:
                callback()
            self.accept()

        return invoke


_PROTOCOL_RU = {"auto": "Авто", "sftp": "SFTP", "scp": "SCP (shell)"}


# ── File properties (owner/group/permissions) ───────────────────────────────
_PERM_COLUMNS = (
    ("owner", "Владелец"),
    ("group", "Группа"),
    ("other", "Другие"),
)
_PERM_BITS = (0o400, 0o200, 0o100, 0o040, 0o020, 0o010, 0o004, 0o002, 0o001)
_SPECIALS = (
    ("setuid", 0o4000),
    ("setgid", 0o2000),
    ("sticky", 0o1000),
)


def mode_to_octal(mode: int) -> str:
    """Render a permission-mode integer as a 4-digit octal string (e.g. 0755)."""
    return f"{mode & 0o7777:04o}"


def octal_to_mode(text: str) -> int | None:
    """Parse an octal string like '755' or '0777'; returns None if invalid."""
    digits = text.strip()
    if not 1 <= len(digits) <= 4 or not all(ch in "01234567" for ch in digits):
        return None
    return int(digits, 8)


def mode_to_symbolic(mode: int | None) -> str:
    """Render a mode integer as `-rwxr-xr-x`, using the file-type prefix."""
    if mode is None:
        return "---------"
    return _stat.filemode(mode & 0o7777)[1:]


def perm_checkboxes_state(states: list[bool]) -> int:
    """Combine 9 rwx checkboxes plus 3 special bits into a permission mode."""
    if len(states) != 9:
        raise ValueError("expected 9 permission states")
    mode = sum(
        _PERM_BITS[i] for i, checked in enumerate(states) if checked
    )
    return mode


class PropertiesDialog(QDialog):
    """View/edit owner, group and permissions of a local or remote file.

    ``apply_callback(mode, owner, group)`` is invoked with ``None`` values for
    the attributes the user did not request to change.
    """

    def __init__(
        self,
        info: RemoteFileInfo,
        parent: Any = None,
        can_own: bool = True,
        apply_callback: Any = None,
    ) -> None:
        super().__init__(parent)
        self._info = info
        self._apply_callback = apply_callback
        self.setWindowTitle("Свойства и права доступа")
        self.setMinimumWidth(460)

        layout = QVBoxLayout(self)

        info_label = QLabel(self)
        info_label.setWordWrap(True)
        info_label.setText(
            f"{info.path}\n"
            f"Тип: {_KIND_RU.get(info.kind, str(info.kind.value))}    "
            f"Размер: {info.size_formatted}    "
            f"Изменён: {info.modified_at.strftime('%Y-%m-%d %H:%M:%S') if info.modified_at else 'н/д'}"
        )
        info_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(info_label)

        form = QFormLayout()
        self._owner_edit = QLineEdit(info.owner or "", self)
        self._group_edit = QLineEdit(info.group or "", self)
        self._owner_edit.setPlaceholderText("н/д")
        self._group_edit.setPlaceholderText("н/д")
        self._owner_edit.setEnabled(can_own)
        self._group_edit.setEnabled(can_own)
        self._owner_edit.setToolTip("Новое имя владельца (или uid). Требуются права root.")
        self._group_edit.setToolTip("Новое имя группы (или gid). Требуются права root.")
        form.addRow("Владелец:", self._owner_edit)
        form.addRow("Группа:", self._group_edit)
        layout.addLayout(form)

        perm_box = QGroupBox("Права доступа", self)
        perm_layout = QVBoxLayout(perm_box)

        self._special = [QCheckBox(label, self) for label, _bit in _SPECIALS]
        special_row = QHBoxLayout()
        for check in self._special:
            check.toggled.connect(self._sync_from_checks)
            special_row.addWidget(check)
        special_row.addStretch(1)
        perm_layout.addLayout(special_row)

        self._perm_checks: list[QCheckBox] = []
        cols = QHBoxLayout()
        for _col, (_key, title) in enumerate(_PERM_COLUMNS):
            column = QVBoxLayout()
            header = QLabel(title, self)
            header.setStyleSheet("font-weight: 600;")
            header.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            column.addWidget(header)
            for label in "rwx":
                check = QCheckBox(label, self)
                check.toggled.connect(self._sync_from_checks)
                self._perm_checks.append(check)
                column.addWidget(check, alignment=Qt.AlignmentFlag.AlignHCenter)
            cols.addLayout(column, stretch=1)
        perm_layout.addLayout(cols)

        self._octal_edit = QLineEdit(self)
        self._octal_edit.setMaxLength(4)
        self._octal_edit.setFixedWidth(64)
        self._octal_edit.setToolTip("Код в восьмеричной системе, например 0777")
        fix = QLabel("octal (например 0777):", self)
        self._symbol_label = QLabel("", self)
        self._symbol_label.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace;"
        )
        octal_row = QHBoxLayout()
        octal_row.addWidget(fix)
        octal_row.addWidget(self._octal_edit)
        octal_row.addSpacing(12)
        octal_row.addWidget(self._symbol_label)
        octal_row.addStretch(1)
        perm_layout.addLayout(octal_row)

        layout.addWidget(perm_box)

        hint = QLabel("Примечание: смена владельца/группы обычно требует прав root.", self)
        hint.setWordWrap(True)
        layout.addWidget(hint)

        buttons = QHBoxLayout()
        apply_btn = QPushButton("Применить", self)
        apply_btn.clicked.connect(self._apply)
        close_btn = QPushButton("Закрыть", self)
        close_btn.clicked.connect(self.accept)
        buttons.addStretch(1)
        buttons.addWidget(apply_btn)
        buttons.addWidget(close_btn)
        layout.addLayout(buttons)

        self._updating = False
        self._octal_edit.textChanged.connect(self._sync_from_octal)
        initial = (info.mode or 0) & 0o7777
        for i, bit in enumerate(_PERM_BITS):
            self._perm_checks[i].setChecked(bool(initial & bit))
        for check, (_name, bit) in zip(self._special, _SPECIALS, strict=True):
            check.setChecked(bool(initial & bit))
        self._octal_edit.setText(mode_to_octal(initial))
        self._symbol_label.setText(mode_to_symbolic(initial))

    # ── state sync ──────────────────────────────────────────
    def _widgets_mode(self) -> int:
        return perm_checkboxes_state([c.isChecked() for c in self._perm_checks]) | sum(
            bit for (_name, bit), check in zip(_SPECIALS, self._special, strict=True) if check.isChecked()
        )

    def _sync_from_checks(self) -> None:
        if self._updating:
            return
        self._updating = True
        try:
            mode = self._widgets_mode()
            self._octal_edit.setText(mode_to_octal(mode))
            self._symbol_label.setText(mode_to_symbolic(mode))
        finally:
            self._updating = False

    def _sync_from_octal(self) -> None:
        if self._updating:
            return
        mode = octal_to_mode(self._octal_edit.text())
        if mode is None:
            self._symbol_label.setText("— код неверен —")
            return
        self._updating = True
        try:
            for i, bit in enumerate(_PERM_BITS):
                self._perm_checks[i].setChecked(bool(mode & bit))
            for check, (_name, bit) in zip(self._special, _SPECIALS, strict=True):
                check.setChecked(bool(mode & bit))
            self._symbol_label.setText(mode_to_symbolic(mode))
        finally:
            self._updating = False

    # ── results ─────────────────────────────────────────────
    def requested_mode(self) -> int | None:
        mode = octal_to_mode(self._octal_edit.text())
        if mode is None:
            return None
        original = (self._info.mode or 0) & 0o7777
        return mode if mode != original else None

    def requested_owner(self) -> str | None:
        return self._changed_or_none(self._owner_edit.text(), self._info.owner)

    def requested_group(self) -> str | None:
        return self._changed_or_none(self._group_edit.text(), self._info.group)

    @staticmethod
    def _changed_or_none(current: str, original: str | None) -> str | None:
        current = current.strip()
        if current and current != (original or ""):
            return current
        return None

    def _apply(self) -> None:
        if octal_to_mode(self._octal_edit.text()) is None:
            self._octal_edit.setFocus()
            self._octal_edit.selectAll()
            return
        if self._apply_callback is not None:
            self._apply_callback(
                self.requested_mode(),
                self.requested_owner(),
                self.requested_group(),
            )
        self.accept()


__all__ = [
    "ConflictDialog",
    "ConnectDialog",
    "ConnectErrorDialog",
    "DeleteConfirmDialog",
    "PathInputDialog",
    "PropertiesDialog",
    "mode_to_octal",
    "mode_to_symbolic",
    "octal_to_mode",
    "perm_checkboxes_state",
]


# --- merged from editor.py ---


"""Text file editor dialog with encoding detection (CP1251, UTF-8, …)

Standard editing functions: copy, paste, select-all, search bar (with match
highlighting), replace / replace-all, jump-to-line, and an encoding selector.
The dialog itself is synchronous — byte loading/saving is done by the owning
session through signals ``load_requested`` / ``save_requested``.
"""


EDITOR_MAX_BYTES = 5 * 1024 * 1024

# (codec, human label) — displayed in the encoding selector, in save-order.
EDITOR_ENCODINGS = (
    ("utf-8", "UTF-8"),
    ("utf-8-sig", "UTF-8 с BOM"),
    ("cp1251", "Windows-1251"),
    ("cp866", "CP866 (DOS)"),
    ("koi8-r", "KOI8-R"),
    ("iso-8859-1", "ISO-8859-1 (Latin-1)"),
    ("utf-16", "UTF-16"),
)

_DETECT_ORDER = ("utf-8", "cp1251", "cp866", "koi8-r", "iso-8859-1")


def decode_bytes(data: bytes, codec: str) -> str:
    """Decode the buffer with the given codec, raising UnicodeDecodeError on failure."""
    return data.decode(codec)


def encode_text(text: str, codec: str) -> bytes:
    """Encode the text with the given codec, raising UnicodeEncodeError on failure."""
    return text.encode(codec)


def _decode_penalty(text: str) -> int:
    """Penalize control characters and replacement glyphs when guessing codecs."""
    penalized = 0
    for char in text:
        code = ord(char)
        if char == "\ufffd" or (code < 32 and char not in "\t\r\n\f\b"):
            penalized += 1
    return penalized


def detect_encoding(data: bytes) -> tuple[str, str]:
    """Pick the most plausible codec for a byte buffer and return (codec, text)."""
    if data.startswith(b"\xef\xbb\xbf"):
        return ("utf-8-sig", data.decode("utf-8-sig"))
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return ("utf-16", data.decode("utf-16"))
    best_codec: str | None = None
    best_penalty: int | None = None
    for codec in _DETECT_ORDER:
        try:
            text = data.decode(codec)
        except (UnicodeDecodeError, ValueError):
            continue
        penalty = _decode_penalty(text)
        if best_penalty is None or penalty < best_penalty:
            best_codec, best_penalty = codec, penalty
    if best_codec is None:
        return ("iso-8859-1", data.decode("iso-8859-1"))
    return (best_codec, data.decode(best_codec))


def _glyph_icon(glyph: str, size: int = 16) -> QIcon:
    """Build a small monochrome icon from a text glyph (no bundled assets)."""
    app = QApplication.instance()
    dpr = float(app.devicePixelRatio()) if app is not None else 1.0
    pixmap = QPixmap(round(size * dpr), round(size * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    font = QFont()
    font.setPixelSize(round(size * 0.9))
    painter.setFont(font)
    painter.setPen(QColor(30, 30, 30))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, glyph)
    painter.end()
    return QIcon(pixmap)


def _icon_button(glyph: str, tip: str, parent: Any = None) -> QToolButton:
    button = QToolButton(parent)
    button.setIcon(_glyph_icon(glyph))
    button.setAutoRaise(True)
    button.setToolTip(tip)
    button.setFixedSize(24, 24)
    return button


class FileEditorDialog(QDialog):
    """Non-modal text editor: encoding selector, search/replace and save."""

    load_requested = Signal()
    save_requested = Signal(bytes)

    def __init__(
        self,
        parent: Any = None,
        path: str = "",
        remote: bool = True,
    ) -> None:
        super().__init__(parent)
        self._raw: bytes | None = None
        self._locked = True
        self._replace_row_visible = False
        self.setWindowTitle("Редактор файла")
        self.resize(800, 580)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 4)

        toolbar = QToolBar("Правка", self)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        toolbar.setIconSize(QSize(16, 16))

        self._copy_action = QAction("Копировать", self)
        self._copy_action.setShortcut(QKeySequence.StandardKey.Copy)
        self._copy_action.triggered.connect(lambda: self._editor.copy())
        self._paste_action = QAction("Вставить", self)
        self._paste_action.setShortcut(QKeySequence.StandardKey.Paste)
        self._paste_action.triggered.connect(lambda: self._editor.paste())
        self._select_all_action = QAction("Выделить всё", self)
        self._select_all_action.setShortcut(QKeySequence.StandardKey.SelectAll)
        self._select_all_action.triggered.connect(lambda: self._editor.selectAll())
        self._find_action = QAction("Найти…", self)
        self._find_action.setShortcut(QKeySequence.StandardKey.Find)
        self._find_action.triggered.connect(lambda: self._show_find(False))
        self._replace_action = QAction("Заменить…", self)
        self._replace_action.setShortcut(QKeySequence.StandardKey.Replace)
        self._replace_action.triggered.connect(lambda: self._show_find(True))
        self._goto_action = QAction("Перейти к строке…", self)
        self._goto_action.setShortcut(QKeySequence("Ctrl+G"))
        self._goto_action.triggered.connect(self._go_to_line_dialog)
        self._save_action = QAction("Сохранить", self)
        self._save_action.setShortcut(QKeySequence.StandardKey.Save)
        self._save_action.triggered.connect(self._on_save_clicked)
        self._reload_action = QAction("Перезагрузить", self)
        self._reload_action.triggered.connect(self.request_load)
        self._close_action = QAction("Закрыть", self)
        self._close_action.triggered.connect(self.accept)
        for action, glyph, tip in (
            (self._copy_action, "⧉", "Копировать (Ctrl+C)"),
            (self._paste_action, "▤", "Вставить (Ctrl+V)"),
            (self._select_all_action, "▦", "Выделить всё (Ctrl+A)"),
            (self._find_action, "🔍", "Найти (Ctrl+F)"),
            (self._replace_action, "🔄", "Заменить (Ctrl+H)"),
            (self._goto_action, "↕", "Перейти к строке (Ctrl+G)"),
            (self._save_action, "💾", "Сохранить (Ctrl+S)"),
            (self._reload_action, "⟳", "Перезагрузить файл с диска"),
            (self._close_action, "✕", "Закрыть (Esc)"),
        ):
            action.setIcon(_glyph_icon(glyph))
            action.setToolTip(tip)
            self.addAction(action)
        for action in (
            self._copy_action,
            self._paste_action,
            self._select_all_action,
            self._find_action,
            self._replace_action,
            self._goto_action,
            self._save_action,
            self._reload_action,
            self._close_action,
        ):
            toolbar.addAction(action)
        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Кодировка:", toolbar))
        self._encoding = QComboBox(toolbar)
        for codec, label in EDITOR_ENCODINGS:
            self._encoding.addItem(label, codec)
        self._encoding.currentIndexChanged.connect(self._on_encoding_changed)
        self._encoding.setToolTip("Сменить кодировку файла")
        toolbar.addWidget(self._encoding)
        layout.addWidget(toolbar)

        location = QLabel(path or "(не указан)", self)
        location.setWordWrap(True)
        location.setStyleSheet("font-weight: 600;")
        location.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(location)

        self._editor = QPlainTextEdit(self)
        font = QFont("Consolas", 10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._editor.setFont(font)
        self._editor.document().setDefaultFont(font)
        self._editor.textChanged.connect(self._on_text_changed)
        self._editor.cursorPositionChanged.connect(self._update_position)
        layout.addWidget(self._editor, 1)

        layout.addWidget(self._build_find_bar())

        status_row = QHBoxLayout()
        self._pos_label = QLabel("", self)
        status_row.addWidget(self._pos_label)
        status_row.addStretch(1)
        self._status = QLabel("", self)
        self._status.setStyleSheet("color: #444;")
        status_row.addWidget(self._status)
        layout.addLayout(status_row)

        self._save_action.setEnabled(False)
        self._editor.setEnabled(False)
        self._set_status("Загрузка…")

# ── find/replace bar ────────────────────────────────────
    def _build_find_bar(self) -> QFrame:
        bar = QFrame(self)
        bar.setFrameShape(QFrame.Shape.StyledPanel)

        find_row = QHBoxLayout()
        find_row.setContentsMargins(4, 4, 4, 2)
        find_row.addWidget(QLabel("Найти:", bar))
        self._find_edit = QLineEdit(bar)
        self._find_edit.setPlaceholderText("текст для поиска…")
        self._find_edit.setMinimumWidth(240)
        self._find_edit.returnPressed.connect(lambda: self._find_next(forward=True))
        self._match_case = QCheckBox("Аа", bar)
        self._match_case.setToolTip("Учитывать регистр")
        self._prev_match_btn = _icon_button("◀", "Предыдущее совпадение (Shift+Enter)", bar)
        self._prev_match_btn.clicked.connect(lambda: self._find_next(forward=False))
        self._next_match_btn = _icon_button("▶", "Следующее совпадение (Enter)", bar)
        self._next_match_btn.clicked.connect(lambda: self._find_next(forward=True))
        self._match_count = QLabel("", bar)
        self._close_find_btn = _icon_button("✕", "Закрыть поиск", bar)
        self._close_find_btn.clicked.connect(self._hide_find)
        find_row.addWidget(self._find_edit, 1)
        find_row.addWidget(self._match_case)
        find_row.addWidget(self._prev_match_btn)
        find_row.addWidget(self._next_match_btn)
        find_row.addWidget(self._match_count)
        find_row.addWidget(self._close_find_btn)

        replace_row = QHBoxLayout()
        replace_row.setContentsMargins(4, 2, 4, 4)
        self._replace_label = QLabel("Заменить:", bar)
        self._replace_edit = QLineEdit(bar)
        self._replace_edit.setPlaceholderText("новый текст…")
        self._replace_edit.setMinimumWidth(240)
        self._replace_edit.returnPressed.connect(self._replace_next)
        self._replace_one = _icon_button("↻", "Заменить текущее совпадение", bar)
        self._replace_one.clicked.connect(self._replace_next)
        self._replace_all = _icon_button("⇝", "Заменить все совпадения", bar)
        self._replace_all.clicked.connect(self._replace_all_handler)
        replace_row.addWidget(self._replace_label)
        replace_row.addWidget(self._replace_edit, 1)
        replace_row.addWidget(self._replace_one)
        replace_row.addWidget(self._replace_all)
        replace_row.addStretch(1)

        bar_layout = QVBoxLayout(bar)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        bar_layout.addLayout(find_row)
        bar_layout.addLayout(replace_row)

        self._find_bar = bar
        self._update_replace_visibility()
        bar.hide()
        return bar

    def _show_find(self, with_replace: bool) -> None:
        self._find_bar.show()
        if self._editor.textCursor().hasSelection():
            self._find_edit.setText(self._editor.textCursor().selectedText())
            self._find_edit.selectAll()
        self._replace_row_visible = with_replace
        self._update_replace_visibility()
        self._find_edit.setFocus()
        self._find_edit.selectAll()

    def _hide_find(self) -> None:
        self._find_bar.hide()
        self._clear_highlights()
        self._editor.setFocus()

    def _update_replace_visibility(self) -> None:
        for widget in (self._replace_label, self._replace_edit, self._replace_one,
                       self._replace_all):
            widget.setVisible(self._replace_row_visible)
        if self._replace_row_visible:
            self._replace_edit.setFocus()

    def _find_flags(self) -> QTextDocument.FindFlags:
        if self._match_case.isChecked():
            return QTextDocument.FindFlag.FindCaseSensitively
        return QTextDocument.FindFlag(0)

    def _find_next(self, forward: bool) -> None:
        needle = self._find_edit.text()
        if not needle:
            self._set_status("Введите текст для поиска")
            return
        flags = self._find_flags()
        if not forward:
            flags |= QTextDocument.FindFlag.FindBackward
        self._editor.find(needle, flags)
        self._highlight_all(needle)

    def _find_match_count(self, needle: str) -> int:
        if not needle:
            return 0
        cursor = QTextCursor(self._editor.document())
        count = 0
        while True:
            cursor = self._editor.document().find(needle, cursor, self._find_flags())
            if cursor.isNull():
                break
            count += 1
        return count

    def _highlight_all(self, needle: str) -> None:
        selections = []
        if needle:
            cursor = QTextCursor(self._editor.document())
            while True:
                cursor = self._editor.document().find(needle, cursor, self._find_flags())
                if cursor.isNull():
                    break
                extra = QTextEdit.ExtraSelection()
                extra.cursor = QTextCursor(cursor)
                extra.format.setBackground(Qt.GlobalColor.yellow)
                selections.append(extra)
        self._editor.setExtraSelections(selections)
        self._match_count.setText(str(self._find_match_count(needle)) if needle else "")

    def _clear_highlights(self) -> None:
        self._editor.setExtraSelections([])
        self._match_count.setText("")

    def _replace_next(self) -> None:
        needle = self._find_edit.text()
        if not needle:
            return
        cursor = self._editor.textCursor()
        if cursor.hasSelection() and cursor.selectedText() == needle:
            cursor.insertText(self._replace_edit.text())
            self._editor.setTextCursor(cursor)
        self._find_next(forward=True)

    def _replace_all_handler(self) -> None:
        needle = self._find_edit.text()
        if not needle:
            self._set_status("Введите текст для замены")
            return
        count = 0
        cursor = QTextCursor(self._editor.document())
        while True:
            cursor = self._editor.document().find(needle, cursor, self._find_flags())
            if cursor.isNull():
                break
            cursor.insertText(self._replace_edit.text())
            count += 1
        self._clear_highlights()
        self._set_status(f"Заменено вхождений: {count}")

    def _go_to_line_dialog(self) -> None:
        if not self._editor.isEnabled():
            return
        total = self._editor.document().blockCount()
        number, ok = QInputDialog.getInt(
            self, "Перейти к строке", f"Номер строки (1–{total}):", 1, 1, max(1, total)
        )
        if ok:
            self._go_to_line(number)

    def _go_to_line(self, number: int) -> None:
        block = self._editor.document().findBlockByNumber(number - 1)
        if block.isValid():
            cursor = QTextCursor(block)
            self._editor.setTextCursor(cursor)
            self._editor.centerCursor()

    # ── public sync API (called from the executors' finished slot) ──
    def apply_load(self, raw: bytes | None, error: str | None) -> None:
        self._locked = False
        self._save_action.setEnabled(False)
        if error is not None:
            self._locked = True
            self._editor.setEnabled(False)
            self._set_status(f"Ошибка чтения: {error}")
            return
        assert raw is not None
        self._raw = raw
        codec, text = detect_encoding(raw)
        index = self._encoding.findData(codec)
        if index >= 0:
            self._encoding.blockSignals(True)
            self._encoding.setCurrentIndex(index)
            self._encoding.blockSignals(False)
        self._editor.setPlainText(text)
        self._editor.setEnabled(True)
        self._set_status(
            f"Кодировка: {codec} • {self._editor.document().blockCount():,} строк • "
            f"{len(raw):,} байт"
        )

    def show_save_result(self, error: str | None) -> None:
        self._locked = False
        self._save_action.setEnabled(True)
        if error is not None:
            self._set_status(f"Ошибка сохранения: {error}")
            return
        if self._raw is not None:
            self._raw = encode_text(self._editor.toPlainText(), self._encoding.currentData())
        self._set_status("Сохранено")

# ── internal ────────────────────────────────────────────
    def request_load(self) -> None:
        self._locked = True
        self._editor.setEnabled(False)
        self._set_status("Загрузка…")
        self.load_requested.emit()

    def _on_encoding_changed(self) -> None:
        if self._raw is None or self._locked:
            return
        try:
            text = decode_bytes(self._raw, self._encoding.currentData())
        except (UnicodeDecodeError, ValueError) as exc:
            self._set_status(f"Данные не читаются в этой кодировке: {exc}")
            return
        self._editor.setPlainText(text)
        self._set_status(f"Кодировка: {self._encoding.currentData()}")

    def _on_save_clicked(self) -> None:
        if self._locked:
            return
        codec = self._encoding.currentData()
        try:
            data = encode_text(self._editor.toPlainText(), codec)
        except (UnicodeEncodeError, ValueError) as exc:
            self._set_status(f"Текст не представим в {codec}: {exc}")
            return
        self._locked = True
        self._save_action.setEnabled(False)
        self._set_status("Сохранение…")
        self.save_requested.emit(data)

    def _on_text_changed(self) -> None:
        if not self._locked:
            self._save_action.setEnabled(True)

    def _update_position(self) -> None:
        cursor = self._editor.textCursor()
        self._pos_label.setText(
            f"Строка {cursor.blockNumber() + 1}, колонка {cursor.columnNumber() + 1}"
        )

    def _set_status(self, text: str) -> None:
        self._status.setText(text)


__all__ = [
    "EDITOR_ENCODINGS",
    "EDITOR_MAX_BYTES",
    "FileEditorDialog",
    "decode_bytes",
    "detect_encoding",
    "encode_text",
]
