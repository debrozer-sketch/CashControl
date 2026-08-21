"""
Virtual keyboard widget for CashControl.

Provides:
  - VirtualKeyboardWindow  — read-only keyboard for operators (sends xdotool via SSH)
  - KeyboardEditorWindow   — editor for configuring button labels and hotkeys
  - _KeyButton             — custom button with auto-scaling text
  - _ButtonSettingsDialog  — dialog for editing a single button

Layout files are stored in data/keyboard_layouts/<name>.json.
Three fixed layouts: csi_hengyu_s84e, vioteh_kb66, hengyu_s78d.

Layout→file mapping uses normalized string matching:
  keyboard_model (from XML) is normalized (lowercase, alphanumeric only)
  and compared against layout filenames.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QSize, Qt, QTimer
from PySide6.QtGui import QFont, QFontMetrics, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QMainWindow,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    FluentIcon,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
)

from cashcontrol.gui.notification_manager import get_notification_manager
from cashcontrol.infrastructure.audit_logger import get_logger
from cashcontrol.infrastructure.path_resolver import get_app_root

if TYPE_CHECKING:
    from cashcontrol.core.session import CashSession

logger = get_logger()

# ── Constants ──────────────────────────────────────────────────────────────────

# Fixed layout definitions: file_stem → (rows, cols, display_name)
LAYOUTS: dict[str, tuple[int, int, str]] = {
    "csi_hengyu_s84e": (7, 8, "CSI Hengyu S84E"),
    "vioteh_kb66":     (6, 11, "Vioteh KB66"),
    "hengyu_s78d":     (7, 8, "Hengyu S78D"),
}

# Aliases: normalized fragments of localizedName → layout stem
# Used when filename-based matching fails
_LAYOUT_ALIASES: dict[str, str] = {
    "csikeys84":  "csi_hengyu_s84e",
    "csikeys84e": "csi_hengyu_s84e",
    "s84e":       "csi_hengyu_s84e",
    "s84":        "csi_hengyu_s84e",
    "hengyus84":  "csi_hengyu_s84e",
    "kb66":       "vioteh_kb66",
    "vioteh":     "vioteh_kb66",
    "s78d":       "hengyu_s78d",
    "s78":        "hengyu_s78d",
}

# Keymap: our internal names → xdotool key names
XDOTOOL_KEYMAP: dict[str, str] = {
    "Space": "space", "Backspace": "BackSpace", "Tab": "Tab",
    "Enter": "Return", "Esc": "Escape", "Delete": "Delete",
    "Insert": "Insert", "Home": "Home", "End": "End",
    "PageUp": "Page_Up", "PageDown": "Page_Down",
    "Up": "Up", "Down": "Down", "Left": "Left", "Right": "Right",
    "Num+": "KP_Add", "Num-": "KP_Subtract",
    "Num*": "KP_Multiply", "Num/": "KP_Divide", "NumEnter": "KP_Enter",
    "F1": "F1", "F2": "F2", "F3": "F3", "F4": "F4",
    "F5": "F5", "F6": "F6", "F7": "F7", "F8": "F8",
    "F9": "F9", "F10": "F10", "F11": "F11", "F12": "F12",
    "[": "bracketleft", "]": "bracketright",
    "{": "braceleft", "}": "braceright",
    "=": "equal", "+": "plus", "-": "minus", "_": "underscore",
    ";": "semicolon", ":": "colon", "'": "apostrophe",
    '"': "quotedbl", "`": "grave", "~": "asciitilde",
    "\\": "backslash", "|": "bar", ",": "comma", ".": "period",
    "/": "slash", "<": "less", ">": "greater", "?": "question",
    "!": "exclam", "@": "at", "#": "numbersign", "$": "dollar",
    "%": "percent", "^": "asciicircum", "&": "ampersand",
    "*": "asterisk", "(": "parenleft", ")": "parenright",
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def get_layouts_dir() -> Path:
    """
    Layouts are stored under cashcontrol/gui/widgets/keyboard_layouts/ in prod,
    matching the structure build.bat creates (external files under cashcontrol/).
    In dev they sit next to virtual_keyboard.py in src/cashcontrol/gui/widgets/.
    """
    from cashcontrol.infrastructure.path_resolver import _is_production
    if _is_production():
        d = get_app_root() / "cashcontrol" / "gui" / "widgets" / "keyboard_layouts"
    else:
        d = Path(__file__).parent / "keyboard_layouts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def find_layout_for_keyboard(keyboard_model: str) -> str | None:
    """
    Match keyboard_model string (from XML localizedName) to a layout file stem.
    Uses normalized alphanumeric comparison + alias table.
    Returns layout stem (e.g. 'csi_hengyu_s84e') or None.
    """
    if not keyboard_model:
        return None
    normalized = re.sub(r"[^a-z0-9]", "", keyboard_model.lower())

    # 1. Direct alias match
    for fragment, stem in _LAYOUT_ALIASES.items():
        if fragment in normalized:
            logger.debug(f"[Keyboard] alias match '{keyboard_model}' → '{stem}'")
            return stem

    # 2. Filename-based fuzzy match
    for stem in LAYOUTS:
        clean = re.sub(r"[^a-z0-9]", "", stem.lower())
        if clean in normalized or normalized in clean:
            logger.debug(f"[Keyboard] fuzzy match '{keyboard_model}' → '{stem}'")
            return stem

    logger.warning(f"[Keyboard] no layout match for '{keyboard_model}'")
    return None


def load_layout(stem: str) -> list[dict]:
    """Load layout from JSON. Returns list of button dicts."""
    path = get_layouts_dir() / f"{stem}.json"
    if not path.exists():
        logger.warning(f"[Keyboard] layout file not found: {path}")
        rows, cols, _ = LAYOUTS.get(stem, (7, 8, ""))
        return [{"name": f"btn_{r}_{c}", "text": "", "action": ""}
                for r in range(rows) for c in range(cols)]
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"[Keyboard] failed to load layout {stem}: {e}")
        rows, cols, _ = LAYOUTS.get(stem, (7, 8, ""))
        return [{"name": f"btn_{r}_{c}", "text": "", "action": ""}
                for r in range(rows) for c in range(cols)]


def save_layout(stem: str, buttons: list[dict]) -> bool:
    """Save layout to JSON. Returns True on success."""
    path = get_layouts_dir() / f"{stem}.json"
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(buttons, f, ensure_ascii=False, indent=2)
        logger.info(f"[Keyboard] layout saved: {path}")
        return True
    except Exception as e:
        logger.error(f"[Keyboard] failed to save layout {stem}: {e}")
        return False


def build_xdotool_cmd(key_seq: str) -> str | None:
    """Convert internal key sequence string to xdotool command."""
    if not key_seq.strip():
        return None
    parts = [p.strip() for p in key_seq.split("+")]
    modifiers = []
    main_key = None
    for part in parts:
        if part == "Ctrl":
            modifiers.append("Control")
        elif part == "Alt":
            modifiers.append("Alt")
        elif part == "Shift":
            modifiers.append("Shift")
        elif part == "Win":
            modifiers.append("Super")
        else:
            main_key = XDOTOOL_KEYMAP.get(part, part.lower())
    if main_key is None:
        return None
    full_key = "+".join([*modifiers, main_key])
    return f"DISPLAY=:0 xdotool key --clearmodifiers {full_key}"


# ── Custom button ──────────────────────────────────────────────────────────────

class _KeyButton(PushButton):
    """
    Keyboard button with auto-scaling text and stored action_data.
    Uses qfluentwidgets PushButton as base for consistent styling.
    """

    BTN_SIZE = 62

    def __init__(self, text: str = "", action: str = "", parent: QWidget | None = None):
        super().__init__(parent=parent)
        self._label = text
        self.action_data = action
        self.setFixedSize(self.BTN_SIZE, self.BTN_SIZE)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        # Hide default text — we draw it ourselves
        self.setText("")

    def get_label(self) -> str:
        return self._label

    def set_label(self, text: str) -> None:
        self._label = text
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        super().paintEvent(event)
        if not self._label:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.rect().adjusted(4, 4, -4, -4)
        font = QFont(self.font())
        max_size = 22

        for size in range(max_size, 4, -1):
            font.setPointSize(size)
            fm = QFontMetrics(font)
            br = fm.boundingRect(
                rect,
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                self._label,
            )
            if br.height() <= rect.height() and br.width() <= rect.width():
                break

        painter.setFont(font)
        # Use theme-appropriate color
        painter.setPen(self.palette().buttonText().color())
        painter.drawText(
            rect,
            Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
            self._label,
        )

    def sizeHint(self) -> QSize:
        return QSize(self.BTN_SIZE, self.BTN_SIZE)


# ── Button settings dialog ─────────────────────────────────────────────────────

class _ButtonSettingsDialog(QDialog):
    """Dialog for editing a single keyboard button: label + hotkey."""

    def __init__(self, current_text: str = "", current_action: str = "",
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Настройка кнопки")
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.WindowCloseButtonHint
        )
        self.resize(420, 280)
        self._init_ui(current_text, current_action)

    def _init_ui(self, text: str, action: str) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Label field
        layout.addWidget(BodyLabel("Текст на кнопке:"))
        self._text_edit = QTextEdit()
        self._text_edit.setPlainText(text)
        self._text_edit.setMaximumHeight(56)
        self._text_edit.setPlaceholderText("Например: Сторно, F5, Итог…")
        layout.addWidget(self._text_edit)

        # Hotkey field
        layout.addWidget(BodyLabel("Горячая клавиша (кликни и нажми):"))
        self._hotkey_edit = QTextEdit()
        self._hotkey_edit.setReadOnly(True)
        self._hotkey_edit.setMaximumHeight(42)
        self._hotkey_edit.setPlainText(action)
        self._hotkey_edit.setPlaceholderText("Кликните сюда и нажмите клавишу…")
        self._hotkey_edit.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._hotkey_edit.installEventFilter(self)
        self._hotkey_edit.focusInEvent = self._on_focus_in  # type: ignore
        layout.addWidget(self._hotkey_edit)

        layout.addWidget(BodyLabel(
            "Правый клик на кнопке в клавиатуре — очистить кнопку",
        ))

        # Buttons
        layout.addStretch()
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok |
            QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)
        self._ok_btn = btns.button(QDialogButtonBox.StandardButton.Ok)

        self._stop_timer = QTimer(self)
        self._stop_timer.setSingleShot(True)
        self._stop_timer.timeout.connect(self._finish_recording)

    def _on_focus_in(self, event) -> None:
        from cashcontrol.gui.theme_helper import color as _tc
        self._hotkey_edit.setStyleSheet(
            f"border: 2px solid {_tc('accent')}; background: rgba(0,120,212,0.08);"
        )
        QTextEdit.focusInEvent(self._hotkey_edit, event)

    def _finish_recording(self) -> None:
        self._hotkey_edit.setStyleSheet("")
        self._hotkey_edit.clearFocus()
        self._ok_btn.setFocus()

    def eventFilter(self, source, event) -> bool:  # type: ignore[override]
        if source is self._hotkey_edit and event.type() in (
            QEvent.Type.KeyPress, QEvent.Type.ShortcutOverride
        ):
            self._process_key(event)
            return True
        return super().eventFilter(source, event)

    def _process_key(self, event) -> None:
        mods = event.modifiers()
        key = event.key()
        parts = []

        if mods & Qt.KeyboardModifier.ControlModifier:
            parts.append("Ctrl")
        if mods & Qt.KeyboardModifier.AltModifier:
            parts.append("Alt")
        if mods & Qt.KeyboardModifier.ShiftModifier:
            parts.append("Shift")
        if mods & Qt.KeyboardModifier.MetaModifier:
            parts.append("Win")

        key_seq = QKeySequence(key).toString()

        # Numpad by scan code
        sc = event.nativeScanCode()
        if sc == 0x4E:
            key_seq = "Num+"
        elif sc == 0x4A:
            key_seq = "Num-"
        elif sc == 0x37:
            key_seq = "Num*"
        elif sc == 0x35:
            key_seq = "Num/"

        # Aliases
        if key_seq == "Return":
            key_seq = "Enter"

        # Special keys not covered by QKeySequence
        _specials = {
            Qt.Key.Key_Space: "Space",
            Qt.Key.Key_Backspace: "Backspace",
            Qt.Key.Key_Tab: "Tab",
            Qt.Key.Key_Escape: "Esc",
            Qt.Key.Key_CapsLock: "CapsLock",
            Qt.Key.Key_Home: "Home",
            Qt.Key.Key_End: "End",
            Qt.Key.Key_PageUp: "PageUp",
            Qt.Key.Key_PageDown: "PageDown",
            Qt.Key.Key_Insert: "Insert",
            Qt.Key.Key_Delete: "Delete",
            Qt.Key.Key_Up: "Up",
            Qt.Key.Key_Down: "Down",
            Qt.Key.Key_Left: "Left",
            Qt.Key.Key_Right: "Right",
        }
        if key in _specials:
            key_seq = _specials[key]

        if key_seq:
            parts.append(key_seq)
            self._hotkey_edit.setPlainText("+".join(parts))
            self._stop_timer.start(500)
        else:
            self._stop_timer.start(500)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if not self._hotkey_edit.hasFocus():
            super().keyPressEvent(event)

    def get_data(self) -> tuple[str, str]:
        return (
            self._text_edit.toPlainText().strip(),
            self._hotkey_edit.toPlainText().strip(),
        )


# ── Shared grid builder ────────────────────────────────────────────────────────

def _build_grid(
    parent: QWidget,
    layout_stem: str,
    button_data: list[dict],
    edit_mode: bool,
    click_callback,  # callable(btn: _KeyButton, action: str, text: str)
) -> tuple[QGridLayout, list[_KeyButton]]:
    """Build button grid. Returns (grid_layout, buttons_list)."""
    rows, cols, _ = LAYOUTS.get(layout_stem, (7, 8, ""))
    grid = QGridLayout()
    grid.setHorizontalSpacing(6)
    grid.setVerticalSpacing(6)
    grid.setContentsMargins(10, 10, 10, 10)

    buttons: list[_KeyButton] = []
    for idx in range(rows * cols):
        d = button_data[idx] if idx < len(button_data) else {}
        text = d.get("text", "")
        action = d.get("action", "")
        btn = _KeyButton(text=text, action=action, parent=parent)

        if edit_mode:
            btn.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
            btn.mouseDoubleClickEvent = (  # type: ignore[method-assign]
                lambda e, b=btn: click_callback(b)
            )
            btn.mousePressEvent = (  # type: ignore[method-assign]
                lambda e, b=btn: _editor_press(e, b, click_callback)
            )
        else:
            btn.clicked.connect(
                lambda _checked=False, b=btn, a=action, t=text:
                click_callback(b, a, t)
            )

        grid.addWidget(btn, idx // cols, idx % cols)
        buttons.append(btn)

    return grid, buttons


def _editor_press(event, btn: _KeyButton, _callback) -> None:
    """Handle mouse press in edit mode: RMB clears, LMB opens settings."""
    if event.button() == Qt.MouseButton.RightButton:
        btn.set_label("")
        btn.action_data = ""
    else:
        PushButton.mousePressEvent(btn, event)


# ── Keyboard editor window ─────────────────────────────────────────────────────

class KeyboardEditorWindow(QMainWindow):
    """
    Editor for configuring keyboard layouts.
    Double-click a button to edit its label and hotkey.
    Right-click to clear a button.
    """

    def __init__(self, layout_stem: str | None = None,
                 parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Конструктор клавиатуры")
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowCloseButtonHint |
            Qt.WindowType.WindowMinimizeButtonHint
        )
        self._layout_stem = layout_stem or next(iter(LAYOUTS))
        self._buttons: list[_KeyButton] = []
        self._init_ui()
        self._load()

    def _init_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top bar ──
        top = QFrame()
        top.setObjectName("KbEditorTopBar")
        top.setFixedHeight(48)
        top.setStyleSheet(
            "#KbEditorTopBar { border-bottom: 1px solid palette(mid); }"
        )
        top_row = QHBoxLayout(top)
        top_row.setContentsMargins(12, 0, 12, 0)
        top_row.setSpacing(8)

        top_row.addWidget(StrongBodyLabel("Конструктор клавиатуры"))
        top_row.addStretch()

        # Layout switcher buttons
        for stem, (_, _, name) in LAYOUTS.items():
            btn = PushButton(name)
            btn.setCheckable(True)
            btn.setChecked(stem == self._layout_stem)
            btn.clicked.connect(lambda _checked, s=stem: self._switch_layout(s))
            btn.setObjectName(f"layout_btn_{stem}")
            top_row.addWidget(btn)
            setattr(self, f"_btn_{stem}", btn)

        top_row.addSpacing(16)

        save_btn = PrimaryPushButton(FluentIcon.SAVE, "Сохранить")
        save_btn.clicked.connect(self._save)
        top_row.addWidget(save_btn)

        root.addWidget(top)

        # ── Hint ──
        hint = BodyLabel(
            "  Двойной клик — настроить кнопку   •   Правый клик — очистить кнопку"
        )
        hint.setStyleSheet("color: palette(mid); padding: 4px 12px;")
        root.addWidget(hint)

        # ── Grid area ──
        self._grid_container = QWidget()
        self._grid_vbox = QVBoxLayout(self._grid_container)
        self._grid_vbox.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._grid_container, stretch=1)

        self._update_window_size()

    def _update_window_size(self) -> None:
        rows, cols, _ = LAYOUTS.get(self._layout_stem, (7, 8, ""))
        btn = _KeyButton.BTN_SIZE
        sp = 6
        w = cols * btn + (cols - 1) * sp + 20 + 24
        h = rows * btn + (rows - 1) * sp + 20 + 48 + 28 + 48
        self.resize(w, h)

    def _load(self) -> None:
        # Clear old grid
        for i in reversed(range(self._grid_vbox.count())):
            item = self._grid_vbox.takeAt(i)
            if w := item.widget():
                w.deleteLater()

        data = load_layout(self._layout_stem)
        grid, self._buttons = _build_grid(
            self._grid_container,
            self._layout_stem,
            data,
            edit_mode=True,
            click_callback=self._open_settings,
        )

        wrapper = QWidget()
        wl = QVBoxLayout(wrapper)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addLayout(grid)
        wl.addStretch()
        self._grid_vbox.addWidget(wrapper)

    def _switch_layout(self, stem: str) -> None:
        if stem == self._layout_stem:
            return
        self._layout_stem = stem
        # Update toggle states
        for s in LAYOUTS:
            btn = getattr(self, f"_btn_{s}", None)
            if btn:
                btn.setChecked(s == stem)
        self._update_window_size()
        self._load()

    def _open_settings(self, btn: _KeyButton) -> None:
        dlg = _ButtonSettingsDialog(
            current_text=btn.get_label(),
            current_action=btn.action_data,
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            text, action = dlg.get_data()
            btn.set_label(text)
            btn.action_data = action

    def _save(self) -> None:
        data = [
            {
                "name": btn.objectName() or f"btn_{i}",
                "text": btn.get_label(),
                "action": btn.action_data,
            }
            for i, btn in enumerate(self._buttons)
        ]
        if save_layout(self._layout_stem, data):
            get_notification_manager().notify("Раскладка сохранена", level="success")
        else:
            QMessageBox.critical(self, "Ошибка", "Не удалось сохранить раскладку.")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._save()
        super().closeEvent(event)


# ── Operator keyboard window ───────────────────────────────────────────────────

class VirtualKeyboardWindow(QMainWindow):
    """
    Read-only keyboard for operator use.
    Clicking a button sends the assigned hotkey via xdotool over SSH.
    """

    def __init__(self, session: CashSession, layout_stem: str,
                 parent: QWidget | None = None):
        super().__init__(parent)
        _, _, display_name = LAYOUTS.get(layout_stem, (7, 8, layout_stem))
        self.setWindowTitle(f"Клавиатура — {display_name}")
        self.setWindowFlags(
            Qt.WindowType.Window |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.WindowCloseButtonHint
        )
        self._session = session
        self._layout_stem = layout_stem
        self._xdotool_ready = False
        self._bg_tasks: set[asyncio.Task] = set()
        self._init_ui()
        self._load()
        self._ensure_xdotool()

    def _init_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top bar ──
        top = QFrame()
        top.setObjectName("KbTopBar")
        top.setFixedHeight(36)
        top.setStyleSheet(
            "#KbTopBar { border-bottom: 1px solid palette(mid); }"
        )
        top_row = QHBoxLayout(top)
        top_row.setContentsMargins(12, 0, 12, 0)

        _, _, name = LAYOUTS.get(self._layout_stem, (7, 8, self._layout_stem))
        lbl = StrongBodyLabel(f"Шаблон: {name}")
        top_row.addWidget(lbl)
        top_row.addStretch()

        self._status_lbl = BodyLabel("Инициализация…")
        self._status_lbl.setStyleSheet("color: palette(mid);")
        top_row.addWidget(self._status_lbl)

        root.addWidget(top)

        # ── Grid area ──
        self._grid_container = QWidget()
        self._grid_vbox = QVBoxLayout(self._grid_container)
        self._grid_vbox.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._grid_container, stretch=1)

        rows, cols, _ = LAYOUTS.get(self._layout_stem, (7, 8, ""))
        btn = _KeyButton.BTN_SIZE
        sp = 6
        w = cols * btn + (cols - 1) * sp + 20 + 24
        h = rows * btn + (rows - 1) * sp + 20 + 36 + 48
        self.resize(w, h)

    def _load(self) -> None:
        for i in reversed(range(self._grid_vbox.count())):
            item = self._grid_vbox.takeAt(i)
            if w := item.widget():
                w.deleteLater()

        data = load_layout(self._layout_stem)
        grid, self._buttons = _build_grid(
            self._grid_container,
            self._layout_stem,
            data,
            edit_mode=False,
            click_callback=self._on_button_click,
        )
        wrapper = QWidget()
        wl = QVBoxLayout(wrapper)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.addLayout(grid)
        wl.addStretch()
        self._grid_vbox.addWidget(wrapper)

    def _set_status(self, text: str) -> None:
        self._status_lbl.setText(text)

    def _bg(self, coro) -> asyncio.Task:
        task = asyncio.ensure_future(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task

    def _ensure_xdotool(self) -> None:
        """Install xdotool on the cash register if not present (async)."""
        async def _check():
            try:
                result = await self._session.ssh.execute(
                    "which xdotool > /dev/null 2>&1 && echo OK || "
                    "tce-load -i xdotool.tcz 2>/dev/null && echo OK || echo FAIL",
                    timeout=15,
                )
                if "OK" in result.stdout:
                    self._xdotool_ready = True
                    self._set_status("Готово")
                else:
                    self._set_status("xdotool недоступен")
                    logger.warning(
                        f"[Keyboard] xdotool not available on {self._session.host}"
                    )
            except Exception as e:
                self._set_status("Ошибка инициализации")
                logger.error(f"[Keyboard] xdotool check failed: {e}")

        self._bg(_check())

    def _on_button_click(self, btn: _KeyButton, action: str, text: str) -> None:
        if not action.strip():
            return
        if not self._xdotool_ready:
            self._set_status("xdotool не готов")
            return

        cmd = build_xdotool_cmd(action)
        if not cmd:
            logger.warning(f"[Keyboard] cannot build xdotool cmd for: {action}")
            return

        async def _send():
            try:
                result = await self._session.ssh.execute(cmd, timeout=5)
                if result.success:
                    logger.debug(f"[Keyboard] sent: {cmd}")
                else:
                    logger.warning(f"[Keyboard] xdotool error: {result.stderr}")
                    self._set_status(f"Ошибка: {result.stderr[:40]}")
            except Exception as e:
                logger.error(f"[Keyboard] send failed: {e}")
                self._set_status("Ошибка отправки")

        self._bg(_send())

    def closeEvent(self, event) -> None:  # type: ignore[override]
        for task in list(self._bg_tasks):
            task.cancel()
        super().closeEvent(event)