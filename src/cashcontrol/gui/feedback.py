"""Единая обратная связь: журнал панели плюс всплывашка одним вызовом.

Раньше обратная связь была в семи местах: ``InfoBar`` напрямую, свой
``_toast`` в db_viewer, ``QMessageBox`` из Qt, ``MessageBox`` из
qfluentwidgets, ``showMessage`` в чужой статус-бар. Вспышки появлялись
в разных углах и в разное время, а в журнал панели попадали только
20 мест вызова из 86.

Здесь одна функция ``notify`` делает обе половины: пишет в журнал и
показывает. Забыть журнал конструктивно нельзя.

Второй вызов — ``confirm``, для мест, где нужен ответ пользователя.
Он остаётся модальным и в журнал не пишет: отказ от подтверждения —
действие пользователя, ему принадлежит ``HistoryManager``.
"""

from __future__ import annotations

import time
from functools import partial
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QThread, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QStackedWidget,
    QTabWidget,
)
from qfluentwidgets import (
    InfoBar,
    InfoBarIcon,
    InfoBarManager,
    InfoBarPosition,
    MessageBox,
)

from cashcontrol.gui.notification_manager import (
    Level,
    get_notification_manager,
    normalize_level,
)
from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from PySide6.QtWidgets import QWidget

logger = get_logger()

# Позиция одна на всё приложение. Раньше здесь стояло значение, которого
# нет в enum qfluentwidgets: обращение к нему давало AttributeError, и
# вспышка тулбара не появлялась вовсе.
#
# Само значение TOP_RIGHT задаёт только сторону: библиотека кладёт полосу
# в угол той области, которую получила в ``parent``. Положение по вертикали
# отсчитывается от верхнего края этой области, поэтому важно, что именно
# передано как ``parent`` — см. ``_anchor``.
TOAST_POSITION = InfoBarPosition.TOP_RIGHT

# Отступ, который библиотека оставляет от края области до полосы. Полоса
# не должна быть шире области за вычетом этого отступа: правый край
# считается от ширины полосы, иначе она уезжает за левый край окна.
# Значение берётся у менеджера позиции, а не зашито руками: смена
# ``TOAST_POSITION`` на нижний угол меняет и отступ.
TOAST_MARGIN = getattr(
    InfoBarManager.make(TOAST_POSITION), "margin", 24
)

# Время жизни по уровню. Отрицательное значение отключает автоскрытие.
DURATION_MS: dict[Level, int] = {
    Level.INFO: 4000,
    Level.SUCCESS: 4000,
    Level.WARNING: 7000,
    Level.ERROR: -1,
}

# Окно склейки: одинаковый текст в пределах этого времени не плодит
# полоски, а увеличивает счётчик.
COALESCE_MS = 5000

# Предел числа ключей в Coalescer. Ключ строится из текста сообщения,
# то есть заранее не ограничен, и без вытеснения словарь рос бы весь
# процесс. 128 с запасом перекрывает пару десятков одновременных
# источников сообщений.
SEEN_CAPACITY = 128

_ICONS: dict[Level, InfoBarIcon] = {
    Level.INFO: InfoBarIcon.INFORMATION,
    Level.SUCCESS: InfoBarIcon.SUCCESS,
    Level.WARNING: InfoBarIcon.WARNING,
    Level.ERROR: InfoBarIcon.ERROR,
}


# Ключ склейки: текст, уровень и окно.
#
# Окно входит в ключ по одной причине: полоса строится с ``parent`` этого
# окна, и из чужого окна её не видно. Совпавший текст из двух окон без
# окна в ключе дал бы одну запись — вторая полоса не построилась бы, а
# обновила бы первую, то есть в своём окне оператор не увидел бы
# ничего. Это два разных события, и склеивать их нельзя.
#
# Различать источник в тексте не нужно: тогда каждое новое место вызова
# обязано дописывать имя таблицы или вкладки, и забытое место снова
# дало бы одну полосу на два события.
#
# В ключ кладётся id() окна, а не сам виджет: удерживать виджет ключом
# нельзя, он и так живёт в ``_live`` отдельно. Адрес после сборки мусора
# переиспользуется, но запись к этому моменту уже снята сигналом
# ``destroyed`` — см. ``_drop``.
CoalesceKey = tuple[str, str] | tuple[str, str, int]


def _coalesce_key(
    text: str,
    level: str | Level,
    host: QWidget | None = None,
) -> CoalesceKey:
    """Ключ склейки. Единственное место, где ключ строится.

    Повтор в том же окне склеивается, одинаковый текст из разных окон —
    нет. Без окна полоска не показывается, и в ключ такая запись не
    попадает вовсе.
    """
    if host is None:
        return (text, str(level))
    return (text, str(level), id(host))


class Coalescer:
    """Считает повторы одинакового сообщения в окне ``window_ms``."""

    def __init__(
        self,
        window_ms: int = COALESCE_MS,
        *,
        clock: Callable[[], float] = time.monotonic,
        capacity: int = SEEN_CAPACITY,
    ) -> None:
        self._window_ms = window_ms
        self._clock = clock
        self._capacity = capacity
        self._seen: dict[CoalesceKey, tuple[float, int]] = {}

    def __len__(self) -> int:
        return len(self._seen)

    def bump(self, text: str, level: str | Level, host: QWidget | None = None) -> int:
        """Вернуть счётчик для ``text``/``level`` в ``host``, создав запись."""
        key = _coalesce_key(text, level, host)
        now = self._clock()
        previous = self._seen.get(key)
        if previous is not None and (now - previous[0]) * 1000 < self._window_ms:
            count = previous[1] + 1
        else:
            count = 1
        self._seen[key] = (now, count)
        self._evict()
        return count

    def forget(self, text: str, level: str | Level, host: QWidget | None = None) -> None:
        """Забыть счётчик.

        Нужен при закрытии полоски: без него тот же текст, пришедший вскоре
        после ручного закрытия, получил бы счётчик ×2 при единственном
        реальном показе.
        """
        self.forget_key(_coalesce_key(text, level, host))

    def forget_key(self, key: CoalesceKey) -> None:
        """Забыть запись по готовому ключу.

        Отдельный вход для обработчика ``destroyed``: он получает ключ, а
        не пару «текст, уровень». Собирать ключ заново из частей было бы
        второй копией правила склейки.
        """
        self._seen.pop(key, None)

    def _evict(self) -> None:
        # Вытесняется самая старая по времени показа, а не первая во
        # словаре: повтор обновляет метку, но не двигает ключ.
        while len(self._seen) > self._capacity:
            oldest = min(self._seen, key=lambda k: self._seen[k][0])
            self._seen.pop(oldest, None)


_coalescer = Coalescer()
# Живые полоски: ключ -> виджет. Нужны, чтобы при повторе обновить текст
# вместо создания второй полоски. Удаление полоски убирает её из словаря
# по сигналу destroyed, поэтому просроченные ключи не копятся.
_live: dict[CoalesceKey, InfoBar] = {}


def _gui_thread() -> QThread:
    """Поток, в котором строятся виджеты."""
    app = QApplication.instance()
    if app is None:
        # Тесты идут без QApplication: главным считается текущий поток.
        return QThread.currentThread()
    return app.thread()


def _resolve_parent(parent: QWidget | None) -> QWidget | None:
    """Окно, к которому относится всплывашка.

    ``widget.window()`` вместо верхнего края экрана: иначе вспышка из
    CashSCP встаёт над главным окном, а это разные окна приложения.
    """
    if parent is None:
        return None
    return parent.window()


def _show(
    message: str,
    level: Level,
    title: str,
    parent: QWidget | None,
) -> None:
    """Показать полосу. Из рабочего потока — через очередь GUI-потока."""
    if parent is None:
        # Без окна показать нечего; запись в журнале уже сделана.
        return
    if QThread.currentThread() is _gui_thread():
        _deliver_local(message, level, title, parent)
        return
    # Виджет принадлежит создавшему потоку, из чужого его не трогают.
    # Контекстом singleShot служит само приложение: оно живёт в
    # GUI-потоке, поэтому событие попадает именно туда.
    app = QApplication.instance()
    if app is None:
        # Строить виджет негде, но запись в журнале уже есть. Молча
        # терять нельзя — иначе пропавший вызов не объяснить.
        logger.warning(f"Нет QApplication, всплывашка не показана: {message!r}")
        return
    QTimer.singleShot(0, app, partial(_deliver_local, message, level, title, parent))


def _deliver_local(
    message: str,
    level: Level,
    title: str,
    parent: QWidget | None,
) -> None:
    """Построить или обновить полосу. Всегда вызывается из GUI-потока."""
    _present(message, level, title, _resolve_parent(parent))


# Qt даёт своему внутреннему стеку в ``QTabWidget`` именно это имя. Само
# ``objectName()`` — публичный API Qt; приватным остаётся только факт
# существования стека, и на случай его переименования ниже есть откат на
# саму панель вкладок.
_QT_TABWIDGET_STACK = "qt_tabwidget_stackedwidget"


def _anchor(host: QWidget | None) -> QWidget | None:
    """Область содержимого окна, к которой крепится всплывашка.

    Почему не само окно. ``TopRightInfoBarManager`` кладёт полосу в
    ``margin``=24 от верхнего края области, которой передан ``parent``.
    В главном окне сверху идёт панель вкладок (измерено: ``y=4..49``), то
    есть полоса, привязанная к окну, ложилась ровно на подписи вкладок —
    26 строк из 50. Привязка к стеку содержимого сдвигает отсчёт за панель
    вкладок и панель инструментов, и бороться с анимацией не нужно: её
    конечную позицию считает сама библиотека от геометрии родителя.
    """
    if host is None:
        return None

    # Импорт внутри функции: ``tab_bar`` тянет за собой тему, а ``feedback``
    # импортируется из панелей инструментов, и верхний импорт здесь замкнул
    # бы круг. Признак области содержимого главного окна — панель вкладок
    # ``CashTabBar`` лежит с этим стеком в одном контейнере (внутри
    # ``TabManager``). У второго стека в окне, раскрытой панели журнала у
    # статус-бара, такого соседа нет.
    from cashcontrol.gui.tab_bar import CashTabBar

    fallback = host
    for stack in host.findChildren(QStackedWidget):
        # Сам ``QTabWidget`` пропускаем: его полоса вкладок лежит поверх
        # содержимого, и полоса, привязанная к нему, легла бы на подписи.
        if isinstance(stack, QTabWidget):
            continue
        parent = stack.parentWidget()
        if parent is not None and parent.findChild(CashTabBar) is not None:
            return stack
        # CashSCP: вкладки — это QTabWidget, содержимое лежит во внутреннем
        # стеке под его полосой вкладок.
        if stack.objectName() == _QT_TABWIDGET_STACK:
            fallback = stack
    return fallback


class _BoundedInfoBar(InfoBar):
    """Полоса, которая не шире области, к которой привязана.

    ``InfoBar._adjustText`` переносит текст по 120 символов в строку, а
    это примерно 1700 px: длинное сообщение давало полосу шире окна, и
    правый край, посчитанный библиотекой от ширины полосы, уезжал за
    левый край окна на 450 px. Перенос оставляем библиотечный, ограничение
    ширины добавляем своё.

    Переопределение одного метода — единственная точка сцепления с
    внутренностью qfluentwidgets. Оно выбрано потому, что библиотека сама
    вызывает ``_adjustText`` и при показе, и по каждому ``Resize``
    родителя, поэтому ограничение переживает изменение размера окна.
    Порядок обработчиков Qt таков, что фильтр полосы (он установлен
    позже) срабатывает раньше фильтра менеджера позиции, и уже
    посчитанная по новой ширине точка остаётся верной. Что за это
    заплачено: переименование ``_adjustText`` в qfluentwidgets молча
    отключит ограничение ширины, полоса снова станет шире окна, — но
    показ и позиционирование продолжат работать.
    """

    def _adjustText(self) -> None:
        super()._adjustText()
        parent = self.parentWidget()
        if parent is None:
            return
        self.setMaximumWidth(max(parent.width() - TOAST_MARGIN, 160))
        # Перенос по словам нужен, чтобы ужатая полоса разбила текст, а не
        # обрезала его.
        self.titleLabel.setWordWrap(True)
        self.contentLabel.setWordWrap(True)
        self.adjustSize()

    @classmethod
    def new(
        cls,
        icon,
        title,
        content,
        orient=Qt.Horizontal,
        isClosable=True,  # noqa: N803 — имя из сигнатуры InfoBar.new
        duration=1000,
        position=InfoBarPosition.TOP_RIGHT,
        parent=None,
    ):
        # Переопределение нужно потому, что ``InfoBar.new`` собирает базовый
        # ``InfoBar`` напрямую и подкласс из него не делает: ``cls`` в
        # фабрике используется только как имя. Тело — копия исходной
        # фабрики; меняется она так же, как и там.
        w = cls(icon, title, content, orient, isClosable, duration, position, parent)
        w.show()
        return w


def _present(
    message: str,
    level: Level,
    title: str,
    host: QWidget | None,
) -> None:
    """Создать или обновить полосу. Только из GUI-потока."""
    if host is None:
        return

    key = _coalesce_key(message, level, host)
    count = _coalescer.bump(message, level, host)

    existing = _live.get(key)
    if existing is not None:
        # Заголовок полосы тоже устаревает: полоса переживает первое
        # событие, а второй вызов может описывать уже другое.
        existing.titleLabel.setText(title)
        existing.contentLabel.setText(f"{message}  ×{count}")
        return

    anchor = _anchor(host)
    if anchor is None or anchor.isHidden():
        # Область содержимого скрыта — показывать негде, а запись в
        # журнале панели уже сделана.
        return

    bar = _BoundedInfoBar.new(
        _ICONS[level],
        title,
        f"{message}  ×{count}" if count > 1 else message,
        isClosable=True,
        duration=DURATION_MS[level],
        position=TOAST_POSITION,
        parent=anchor,
    )
    # ``QStackedWidget`` не поднимает полосу над страницей, добавленной
    # позже: новая вкладка закрыла бы её собой.
    bar.raise_()
    bar.destroyed.connect(lambda *_, k=key: _drop(k))
    _live[key] = bar


def _drop(key: CoalesceKey) -> None:
    """Полоска уничтожена: забыть её и её счётчик.

    Иначе через пару секунд тот же текст вернулся бы счётчиком ×2, хотя
    его показывали один раз, и пользователь увидел бы несуществующее
    повторение. Ключ приходит готовым и снимает запись только своего
    окна: чужую полоску по соседней вкладке это не должно трогать.
    """
    _live.pop(key, None)
    _coalescer.forget_key(key)


def notify(
    message: str,
    level: str | Level = Level.INFO,
    *,
    title: str = "",
    parent: QWidget | None = None,
) -> None:
    """Сообщить пользователю: записать в журнал и показать всплывашку."""
    resolved = normalize_level(level)
    get_notification_manager().record(message, resolved, title=title)
    _show(message, resolved, title, parent)


def confirm(
    title: str,
    text: str,
    *,
    parent: QWidget | None = None,
    destructive: bool = False,
    yes_text: str | None = None,
) -> bool:
    """Спросить подтверждение. Остаётся модальным, в журнал не пишет.

    Вызывать только из обработчика Qt-слота: ``exec()`` внутри
    asyncio-колбэка роняет вложенный Qt-цикл.

    ``destructive`` задаёт надпись по умолчанию: «Удалить» вместо
    «Выполнить». Места, где надпись своя — «Перезагрузить», «Очистить»,
    «Сбросить» — передают ``yes_text``: иначе кнопка удаления обещает
    действие, которого в этом окне нет.
    """
    host = _resolve_parent(parent)
    if host is None:
        return False
    dialog = MessageBox(title, text, host)
    dialog.yesButton.setText(yes_text or ("Удалить" if destructive else "Выполнить"))
    dialog.cancelButton.setText("Отмена")
    return bool(dialog.exec())
