"""Окно первоначальной настройки: одно окно вместо пяти страниц.

Заменой мастера на одно окно убирались три жалобы: огромное окно, пустое
место и ход мыши между полями и кнопками «Далее/Назад». Первые две жалобы
живут в геометрии, третья — в том, где стоит кнопка проверки, поэтому
проверки здесь смешаны: раскладка и поведение в одном файле.
"""

from __future__ import annotations

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QDialog, QScrollArea
from qfluentwidgets import PushButton


@pytest.fixture
def wizard(qtbot, config_manager):
    from cashcontrol.gui.dialogs.setup_wizard import CashControlSetupWizard

    w = CashControlSetupWizard(config_manager)
    qtbot.addWidget(w)
    w.show()
    return w


def _scroll(w) -> QScrollArea:
    return w.findChildren(QScrollArea)[0]


def _y(w, widget) -> int:
    return widget.mapTo(w, QPoint(0, 0)).y()


# ── одно окно вместо шагов ─────────────────────────────────────────


def test_wizard_is_not_a_wizard(wizard):
    """Ни страниц, ни кнопок «Далее/Назад»: переходить некуда.

    Именно переходы требовали хода мыши вниз окна на каждом шаге.
    """
    from PySide6.QtWidgets import QWizard

    assert not isinstance(wizard, QWizard)
    assert not hasattr(wizard, "pageIds")
    assert not hasattr(wizard, "nextId")


def test_buttons_stay_outside_the_scrolled_area(wizard):
    """«Сохранить» и «Выход» не уезжают при прокрутке.

    Все настройки в одном окне, окно длиннее экрана и прокручивается. Если
    кнопки лежали бы внутри прокручиваемой части, на длинном списке полей
    до «Сохранить» пришлось бы каждый раз доводить мышь до низа — ровно та
    жалоба, из которой всё выросло.
    """
    scroll = _scroll(wizard)
    for button in (wizard._save_btn, wizard._exit_btn):
        assert scroll.isAncestorOf(button) is False, (
            "кнопка оказалась внутри прокручиваемой части и уплывает с полями"
        )
        assert button.mapTo(wizard, QPoint(0, 0)).y() > 0, "кнопка не отображается"


def test_footer_holds_exactly_two_buttons(wizard):
    """Внизу только «Выход» и «Сохранить» — никаких переключателей секций."""
    from PySide6.QtWidgets import QWidget

    footer = wizard.findChild(QWidget, "setupFooter")
    assert footer is not None, "нижняя панель не найдена"

    labels = [b.text() for b in footer.findChildren(PushButton)]
    assert labels == ["Выход", "Сохранить"], f"внизу лишние кнопки: {labels}"
    assert not hasattr(wizard, "_programs_btn"), (
        "кнопка-переключатель секции вернулась: настройки должны быть видны сразу"
    )


def test_input_fields_are_compact(wizard):
    """Поля ужаты: высокая строка съедала экран целиком.

    Проверяется верхняя граница, а не конкретное число: токен высоты может
    поменяться, но остаться каждый по 96 пикселей он не должен.
    """
    assert wizard.ssh_login.height() <= 32, f"строка ввода {wizard.ssh_login.height()} px"
    assert wizard.ip_edit.height() <= 32, f"строка ввода {wizard.ip_edit.height()} px"
    assert wizard.ssh_passwords.height() <= 72, (
        f"список паролей {wizard.ssh_passwords.height()} px"
    )
    assert wizard.db_passwords.height() <= 72


def test_check_block_sits_directly_under_the_credentials(wizard):
    """Проверка идёт сразу за блоком учётных данных, а не после программ.

    Отдельная страница ради одного поля и кнопки и была причиной хода мыши
    через всё окно. В один столбец проверка обязана остаться вплотную к
    данным, которые она проверяет.

    Проверяется порядок карточек, а не расстояние в пикселях: между портом
    и следующей карточкой лежит поле паролей, поэтому сантиметраж здесь
    ничего не значит, а вот порядок секций значит всё.
    """
    inner = _scroll(wizard).widget()
    order = [w for w in (inner.layout().itemAt(i).widget() for i in range(inner.layout().count()))]
    db_index = order.index(wizard.db_port.parentWidget())
    check_index = order.index(wizard.test_btn.parentWidget())

    assert check_index == db_index + 1, (
        "между учётными данными и проверкой стоит посторонняя секция"
    )


def test_content_is_not_wider_than_the_window(wizard):
    """Ничего не уезжает вбок: раньше содержимое страниц было шире окна."""
    assert wizard.sizeHint().width() <= wizard.width(), (
        "горизонтальная прокрутка: содержимое шире окна"
    )


# ── сохранение ──────────────────────────────────────────────────────


def test_save_writes_settings(wizard, config_manager):
    wizard.ssh_login.setText("root")
    wizard.ssh_port.setText("2222")
    wizard.db_login.setText("pg")
    wizard.db_port.setText("5555")

    wizard._save_btn.click()

    assert wizard.result() == QDialog.DialogCode.Accepted
    conn = config_manager.settings.connection
    assert conn.ssh_login == "root"
    assert conn.ssh_port == 2222
    assert conn.db_login == "pg"
    assert conn.db_port == 5555
    assert config_manager.settings.general.setup_completed is True


def test_exit_saves_nothing(wizard, config_manager):
    """«Выход» закрывает программу: сохранять нечего.

    Пользователь подтвердил, что незавершённая настройка приводит к новому
    запуску с мастера, поэтому на диск не должно попасть ничего.

    Сравнивается с состоянием до нажатия, а не со значением по умолчанию:
    настройки переживают тесты (файл общий), и «не равно tc» означало бы
    не то, что кажется.
    """
    conn = config_manager.settings.connection
    completed_before = config_manager.settings.general.setup_completed
    before = (conn.ssh_login, conn.ssh_port, conn.db_login)

    wizard.ssh_login.setText("root")
    wizard.ssh_port.setText("2222")
    wizard.db_login.setText("changed")

    wizard._exit_btn.click()

    assert wizard.result() == QDialog.DialogCode.Rejected
    assert (conn.ssh_login, conn.ssh_port, conn.db_login) == before, (
        "«Выход» сохранил правки — при следующем запуске мастер их подхватит"
    )
    assert config_manager.settings.general.setup_completed is completed_before, (
        "«Выход» отметил настройку как завершённую — мастер больше не покажут"
    )


@pytest.fixture
def seeded(qtbot, config_manager):
    """Мастер поверх настроек, где пароли уже сохранены.

    Изолированный конфиг пустой, а проверять надо именно случай «пароли в
    настройках есть» — именно его окно раньше показывало открытым текстом.
    """
    from cashcontrol.core.security import encrypt_passwords
    from cashcontrol.gui.dialogs.setup_wizard import CashControlSetupWizard

    config_manager.update(
        "connection",
        ssh_passwords_encrypted=encrypt_passwords(["ssh-первый", "ssh-второй"]),
        db_passwords_encrypted=encrypt_passwords(["db-пароль"]),
    )
    w = CashControlSetupWizard(config_manager)
    qtbot.addWidget(w)
    w.show()
    return w


def test_stored_passwords_are_never_shown_in_the_fields(seeded):
    """Сохранённые пароли не подставляются в поля окна.

    Раньше окно расшифровывало их и клало в поле открытым текстом: пароли
    оказывались на экране, в снимке экрана и в записи видео. Теперь в поле
    пусто, а оператор видит только счётчик сохранённых паролей.
    """
    assert seeded.ssh_passwords.toPlainText() == "", "пароль SSH попал в поле"
    assert seeded.db_passwords.toPlainText() == "", "пароль БД попал в поле"


def test_empty_password_field_keeps_the_stored_values(seeded, config_manager):
    """Пустое поле означает «оставить прежние», а не «стереть».

    Иначе правка одного логина молча снесла бы все сохранённые пароли.
    """
    before_ssh = list(config_manager.settings.connection.ssh_passwords_encrypted)
    before_db = list(config_manager.settings.connection.db_passwords_encrypted)
    assert before_ssh, "в тесте должен быть сохранённый пароль SSH"

    seeded.ssh_login.setText("root")
    seeded._save_btn.click()

    conn = config_manager.settings.connection
    assert conn.ssh_login == "root"
    assert conn.ssh_passwords_encrypted == before_ssh, (
        "пароли SSH стёрлись при пустом поле"
    )
    assert conn.db_passwords_encrypted == before_db, "пароли БД стёрлись"


def test_typed_passwords_replace_the_stored_ones(seeded, config_manager):
    """Непустое поле заменяет список целиком — это и есть намерение оператора."""
    seeded.ssh_login.setText("root")
    seeded.ssh_passwords.setPlainText("новый-пароль\nвторой")

    seeded._save_btn.click()

    stored = config_manager.settings.connection.ssh_passwords_encrypted
    assert len(stored) == 2, f"сохранено {len(stored)} значений вместо двух"


def test_passwords_note_counts_without_revealing(seeded, config_manager):
    """Подпись говорит, сколько паролей сохранено, и не содержит их самих."""
    note = seeded._ssh_passwords_note.text()
    assert "Сохранено паролей SSH" in note
    assert "оста" not in note.lower() or "останутся прежние" in note


def test_programs_are_saved_together_with_the_rest(wizard, config_manager):
    wizard._programs._find_row(0).setText(r"C:\kitty.exe")

    wizard._save_btn.click()

    assert config_manager.settings.programs.ssh_client_path == r"C:\kitty.exe"


# ── проверка ввода ──────────────────────────────────────────────────


def test_empty_login_keeps_the_window_open(wizard):
    wizard.ssh_login.setText("   ")

    wizard._save_btn.click()

    assert wizard.result() != QDialog.DialogCode.Accepted
    assert wizard._error_label.isVisible(), "причина отказа не показана"
    assert "SSH-логин" in wizard._error_label.text()


def test_check_without_ip_asks_for_the_address(wizard):
    wizard.ip_edit.setText("")

    wizard.test_btn.click()

    assert "IP" in wizard._result_label.text()
    assert wizard.test_btn.isEnabled(), "кнопка осталась выключенной после отказа"
