"""seed_defaults must copy only missing defaults and never touch user files."""

import logging

import pytest

from cashcontrol.infrastructure import seed_defaults


@pytest.fixture()
def app_root(tmp_path, monkeypatch):
    logging.getLogger("cashcontrol.infrastructure").disabled = True
    monkeypatch.setattr(seed_defaults, "get_app_root", lambda: tmp_path)
    return tmp_path


def _file(path, content="x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_seeds_missing_files_only(app_root):
    _file(app_root / "defaults" / "commands" / "restart.toml")
    _file(app_root / "defaults" / "commands" / "sub" / "nested.toml")
    _file(app_root / "defaults" / "collectors" / "dns.toml")

    _file(app_root / "commands" / "restart.toml", "USER_EDITED")
    _file(app_root / "commands" / "user_custom.toml", "KEEP_ME")

    assert seed_defaults.seed_defaults() == 2

    assert (app_root / "commands" / "restart.toml").read_text(encoding="utf-8") == "USER_EDITED"
    assert (app_root / "commands" / "user_custom.toml").read_text(encoding="utf-8") == "KEEP_ME"
    assert (app_root / "commands" / "sub" / "nested.toml").read_text(encoding="utf-8") == "x"
    assert (app_root / "collectors" / "dns.toml").read_text(encoding="utf-8") == "x"


def test_no_defaults_dir_returns_zero(app_root):
    assert seed_defaults.seed_defaults() == 0


def test_defaults_do_not_overwrite_existing_files(app_root):
    _file(app_root / "defaults" / "cash_types" / "w5.toml", "NEW")
    _file(app_root / "cash_types" / "w5.toml", "OLD")

    assert seed_defaults.seed_defaults() == 0
    assert (app_root / "cash_types" / "w5.toml").read_text(encoding="utf-8") == "OLD"
