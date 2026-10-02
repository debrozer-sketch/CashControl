"""Перетаскивание файла на вкладку кассы отправляет его на кассу.

Функция из бэклога: файл с рабочего стола тащат на открытую вкладку, он
уезжает на кассу средствами встроенного CashSCP. Окно файлового менеджера не
открывается, программа не блокируется, есть уведомление по завершении.

Каталог назначения берётся из существующей настройки
``builtin.file_manager_start_dir``, отдельная настройка не заводилась.
"""

from __future__ import annotations

import inspect
import textwrap
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest
from PySide6.QtCore import QMimeData, QPointF, Qt, QUrl
from PySide6.QtGui import QDropEvent

from cashcontrol.gui.cash_session_widget import CashSessionWidget

if TYPE_CHECKING:
    from collections.abc import Iterator


class _DummyWidget:
    def setVisible(self, *_a):
        pass

    def setEnabled(self, *_a):
        pass

    def setText(self, *_a):
        pass

    def setStyleSheet(self, *_a):
        pass


class _Notices:
    """Снятые уведомления: текст и уровень отдельными списками."""

    def __init__(self) -> None:
        self.messages: list[str] = []
        self.levels: list[str] = []


@contextmanager
def _capture_notices() -> Iterator[_Notices]:
    """Перехватить ``feedback.notify``.

    Подменяется сам модуль ``cashcontrol.gui.feedback``: вкладка обращается
    к нему как к модулю, поэтому подмена ``get_notification_manager`` после
    перехода на единый API перестала бы что-либо ловить.

    Перехватчики нужны именно у модуля: если бы вызов шёл через локальный
    импорт ``from cashcontrol.gui.feedback import notify``, подмена молчала
    бы, уведомлений в списке не оказалось бы и тест упал бы на пустом
    сообщении. Проверка не проходит вхолостую именно потому, что список
    пустым быть не может: подмена вызывается вместо настоящей полосы.
    """
    import cashcontrol.gui.feedback as fb
    from cashcontrol.gui.notification_manager import Level

    notices = _Notices()

    def _fake(message: str, level=Level.INFO, **_kw) -> None:
        notices.messages.append(message)
        notices.levels.append(level)

    orig = fb.notify
    fb.notify = _fake
    try:
        yield notices
    finally:
        fb.notify = orig


@pytest.fixture
def widget():
    from PySide6.QtWidgets import QWidget

    # Конструктор CashSessionWidget тянет за собой SSH и сбор информации,
    # поэтому инициализируем только базовую часть QWidget.
    w = CashSessionWidget.__new__(CashSessionWidget)
    QWidget.__init__(w)
    w._ip = "10.0.0.1"
    w._session = None
    w._vnc_widget = _DummyWidget()
    w._btn_vnc_connect = _DummyWidget()
    w._btn_vnc_disconnect = _DummyWidget()
    w._btn_vnc_fullscreen = _DummyWidget()
    w._vnc_status_label = _DummyWidget()
    w.setAcceptDrops(True)
    return w


def _mime(*paths: str) -> QMimeData:
    m = QMimeData()
    m.setUrls([QUrl.fromLocalFile(p) for p in paths])
    return m


def _event(mime: QMimeData) -> QDropEvent:
    return QDropEvent(
        QPointF(10, 10),
        Qt.DropAction.CopyAction,
        mime,
        Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    )


# ── приём drop ─────────────────────────────────────────────────────────

def test_widget_accepts_drops():
    """Вкладка должна принимать файлы, иначе drop не дойдёт."""
    src = textwrap.dedent(inspect.getsource(CashSessionWidget._init_ui))
    assert "setAcceptDrops(True)" in src, (
        "виджет вкладки не включил приём перетаскивания"
    )


def test_only_local_files_accepted(qtbot):
    """Ссылку в интернет принять нельзя, только файлы с диска."""
    mime = QMimeData()
    mime.setUrls([QUrl("https://example.com/file.txt")])
    assert CashSessionWidget._can_accept_drop(_event(mime)) is False

    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("C:/tmp/file.txt")])
    assert CashSessionWidget._can_accept_drop(_event(mime)) is True


def test_plain_text_mime_rejected(qtbot):
    mime = QMimeData()
    mime.setText("просто текст")
    assert CashSessionWidget._can_accept_drop(_event(mime)) is False


def test_drop_with_no_session_warns(qtbot, widget, tmp_path):
    """Без подключения файл не отправляется, пользователь получает предупреждение."""
    f = tmp_path / "a.txt"
    f.write_text("x", encoding="utf-8")

    with _capture_notices() as notices:
        widget.upload_dropped_files([str(f)])

    # Проверяется именно уведомление о неудачной выгрузке: и текст, и его
    # уровень. Ровно одно уведомление — без подключения выгрузка не
    # начинается, поэтому сообщения о копировании быть не должно: лишнее
    # означало бы, что фоновая отправка стартовала без сессии. Сверять
    # длины двух списков подмены бессмысленно: подмена дописывает в них по
    # одному элементу за вызов, и равенство длин не может упасть.
    assert len(notices.messages) == 1, (
        f"ожидалось одно уведомление, получено {notices.messages}"
    )
    (message,) = notices.messages
    assert "подключени" in message
    assert "не отправлен" in message, (
        "оператору не сказано, что файл не ушёл"
    )
    assert notices.levels == ["warning"], f"уровень не тот: {notices.levels}"


def test_missing_files_warn(qtbot, widget):
    widget._session = type("S", (), {"is_connected": True})()
    with _capture_notices() as notices:
        widget.upload_dropped_files(["Z:/нет/такого/файла.txt"])

    assert len(notices.messages) == 1, (
        f"ожидалось одно уведомление о ненайденных файлах: {notices.messages}"
    )
    assert "не найдены" in notices.messages[0]
    assert notices.levels == ["warning"], f"уровень не тот: {notices.levels}"


# ── каталог назначения ─────────────────────────────────────────────────

def test_upload_dir_from_settings(qtbot, widget):
    from cashcontrol.infrastructure.config_manager import ConfigManager

    cfg = ConfigManager()
    widget._drop_upload_dir()
    dest = widget._drop_upload_dir()
    assert dest == cfg.settings.builtin.file_manager_start_dir
    assert dest, "каталог назначения не должен быть пустым"


def test_upload_dir_falls_back_to_storage(qtbot, widget, monkeypatch):
    """Пустая настройка не должна приводить к ошибке загрузки."""
    from cashcontrol.infrastructure.config_manager import ConfigManager

    cfg = ConfigManager()
    monkeypatch.setattr(
        type(cfg.settings.builtin), "file_manager_start_dir", "", raising=False
    )
    assert widget._drop_upload_dir() == "/home/tc/storage"


# ── фоновость и уведомления ────────────────────────────────────────────

async def test_upload_runs_in_background_task(qtbot, widget, monkeypatch, tmp_path):
    """Главный сценарий: работа уходит в задачу, а не выполняется на месте."""
    import asyncio

    from cashcontrol.infrastructure import task_runner

    f = tmp_path / "payload.bin"
    f.write_bytes(b"data")

    started: list = []
    widget._session = type("S", (), {"is_connected": True})()

    async def _fake_upload(session, paths, dest):
        started.append((paths, dest))

    monkeypatch.setattr(
        CashSessionWidget, "_upload_to_cash", staticmethod(_fake_upload), raising=False
    )

    async def _go():
        widget.upload_dropped_files([str(f)])

    task = task_runner.spawn(_go())
    await asyncio.gather(task, return_exceptions=True)
    assert started, "загрузка не была запущена"
    paths, dest = started[0]
    assert paths == [str(f)]
    assert dest == widget._drop_upload_dir()
