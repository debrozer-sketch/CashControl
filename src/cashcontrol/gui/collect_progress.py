"""Строка состояния сбора логов в зоне коллекторов.

Всплывающее окно для этого не подходит: сбор идёт на фоне, а пользователь
продолжает работать с другими кассами. Поэтому ход работы показывается
компактной строкой над панелями коллекторов.

Строка показывает этап, полосу прогресса, подробности и прошедшее время,
а через 15 секунд после последнего обновления сама скрывается, чтобы не
занимать место под панелями коллекторов. Кнопка открытия папки появляется
после завершения.

Виджеты взяты из Fluent-набора вместе с остальным интерфейсом. Разделитель
сделан отдельной полосой, а не свойством контейнера: стиль с рамкой в Qt
наследуется всеми дочерними виджетами и обводит рамкой каждый элемент.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget
from qfluentwidgets import (
    CaptionLabel,
    FluentIcon,
    StrongBodyLabel,
    TransparentToolButton,
)

from cashcontrol.gui.theme_helper import color as _tc
from cashcontrol.infrastructure.audit_logger import get_logger
from cashcontrol.infrastructure.path_resolver import open_in_explorer

if TYPE_CHECKING:
    from pathlib import Path

    from cashcontrol.core.collect import Progress

logger = get_logger()

#: Через сколько секунд без обновлений строка скрывается.
AUTO_HIDE_MS = 15_000

#: Высота строки: достаточно для полосы, не вытесняет панели коллекторов.
BAR_HEIGHT = 34

#: Ширина и высота полосы прогресса.
PROGRESS_WIDTH = 150
PROGRESS_HEIGHT = 6

#: Ширина колонки с процентом.
PERCENT_WIDTH = 38

#: Насколько полоса может сжаться на узкой панели, оставаясь читаемой.
TRACK_MIN_WIDTH = 80

#: Предельная ширина колонки с названием этапа. Точная ширина считается
#: по шрифту при создании, этот предел нужен только для широких заголовков.
STAGE_WIDTH_MAX = 150

_STAGE_TITLES = {
    "measure": "Измерение объёма",
    "count": "Подсчёт файлов",
    "pack": "Упаковка на кассе",
    "download": "Скачивание",
    "done": "Готово",
}


class _Separator(QWidget):
    """Тонкая линия под строкой.

    Отдельный виджет вместо ``border-bottom`` у контейнера: стиль с рамкой
    распространяется на дочерние виджеты и обводит рамкой каждый из них.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setStyleSheet(f"background: {_tc('separator')};")


class _ElidedMixin:
    """Сокращение текста многоточием вместо обрезки по краю.

    Без этого длинный путь или имя архива налезал бы на счётчик времени.
    Полный текст уходит в подсказку, чтобы его можно было прочитать.

    Политика размера остаётся обычной: ``Ignored`` по горизонтали заставил бы
    разметку сжать виджет до нуля и сдвинуть на его место соседние элементы.
    """

    def _init_elided(self, min_text: str = "") -> None:
        self._full_text = ""
        # Виджет без родителя получает нулевую ширину и сокращает текст
        # в многоточие, поэтому минимум задаётся по самому длинному
        # ожидаемому значению, а не по текущему
        if min_text:
            self.setMinimumWidth(self.fontMetrics().horizontalAdvance(min_text))

    def setText(self, text: str) -> None:
        self._full_text = text
        self._apply_elide()

    def fullText(self) -> str:
        return self._full_text

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_elide()

    def _apply_elide(self) -> None:
        elided = self.fontMetrics().elidedText(
            self._full_text, Qt.TextElideMode.ElideRight, self.width()
        )
        QLabel.setText(self, elided)
        self.setToolTip(self._full_text if elided != self._full_text else "")


class _ElidedStrong(_ElidedMixin, StrongBodyLabel):
    """Заголовок этапа с сокращением текста."""

    def __init__(self, parent: QWidget | None = None, min_text: str = "") -> None:
        StrongBodyLabel.__init__(self, parent)
        self._init_elided(min_text)


class _ElidedCaption(_ElidedMixin, CaptionLabel):
    """Подпись с сокращением текста."""

    def __init__(self, parent: QWidget | None = None, min_text: str = "") -> None:
        CaptionLabel.__init__(self, parent)
        self._init_elided(min_text)


class _ProgressTrack(QWidget):
    """Плоская полоса прогресса в цветах темы.

    Готовые виджеты не подошли: ``QProgressBar`` рисует глянцевый
    градиент стиля Windows, а полосы из Fluent используют собственный
    бирюзовый цвет вместо акцента приложения и не показывают движение
    при неопределённом проценте. Здесь всё своё, поэтому вид предсказуем
    в обеих темах.
    """

    #: Интервал перерисовки бегущей полосы, мс.
    _TICK_MS = 40

    #: Доля ширины, которую занимает бегущий кусок.
    _BUSY_FRACTION = 0.35

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(PROGRESS_WIDTH, PROGRESS_HEIGHT)
        self._percent = 0
        self._busy = False
        self._offset = 0.0

        self._timer = QTimer(self)
        self._timer.setInterval(self._TICK_MS)
        self._timer.timeout.connect(self._advance)

    def set_percent(self, percent: int) -> None:
        """Показать конкретный процент от 0 до 100."""
        if self._busy:
            self._busy = False
            self._timer.stop()
        self._percent = max(0, min(100, percent))
        self.update()

    def set_busy(self, busy: bool) -> None:
        """Переключить вид без точного процента."""
        self._busy = busy
        if busy:
            self._offset = 0.0
            self._timer.start()
        else:
            self._timer.stop()
        self.update()

    def _advance(self) -> None:
        width = max(self.width(), 1)
        span = width * (1.0 - self._BUSY_FRACTION)
        step = max(span / 18.0, 1.0)
        self._offset += step
        if self._offset > span:
            self._offset = 0.0
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        radius = self.height() / 2

        track = QColor(_tc("border_secondary"))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), radius, radius)

        if self._busy:
            span = self.width() * self._BUSY_FRACTION
            painter.setBrush(QColor(_tc("accent")))
            painter.drawRoundedRect(
                QRectF(self._offset, 0, span, self.height()), radius, radius
            )
        elif self._percent > 0:
            width = self.width() * self._percent / 100
            painter.setBrush(QColor(self._fill_color()))
            painter.drawRoundedRect(QRectF(0, 0, max(width, radius * 2), self.height()), radius, radius)

        painter.end()

    def _fill_color(self) -> str:
        return self.property("fillColor") or _tc("accent")

    def set_fill_color(self, name: str) -> None:
        """Задать цвет заливки по имени ключа темы."""
        self.setProperty("fillColor", _tc(name))
        self.update()


class CollectStatusBar(QWidget):
    """Компактная строка хода сбора, встроенная в панель коллекторов."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedHeight(BAR_HEIGHT + 1)
        # Expanding по горизонтали, чтобы строка занимала всю ширину панели
        # коллекторов: при Ignored или Fixed она оставалась размером по
        # умолчанию, и поля внутри неё наезжали друг на друга
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._folder: Path | None = None
        self._start = 0.0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        row = QWidget(self)
        row.setFixedHeight(BAR_HEIGHT)
        # Expanding обязателен: по умолчанию QWidget держит размер 100 и
        # не растягивается вместе с родителем, из-за чего элементы внутри
        # выходят за пределы строки
        row.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(10)

        # Фиксированная ширина через setFixedWidth, но снятое ограничение
        # minimum позволяет разметке сжать элемент на узкой панели.
        # Ширина колонки с этапом считается по реальному шрифту и задаётся
        # жёстко: сжимать заголовок нельзя, иначе он наезжает на полосу и
        # ломает всю раскладку. Не помещается — прячем второстепенные поля.
        self._stage = _ElidedStrong(row)
        longest = max((*_STAGE_TITLES.values(), "Сбор не удался"), key=len)
        self._stage_width = min(
            self._stage.fontMetrics().horizontalAdvance(longest) + 8, STAGE_WIDTH_MAX
        )
        # Preferred, а не Fixed: при Fixed заголовок держит максимум и не
        # даёт строке сжаться, из-за чего она выходит за панель
        self._stage.setMaximumWidth(self._stage_width)
        self._stage.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        layout.addWidget(self._stage)

        # Одна полоса на оба случая: с процентом и без него.
        # Полоса держит свой размер всегда: сжимать её до нуля незачем,
        # вместо этого при нехватке места скрываются второстепенные поля.
        self._track = _ProgressTrack(row)
        # Полоса держит размер на широкой панели и сжимается на узкой,
        # но не до нуля: иначе теряется сам смысл показа
        self._track.setFixedHeight(PROGRESS_HEIGHT)
        self._track.setMaximumWidth(PROGRESS_WIDTH)
        self._track.setMinimumWidth(TRACK_MIN_WIDTH)
        self._track.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        layout.addWidget(self._track)

        self._percent = CaptionLabel("", row)
        self._percent.setMaximumWidth(PERCENT_WIDTH)
        self._percent.setMinimumWidth(0)
        self._percent.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        layout.addWidget(self._percent)

        # Подробность забирает остаток и сокращается многоточием.
        # Expanding, а не Ignored: при Ignored разметка отдаёт ей ноль
        # ширины и на её место сдвигается следующий элемент
        self._detail = _ElidedCaption(row)
        self._detail_min = 70
        self._detail.setMinimumWidth(0)
        self._detail.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        layout.addWidget(self._detail, 1)

        self._elapsed = CaptionLabel("", row)
        layout.addWidget(self._elapsed)

        self._open_btn = TransparentToolButton(FluentIcon.FOLDER, row)
        self._open_btn.setToolTip("Открыть папку с архивом")
        self._open_btn.setFixedSize(24, 24)
        self._open_btn.setEnabled(False)
        self._open_btn.hide()
        self._open_btn.clicked.connect(self._open_folder)
        layout.addWidget(self._open_btn)

        # Явное растяжение по горизонтали: без него внутренний ряд
        # остаётся размером по умолчанию (100 px), а поля внутри
        # выходят за пределы строки
        outer.addWidget(row, 1)
        outer.addWidget(_Separator(self), 0)

        # На узкой панели зона коллекторов остаётся ~300 px, а сумма
        # фиксированных ширин больше. Разбивка подстраивается под место,
        # иначе элементы наезжают друг на друга.
        self._row = row
        self._relayout()

        # Обновления идут пачками, поэтому отсчёт ведётся по последнему
        # событию, а не по времени жизни виджета
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.setInterval(AUTO_HIDE_MS)
        self._hide_timer.timeout.connect(self.hide)

        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._tick)

        self.hide()

    # ── обновление из фоновой задачи ─────────────────────────────────

    def show_progress(self, progress: Progress) -> None:
        """Показать очередное состояние сбора."""
        self._start = time.monotonic() - progress.elapsed
        self._open_btn.hide()
        self._stage.setText(_STAGE_TITLES.get(progress.stage, progress.stage))
        self._detail.setText(progress.detail)
        self._track.set_fill_color("accent")
        self._track.set_busy(progress.percent < 0)
        if progress.percent >= 0:
            self._track.set_percent(progress.percent)
            self._percent.setText(f"{progress.percent}%")
        else:
            # точной величины нет: полоса бегает, чтобы было видно, что идёт работа
            self._percent.setText("")

        self._tick()
        self._restart_hide()
        if not self._tick_timer.isActive():
            self._tick_timer.start()
        self.show()
        # Ширина становится известна только после показа, поэтому
        # разметка пересчитывается ещё раз уже по факту
        self._relayout()

    def show_done(self, detail: str, folder: Path | None = None) -> None:
        """Сбор завершён: итог и кнопка открытия папки."""
        self._tick_timer.stop()
        self._track.set_fill_color("accent")
        self._track.set_busy(False)
        self._track.set_percent(100)
        self._percent.setText("100%")
        self._stage.setText("Готово")
        self._detail.setText(detail)
        self._elapsed.setText(f"Прошло: {self._format(self._elapsed_now())}")
        self._folder = folder
        if folder is not None:
            self._open_btn.setEnabled(True)
            self._open_btn.show()
        self._restart_hide()
        self.show()

    def show_error(self, message: str) -> None:
        """Сбор не удался."""
        self._tick_timer.stop()
        self._track.set_fill_color("error")
        self._track.set_busy(False)
        self._track.set_percent(0)
        self._percent.setText("")
        self._stage.setText("Сбор не удался")
        self._detail.setText(message)
        self._open_btn.hide()
        self._restart_hide()
        self.show()

    # ── внутреннее ───────────────────────────────────────────────────

    #: Горизонтальные отступы и промежуток строки, нужны для расчёта
    #: доступного места во время переразметки.
    _H_MARGIN = 24
    _H_SPACING = 10

    #: Места нужно столько, чтобы поместились заголовок, полоса,
    #: подробность и счётчик времени.
    _WIDE_ENOUGH = PROGRESS_WIDTH + 150 + 110 + 40

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._relayout()

    def _relayout(self) -> None:
        """Скрыть второстепенные поля, если панели не хватает ширины.

        Заголовок, полоса и подробность показываются всегда: без них
        строка теряет смысл. Числа уступают им первыми, а длинный текст
        сокращается многоточием.
        """
        panel = self.parentWidget()
        available = (panel.width() if panel else self.width()) - self._H_MARGIN
        if available <= 0:
            return

        self._stage.setVisible(True)
        self._track.setVisible(True)
        self._detail.setVisible(True)
        self._elapsed.setVisible(available >= self._WIDE_ENOUGH)
        self._percent.setVisible(available >= self._WIDE_ENOUGH + PERCENT_WIDTH)

    def _restart_hide(self) -> None:
        self._hide_timer.start()

    def _elapsed_now(self) -> float:
        if not self._start:
            self._start = time.monotonic()
        return time.monotonic() - self._start

    def _tick(self) -> None:
        self._elapsed.setText(self._format(self._elapsed_now()))

    @staticmethod
    def _format(seconds: float) -> str:
        total = int(seconds)
        if total < 60:
            return f"{total} с"
        return f"{total // 60} мин {total % 60} с"

    def _open_folder(self) -> None:
        if self._folder is None:
            return
        try:
            open_in_explorer(self._folder)
        except Exception as exc:
            logger.error("Не удалось открыть папку с архивом: %s", exc)


class CollectBridge(QObject):
    """Передаёт ход сбора из фонового потока в GUI.

    Фоновая задача asyncio не может трогать виджеты напрямую, поэтому
    значения отправляются сигналом, а слоты выполняются в потоке GUI.
    """

    progress = Signal(object)

    def publish(self, progress: Progress) -> None:
        self.progress.emit(progress)


__all__ = ["AUTO_HIDE_MS", "BAR_HEIGHT", "CollectBridge", "CollectStatusBar"]
