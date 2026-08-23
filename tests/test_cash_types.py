"""Tests for the cash_types TOML system (registry, merge, features, detection)."""

from pathlib import Path

import pytest

from cashcontrol.core.cash_types import (
    CashTypeRegistry,
    TypeDetector,
    get_cash_type_registry,
)
from cashcontrol.core.cash_types.merge import ExtendsCycleError, resolve_extends
from cashcontrol.core.cash_types.models import CashTypeDefinition


@pytest.fixture()
def registry(monkeypatch, tmp_path: Path) -> CashTypeRegistry:
    monkeypatch.setattr(
        "cashcontrol.infrastructure.path_resolver.get_cash_types_dir",
        lambda: tmp_path / "cash_types",
    )
    reg = CashTypeRegistry()
    reg.load()
    return reg


class TestBundledTypes:
    def test_four_default_types_loaded(self, registry):
        ids = set(registry.types.keys())
        assert {"pos", "touch", "sco", "sco3"} <= ids

    def test_alias_resolution(self, registry):
        assert registry.resolve("SCO_V3") == "sco3"
        assert registry.resolve("selfcheckout") == "sco"
        assert registry.resolve("nope") is None

    def test_features(self, registry):
        pos = registry.get("pos")
        assert pos is not None
        assert pos.has("keyboard") and pos.has("customer_display")
        assert not pos.has("barcode_from_db")

    def test_extends_union(self, registry):
        sco3 = registry.get("scov3")
        assert sco3 is not None and sco3.id == "sco3"
        for feature in ("fiscal_register", "barcode_from_xml", "payment_ranks", "barcode_from_db"):
            assert sco3.has(feature), feature

    def test_db_connection_sco3(self, registry):
        db = registry.get("sco3").connection.db
        assert db.enabled and db.database == "sco_v3"
        assert not registry.get("pos").connection.db.enabled


class TestMerge:
    @staticmethod
    def _make(tid, extends=None, features=(), mode="union"):
        return CashTypeDefinition(
            id=tid, extends=extends, features=set(features), features_mode=mode
        )

    def test_cycle_raises(self):
        raw = {"a": self._make("a", "b"), "b": self._make("b", "a")}
        with pytest.raises(ExtendsCycleError):
            resolve_extends(raw)

    def test_unknown_parent_raises(self):
        with pytest.raises(ValueError):
            resolve_extends({"a": self._make("a", "ghost")})

    def test_replace_mode(self):
        raw = {
            "base": self._make("base", features={"x", "y"}),
            "child": self._make("child", "base", features={"z"}, mode="replace"),
        }
        out = resolve_extends(raw)
        assert out["child"].features == {"z"}


class TestOverlay:
    def test_overlay_overrides_bundled(self, registry, tmp_path):
        overlay = tmp_path / "cash_types"
        overlay.mkdir(exist_ok=True)
        (overlay / "pos.toml").write_text(
            'features = ["keyboard"]\n\n'
            '[type]\nid = "pos"\nname = "Custom POS"\n',
            encoding="utf-8",
        )
        registry.load()
        pos = registry.get("pos")
        assert pos.name == "Custom POS"
        assert pos.features == {"keyboard"}

    def test_has_feature_helper(self, registry):
        class FakeSession:
            cash_type = "sco3"

        from cashcontrol.core.cash_types import has_feature

        assert has_feature(FakeSession(), "barcode_from_db")
        assert not has_feature(FakeSession(), "keyboard")

    def test_has_feature_unknown_type(self):
        from cashcontrol.core.cash_types import has_feature

        assert not has_feature("unknown", "db")
        assert not has_feature(None, "db")


class TestDetector:
    def test_rules_loaded(self):
        detector = TypeDetector()
        assert any(r["id"] == "crystal_register_modules" for r in detector.rules)

    def test_priority_order(self):
        detector = TypeDetector()
        priorities = [r.get("priority", 0) for r in detector.rules]
        assert priorities == sorted(priorities, reverse=True)

    def test_registry_resolves_xml_values(self):
        """The xml_keywords strategy maps XML attribute values via aliases."""
        reg = get_cash_type_registry()
        for raw, expected in (("sco_v3", "sco3"), ("SelfCheckout", "sco"), ("POS", "pos")):
            assert reg.resolve(raw) == expected
