"""Tests for declarative TOML problem rules (checks without Python code)."""

from pathlib import Path

import pytest

from cashcontrol.core.info.info_manager import (
    CashInfoSnapshot,
    CollectionStatus,
    InfoSection,
)
from cashcontrol.core.info.toml_rules import TomlRule, TomlRuleChecker


def _snapshot(**sections) -> CashInfoSnapshot:
    snap = CashInfoSnapshot()
    for name, data in sections.items():
        setattr(
            snap,
            name,
            InfoSection(name, CollectionStatus.COMPLETE, data=data),
        )
    return snap


class TestTomlRule:
    def test_numeric_less_with_message_value(self):
        rule = TomlRule("disk", "free", "<", 100, "мало места: {value} МБ",
                        "warning", [], "Диск")
        issue = rule.check(_snapshot(disk={"free": "50"}), "pos")
        assert issue is not None
        assert issue.message == "мало места: 50 МБ"
        assert issue.section == "Диск"
        assert rule.check(_snapshot(disk={"free": "200"}), "pos") is None

    def test_equal_string_case_insensitive(self):
        rule = TomlRule("bank", "usb", "==", "1", "EnableUSB=1")
        assert rule.check(_snapshot(bank={"usb": "1"}), "pos") is not None
        assert rule.check(_snapshot(bank={"usb": "0"}), "pos") is None

    def test_boolean_value(self):
        rule = TomlRule("drawer", "flag", "==", True, "открыт")
        assert rule.check(_snapshot(drawer={"flag": "true"}), "pos") is not None
        assert rule.check(_snapshot(drawer={"flag": "false"}), "pos") is None
        assert rule.check(_snapshot(drawer={"flag": "вообще нет"}), "pos") is None

    def test_is_null_and_not_null(self):
        is_null = TomlRule("os", "ver", "is_null", "", "нет версии")
        assert is_null.check(_snapshot(os={"ver": None}), "pos") is not None
        assert is_null.check(_snapshot(os={"ver": ""}), "pos") is not None
        assert is_null.check(_snapshot(os={"ver": "1.2"}), "pos") is None
        not_null = TomlRule("os", "ver", "not_null", "", "есть версия")
        assert not_null.check(_snapshot(os={"ver": "1.2"}), "pos") is not None
        assert not_null.check(_snapshot(os={"ver": None}), "pos") is None

    def test_contains(self):
        rule = TomlRule("os", "name", "contains", "stream", "имя содержит stream")
        assert rule.check(_snapshot(os={"name": "alt-stream 5"}), "pos") is not None
        assert rule.check(_snapshot(os={"name": "Ubuntu"}), "pos") is None

    def test_missing_section_or_key_skipped(self):
        rule = TomlRule("nope", "x", "==", "1", "")
        assert rule.check(_snapshot(os={"ver": "1"}), "pos") is None

    def test_cash_types_restriction(self):
        rule = TomlRule("os", "ver", "==", "1", "", cash_types=["sco3"])
        assert rule.applies_to("sco3")
        assert not rule.applies_to("pos")
        assert rule.check(_snapshot(os={"ver": "1"}), "pos") is None
        assert rule.check(_snapshot(os={"ver": "1"}), "sco3") is not None

    def test_invalid_op_rejected(self):
        with pytest.raises(ValueError):
            TomlRule("os", "ver", "regex", "1", "")


class TestTomlRuleChecker:
    def test_loads_rules_with_default_section(self, tmp_path: Path, monkeypatch):
        toml = tmp_path / "collectors" / "disk.toml"
        toml.parent.mkdir()
        toml.write_text(
            '[collector]\n'
            'name = "disk"\n'
            'label = "Диск"\n'
            'group = "other"\n'
            '\n'
            '[[rule]]\n'
            'key = "free"\n'
            'op = "<"\n'
            'value = 100\n'
            'message = "мало места"\n'
            '\n'
            '[[rule]]\n'
            'section = "os"\n'
            'key = "ver"\n'
            'op = "is_null"\n'
            'message = "нет версии"\n'
            'severity = "error"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "cashcontrol.infrastructure.path_resolver.get_collectors_dir",
            lambda: toml.parent,
        )
        rules = TomlRuleChecker().load()
        assert len(rules) == 2
        disk = next(r for r in rules if r.section == "disk")
        os_rule = next(r for r in rules if r.section == "os")
        assert disk.key == "free" and disk.op == "<" and disk.value == 100
        assert os_rule.severity == "error"

    def test_no_rules_dir(self, tmp_path: Path, monkeypatch):
        monkeypatch.setattr(
            "cashcontrol.infrastructure.path_resolver.get_collectors_dir",
            lambda: tmp_path / "absent",
        )
        assert TomlRuleChecker().load() == []

    def test_bad_file_and_bad_op_skipped(self, tmp_path: Path, monkeypatch):
        coll = tmp_path / "collectors"
        coll.mkdir()
        (coll / "bad.toml").write_text('not [valid', encoding="utf-8")
        (coll / "ok.toml").write_text(
            '[[rule]]\n'
            'section = "os"\n'
            'key = "ver"\n'
            'op = "regex"\n'          # unsupported op → skipped
            'value = "x"\n'
            'message = "x"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "cashcontrol.infrastructure.path_resolver.get_collectors_dir",
            lambda: coll,
        )
        assert TomlRuleChecker().load() == []

    def test_integration_with_problem_checker(self, tmp_path: Path, monkeypatch):
        coll = tmp_path / "collectors"
        coll.mkdir()
        (coll / "disk.toml").write_text(
            '[collector]\n'
            'name = "disk"\n'
            'label = "Диск"\n'
            'group = "other"\n'
            '\n'
            '[[rule]]\n'
            'key = "free"\n'
            'op = "<"\n'
            'value = 100\n'
            'message = "мало места: {value} МБ"\n',
            encoding="utf-8",
        )
        monkeypatch.setattr(
            "cashcontrol.infrastructure.path_resolver.get_collectors_dir",
            lambda: coll,
        )
        from cashcontrol.core.info.rules import ProblemChecker

        checker = ProblemChecker()
        wait_snap = _snapshot(disk={"free": "50"}, cash_type={})
        issues = checker.check(wait_snap, "pos")
        assert any(i.section == "disk" and "50" in i.message for i in issues)


class TestShippedOldPasswordRule:
    """Боевой пример: коллектор connection + правило «Старый пароль!»."""

    def test_connection_collector_reads_ssh_password(self):
        import asyncio

        from cashcontrol.core.info.collectors.connection import ConnectionCollector

        class FakeSSH:
            successful_password = "324012"

        class FakeSession:
            ssh = FakeSSH()

        data = asyncio.run(ConnectionCollector().collect(FakeSession()))
        assert data["ssh_password_used"] == "324012"
        assert data["_fields"] == []

    def test_shipped_rule_fires_on_old_password(self, tmp_path: Path, monkeypatch):
        import cashcontrol.infrastructure.path_resolver as pr

        shipped = Path(__file__).resolve().parents[1] / "collectors" / "ssh_old_password.toml"
        assert shipped.exists()
        monkeypatch.setattr(pr, "get_collectors_dir", lambda: shipped.parent)
        from cashcontrol.core.info.rules import ProblemChecker

        checker = ProblemChecker()
        old = _snapshot(connection={"ssh_password_used": "324012"})
        assert any(
            i.section == "SSH" and i.message == "Старый пароль!" and i.severity == "warning"
            for i in checker.check(old, "pos")
        )
        fresh = _snapshot(connection={"ssh_password_used": "another"})
        assert all(i.section != "SSH" for i in checker.check(fresh, "pos"))
