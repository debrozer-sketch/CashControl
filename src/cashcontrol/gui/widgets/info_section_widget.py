from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QFrame, QLabel, QMenu, QVBoxLayout, QWidget

from cashcontrol.core.aliases.alias_manager import get_alias_manager
from cashcontrol.core.info.info_manager import InfoField
from cashcontrol.gui.theme_helper import color as _tc


class InfoGroupWidget(QFrame):
    """A group box widget that displays a named group of info fields.

    Matches the visual style of cashcontrol2: bold title, key-value rows,
    no emoji icons. Supports progressive field addition and alias links.
    """

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("InfoCard")
        self._title_text = title
        self._fields: list[InfoField] = []

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(8, 6, 8, 8)
        self._layout.setSpacing(4)

        self._title = QLabel(f"<b>{title}</b>")
        self._title.setTextFormat(Qt.TextFormat.RichText)
        self._title.setStyleSheet(f"font-size: 13px; color: {_tc('text_primary')};")
        self._layout.addWidget(self._title)

        self._body = QLabel()
        self._body.setTextFormat(Qt.TextFormat.RichText)
        self._body.setWordWrap(True)
        self._body.setStyleSheet(
            f"font-size: 12px; color: {_tc('text_primary')}; padding-left: 12px;"
        )
        self._body.linkActivated.connect(self._on_link_activated)
        self._layout.addWidget(self._body)

        self._skeleton: QWidget | None = None

        self.show_loading()

    def show_loading(self) -> None:
        self._show_skeleton()
        if getattr(self, "_ring", None) is None:
            from qfluentwidgets import IndeterminateProgressRing

            self._ring = IndeterminateProgressRing(self)
            self._ring.setFixedSize(18, 18)
            self._layout.insertWidget(1, self._ring)
        self._ring.show()
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
        ring = getattr(self, "_ring", None)
        if ring is not None:
            ring.hide()
        if self._skeleton is not None:
            self._skeleton.setParent(None)
            self._skeleton.deleteLater()
            self._skeleton = None
        self._body.show()

    def show_timeout(self) -> None:
        self._clear_skeleton()
        self._body.setText("<i>Таймаут</i>")
        self.setStyleSheet("")

    def show_error(self, error: str | None = None) -> None:
        self._clear_skeleton()
        text = f"<i>{error or 'Ошибка'}</i>"
        self._body.setText(text)
        self.setStyleSheet("")

    def add_items(self, fields: list[InfoField]) -> None:
        """Append multiple InfoFields to this group and refresh display."""
        self._clear_skeleton()
        self._fields.extend(fields)
        self._render_body()

    def _render_body(self) -> None:
        lines: list[str] = []
        for f in self._fields:
            has_alias = f.alias_key is not None
            displayed = (
                get_alias_manager().resolve(f.alias_key, fallback=f.value)
                if has_alias
                else f.value
            )
            label_html = (
                f'<span style="color:{_tc("text_secondary")};"><b>{f.label}:</b></span>'
            )
            if has_alias:
                lines.append(
                    f'{label_html} '
                    f'<a href="alias:{f.alias_key}" '
                    f'style="color:{_tc("text_link")};text-decoration:none;">{displayed}</a>'
                )
            else:
                lines.append(f"{label_html} {displayed}")

        self._body.setText("<br>".join(lines) if lines else "<i>Нет данных</i>")

        self._body.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextBrowserInteraction
            if any(f.alias_key for f in self._fields)
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
        from qfluentwidgets import MessageBox

        dlg = MessageBox("Сброс алиаса",
                         "Сбросить название к значению из встроенного справочника?", self)
        dlg.yesButton.setText("Сбросить")
        if dlg.exec() and field.alias_key:
            get_alias_manager().delete_alias(field.alias_key)
            self._update_field_display(field, field.value)

    def _update_field_display(self, field: InfoField, new_value: str) -> None:
        text = self._body.text()
        old_display = (
            get_alias_manager().resolve(field.alias_key or "", fallback=field.value)
            if field.alias_key
            else field.value
        )
        text = text.replace(str(old_display), str(new_value))
        self._body.setText(text)


def _simple_field(key: str, value: Any) -> InfoField:
    return InfoField(
        key=key,
        label=key.replace("_", " ").title(),
        value=str(value),
    )
