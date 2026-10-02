"""Файл с одними правилами не должен выглядеть как сломанный коллектор.

В `collectors/` лежат два разных формата:

* ``[collector]`` + ``[[fields]]`` — сбор данных (``_builtin_*.toml``);
* ``[[rule]]`` — проверки без кода (``ssh_old_password.toml``).

`_build_collectors` перебирал все ``*.toml`` и строил из каждого
``TomlCollector``, который требовал ``data["collector"]``. Файл с одними
правилами падал с голым ``KeyError: 'collector'``, и в лог уходило
``Коллектор ssh_old_password.toml не загружен: 'collector'`` — хотя файл
работал исправно и правило проверялось. Пользователь видит в логе ошибку
на своём рабочем файле и ищет поломку у себя.

Правила из такого файла при этом читались нормально: их разбирает
``TomlRuleChecker``, который ``[collector]`` не требует.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

RULES_ONLY = (
    "# Проверка: касса подключилась по старому SSH-паролю.\n"
    '[[rule]]\n'
    'section = "connection"\n'
    'key = "ssh_password_used"\n'
    'op = "=="\n'
    'value = "324012"\n'
    'message = "Старый пароль!"\n'
    'severity = "warning"\n'
)

COLLECTOR = (
    "[collector]\n"
    'name = "демо"\n'
    'label = "Демо"\n\n'
    "[[fields]]\n"
    'key = "uptime"\n'
    'command = "uptime"\n'
)


@pytest.fixture
def collectors_dir(tmp_path: Path, monkeypatch) -> Path:
    folder = tmp_path / "collectors"
    folder.mkdir()
    monkeypatch.setattr(
        "cashcontrol.infrastructure.path_resolver.get_collectors_dir",
        lambda: folder,
    )
    return folder


class TestRulesOnlyFileIsNotACollector:
    def test_no_warning_and_rules_still_load(self, collectors_dir, caplog):
        from cashcontrol.core.info.info_manager import get_info_collector
        from cashcontrol.core.info.toml_rules import TomlRuleChecker

        (collectors_dir / "ssh_old_password.toml").write_text(
            RULES_ONLY, encoding="utf-8"
        )

        with caplog.at_level("WARNING", logger="cashcontrol"):
            get_info_collector()._build_collectors()

        noise = [r.getMessage() for r in caplog.records if "ssh_old_password" in r.getMessage()]
        assert not noise, f"работающий файл правил не должен попадать в лог как битый: {noise}"

        rules = TomlRuleChecker().load()
        assert len(rules) == 1, "правило из того же файла обязано грузиться"
        assert rules[0].key == "ssh_password_used"

    def test_shipped_example_file_stays_quiet(self, caplog):
        """Файл из репозитория — эталон, а не тестовый синтетик."""
        from cashcontrol.infrastructure.path_resolver import get_app_root

        root = get_app_root()
        candidates = [
            root / "cashcontrol" / "collectors",
            root / "collectors",
            root / "src" / "cashcontrol" / "collectors",
        ]
        folder = next((c for c in candidates if c.is_dir()), None)
        if folder is None or not (folder / "ssh_old_password.toml").is_file():
            pytest.skip("каталог collectors не найден")

        from cashcontrol.core.info.info_manager import get_info_collector

        with caplog.at_level("WARNING", logger="cashcontrol"):
            get_info_collector()._build_collectors()

        assert not [r for r in caplog.records if "ssh_old_password" in r.getMessage()]


class TestBrokenCollectorFileSaysWhatIsWrong:
    def test_missing_collector_section_names_the_reason(self, tmp_path):
        from cashcontrol.core.info.collectors._toml_collector import TomlCollector

        path = tmp_path / "rules.toml"
        path.write_text(RULES_ONLY, encoding="utf-8")

        with pytest.raises(ValueError, match=r"\[collector\]"):
            TomlCollector(path)

    def test_missing_name_names_the_key(self, tmp_path):
        from cashcontrol.core.info.collectors._toml_collector import TomlCollector

        path = tmp_path / "half.toml"
        path.write_text(
            '[collector]\nlabel = "Без имени"\n\n[[fields]]\nkey = "k"\ncommand = "x"\n',
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="name"):
            TomlCollector(path)

    def test_valid_collector_still_loads(self, tmp_path):
        from cashcontrol.core.info.collectors._toml_collector import TomlCollector

        path = tmp_path / "good.toml"
        path.write_text(COLLECTOR, encoding="utf-8")

        tc = TomlCollector(path)
        assert tc.name == "демо"
        assert tc.label == "Демо"
        assert len(tc.fields) == 1
