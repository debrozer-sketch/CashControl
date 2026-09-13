"""Qt-виджет терминала: рендер pyte-экранов, ввод, мышь, выделение, прокрутка."""

from __future__ import annotations

import logging
import re
from typing import Optional

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (
    QClipboard,
    QColor,
    QFont,
    QFontDatabase,
    QFontMetrics,
    QGuiApplication,
    QKeyEvent,
    QKeySequence,
    QPainter,
    QPaintEvent,
    QActionGroup,
    QPalette,
    QPen,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import QApplication, QWidget

from terminal.emulator import MouseEvent, TerminalEmulator, color_to_hex

_LOG = logging.getLogger("ssh_term.ui.terminal_widget")

_KEYS_PER_SECOND = 30  # частота перерисовки при потоке данных

_URL_RE = re.compile(r"https?://[^\s\x00]+")

_KEYMAP_BASE: dict[str, str] = {
    "up": "\x1b[A", "down": "\x1b[B", "right": "\x1b[C", "left": "\x1b[D",
    "home": "\x1b[H", "end": "\x1b[F", "insert": "\x1b[2~", "delete": "\x1b[3~",
    "pgup": "\x1b[5~", "pgdown": "\x1b[6~",
    "f1": "\x1bOP", "f2": "\x1bOQ", "f3": "\x1bOR", "f4": "\x1bOS",
    "f5": "\x1b[15~", "f6": "\x1b[17~", "f7": "\x1b[18~", "f8": "\x1b[19~",
    "f9": "\x1b[20~", "f10": "\x1b[21~", "f11": "\x1b[23~", "f12": "\x1b[24~",
}
_KEYMAP_APP_CURSOR: dict[str, str] = {
    "up": "\x1bOA", "down": "\x1bOB", "right": "\x1bOC", "left": "\x1bOD",
    "home": "\x1bOH", "end": "\x1bOF",
}


class TerminalColors:
    """Токены цветов терминала (аналог _tc из CashControl — для лёгкого переноса)."""

    def __init__(self) -> None:
        self.bg = QColor("#1e1e2e")
        self.fg = QColor("#cdd6f4")
        self.cursor_color = QColor("#f5e0dc")
        self.cursor_text = QColor("#1e1e2e")
        self.selection_bg = QColor("#45475a")
        self.selection_fg = QColor("#f5e0dc")
        self.base16: list[QColor] = [QColor("#" + h) for h in (
            "000000", "800000", "008000", "808000", "000080", "800080", "008080", "c0c0c0",
            "808080", "ff0000", "00ff00", "ffff00", "0000ff", "ff00ff", "00ffff", "ffffff",
        )]
        self.find_highlight = QColor("#f9e2af")


class TerminalWidget(QWidget):
    """Один терминал: эмулятор + рендер + ввод.

    Включает скроллбар справа (scrollback), как в PuTTY.

    Сигналы:
        dataToWrite(str)   — ввод/вставка, готовая к отправке в PTY
        sizeChanged(rows, cols) — изменился размер сетки
        titleChanged(str)  — OSC-заголовок
        closed(int)        — процесс завершился (exit status)
        bellRung()         — BEL
        cursorModeChanged(str) — режим стрелок изменён
    """

    dataToWrite = Signal(str)
    sizeChanged = Signal(int, int)
    titleChanged = Signal(str)
    closed = Signal(int)
    bellRung = Signal()
    cursorModeChanged = Signal(str)  # "auto" | "normal" | "app"

    def __init__(self, parent: Optional[QWidget] = None, emulator: Optional[TerminalEmulator] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

        # эмулятор можно передать снаружи (владелец — сессия); иначе создаём свой
        if emulator is not None:
            self.emulator = emulator
            self._own_emulator = False
            # подключаем колбэки виджета к чужому эмулятору
            emulator._on_title = self._on_title  # noqa: SLF001
            emulator._on_bell = self._on_bell  # noqa: SLF001
            emulator._on_write_process = self._on_host_request  # noqa: SLF001
        else:
            self.emulator = TerminalEmulator(
                cols=80,
                rows=24,
                on_title=self._on_title,
                on_bell=self._on_bell,
                on_write_process=self._on_host_request,
            )
            self._own_emulator = True
        self.colors = TerminalColors()
        self._setup_font()

        # выделение
        self._selection_active = False
        self._selection_start: Optional[tuple[int, int]] = None  # (глобальная строка, колка)
        self._selection_end: Optional[tuple[int, int]] = None
        self._pending_selection: Optional[tuple[int, int]] = None  # правый клик — позиция

        # мышь
        self._mouse_button_down: Optional[Qt.MouseButton] = None
        self._mouse_last_cell: Optional[tuple[int, int]] = None

        # перерисовка пачками: 30 fps, только если были данные (dirty).
        # _delayed_repaint сам снимает флаг, дублируя логику MainWindow._poll_sessions —
        # между ними остаётся один репаинт в 33 мс, а не два.
        self._repaint_timer = QTimer(self)
        self._repaint_timer.setSingleShot(True)
        self._repaint_timer.timeout.connect(self._delayed_repaint)
        self._blink_timer = QTimer(self)
        self._blink_timer.setInterval(500)
        self._blink_timer.timeout.connect(self._toggle_blink)
        self._blink_timer.start()
        self._cursor_blink_visible = True

        # URL-детект (упрощённый)
        self._url_at_cursor: Optional[str] = None

        # поведение (настраивается снаружи)
        self.copy_on_select = True
        # режим стрелок: None=авто (по DECCKM), "normal"=ESC[A, "app"=ESCOA
        self.forced_cursor_mode: Optional[str] = None
        # лог ввода для диагностики (Ctrl+Alt+L toggle)
        self.input_log_enabled = False
        self._input_log: list[str] = []
        # скроллбар
        self._scrollbar_drag_active = False
        # сниппеты: колбэки от главного окна (None = попап не показывается)
        self.snippet_provider = None  # (query) -> list[Snippet]
        self.snippet_inserter = None  # (snippet) -> None
        # сниппет-попап (создаётся лениво при первом вводе)
        self._snippet_popup = None
        # отслеживание введённого слова для фильтра
        self._typed_word = ""
        # производительность: рисуем только если были данные (dirty)
        self._dirty = True

        self.resize(self._cols_px(), self._rows_px())

    def _ensure_snippet_popup(self) -> None:
        if self._snippet_popup is None and self.snippet_provider is not None:
            from ui.snippet_popup import SnippetPopup

            popup = SnippetPopup()
            popup.activated.connect(self._insert_snippet_inline)
            self._snippet_popup = popup

    def _update_snippet_popup(self, text: str, key: int) -> None:
        """Показать/обновить попап по текущему вводу в командной строке."""
        if self.snippet_provider is None:
            return
        self._ensure_snippet_popup()

        # Backspace: убрать последний символ из накопленного слова
        if key == Qt.Key.Key_Backspace:
            self._typed_word = self._typed_word[:-1]
        elif text and len(text) == 1 and text.isprintable() and not (
            key in (Qt.Key.Key_Tab, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Escape)
        ):
            # одиночный печатаемый символ: дополняем слово.
            # Пробел = конец слова (команда ушла — сброс, кроме первого слова
            # строки, где фильтр по подстроке продолжаем)
            if text == " ":
                self._typed_word = ""
            else:
                self._typed_word += text
        else:
            pass  # служебные клавиши слово не меняют

        matches = self.snippet_provider(self._typed_word) if self._typed_word else []
        popup = self._snippet_popup
        if popup is None:
            return
        popup.update_items(matches)
        if popup.is_active():
            self._position_snippet_popup()

    def _position_snippet_popup(self) -> None:
        popup = self._snippet_popup
        if popup is None:
            return
        emu = self.emulator
        cx, cy = emu.cursor_xy()
        px = min(cx * self._cell_width, max(0, self.width() - popup.width()))
        py = min((cy + 1) * self._cell_height, max(0, self.height() - popup.height()))
        popup.move(self.mapToGlobal(QPoint(px, py)))

    def _insert_snippet_inline(self, snippet) -> None:
        """Вставить сниппет в текущую командную строку (Termius-flow).

        Введённая часть слова уже ушла в PTY посимвольно — стираем её
        DEL-ами, затем вставляем команду сниппета (без/с Enter).
        """
        n = len(self._typed_word)
        self._typed_word = ""
        if n:
            self.dataToWrite.emit("\x7f" * n)
        # вставляем команду (bracketed paste если хост включил)
        self.dataToWrite.emit(self.emulator.wrap_paste(snippet.command))
        if snippet.send_with_enter:
            self.dataToWrite.emit("\r")

    # ==================== ШРИФТ / ГЕОМЕТРИЯ ====================

    def _setup_font(self) -> None:
        font = QFont()
        family = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()
        font.setFamily(family)
        font.setPointSize(10)
        font.setStyleHint(QFont.StyleHint.Monospace)
        self._font = font
        self._apply_font()

    def _apply_font(self) -> None:
        fm = QFontMetrics(self._font)
        self._cell_width = fm.horizontalAdvance("M")
        self._cell_height = fm.height()
        self._font_ascent = fm.ascent()
        self.updateGeometry()

    def set_font(self, font: QFont) -> None:
        self._font = font
        self._apply_font()
        self._recompute_grid()
        self.update()

    def set_font_size(self, point_size: float) -> None:
        font = QFont(self._font)
        font.setPointSizeF(point_size)
        self.set_font(font)

    def _cols_px(self, cols: Optional[int] = None) -> int:
        return self._cell_width * (cols or self.emulator.cols)

    def _rows_px(self, rows: Optional[int] = None) -> int:
        return self._cell_height * (rows or self.emulator.rows)

    def _recompute_grid(self) -> None:
        """Пересчитать rows/cols из текущего размера виджета (минус скроллбар)."""
        usable_w = max(2, (self.width() - self._SCROLLBAR_W) // self._cell_width)
        cols = max(2, usable_w)
        rows = max(2, self.height() // self._cell_height)
        if (cols, rows) != (self.emulator.cols, self.emulator.rows):
            self.emulator.resize(rows, cols)
            self.sizeChanged.emit(rows, cols)

    # ==================== ПОДКЛЮЧЕНИЕ ПОТОКОВ ====================

    def feed_data(self, text: str) -> None:
        """Вывод PTY -> эмулятор (вызывается из SSH-слоя)."""
        self.emulator.feed(text)
        self._dirty = True
        self._schedule_repaint()

    def note_data(self) -> None:
        """Данные уже записаны в общий эмулятор (сессией) — лишь просим репаинт."""
        self._dirty = True
        self._schedule_repaint()

    def mark_closed(self, exit_status: Optional[int]) -> None:
        self.closed.emit(exit_status if exit_status is not None else 0)

    # ==================== ВВОД С КЛАВИАТУРЫ ====================

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        text = event.text()
        modifiers = event.modifiers()

        # Ctrl+Shift+C/V — копи-паста терминала
        if modifiers & Qt.KeyboardModifier.ControlModifier and modifiers & Qt.KeyboardModifier.ShiftModifier:
            if key == Qt.Key.Key_C:
                self.copy_selection()
                return
            if key == Qt.Key.Key_V:
                self.paste_clipboard()
                return
        # Shift+Insert / Ctrl+Insert
        if key == Qt.Key.Key_Insert:
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                self.paste_clipboard()
                return
            if modifiers & Qt.KeyboardModifier.ControlModifier:
                self.copy_selection()
                return

        # прокрутка локальная: Shift+PgUp/PgDn (мышь занята приложением)
        if modifiers & Qt.KeyboardModifier.ShiftModifier and key in (
            Qt.Key.Key_PageUp, Qt.Key.Key_PageDown
        ):
            lines = self.emulator.rows - 1
            self.emulator.scroll_view(lines if key == Qt.Key.Key_PageDown else -lines)
            self.update()
            return

        seq = self._encode_key(key, text, modifiers)

        # ---- сниппет-автодополнение: перехват до PTY ----
        if self._snippet_popup is not None and self._snippet_popup.is_active():
            if self._snippet_popup.handle_key(event):
                return  # клавиша ушла в попап
            # прочие клавиши (буквы/Backspace) падают через и обновляют фильтр

        if seq:
            if self.input_log_enabled:
                self._input_log.append(
                    f"key={key:#x} text={text!r} mods={modifiers.value:#x} -> {seq!r}"
                )
            self.dataToWrite.emit(seq)
            # сброс прокрутки к живому экрану при вводе
            if self.emulator.scroll_offset:
                self.emulator.scroll_offset = 0
                self.update()
            # обновить/показать попап сниппетов по текущему вводу
            self._update_snippet_popup(text, key)
        else:
            super().keyPressEvent(event)

    def _encode_key(self, key: int, text: str, modifiers: Qt.KeyboardModifiers) -> Optional[str]:
        """Клавиша -> байты для PTY. None = не терминальная клавиша."""
        ctrl = modifiers & Qt.KeyboardModifier.ControlModifier
        alt = modifiers & Qt.KeyboardModifier.AltModifier
        shift = modifiers & Qt.KeyboardModifier.ShiftModifier
        keypad = modifiers & Qt.KeyboardModifier.KeypadModifier

        key_name = None
        for name, code in (
            ("up", Qt.Key.Key_Up), ("down", Qt.Key.Key_Down),
            ("right", Qt.Key.Key_Right), ("left", Qt.Key.Key_Left),
            ("home", Qt.Key.Key_Home), ("end", Qt.Key.Key_End),
            ("insert", Qt.Key.Key_Insert), ("delete", Qt.Key.Key_Delete),
            ("pgup", Qt.Key.Key_PageUp), ("pgdown", Qt.Key.Key_PageDown),
        ):
            if key == code:
                key_name = name
                break
        if key_name is None and Qt.Key.Key_F1 <= key <= Qt.Key.Key_F24:
            idx = key - Qt.Key.Key_F1 + 1
            key_name = f"f{idx}"

        if key_name is not None:
            # режим стрелок: авто или принудительный (как в PuTTY).
            # АВТО: некоторые сборки mc шлют только DECPAM (ESC =) без DECCKM (?1h),
            # но ждут application-коды — поэтому учитываем ОБА флага (terminfo
            # vt100/xterm: после smkx стрелки = ESC O A).
            if self.forced_cursor_mode is None:
                app = (
                    self.emulator.application_cursor_keys
                    or self.emulator.application_keypad
                )
            else:
                app = self.forced_cursor_mode == "app"
            table = _KEYMAP_APP_CURSOR if app and key_name in _KEYMAP_APP_CURSOR else _KEYMAP_BASE
            base = table.get(key_name) or _KEYMAP_BASE.get(key_name)
            if base is None:
                return None
            out = base
            # модификаторы на спецклавиши: xterm-стиль CSI 1;m
            mod = 0
            if shift:
                mod |= 1
            if alt:
                mod |= 2
            if ctrl:
                mod |= 4
            if mod:
                # \x1b[1;mX
                letter = out[-1]
                prefix = out[:-1]
                return f"{prefix}1;{mod + 1}{letter}"
            if alt:
                return "\x1b" + out
            return out

        # Backspace: DEL (7F) — стандарт xterm; Ctrl+Backspace = 08
        if key == Qt.Key.Key_Backspace:
            if ctrl:
                return "\x08"
            return "\x7f"
        # Enter
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if keypad and self.emulator.application_keypad:
                return "\x1bOM"
            return "\r"
        # Tab
        if key == Qt.Key.Key_Tab:
            return "\t"
        # Esc
        if key == Qt.Key.Key_Escape:
            return "\x1b"
        # Space с Ctrl
        if key == Qt.Key.Key_Space and ctrl:
            return "\x00"

        # обычный текст
        if text:
            ch = text[0]
            if ctrl and not alt:
                # Ctrl+буква -> control char
                if "a" <= ch <= "z":
                    return chr(ord(ch) - 96)
                if "A" <= ch <= "Z":
                    return chr(ord(ch) - 64)
                specials = {"@": "\x00", "[": "\x1b", "]": "\x1d", "\\": "\x1c", "^": "\x1e", "_": "\x1f"}
                if ch in specials:
                    return specials[ch]
            if ctrl and ch in "@[\\]^_":
                return {"@": "\x00", "[": "\x1b", "\\": "\x1c", "]": "\x1d", "^": "\x1e", "_": "\x1f"}[ch]
            if alt:
                return "\x1b" + (text if not ctrl else "")
            return text
        return None

    # ==================== ВСТАВКА/КОПИРОВАНИЕ ====================

    def paste_clipboard(self) -> None:
        clip = QGuiApplication.clipboard()
        text = clip.text()
        if text:
            self.paste_text(text)

    def paste_text(self, text: str) -> None:
        # нормализуем переводы строк и защищаемся от мегастрок
        text = text.replace("\r\n", "\r").replace("\n", "\r")
        self.dataToWrite.emit(self.emulator.wrap_paste(text))

    def copy_selection(self) -> None:
        text = self.selected_text()
        if text:
            QGuiApplication.clipboard().setText(text)

    def selected_text(self) -> str:
        sel = self._normalized_selection()
        if sel is None:
            return ""
        (r1, c1), (r2, c2) = sel
        emu = self.emulator
        parts: list[str] = []
        for row in range(r1, r2 + 1):
            line = emu.line_at(row)
            if line is None:
                parts.append("")
                continue
            start_col = c1 if row == r1 else 0
            end_col = c2 if row == r2 else emu.cols - 1
            chunk = "".join(ch.data for ch in line[start_col : end_col + 1])
            parts.append(chunk.rstrip())
        return "\n".join(parts)

    def _normalized_selection(self) -> Optional[tuple[tuple[int, int], tuple[int, int]]]:
        if self._selection_start is None or self._selection_end is None:
            return None
        p1, p2 = self._selection_start, self._selection_end
        if (p1[0], p1[1]) > (p2[0], p2[1]):
            p1, p2 = p2, p1
        # прямое выделение по символам
        return p1, p2

    # ==================== МЫШЬ ====================

    def _show_context_menu(self, global_pos: QPoint) -> None:
        menu = self._build_context_menu()
        chosen = menu.exec(global_pos)
        self._apply_context_choice(menu, chosen)

    def _build_context_menu(self) -> "QMenu":
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        act_copy = menu.addAction("Копировать")
        act_copy.setEnabled(bool(self.selected_text()))
        act_paste = menu.addAction("Вставить")
        act_paste.setEnabled(bool(QGuiApplication.clipboard().text()))
        menu.addSeparator()
        act_selall = menu.addAction("Выделить всё")
        act_clear = menu.addAction("Очистить буфер")
        act_reset = menu.addAction("Сбросить терминал")
        menu.addSeparator()

        # режим стрелок (диагностика mc и др. TUI)
        arrows_menu = menu.addMenu("Режим стрелок")
        arrows_group = QActionGroup(self)
        act_arrows_auto = arrows_menu.addAction("Авто (по DECCKM)")
        act_arrows_auto.setCheckable(True)
        act_arrows_auto.setChecked(self.forced_cursor_mode is None)
        act_arrows_normal = arrows_menu.addAction("Обычный  ESC [ A")
        act_arrows_normal.setCheckable(True)
        act_arrows_normal.setChecked(self.forced_cursor_mode == "normal")
        act_arrows_app = arrows_menu.addAction("Application  ESC O A")
        act_arrows_app.setCheckable(True)
        act_arrows_app.setChecked(self.forced_cursor_mode == "app")
        arrows_group.addAction(act_arrows_auto)
        arrows_group.addAction(act_arrows_normal)
        arrows_group.addAction(act_arrows_app)

        act_input_log = menu.addAction("Лог ввода (в буфер)")
        act_input_log.setCheckable(True)
        act_input_log.setChecked(self.input_log_enabled)
        menu.addSeparator()

        # сниппеты (заполняются снаружи через snippet_provider)
        if self.snippet_provider is not None:
            snips = self.snippet_provider()
            if snips:
                snip_menu = menu.addMenu("Сниппеты")
                for s in snips:
                    label = s.name if not s.tags else f"{s.name}   [{', '.join(s.tags)}]"
                    act = snip_menu.addAction(label)
                    act.triggered.connect(lambda checked, sn=s: self.snippet_inserter(sn))
                menu.addSeparator()

        # запоминаем экшены для обработки выбора
        menu.setProperty("act_copy", act_copy)
        menu.setProperty("act_paste", act_paste)
        menu.setProperty("act_selall", act_selall)
        menu.setProperty("act_clear", act_clear)
        menu.setProperty("act_reset", act_reset)
        menu.setProperty("act_arrows_auto", act_arrows_auto)
        menu.setProperty("act_arrows_normal", act_arrows_normal)
        menu.setProperty("act_arrows_app", act_arrows_app)
        menu.setProperty("act_input_log", act_input_log)
        return menu

    def _apply_context_choice(self, menu, chosen) -> None:
        act_copy = menu.property("act_copy")
        act_paste = menu.property("act_paste")
        act_selall = menu.property("act_selall")
        act_clear = menu.property("act_clear")
        act_reset = menu.property("act_reset")
        act_arrows_auto = menu.property("act_arrows_auto")
        act_arrows_normal = menu.property("act_arrows_normal")
        act_arrows_app = menu.property("act_arrows_app")
        act_input_log = menu.property("act_input_log")

        if chosen == act_copy:
            self.copy_selection()
        elif chosen == act_paste:
            self.paste_clipboard()
        elif chosen == act_selall:
            self.select_all()
        elif chosen == act_clear:
            self.clear_scrollback()
        elif chosen == act_reset:
            self.emulator.reset()
            self.update()
        elif chosen == act_arrows_auto:
            self.forced_cursor_mode = None
            self.cursorModeChanged.emit("auto")
        elif chosen == act_arrows_normal:
            self.forced_cursor_mode = "normal"
            self.cursorModeChanged.emit("normal")
        elif chosen == act_arrows_app:
            self.forced_cursor_mode = "app"
            self.cursorModeChanged.emit("app")
        elif chosen == act_input_log:
            self.input_log_enabled = not self.input_log_enabled
            if not self.input_log_enabled and self._input_log:
                QGuiApplication.clipboard().setText("\n".join(self._input_log))
                self._input_log = []

    def select_all(self) -> None:
        emu = self.emulator
        self._selection_start = (0, 0)
        self._selection_end = (emu.total_lines() - 1, emu.cols - 1)
        self.update()

    def _cell_at(self, pos: QPointF) -> tuple[int, int]:
        x = int(pos.x() // self._cell_width)
        y = int(pos.y() // self._cell_height)
        x = max(0, min(x, self.emulator.cols - 1))
        y = max(0, min(y, self.emulator.rows - 1))
        return x, y

    def _global_cell_at(self, pos: QPointF) -> tuple[int, int]:
        """(глобальная строка, колонка) с учётом scroll_offset."""
        x, y = self._cell_at(pos)
        emu = self.emulator
        row = len(emu.scrollback) - emu.scroll_offset + y
        return row, x

    def mousePressEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        # скроллбар: клик = прыжок к позиции, драг = прокрутка
        if pos.x() >= self.width() - self._SCROLLBAR_W:
            if event.button() == Qt.MouseButton.LeftButton:
                self._scrollbar_drag_active = True
                self._scrollbar_drag(event.position())
            return
        x, y = self._cell_at(pos)

        if event.button() == Qt.MouseButton.LeftButton:
            # приложение захотело мышь и не Shift — отправляем ему
            if self._mouse_capture_active() and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self._send_mouse_event(MouseEvent(0, x, y, "press"), event)
                self._mouse_button_down = event.button()
                return
            self._selection_active = True
            self._selection_start = self._global_cell_at(pos)
            self._selection_end = self._selection_start
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            if self._mouse_capture_active():
                self._send_mouse_event(MouseEvent(2, x, y, "press"), event)
                return
            # ПКМ в PuTTY-стиле: если есть выделение — копировать, иначе — вставить.
            # Shift+ПКМ — полное контекстное меню.
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                self._show_context_menu(event.globalPosition().toPoint())
            elif self.selected_text():
                self.copy_selection()
            else:
                self.paste_clipboard()
        elif event.button() == Qt.MouseButton.MiddleButton:
            self.paste_clipboard()

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        if getattr(self, "_scrollbar_drag_active", False):
            self._scrollbar_drag(pos)
            return
        x, y = self._cell_at(pos)

        if self._mouse_button_down == Qt.MouseButton.LeftButton and self._mouse_capture_active():
            self._send_mouse_event(MouseEvent(32, x, y, "drag"), event)
            return

        if self._selection_active:
            self._selection_end = self._global_cell_at(pos)
            self._schedule_repaint()
        else:
            self._update_url_hover(pos)

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        x, y = self._cell_at(pos)

        if event.button() == Qt.MouseButton.LeftButton:
            self._scrollbar_drag_active = False
            if self._mouse_button_down == Qt.MouseButton.LeftButton and self._mouse_capture_active():
                self._send_mouse_event(MouseEvent(0, x, y, "release"), event)
                self._mouse_button_down = None
                return
            # одинарный клик без движения — сброс выделения
            if self._selection_active:
                self._selection_active = False
                if self._selection_start == self._selection_end:
                    self._selection_start = self._selection_end = None
                elif self.copy_on_select:
                    self.copy_selection()  # copy-on-select (настраивается)
                self.update()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        pos = event.position()
        if event.button() == Qt.MouseButton.LeftButton and not self._mouse_capture_active():
            row, col = self._global_cell_at(pos)
            self._select_word_at(row, col)
            self.copy_selection()
        super().mouseDoubleClickEvent(event)

    def _select_word_at(self, row: int, col: int) -> None:
        line = self.emulator.line_at(row)
        if line is None:
            return
        cols = self.emulator.cols
        data = "".join(ch.data for ch in line)
        if col >= len(data) or not (data[col].isalnum() or data[col] in "_-./@:%~?#=&+"):
            return
        lo = col
        while lo > 0 and (data[lo - 1].isalnum() or data[lo - 1] in "_-./@:%~?#=&+"):
            lo -= 1
        hi = col
        while hi < cols - 1 and (data[hi + 1].isalnum() or data[hi + 1] in "_-./@:%~?#=&+"):
            hi += 1
        self._selection_start = (row, lo)
        self._selection_end = (row, hi)
        self.update()

    def wheelEvent(self, event: QWheelEvent) -> None:
        emu = self.emulator
        if self._mouse_capture_active() and not event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            # колесо -> кнопки 64/65 для приложения
            delta = event.angleDelta().y()
            button = 64 if delta > 0 else 65
            y, x = self._cell_y_x(event.position())
            for _ in range(min(3, abs(delta) // 120)):
                seq = emu.mouse_bytes(MouseEvent(button, x, y, "press"))
                if seq:
                    self.dataToWrite.emit(seq)
            return
        lines = -event.angleDelta().y() // 40
        emu.scroll_view(lines)
        self.update()

    def _cell_y_x(self, pos: QPointF) -> tuple[int, int]:
        x, y = self._cell_at(pos)
        return y, x

    def _mouse_capture_active(self) -> bool:
        return self.emulator.mouse_mode != 0

    def _send_mouse_event(self, ev: MouseEvent, event: object) -> None:
        seq = self.emulator.mouse_bytes(ev)
        if seq:
            self.dataToWrite.emit(seq)

    def _scrollbar_drag(self, pos: QPointF) -> None:
        """Прокрутка перетаскиванием ползунка."""
        emu = self.emulator
        total = emu.total_lines()
        visible = emu.rows
        max_scroll = total - visible
        if max_scroll <= 0:
            return
        bar_h = self.height()
        frac = max(0.0, min(1.0, pos.y() / bar_h))
        # низ полосы = живой экран (offset 0); верх = вся история
        emu.scroll_offset = int((1.0 - frac) * max_scroll)
        self.update()

    # ==================== РЕНДЕР ====================

    def paintEvent(self, event: QPaintEvent) -> None:
        painter = QPainter(self)
        try:
            self._paint_contents(painter)
        except Exception:  # noqa: BLE001 - рендер не должен уходить в спам-цикл
            import logging

            logging.getLogger("ssh_term.ui.terminal_widget").exception("paint failed")
            painter.end()  # гарантия: никогда не оставляем активный painter
            painter = QPainter(self)
            painter.fillRect(self.rect(), self.colors.bg)
        finally:
            painter.end()

    def _paint_contents(self, painter: QPainter) -> None:
        painter.fillRect(self.rect(), self.colors.bg)
        emu = self.emulator

        if emu.in_alternate:
            # alt-screen: рисуем только его, без scrollback (как mc/vim)
            for y in range(emu.rows):
                line = emu.line_at(y)
                if line is None:
                    continue
                self._draw_line(painter, y, line, y)
        else:
            # primary: последние (rows) строк ленты [scrollback | primary]
            top_global = len(emu.scrollback) - emu.scroll_offset
            for y in range(emu.rows):
                row = top_global + y
                line = emu.line_at(row)
                if line is None:
                    continue
                self._draw_line(painter, y, line, row)

        # курсор
        if emu.is_cursor_visible() and emu.scroll_offset == 0:
            cx, cy = emu.cursor_xy()
            self._draw_cursor(painter, cx, cy)

        # скроллбар: тонкая полоса справа (как в PuTTY)
        self._draw_scrollbar(painter)

    _SCROLLBAR_W = 8  # px

    def _draw_scrollbar(self, painter: QPainter) -> None:
        emu = self.emulator
        total = emu.total_lines()
        visible = emu.rows
        if total <= visible or emu.in_alternate:
            return
        # позиция: низ = живой экран
        offset_from_bottom = emu.scroll_offset
        max_scroll = total - visible
        if max_scroll <= 0:
            return
        bar_h = self.height()
        sb_x = self.width() - self._SCROLLBAR_W
        painter.fillRect(sb_x, 0, self._SCROLLBAR_W, bar_h, QColor(30, 30, 46, 120))
        thumb_h = max(20, int(bar_h * visible / total))
        thumb_y = int((bar_h - thumb_h) * (offset_from_bottom / max_scroll))
        thumb_y = bar_h - thumb_h - thumb_y  # низ = 0 offset
        painter.fillRect(sb_x, thumb_y, self._SCROLLBAR_W, thumb_h, QColor(120, 120, 160))

    def _draw_line(self, painter: QPainter, y: int, line: list, row: int) -> None:
        """Батч-рисовка строки: подряд идущие ячейки с одним стилем — один drawText."""
        py = y * self._cell_height
        cw, chh = self._cell_width, self._cell_height
        painter.setFont(self._font)

        x = 0
        cols = self.emulator.cols
        while x < cols:
            ch = line[x]
            style = self._style_key(ch, row, x)
            fg, bg = self._style_colors(style)
            run_start = x
            text_parts: list[str] = []
            while x < cols:
                ch2 = line[x]
                style2 = self._style_key(ch2, row, x)
                if style2 != style:
                    break
                text_parts.append(ch2.data)
                x += 1
            run_w = (x - run_start) * cw
            painter.fillRect(run_start * cw, py, run_w, chh, bg)
            text = "".join(text_parts)
            if text.strip():
                painter.setPen(fg)
                painter.drawText(
                    QRect(run_start * cw, py, run_w, chh),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                    | Qt.TextFlag.TextDontClip | Qt.TextFlag.TextSingleLine,
                    text,
                )

    # ---- стиль-кеш: ключ по pyte-атрибутам, QColor-кеш поверх ----

    def _style_key(self, ch, row: int, x: int) -> tuple:
        """Ключ стиля ячейки (без QColor-конверсий — дёшево)."""
        selected = self._in_selection(row, x)
        return (ch.fg, ch.bg, ch.bold, ch.reverse, selected)

    def _style_colors(self, style: tuple) -> tuple[QColor, QColor]:
        """(fg, bg) по стилю с кешированием конверсий."""
        cache = getattr(self, "_style_cache", None)
        if cache is None:
            cache = self._style_cache = {}
        cached = cache.get(style)
        if cached is not None:
            return cached
        fg_attr, bg_attr, bold, reverse, selected = style
        if selected:
            result = (self.colors.selection_fg, self.colors.selection_bg)
        else:
            fg_hex = self._hex_cached(fg_attr)
            bg_hex = self._hex_cached(bg_attr)
            fg = self._qcolor(fg_hex) or self.colors.fg
            bg = self._qcolor(bg_hex) or self.colors.bg
            if bold and fg_hex:
                fg = self._brighter(fg)
            if reverse:
                fg, bg = bg, fg
            result = (fg, bg)
        cache[style] = result
        return result

    def _hex_cached(self, color_attr: str) -> Optional[str]:
        """hex от pyte-цвета с кешем (палитра считается один раз)."""
        hex_cache = getattr(self, "_hex_cache", None)
        if hex_cache is None:
            # палитра конвертируется ОДИН раз, не на каждую ячейку
            self._palette = tuple(c.name().lstrip("#") for c in self.colors.base16)
            hex_cache = self._hex_cache = {}
        if color_attr not in hex_cache:
            hex_cache[color_attr] = color_to_hex(color_attr, self._palette)
        return hex_cache[color_attr]

    def _draw_cell(self, painter: QPainter, x: int, py: int, ch, row: int) -> None:
        """Одиночная ячейка (используется тестами)."""
        px = x * self._cell_width
        fg, bg = self._style_colors(self._style_key(ch, row, x))
        painter.fillRect(px, py, self._cell_width, self._cell_height, bg)
        if ch.data.strip():
            painter.setFont(self._font)
            painter.setPen(fg)
            painter.drawText(
                QRect(px, py, self._cell_width, self._cell_height),
                Qt.AlignmentFlag.AlignCenter,
                ch.data,
            )

    def _cell_colors(self, ch, row: int, x: int) -> tuple[QColor, QColor]:
        """Совместимость: (fg, bg) ячейки. bg всегда валиден."""
        return self._style_colors(self._style_key(ch, row, x))

    def _qcolor(self, hex_str: Optional[str]) -> Optional[QColor]:
        if not hex_str:
            return None
        return QColor(hex_str)

    def _brighter(self, color: QColor) -> QColor:
        if color.lightness() < 180:
            return color.lighter(140)
        return color

    def _in_selection(self, row: int, col: int) -> bool:
        sel = self._normalized_selection()
        if sel is None:
            return False
        (r1, c1), (r2, c2) = sel
        if row < r1 or row > r2:
            return False
        if row == r1 and col < c1:
            return False
        if row == r2 and col > c2:
            return False
        return True

    def _draw_selection_row(self, painter: QPainter, y: int, row: int) -> None:
        pass  # выделение отрисовано в _cell_colors

    def _draw_cursor(self, painter: QPainter, cx: int, cy: int) -> None:
        if not self._cursor_blink_visible:
            return
        px = cx * self._cell_width
        py = cy * self._cell_height
        # блок: заливка цветом курсора + перерисовка символа цветом фона
        painter.fillRect(px, py, self._cell_width, self._cell_height, self.colors.cursor_color)
        line = self.emulator.line_at(
            cy if self.emulator.in_alternate
            else len(self.emulator.scrollback) + cy
        )
        if line is not None and cx < len(line):
            ch = line[cx]
            if ch.data.strip():
                painter.setFont(self._font)
                painter.setPen(self.colors.cursor_text)
                painter.drawText(
                    QRect(px, py, self._cell_width, self._cell_height),
                    Qt.AlignmentFlag.AlignCenter,
                    ch.data,
                )

    # ==================== SCROLLBAR-ИМЕНОВАННЫЕ ОБРАБОТЧИКИ ====================

    def resizeEvent(self, event: QResizeEvent) -> None:
        self._recompute_grid()
        super().resizeEvent(event)

    # ==================== СЕРВИС ====================

    def _on_title(self, title: str) -> None:
        self.titleChanged.emit(title)

    def _on_bell(self) -> None:
        self.bellRung.emit()

    def _on_host_request(self, data: str) -> None:
        self.dataToWrite.emit(data)

    def _schedule_repaint(self) -> None:
        if not self._repaint_timer.isActive():
            self._repaint_timer.start(1000 // _KEYS_PER_SECOND)

    def _delayed_repaint(self) -> None:
        """Repaint-тик виджета: рисуем только если пришли данные.

        Флаг снимаем здесь, а не в paintEvent, чтобы MainWindow._poll_sessions
        (тоже 33 мс, тот же _dirty) не дублировал перерисовку."""
        if self._dirty:
            self._dirty = False
            self.update()

    def _toggle_blink(self) -> None:
        self._cursor_blink_visible = not self._cursor_blink_visible
        self.update()

    def _update_url_hover(self, pos: QPointF) -> None:
        url = self._url_under(pos)
        if url != self._url_at_cursor:
            self._url_at_cursor = url
            if url:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.setCursor(Qt.CursorShape.IBeamCursor)

    def _url_under(self, pos: QPointF) -> Optional[str]:
        row, col = self._global_cell_at(pos)
        line = self.emulator.line_at(row)
        if line is None:
            return None
        text = "".join(ch.data for ch in line)
        for m in _URL_RE.finditer(text):
            if m.start() <= col < m.end():
                return m.group(0)
        return None

    def open_url_at_cursor(self) -> None:
        if self._url_at_cursor:
            import webbrowser

            webbrowser.open(self._url_at_cursor)

    def clear_scrollback(self) -> None:
        self.emulator.clear_scrollback()
        self.update()

    def search_text(self, pattern: str) -> None:
        """Заготовка поиска (Фаза 7)."""
        # TODO: подсветка совпадений
        pass


# import в конце для типизации событий
from PySide6.QtGui import QMouseEvent, QWheelEvent  # noqa: E402
