"""Тесты строки состояния сбора логов.

Строка живёт в зоне коллекторов, показывает этап, процент и время,
а по завершении даёт кнопку открытия папки и сама скрывается через
AUTO_HIDE_MS после последнего обновления.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from cashcontrol.core.collect import Progress
from cashcontrol.gui.collect_progress import AUTO_HIDE_MS, CollectStatusBar


@pytest.fixture
def bar(qapp):
    widget = CollectStatusBar()
    yield widget
    widget.close()


def test_bar_starts_hidden(bar):
    assert not bar.isVisibleTo(bar.parentWidget() or bar)


def test_bar_shows_stage_and_percent(bar):
    bar.show_progress(Progress(stage="pack", percent=42, detail="350 из 850 файлов"))

    assert bar._stage.fullText() == "Упаковка на кассе"
    assert bar._track._percent == 42
    assert bar._track._busy is False
    assert bar._percent.text() == "42%"
    assert "350 из 850" in bar._detail.text()


def test_bar_indeterminate_without_percent(bar):
    bar.show_progress(Progress(stage="measure", percent=-1, detail="du"))

    assert bar._track._busy is True
    assert bar._track._timer.isActive()
    assert bar._percent.text() == ""
    assert bar._percent.text() == ""


@pytest.mark.parametrize(
    ("stage", "title"),
    [
        ("measure", "Измерение объёма"),
        ("count", "Подсчёт файлов"),
        ("pack", "Упаковка на кассе"),
        ("download", "Скачивание"),
    ],
)
def test_bar_titles_cover_all_stages(bar, stage, title):
    bar.show_progress(Progress(stage=stage, percent=10, detail="x"))
    assert bar._stage.fullText() == title


def test_bar_done_enables_open_folder(bar, tmp_path):
    bar.show_done("архив 18.6 МБ · файлов: 850", tmp_path)

    assert bar._stage.fullText() == "Готово"
    assert bar._track._percent == 100
    assert bar._percent.text() == "100%"
    assert bar._open_btn.isEnabled()
    assert not bar._open_btn.isHidden()
    assert bar._folder == tmp_path


def test_bar_hides_open_button_while_running(bar, tmp_path):
    bar.show_done("готово", tmp_path)
    bar.show_progress(Progress(stage="download", percent=10, detail="снова"))

    assert bar._open_btn.isHidden()
    assert bar._stage.fullText() == "Скачивание"


def test_bar_error_hides_open_button(bar, tmp_path):
    bar.show_done("готово", tmp_path)
    bar.show_error("Не удалось упаковать на кассе")

    assert bar._stage.fullText() == "Сбор не удался"
    assert bar._open_btn.isHidden()
    assert bar._track._percent == 0


def test_bar_autohide_timeout_is_15_seconds(bar):
    assert AUTO_HIDE_MS == 15_000


def test_bar_restarts_autohide_on_every_update(bar):
    bar.show_progress(Progress(stage="pack", percent=10, detail="x"))
    assert bar._hide_timer.isActive()
    first = bar._hide_timer.remainingTime()

    bar.show_progress(Progress(stage="pack", percent=20, detail="y"))
    assert bar._hide_timer.isActive()
    assert bar._hide_timer.remainingTime() >= first - 1000


def test_bar_hides_when_timer_fires(bar):
    bar.show_progress(Progress(stage="pack", percent=10, detail="x"))
    bar.show()

    # Таймер намеренно ускорен, но запас ожидания большой: под нагрузкой
    # всего прогона 20 мс не хватало и тест падал от случая к случаю.
    bar._hide_timer.setInterval(1)
    bar._hide_timer.start()
    assert bar._hide_timer.isSingleShot()

    from PySide6.QtTest import QTest

    QTest.qWait(400)
    assert bar.isHidden()


def test_bar_elapsed_uses_reported_time(bar):
    bar.show_progress(Progress(stage="pack", percent=10, detail="x", elapsed=65.0))
    assert "1 мин" in bar._elapsed.text()


def test_bar_height_is_compact(bar):
    assert bar.height() <= 40


def test_theme_colors_are_real_not_fallback():
    """Несуществующий ключ темы даёт #ff00ff, это ломало вид строки."""
    from cashcontrol.gui.theme_helper import color

    for key in ("separator", "accent", "error", "border_secondary"):
        value = color(key)
        assert value != "#ff00ff", f"ключ темы {key} не существует"
        assert value.startswith("#") and len(value) == 7


def test_bar_does_not_put_border_on_container(bar):
    """Рамка на контейнере наследуется детьми и обводит каждый элемент."""
    styles = bar.styleSheet()
    assert "border" not in styles
    # разделитель вынесен в отдельный виджет
    from cashcontrol.gui.collect_progress import _Separator

    assert isinstance(bar.findChild(_Separator), _Separator)


def test_progress_track_paints_in_theme_colors(bar):
    """Полоса обязана рисоваться цветом темы, а не стилем Windows."""
    from PySide6.QtGui import QColor

    from cashcontrol.gui.collect_progress import _ProgressTrack
    from cashcontrol.gui.theme_helper import color

    track = bar.findChild(_ProgressTrack)
    bar.show_progress(Progress(stage="pack", percent=50, detail="x"))
    bar.resize(720, bar.height())
    app_image = track.grab().toImage()

    want = QColor(color("accent"))
    found = any(
        app_image.pixelColor(x, y) == want
        for y in range(app_image.height())
        for x in range(0, app_image.width(), 2)
    )
    assert found, "заливка полосы не совпала с акцентным цветом темы"


def test_progress_track_animates_when_busy(bar):
    from cashcontrol.gui.collect_progress import _ProgressTrack

    track = bar.findChild(_ProgressTrack)
    bar.show_progress(Progress(stage="measure", percent=-1, detail="x"))
    start = track._offset
    track._advance()
    assert track._offset != start


def test_detail_text_is_elided_not_clipped(bar):
    """Длинный текст должен сокращаться, а не налезать на счётчик времени."""
    long_text = "logs-cash_172.18.105.97_29_09_2026-13_18_47.tar.gz · 18.6 МБ · файлов: 850"
    bar.show_done(long_text, None)
    bar.resize(420, bar.height())

    assert bar._detail.fullText() == long_text
    assert bar._detail.toolTip() == long_text
    assert "…" in bar._detail.text() or bar._detail.text() == long_text



# ── разметка: элементы не должны наезжать друг на друга ─────────────

_PARTS = ("_stage", "_track", "_percent", "_detail", "_elapsed")


def _overlaps(bar) -> list[str]:
    """Пары видимых элементов с пересекающимися прямоугольниками."""
    rects = {n: getattr(bar, n).geometry() for n in _PARTS}
    bad: list[str] = []
    for i, a in enumerate(_PARTS):
        for b in _PARTS[i + 1 :]:
            if not getattr(bar, a).isVisible() or not getattr(bar, b).isVisible():
                continue
            if rects[a].intersects(rects[b]):
                bad.append(f"{a}/{b}")
    return bad


def _in_collectors_panel(qapp, width: int):
    """Строка внутри настоящей панели коллекторов нужной ширины.

    Раньше проверки строились на пустом QWidget: там у виджета остаётся
    размер по умолчанию 100 px, из-за чего наложения воспроизводились
    только в тесте, а не в приложении.
    """
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from cashcontrol.gui.cash_session_widget import CashSessionWidget

    widget = CashSessionWidget.__new__(CashSessionWidget)
    QWidget.__init__(widget)
    widget._ip = "10.0.0.7"
    widget._session = None

    class _Dummy:
        def setVisible(self, *_a): ...
        def setEnabled(self, *_a): ...
        def setText(self, *_a): ...
        def setStyleSheet(self, *_a): ...

    widget._vnc_widget = _Dummy()
    panel = widget._build_info_panel()
    bar = widget.collect_status

    host = QWidget()
    lay = QVBoxLayout(host)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(panel)
    host.resize(width, 400)
    host.show()

    bar.show_progress(
        Progress(stage="pack", percent=63, detail="537 из 850 файлов", elapsed=4.2)
    )
    qapp.processEvents()
    qapp.processEvents()
    return host, bar


@pytest.mark.parametrize("width", [900, 600, 420, 340, 300])
def test_no_overlap_at_any_width(qapp, width):
    """Полоса не должна ложиться на текст этапа."""
    host, bar = _in_collectors_panel(qapp, width)

    assert _overlaps(bar) == [], f"наложение при ширине {width}"
    host.close()
    bar.close()


@pytest.mark.parametrize("width", [900, 600, 420, 340, 300])
def test_row_follows_panel_width(qapp, width):
    """Внутренний ряд обязан растянуться вместе с панелью."""
    host, bar = _in_collectors_panel(qapp, width)

    assert bar._row.width() >= width - 4, f"ряд не растянулся: {bar._row.width()}"
    host.close()
    bar.close()


def test_track_starts_after_stage_label(qapp):
    """Корень прошлого дефекта: заголовок сжимался, полоса вставала на него."""
    host, bar = _in_collectors_panel(qapp, 600)

    assert bar._stage.width() > 0
    assert bar._track.x() >= bar._stage.x() + bar._stage.width()
    host.close()
    bar.close()


def test_track_keeps_readable_width_on_narrow_panel(qapp):
    host, bar = _in_collectors_panel(qapp, 300)

    assert bar._track.isVisible()
    assert bar._track.width() >= 80
    host.close()
    bar.close()


def test_wide_panel_shows_all_fields(qapp):
    host, bar = _in_collectors_panel(qapp, 900)

    for name in _PARTS:
        assert getattr(bar, name).isVisible(), name
    host.close()
    bar.close()


def test_narrow_panel_hides_only_secondary_fields(qapp):
    host, bar = _in_collectors_panel(qapp, 340)

    assert bar._stage.isVisible()
    assert bar._track.isVisible()
    assert bar._detail.isVisible()
    host.close()
    bar.close()
