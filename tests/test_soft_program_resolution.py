"""Поиск внешних программ в папке soft/.

Регрессии, которые закрывает файл:

- автопоиск на этапе «Программы» мастера настройки не находил ничего,
  потому что искал имена без расширения, а в папке лежат ``.exe``;
- тот же поиск жёстко требовал ``vncviewer.exe``, тогда как
  поставляемый файл называется ``vncviewer_new.exe``;
- подписи кнопок тулбара стали 8px вместо 9px и читались плохо.

Имена кандидатов перечислены в одном месте
(``config_manager``), поиск нечувствителен к регистру и дописывает
расширение, поэтому одни и те же имена работают на Windows и Linux.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from cashcontrol.infrastructure.config_manager import (
    SSH_CLIENT_NAMES,
    VNC_CLIENT_NAMES,
    WINSCP_CLIENT_NAMES,
    ProgramsSettings,
)
from cashcontrol.infrastructure.path_resolver import find_soft_program


def _touch(folder: Path, name: str) -> Path:
    target = folder / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"stub")
    return target


# ── find_soft_program ───────────────────────────────────────────


def test_finds_exact_name(tmp_path):
    _touch(tmp_path, "kitty")
    assert find_soft_program("kitty", directory=tmp_path).name == "kitty"


def test_completes_missing_extension(tmp_path):
    _touch(tmp_path, "kitty.exe")
    assert find_soft_program("kitty", directory=tmp_path).name == "kitty.exe"


def test_strips_extension_from_candidate(tmp_path):
    _touch(tmp_path, "kitty")
    assert find_soft_program("kitty.exe", directory=tmp_path).name == "kitty"


def test_match_is_case_insensitive(tmp_path):
    _touch(tmp_path, "WinSCP.exe")
    assert find_soft_program("winscp", directory=tmp_path).name == "WinSCP.exe"


def test_first_candidate_wins(tmp_path):
    _touch(tmp_path, "vncviewer_new.exe")
    _touch(tmp_path, "vncviewer.exe")
    found = find_soft_program("vncviewer_new", "vncviewer", directory=tmp_path)
    assert found.name == "vncviewer_new.exe"


def test_falls_back_to_later_candidate(tmp_path):
    _touch(tmp_path, "vncviewer.exe")
    found = find_soft_program("vncviewer_new", "vncviewer", directory=tmp_path)
    assert found.name == "vncviewer.exe"


def test_returns_none_when_absent(tmp_path):
    _touch(tmp_path, "kitty.exe")
    assert find_soft_program("WinSCP", directory=tmp_path) is None


def test_returns_none_for_missing_directory(tmp_path):
    assert find_soft_program("kitty", directory=tmp_path / "nope") is None


def test_ignores_directories(tmp_path):
    (tmp_path / "kitty.exe").mkdir()
    assert find_soft_program("kitty", directory=tmp_path) is None


def test_shipped_soft_folder_names_are_found(tmp_path):
    """Имена из soft/README.txt обязаны находиться автопоиском."""
    for name in ("kitty.exe", "vncviewer_new.exe", "WinSCP.exe"):
        _touch(tmp_path, name)
    for names in (SSH_CLIENT_NAMES, VNC_CLIENT_NAMES, WINSCP_CLIENT_NAMES):
        assert find_soft_program(*names, directory=tmp_path) is not None


# ── ProgramsSettings ────────────────────────────────────────────


def test_default_client_points_at_existing_file(tmp_path, monkeypatch):
    _touch(tmp_path, "kitty.exe")
    monkeypatch.setattr(ProgramsSettings, "_resolve_dir", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(
        "cashcontrol.infrastructure.config_manager._IS_LINUX", False, raising=False
    )
    assert ProgramsSettings().get_ssh_client() == str(tmp_path / "kitty.exe")


def test_default_vnc_client_uses_shipped_name(tmp_path, monkeypatch):
    _touch(tmp_path, "vncviewer_new.exe")
    monkeypatch.setattr(ProgramsSettings, "_resolve_dir", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(
        "cashcontrol.infrastructure.config_manager._IS_LINUX", False, raising=False
    )
    assert ProgramsSettings().get_vnc_client() == str(tmp_path / "vncviewer_new.exe")


def test_default_client_empty_when_file_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(ProgramsSettings, "_resolve_dir", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(
        "cashcontrol.infrastructure.config_manager._IS_LINUX", False, raising=False
    )
    assert ProgramsSettings().get_ssh_client() == ""


def test_explicit_field_wins_over_folder(tmp_path, monkeypatch):
    _touch(tmp_path, "kitty.exe")
    monkeypatch.setattr(ProgramsSettings, "_resolve_dir", staticmethod(lambda: tmp_path))
    monkeypatch.setattr(
        "cashcontrol.infrastructure.config_manager._IS_LINUX", False, raising=False
    )
    s = ProgramsSettings(ssh_client_path="Z:/custom/kitty.exe")
    assert s.get_ssh_client() == "Z:/custom/kitty.exe"


# ── programs section ─────────────────────────────────────────────


@pytest.fixture
def programs_page(qapp, tmp_path, monkeypatch):
    pytest.importorskip("PySide6")
    from cashcontrol.gui.dialogs.setup_wizard import section_programs

    monkeypatch.setattr(
        section_programs, "find_soft_program",
        lambda *names: find_soft_program(*names, directory=tmp_path),
    )
    page = section_programs.ProgramsSection()
    yield page, tmp_path
    page.deleteLater()


def test_auto_find_fills_windows_layout(programs_page):
    page, folder = programs_page
    _touch(folder, "kitty.exe")
    _touch(folder, "vncviewer_new.exe")
    _touch(folder, "WinSCP.exe")

    page._auto_find()

    assert page._find_row(0).text() == str(folder / "kitty.exe")
    assert page._find_row(1).text() == str(folder / "vncviewer_new.exe")
    assert page._find_row(2).text() == str(folder / "WinSCP.exe")


def test_auto_find_fills_linux_layout(programs_page):
    page, folder = programs_page
    for name in ("kitty", "vncviewer_new", "WinSCP"):
        _touch(folder, name)

    page._auto_find()

    assert page._find_row(0).text() == str(folder / "kitty")


def test_auto_find_keeps_manual_value(programs_page):
    page, folder = programs_page
    _touch(folder, "kitty.exe")
    page._find_row(0).setText("Z:/mine/kitty.exe")

    page._auto_find()

    assert page._find_row(0).text() == "Z:/mine/kitty.exe"


def test_auto_find_reports_when_nothing_found(programs_page):
    page, _folder = programs_page

    page._auto_find()

    assert "не найден" in page.status_text().lower()


def test_set_default_uses_resolver(programs_page):
    page, folder = programs_page
    _touch(folder, "WinSCP.exe")

    page._set_default(page._find_row(2), WINSCP_CLIENT_NAMES)

    assert page._find_row(2).text() == str(folder / "WinSCP.exe")


def test_save_persists_auto_found_paths(programs_page, tmp_path):
    page, folder = programs_page
    _touch(folder, "kitty.exe")
    page._auto_find()

    config = ProgramsSettings()
    saved = {}
    page.save(type("Cfg", (), {"settings": config, "update": lambda _self, key, **kw: saved.update(kw)})())

    assert saved["ssh_client_path"] == str(folder / "kitty.exe")


# ── toolbar captions ────────────────────────────────────────────


def test_toolbar_caption_font_is_readable(qapp):
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QLabel
    from qfluentwidgets import FluentIcon

    from cashcontrol.gui.toolbar import _make_labeled_btn

    container = _make_labeled_btn(FluentIcon.APPLICATION, "Перезагрузка", "tooltip")
    try:
        labels = container.findChildren(QLabel)
        assert labels, "подпись кнопки не найдена"
        for lbl in labels:
            assert "font-size: 8px" not in lbl.styleSheet()
            assert "font-size: 9px" in lbl.styleSheet()
    finally:
        container.deleteLater()
