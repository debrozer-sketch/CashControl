"""Эмуляция терминала: pyte + alt-screen + mouse + scrollback.

Ядро терминала. Не зависит от Qt: принимает str, хранит экраны, отдаёт данные для
рендера и кодирует ввод/мышь в escape-последовательности.

Особенности реализации:
- pyte-парсер кеширует bound-методы экрана при создании диспатчеров, поэтому
  переключение primary/alternate решается через прокси-экран (_ProxyScreen),
  который динамически форвардит события активному экрану.
- pyte не знает режимов 1049/47/1047 (alt screen), 1 (DECCKM), 2004 (bracketed
  paste), 9/1000/1002/1003/1005/1006/1015 (mouse) — отслеживаем сами.
- write_process_input (ответы на DA/DSR-запросы хоста) пробрасывается наружу
  колбэком on_write_process, иначе less/vim повисают на запросе позиции курсора.
"""

from __future__ import annotations

import logging
import unicodedata
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Optional

import pyte
import wcwidth
from pyte import modes as pyte_modes
from pyte.screens import Char

_LOG = logging.getLogger("ssh_term.terminal.emulator")

_SCROLLBACK_DEFAULT = 5000

_CharFactory = Callable[[int], list[Char]]
_FlagCallback = Callable[[str], None]


# стандартные 16 цветов (индекс -> hex), чтобы рендер не зависел от имён pyte
_BASE16 = (
    "000000", "800000", "008000", "808000", "000080", "800080", "008080", "c0c0c0",
    "808080", "ff0000", "00ff00", "ffff00", "0000ff", "ff00ff", "00ffff", "ffffff",
)


def color_to_hex(color: str, palette: tuple[str, ...] = _BASE16) -> Optional[str]:
    """fg/bg из Char -> '#rrggbb'. None = системный (default)."""
    if color == "default":
        return None
    if color.startswith("bright"):
        base = color[len("bright") :]
        idx_map = {
            "black": 8, "red": 9, "green": 10, "brown": 11, "yellow": 11,
            "blue": 12, "magenta": 13, "cyan": 14, "white": 15, "gray": 8,
        }
        i = idx_map.get(base)
        return "#" + palette[i] if i is not None else None
    idx_map = {
        "black": 0, "red": 1, "green": 2, "brown": 3, "yellow": 3, "blue": 4,
        "magenta": 5, "cyan": 6, "white": 7, "gray": 8, "silver": 7,
    }
    i = idx_map.get(color)
    if i is not None:
        return "#" + palette[i]
    if len(color) == 6 and all(ch in "0123456789abcdef" for ch in color):
        return "#" + color
    return None


@dataclass(frozen=True)
class MouseEvent:
    """Событие мыши для передачи удалённому приложению."""

    button: int  # 0=left 1=middle 2=right; 64=wheel-up 65=wheel-down
    x: int  # 0-based колонка
    y: int  # 0-based строка (экрана, не scrollback)
    action: str  # "press" | "drag" | "release"


class _ProxyScreen:
    """Форвардит события pyte активному экрану и перехватывает режимы.

    pyte.Stream при инициализации берёт getattr(listener, attr) для каждого
    события из Stream.events, поэтому подмена self.stream._screen на лету
    бесполезна — методы заморожены. Этот прокси решает проблему: Stream
    создаст диспатчеры из наших методов, а мы в рантайме решаем, кому
    отдать событие.
    """

    def __init__(self, owner: "TerminalEmulator") -> None:
        self._owner = owner

    # ВАЖНО: pyte кеширует getattr(listener, event) в диспатчеры при первом
    # feed, поэтому нельзя отдавать bound-метод активного экрана напрямую.
    # Вместо __getattr__ отдаём собственные обёртки, которые в момент
    # ВЫЗОВА смотрят, какой экран активен.

    _INTERCEPTED = {
        "set_mode",
        "reset_mode",
        "write_process_input",
        "set_title",
        "set_icon_name",
        "bell",
    }

    def __getattr__(self, name: str) -> object:
        if name.startswith("_"):
            raise AttributeError(name)

        def forwarded(*args: object, **kwargs: object) -> object:
            # некоторые CSI-команды приходят с private=True (DECSTBM 'CSI ?..r',
            # DA 'CSI ?..c' и т.п.), но pyte-методы их не принимают:
            # private-варианты либо noop, либо обрабатываются нами в set_mode.
            if kwargs.pop("private", False):
                return None
            return getattr(self._owner.screen, name)(*args, **kwargs)

        forwarded.__name__ = name
        return forwarded

    # --- перехват set_mode/reset_mode: приватные режимы ---

    def set_mode(self, *modes: int, **kwargs: object) -> None:
        if kwargs.get("private"):
            for m in modes:
                self._owner._handle_private_mode(m, True)
        self._owner.screen.set_mode(*modes, **kwargs)  # type: ignore[arg-type]

    def reset_mode(self, *modes: int, **kwargs: object) -> None:
        if kwargs.get("private"):
            for m in modes:
                self._owner._handle_private_mode(m, False)
        self._owner.screen.reset_mode(*modes, **kwargs)  # type: ignore[arg-type]

    # --- keypad (DECPAM/DECPNM): вызывается из escape-таблицы pyte ---

    def _keypad_application_on(self) -> None:
        self._owner.application_keypad = True

    def _keypad_application_off(self) -> None:
        self._owner.application_keypad = False

    # --- ответы хосту (DA/DSR) ---

    def write_process_input(self, data: str) -> None:
        owner = self._owner
        if owner._on_write_process is not None:
            owner._on_write_process(data)

    # --- title/bell наружу ---

    def set_title(self, param: str) -> None:
        owner = self._owner
        if owner._on_title is not None:
            owner._on_title(param)

    def set_icon_name(self, param: str) -> None:
        pass  # прототипу не нужен

    def bell(self) -> None:
        owner = self._owner
        if owner._on_bell is not None:
            owner._on_bell()


# pyte 0.8.2: ('data','fg','bg','bold','italics','underscore','strikethrough',
#              'reverse','blink'). Быстрый draw строится по позициям — при
# другом раскладе полей связь молча сломается, поэтому проверяем жёстко.
if Char._fields != (
    "data", "fg", "bg", "bold", "italics",
    "underscore", "strikethrough", "reverse", "blink",
):
    raise AssertionError(f"неожиданный расклад полей pyte.Char: {Char._fields}")


class _FastScreen(pyte.screens.Screen):
    """Screen с быстрым draw.

    pyte на каждый печатный символ делает attrs._replace(data=...) — две
    аллокации namedtuple (~5 мкс/символ). Мы строим Char напрямую одним
    позиционным конструктором (~в 3 раза дешевле); кэджим значения attrs на
    длину одного draw-рана (внутри рана attrs не меняется — CSI прерывает
    draw). Логика построчно повторяет pyte 0.8.2 Screen.draw.
    """

    def draw(self, data: str) -> None:
        c = self.cursor
        a = c.attrs
        cf = a.__class__  # pyte.Char
        fg, bg = a.fg, a.bg
        bold = a.bold
        italic = a.italics
        under, strike = a.underscore, a.strikethrough
        reverse, blink = a.reverse, a.blink
        data = data.translate(self.g1_charset if self.charset else self.g0_charset)
        cols = self.columns
        for char in data:
            char_width = wcwidth.wcwidth(char)

            if c.x == cols:
                if pyte_modes.DECAWM in self.mode:
                    self.dirty.add(c.y)
                    self.carriage_return()
                    self.linefeed()
                elif char_width > 0:
                    c.x -= char_width

            if pyte_modes.IRM in self.mode and char_width > 0:
                self.insert_characters(char_width)

            line = self.buffer[c.y]
            if char_width == 1:
                line[c.x] = cf(char, fg, bg, bold, italic, under, strike, reverse, blink)
            elif char_width == 2:
                line[c.x] = cf(char, fg, bg, bold, italic, under, strike, reverse, blink)
                if c.x + 1 < cols:
                    line[c.x + 1] = cf("", fg, bg, bold, italic, under, strike, reverse, blink)
            elif char_width == 0 and unicodedata.combining(char):
                if c.x:
                    last = line[c.x - 1]
                    normalized = unicodedata.normalize("NFC", last.data + char)
                    line[c.x - 1] = last._replace(data=normalized)
                elif c.y:
                    last = self.buffer[c.y - 1][cols - 1]
                    normalized = unicodedata.normalize("NFC", last.data + char)
                    self.buffer[c.y - 1][cols - 1] = last._replace(data=normalized)
            else:
                break

            if char_width > 0:
                c.x = min(c.x + char_width, cols)

        self.dirty.add(c.y)


class TerminalEmulator:
    """VT100/xterm-256color эмулятор с scrollback, мышью и alt-screen."""

    def __init__(
        self,
        cols: int = 80,
        rows: int = 24,
        scrollback_lines: int = _SCROLLBACK_DEFAULT,
        on_title: Optional[Callable[[str], None]] = None,
        on_bell: Optional[Callable[[], None]] = None,
        on_write_process: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.cols = cols
        self.rows = rows

        self.primary = _FastScreen(cols, rows)
        self.alternate = _FastScreen(cols, rows)
        self._active = self.primary
        self.in_alternate = False

        self._on_title = on_title
        self._on_bell = on_bell
        self._on_write_process = on_write_process

        # режимы, которых pyte не знает
        self.application_cursor_keys = False  # DECCKM
        self.bracketed_paste = False  # DECSET 2004
        self.mouse_mode = 0  # 0=off 9=X10 1000=click 1002=click+drag 1003=all
        self.mouse_encoding = "x11"  # x11 | utf8 | sgr
        self._mouse_pressed = False  # для X10-протокола

        self.scrollback: Deque[list[Char]] = deque(maxlen=scrollback_lines)
        self.scroll_offset = 0  # 0 = живой экран; >0 = отступ назад в историю

        self._proxy = _ProxyScreen(self)
        # KEYPAD: патчим escape-таблицу ДО создания Stream — диспатчеры
        # pyte строятся один раз в генераторе парсера при attach()
        base_escape = dict(pyte.Stream.escape)
        base_escape["="] = "_keypad_application_on"
        base_escape[">"] = "_keypad_application_off"
        self.stream = pyte.Stream(self._proxy)
        # подмена диспатчеров: пересоздаём парсер с новой таблицей
        self.stream.escape = base_escape
        self.stream._initialize_parser()  # noqa: SLF001 — диспатчеры по новой таблице
        self._patch_primary_index()
        self._patch_responses()

        # ESC = / ESC > (DECPAM/DECPNM): application keypad
        self.application_keypad = False

        # pyte.Stream.feed — без обёрток (перехват keypad в escape-таблице)
        self._orig_feed = self.stream.feed

    def _keypad_application_on(self) -> None:
        self.application_keypad = True

    def _keypad_application_off(self) -> None:
        self.application_keypad = False

    # ==================== ПРИЁМ ДАННЫХ ====================

    def feed(self, text: str) -> None:
        """Скормить вывод удалённой стороны. Отказоустойчиво: падение на
        escape-последовательности не должно выбрасывать обычный текст."""
        try:
            self._orig_feed(text)
        except Exception:  # noqa: BLE001
            _LOG.exception("feed failed on chunk (%d chars), recovering", len(text))
            self._feed_resilient(text)

    def _feed_resilient(self, text: str) -> None:
        """Аварийный путь: делим чанк пополам, пока ошибка не локализуется."""
        half = len(text) // 2
        if half == 0:
            return
        try:
            self._orig_feed(text[:half])
        except Exception:  # noqa: BLE001
            self._feed_resilient(text[:half])
        try:
            self._orig_feed(text[half:])
        except Exception:  # noqa: BLE001
            self._feed_resilient(text[half:])

    # ==================== РАЗМЕР ====================

    def resize(self, rows: int, cols: int) -> None:
        if rows == self.rows and cols == self.cols:
            return
        old_rows = self.rows
        self.rows, self.cols = rows, cols
        for scr in (self.primary, self.alternate):
            scr.resize(rows, cols)
        # pyte при уменьшении строк обрезает буфер сверху с сохранением курсора
        # если строки потерялись — уводим их в scrollback
        if rows < old_rows and not self.in_alternate:
            pass  # resize у pyte уже перераспределил; потери допускаем в прототипе

    # ==================== РЕНДЕРУ ====================

    @property
    def screen(self) -> pyte.Screen:
        return self._active

    def line_at(self, index: int) -> Optional[list[Char]]:
        """Строка экрана. В alt-режиме index = строка экрана (0..rows-1),
        иначе — глобальная: [scrollback ... | primary]. None, если за пределами."""
        if index < 0:
            return None
        if self.in_alternate:
            if index < self.rows:
                return self._alternate_line(index)
            return None
        sb = self.scrollback
        if index < len(sb):
            line = sb[index]
            # строки scrollback могли остаться от другой ширины экрана:
            # нормализуем к текущей ширине (защита рендера от IndexError)
            if len(line) < self.cols:
                default = self.primary.default_char
                line = line + [default] * (self.cols - len(line))
                sb[index] = line
            elif len(line) > self.cols:
                line = line[: self.cols]
                sb[index] = line
            return line
        y = index - len(sb)
        if y < self.rows:
            return self._primary_line(y)
        return None

    def total_lines(self) -> int:
        return len(self.scrollback) + self.rows

    def _primary_line(self, y: int) -> list[Char]:
        line = self.primary.buffer[y]
        default = self.primary.default_char
        return [line.get(x, default) for x in range(self.cols)]

    def _alternate_line(self, y: int) -> list[Char]:
        line = self.alternate.buffer[y]
        default = self.alternate.default_char
        return [line.get(x, default) for x in range(self.cols)]

    def cursor_xy(self) -> tuple[int, int]:
        c = self.screen.cursor
        return c.x, c.y

    def is_cursor_visible(self) -> bool:
        return not self.screen.cursor.hidden

    # ==================== SCROLLBACK ====================

    def scroll_view(self, delta: int) -> None:
        """Прокрутка viewport: положительное = к живому экрану."""
        if self.in_alternate:
            return  # mc/vim: колесо уйдёт мышиными wheel-событиями
        self.scroll_offset = max(0, min(self.scroll_offset - delta, len(self.scrollback)))

    def scroll_to(self, offset: int) -> None:
        self.scroll_offset = max(0, min(offset, len(self.scrollback)))

    # ==================== ПЕРЕХВАТЫ PYTE ====================

    def _patch_primary_index(self) -> None:
        """Уход верхней строки primary за экран -> scrollback."""
        screen = self.primary
        orig_index = screen.index

        def index() -> None:
            top, bottom = screen.margins or pyte.screens.Margins(0, screen.lines - 1)
            if screen.cursor.y == bottom and not self.in_alternate:
                self.scrollback.append(self._primary_line(top))
            orig_index()

        screen.index = index  # type: ignore[method-assign]
        screen.linefeed = index  # type: ignore[method-assign]

    def _patch_responses(self) -> None:
        """DA/DSR-ответы: pyte вызывает write_process_input на самом экране,
        поэтому патчим оба экрана напрямую (прокси тут не помогает)."""

        def wpi(data: str) -> None:
            if self._on_write_process is not None:
                self._on_write_process(data)

        self.primary.write_process_input = wpi  # type: ignore[method-assign]
        self.alternate.write_process_input = wpi  # type: ignore[method-assign]

    def _handle_private_mode(self, mode: int, enable: bool) -> None:
        if mode in (1049, 1047, 47):
            if enable:
                self._save_cursor()
                self._enter_alternate()
            else:
                self._exit_alternate()
                if mode == 1049:
                    self._restore_cursor()
        elif mode == 1:
            self.application_cursor_keys = enable
        elif mode == 2004:
            self.bracketed_paste = enable
        elif mode in (9, 1000, 1002, 1003):
            self.mouse_mode = mode if enable else 0
            if not enable:
                self._mouse_pressed = False
        elif mode == 1005:
            self.mouse_encoding = "utf8" if enable else "x11"
        elif mode == 1006:
            self.mouse_encoding = "sgr" if enable else "x11"
        elif mode == 1015:
            self.mouse_encoding = "urxvt" if enable else "x11"
        # 25 (cursor), 7 (wrap), 6 (origin) и др. pyte обрабатывает сам

    def _enter_alternate(self) -> None:
        if not self.in_alternate:
            self.in_alternate = True
            self._active = self.alternate
            self.scroll_offset = 0
            self.alternate.reset()
            _LOG.debug("alt screen ON")

    def _save_cursor(self) -> None:
        c = self.primary.cursor
        self._saved_cursor = (c.x, c.y)

    def _restore_cursor(self) -> None:
        pos = getattr(self, "_saved_cursor", None)
        if pos is not None:
            self.primary.cursor.x, self.primary.cursor.y = pos

    def _exit_alternate(self) -> None:
        if self.in_alternate:
            self.in_alternate = False
            self._active = self.primary
            self.scroll_offset = 0
            _LOG.debug("alt screen OFF")

    # ==================== МЫШЬ ====================

    def mouse_bytes(self, ev: MouseEvent) -> Optional[str]:
        """Событие мыши -> escape-строка для хоста. None = не отправлять."""
        mode = self.mouse_mode
        if mode == 0:
            return None
        # Shift+мышь всегда локальный (выделение/скролл) — обрабатывает виджет
        enc = self.mouse_encoding

        if enc == "sgr":
            act = "m" if ev.action == "release" else "M"
            btn = ev.button if ev.action != "release" else 3
            return f"\x1b[<{btn};{ev.x + 1};{ev.y + 1}{act}"

        # X10: только press
        if mode == 9 and ev.action != "press":
            return None
        if ev.action == "release" and mode != 1003:
            # x11/utf8/urxvt не имеют release-кода (кроме 1003 all-motion)
            if mode in (1000, 1002) and enc in ("x11", "utf8"):
                return None
        btn = ev.button
        cb = 32 + btn
        if ev.action == "drag":
            pass  # button уже содержит код 32 (motion + button)

        if enc == "utf8":
            # UTF-8 Extended: coords кодируются >= 127 как utf-8 codepoints
            def enc_byte(v: int) -> str:
                return chr(v)

            return "\x1b[M" + enc_byte(cb) + enc_byte(ev.x + 33) + enc_byte(ev.y + 33)

        if enc == "urxvt":
            btn_code = btn + 32
            return f"\x1b[{btn_code};{ev.x + 1};{ev.y + 1}M"

        # x11 (классика)
        if ev.x + 33 > 255 or ev.y + 33 > 255:
            return None
        return "\x1b[M" + chr(cb) + chr(ev.x + 33) + chr(ev.y + 33)

    # ==================== КЛАВИАТУРА -> ХОСТУ ====================

    def key_bytes(self, text: str) -> str:
        """Обычный текст (в т.ч. Ctrl+буква) — напрямую."""
        return text

    # ==================== ВСТАВКА ====================

    def wrap_paste(self, text: str) -> str:
        """Оформить вставку с учётом bracketed paste mode."""
        if self.bracketed_paste:
            return "\x1b[200~" + text + "\x1b[201~"
        return text

    # ==================== ОЧИСТКА ====================

    def clear_scrollback(self) -> None:
        self.scrollback.clear()
        self.scroll_offset = 0

    def reset(self) -> None:
        """Полный сброс эмулятора (RIS)."""
        self.primary.reset()
        self.alternate.reset()
        self.in_alternate = False
        self._active = self.primary
        self.scrollback.clear()
        self.scroll_offset = 0
        self.application_keypad = False
        self.application_cursor_keys = False
        self.bracketed_paste = False
        self.mouse_mode = 0
