from __future__ import annotations

import html
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import PushButton

from cashcontrol.core.aliases.alias_manager import get_alias_manager
from cashcontrol.gui import feedback
from cashcontrol.gui.theme_engine import ThemeEngine
from cashcontrol.gui.theme_helper import color as _tc
from cashcontrol.gui.theme_helper import control_size, font_size

if TYPE_CHECKING:
    from cashcontrol.core.info.info_manager import InfoField


def _squeeze_width(label: QLabel) -> None:
    """Разрешить подписи сжиматься вместе с панелью.

    QLabel с переносом сообщает layout'у minimumSizeHint по самой длинной
    неразрывной части. На кассе это путь к профилю вроде
    ``/home/tc/storage/crystal-cash/…`` — слово без пробелов на 130+ символов.
    Такая подпись раздувала содержимое панели до 1344 px: панель переставала
    сжиматься вместе с окном, а кнопка «Исправить» уезжала целиком за
    правый край, и на экране от неё не оставалось ничего.

    ``setWidgetResizable`` и ``setMinimumWidth(0)`` этот минимум не снимают —
    помогает только ``QSizePolicy.Ignored``, который говорит layout'у
    игнорировать sizeHint и отдать подписи ровно столько места, сколько есть.
    """
    label.setMinimumWidth(0)
    policy = label.sizePolicy()
    policy.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
    label.setSizePolicy(policy)


def _tone_key(severity: str) -> str:
    """Ключ палитры для серьёзности проблемы.

    Серьёзность приходит из проверки, и раньше она доходила до панели, но
    ни на что не влияла: и ошибка, и предупреждение рисовались одинаковым
    цветом. Оператор не мог отличить «касса не отвечает» от «значение
    спорное», а у этих двух разные действия.
    """
    return {
        "error": "error",
        "warning": "warning",
        "info": "info",
    }.get(severity, "text_secondary")


def _problem_html(section: str, message: str, severity: str) -> str:
    """Строка проблемы с тоном по серьёзности.

    Текст проблемы приходит от проверки, а проверка строит его из собранных с
    кассы значений, поэтому `<` в данных съел бы часть строки. Экранируются
    и подпись, и текст.
    """
    tone = _tc(_tone_key(severity))
    return (
        f'<span style="color:{tone};">'
        f"<b>{html.escape(str(section))}:</b></span> "
        f'<span style="color:{_tc("text_primary")};">'
        f"{html.escape(str(message))}</span>"
    )


class ProblemListWidget(QFrame):
    """Панель «Проблемы»: строка на проблему и кнопка у каждой строки.

    Отдельный виджет, а не ``InfoGroupWidget``, потому что там все строки
    склеены в одном HTML-лейбле: кнопку рядом с проблемой в такой разметке
    не разместить, а ``QLabel`` не умеет отдать клик по нужной строке.

    Ряд — отдельный виджет, поэтому у проблемы может быть своё действие, а
    не одно на всю панель.
    """

    # Идентификатор проверки, у которой оператор нажал «Исправить».
    # Сигнал, а не вызов обработчика: сама панель не знает ни про сессию, ни
    # про запись в базу кассы, этим занимается виджет сессии.
    fix_requested = Signal(str)

    def __init__(self, title: str = "Проблемы", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._rows_layout = QVBoxLayout(self)
        self._rows_layout.setContentsMargins(8, 6, 8, 8)
        self._rows_layout.setSpacing(4)

        self._title = QLabel(f"<b>{title}</b>")
        self._title.setTextFormat(Qt.TextFormat.RichText)
        _squeeze_width(self._title)
        self._rows_layout.addWidget(self._title)

        # Строки пометок: их текст собирается из цвета темы, поэтому при
        # смене темы их надо пересобрать, а не только заголовок перекрасить.
        self._rows: list[tuple[QLabel, str, str, str]] = []

        # Подписка на тему по той же причине, что в ``InfoGroupWidget``.
        ThemeEngine.instance().theme_changed.connect(self._apply_theme)
        self._apply_theme()

    def _apply_theme(self) -> None:
        """Перекрасить заголовок и строки под текущую тему."""
        self._title.setStyleSheet(
            f"font-size: {font_size('section')}px; color: {_tc('text_primary')};"
        )
        for label, section, message, severity in self._rows:
            label.setText(_problem_html(section, message, severity))

    def add_problem(
        self,
        section: str,
        message: str,
        severity: str = "warning",
        check_id: str = "",
    ) -> QWidget:
        """Добавить строку с описанием проблемы.

        Кнопка «Исправить» рисуется только когда у проверки действительно
        есть исправление. Список таких проверок живёт в реестре
        ``core.info.fixer``, а не здесь: интерфейс не перечисляет проверки и
        не меняется, когда появляется новое исправление. Проверки без
        исправления остаются строкой текста — молчаливая кнопка, которая
        ничего не делает, выглядела бы поломкой.
        """
        from cashcontrol.core.info.fixes import get_fix

        row = QWidget(self)
        lay = QHBoxLayout(row)
        lay.setContentsMargins(12, 0, 0, 0)
        lay.setSpacing(8)

        text = QLabel(_problem_html(section, message, severity), row)
        text.setTextFormat(Qt.TextFormat.RichText)
        text.setWordWrap(True)
        text.setStyleSheet(f"font-size: {font_size('body')}px; color: {_tc('text_primary')};")
        text.setCursor(QCursor(Qt.CursorShape.IBeamCursor))
        _squeeze_width(text)
        lay.addWidget(text, 1)
        self._rows.append((text, section, message, severity))

        fix = get_fix(check_id) if check_id else None
        if fix is not None:
            button = PushButton("Исправить", row)
            button.setFixedHeight(control_size("chip"))
            # Кегль задаётся через setFont, а не через setStyleSheet: у
            # qfluentwidgets последний заменяет таблицу стилей виджета целиком,
            # и кнопка теряла фон, рамку, радиус и состояния :hover/:disabled.
            # Через setFont оформление компонента остаётся и следует за темой.
            font = button.font()
            font.setPixelSize(font_size("hint"))
            button.setFont(font)
            button.setToolTip(f"{fix.title}: изменить значение на кассе")
            button.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
            button.clicked.connect(lambda _=False, cid=check_id: self.fix_requested.emit(cid))
            lay.addWidget(button, 0, Qt.AlignmentFlag.AlignRight)

        self._rows_layout.addWidget(row)
        return row


class InfoGroupWidget(QFrame):
    """A group box widget that displays a named group of info fields.

    Matches the visual style of cashcontrol2: bold title, key-value rows,
    no emoji icons. Supports progressive field addition and alias links.
    """

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title_text = title
        # Строки принадлежат секциям: секция из группы «Прочее» и секция
        # в одной группе «Прочее», и повторный сбор каждой заменяет только её
        # строки. Плоский список дописывал бы значения, и после «Обновить»
        # панель показывала бы прежнюю ошибку рядом с новым значением.
        self._sections: dict[str, list[InfoField]] = {}
        self._section_order: list[str] = []
        # Пометки секций без строк-значений: «к этой кассе не применимо».
        # Хранятся рядом со строками и принадлежат своей секции, поэтому
        # перерисовка соседней секции их не теряет, а секция с данными
        # убирает свою пометку сама.
        self._notes: dict[str, str] = {}

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 6, 8, 8)
        self._layout.setSpacing(4)

        self._title = QLabel(f"<b>{title}</b>")
        self._title.setTextFormat(Qt.TextFormat.RichText)
        _squeeze_width(self._title)
        self._layout.addWidget(self._title)

        self._body = QLabel()
        self._body.setTextFormat(Qt.TextFormat.RichText)
        self._body.setWordWrap(True)
        self._body.linkActivated.connect(self._on_link_activated)
        _squeeze_width(self._body)
        self._layout.addWidget(self._body)

        self._skeleton: QWidget | None = None

        # Подписка на тему. Раньше цвета задавались в конструкторе и больше
        # не обновлялись: в тёмной теме текст панели оставался тёмно-синим
        # `#1a1a2e` на тёмном фоне и становился почти нечитаемым. Панель
        # сведений — экран, на котором оператор читает значения, и именно он
        # нельзя оставлять с прошлой темой.
        #
        # Стиль ставится на подписи, а не на сам виджет: `setStyleSheet("")`
        # в show_loading и show_error сбрасывал бы его целиком.
        ThemeEngine.instance().theme_changed.connect(self._apply_theme)

        self._apply_theme()
        self.show_loading()

    def _apply_theme(self) -> None:
        """Перекрасить подписи и скелетоны под текущую тему."""
        self._title.setStyleSheet(
            f"font-size: {font_size('section')}px; color: {_tc('text_primary')};"
        )
        self._body.setStyleSheet(
            f"font-size: {font_size('body')}px; color: {_tc('text_primary')}; "
            "padding-left: 12px;"
        )
        if self._skeleton is not None:
            bar_style = f"background: {_tc('bg_tertiary')}; border-radius: 4px;"
            for bar in self._skeleton.findChildren(QFrame):
                bar.setStyleSheet(bar_style)

    def show_loading(self) -> None:
        self._show_skeleton()
        self.setStyleSheet("")

    # ── Skeleton (placeholder bars while collecting) ──────────────────────

    def _show_skeleton(self, rows: int = 3) -> None:
        self._clear_skeleton()
        self._body.hide()
        sk = QWidget(self)
        v = QVBoxLayout(sk)
        v.setContentsMargins(12, 2, 8, 4)
        v.setSpacing(6)
        for width in (190, 150, 110)[:rows]:
            bar = QFrame()
            bar.setFixedSize(width, 9)
            bar.setStyleSheet(
                f"background: {_tc('bg_tertiary')}; border-radius: 4px;"
            )
            v.addWidget(bar)
        v.addStretch(1)
        self._layout.addWidget(sk)
        self._skeleton = sk

    def _clear_skeleton(self) -> None:
        if self._skeleton is not None:
            self._skeleton.setParent(None)
            self._skeleton.deleteLater()
            self._skeleton = None
        self._body.show()

    def add_error(self, section: str, text: str) -> None:
        """Показать отказ одной секции, не стирая остальные секции группы.

        Раньше ``show_error`` и ``show_timeout`` писали прямо в тело группы,
        и отказ любой секции уничтожал всё собранное по ней. На кассе с
        пустым это выходило так: соседние секции приходили и отрисовывались
        первыми, затем другая отдавала ошибку и затирала их собой — оператор
        видел только ошибку одной секции и считал, что соседние не собираются.
        Отказ относится к секции, а не к группе, поэтому он живёт в
        ``_notes`` рядом с остальными и попадает в общий состав.
        """
        self._clear_skeleton()
        if section not in self._sections:
            self._section_order.append(section)
        self._sections[section] = []
        self._notes[section] = text
        self._render_body()

    def timeout_note(self, reason: str | None) -> str:
        """Текст отказа по таймауту с подсказкой, что делать."""
        head = reason or "Касса не ответила на запрос"
        return (
            f"{head}. Обновите сбор: секции, которые не успели, "
            f"добираются по одной и обычно проходят."
        )

    @property
    def _fields(self) -> list[InfoField]:
        """Плоский список строк в порядке секций."""
        return [f for name in self._section_order for f in self._sections.get(name, ())]

    def add_items(self, section: str, fields: list[InfoField]) -> None:
        """Replace the rows of one section and refresh the display.

        ``fields`` пустой — значит секция больше ничего не сообщает, её
        строки убираются. Иначе прошлая ошибка залипала бы на панели.
        """
        self._clear_skeleton()
        if section not in self._sections:
            self._section_order.append(section)
        self._sections[section] = list(fields)
        # Секция снова с данными — её прежняя пометка «не применимо» больше
        # неправда и обязана уйти вместе со старыми строками.
        self._notes.pop(section, None)
        self._render_body()

    def add_note(self, section: str, text: str) -> None:
        """Пометить секцию текстом, у которого нет строк-значений.

        Нужно для «к этой кассе не применимо»: у такой секции данных нет, но
        молчать о ней нельзя — иначе группа остаётся со скелетоном навсегда и
        оператор не отличает отсутствие оборудования от отказа связи.
        """
        self._clear_skeleton()
        if section not in self._sections:
            self._section_order.append(section)
        self._sections[section] = []
        self._notes[section] = text
        self._render_body()

    def _render_body(self) -> None:
        fields = self._fields
        lines: list[str] = []
        for f in fields:
            has_alias = f.alias_key is not None
            displayed = (
                get_alias_manager().resolve(f.alias_key, fallback=f.value)
                if has_alias
                else f.value
            )
            # Подписи и значения приходят с кассы и из справочника, и там
            # попадаются строки вроде `shop<ИМЯ>001`: QLabel считает `<ИМЯ>`
            # тегом, и часть значения молча исчезала из панели. Всё, что не
            # является нашей разметкой, экранируется.
            label_html = (
                f'<span style="color:{_tc("text_secondary")};">'
                f"<b>{html.escape(str(f.label))}:</b></span>"
            )
            shown = html.escape(str(displayed))
            if has_alias:
                lines.append(
                    f'{label_html} '
                    f'<a href="alias:{html.escape(str(f.alias_key), quote=True)}" '
                    f'style="color:{_tc("text_link")};text-decoration:none;">'
                    f"{shown}</a>"
                )
            else:
                lines.append(f"{label_html} {shown}")

        # Пометки идут после строк: «не применимо» — это отсутствие данных,
        # а не ещё одно значение, и ставить его между строками значило бы
        # выдать за часть результата.
        #
        # Перед текстом идёт название секции. Без него две пометки в одной
        # группе читались одинаково — «К этой кассе не применимо» дважды, и
        # оператор не знал, чего именно нет.
        from cashcontrol.core.info.info_manager import SECTION_TITLES

        for name in self._section_order:
            note = self._notes.get(name)
            if note:
                title = SECTION_TITLES.get(name, name)
                lines.append(
                    f'<span style="color:{_tc("text_secondary")};">'
                    f"<i>{html.escape(str(title))}: {html.escape(str(note))}</i>"
                    f"</span>"
                )

        self._body.setText("<br>".join(lines) if lines else "<i>Нет данных</i>")

        self._body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
            if any(f.alias_key for f in fields)
            else Qt.TextInteractionFlag.NoTextInteraction
        )

        self.setStyleSheet("")

    def _on_link_activated(self, link: str) -> None:
        if not link.startswith("alias:"):
            return
        alias_key = link[len("alias:") :]
        field = next((f for f in self._fields if f.alias_key == alias_key), None)
        if field is None:
            return

        am = get_alias_manager()
        menu = QMenu(self)

        action_edit = menu.addAction(
            "Изменить название" if am.has_alias(alias_key) else "Добавить в справочник"
        )

        action_reset = None
        if am.has_alias(alias_key):
            action_reset = menu.addAction("Сбросить к умолчанию")

        menu.addSeparator()
        action_key = menu.addAction(f"Ключ: {alias_key}")
        action_key.setEnabled(False)

        action = menu.exec(QCursor.pos())

        if action == action_edit:
            self._open_alias_editor(field)
        elif action_reset and action == action_reset:
            self._reset_alias(field)

    def _open_alias_editor(self, field: InfoField) -> None:
        from cashcontrol.gui.dialogs.alias_editor import AliasEditorDialog

        dlg = AliasEditorDialog(
            alias_key=field.alias_key or "",
            current_value=field.value,
            parent=self,
        )
        if dlg.exec() == AliasEditorDialog.DialogCode.Accepted:
            am = get_alias_manager()
            new_name = am.resolve(field.alias_key or "", fallback=field.value)
            self._update_field_display(field, new_name)

    def _reset_alias(self, field: InfoField) -> None:
        # yes_text, а не destructive: надпись «Удалить» обещала бы действие,
        # которого в этом окне нет — здесь сбрасывается только имя.
        if feedback.confirm(
            "Сброс алиаса",
            "Сбросить название к значению из встроенного справочника?",
            parent=self,
            yes_text="Сбросить",
        ) and field.alias_key:
            get_alias_manager().delete_alias(field.alias_key)
            self._update_field_display(field, field.value)

    def _update_field_display(self, field: InfoField, new_value: str) -> None:
        # Полный перерендер, а не str.replace: значение могло быть у нескольких
        # полей, и точечная замена переименовала бы их все. resolve() вернёт
        # новое имя только для этого alias_key.
        self._render_body()
