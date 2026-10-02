"""Правка detection/*.toml действует без перезапуска приложения.

Регрессия: ``TypeDetector.reload()`` не вызывался никем, а
``InfoCollector.reload()`` пересобирал только карту секций. Реестр
``core/info/registry.py`` мемоизирует экземпляры коллекторов, поэтому
возвращался прежний ``CashTypeCollector`` вместе со старым
``TypeDetector``: правило в detection/*.toml редактировали, а оно не
вступало в силу до перезапуска программы.
"""

from __future__ import annotations

import pytest

from cashcontrol.core.cash_types.detector import TypeDetector
from cashcontrol.core.info import registry
from cashcontrol.core.info.collectors.cash_type import CashTypeCollector
from cashcontrol.core.info.info_manager import InfoCollector

_RULE = """
[[rules]]
id = "{rid}"
strategy = "xml_keywords"
priority = {prio}
path = "/tmp/{rid}.xml"
keywords = ["{kw}"]
"""


@pytest.fixture
def detection_dir(tmp_path, monkeypatch):
    """Подменить каталог detection/ и сбросить мемоизацию реестра."""
    from cashcontrol.infrastructure import path_resolver

    d = tmp_path / "detection"
    d.mkdir()
    monkeypatch.setattr(path_resolver, "get_detection_dir", lambda: d)

    registry.invalidate_collectors()
    yield d
    registry.invalidate_collectors()


def _write(d, rid: str, prio: int, kw: str) -> None:
    (d / f"{rid}.toml").write_text(
        _RULE.format(rid=rid, prio=prio, kw=kw), encoding="utf-8"
    )


# ── TypeDetector ───────────────────────────────────────────────────────

def test_detector_picks_up_new_rule_file(detection_dir):
    _write(detection_dir, "новое", 1, "SCANNER_X")
    detector = TypeDetector()
    assert any(r["id"] == "новое" for r in detector.rules)

    _write(detection_dir, "ещё", 2, "SCANNER_Y")
    detector.reload()
    ids = {r["id"] for r in detector.rules}
    assert "ещё" in ids, "новый файл правил не подхватился после reload()"


def test_detector_reload_sees_changed_content(detection_dir):
    _write(detection_dir, "правило", 1, "БЫЛОЕ_СЛОВО")
    detector = TypeDetector()
    assert any("БЫЛОЕ_СЛОВО" in str(r.get("keywords")) for r in detector.rules)

    _write(detection_dir, "правило", 1, "НОВОЕ_СЛОВО")
    detector.reload()
    kws = [str(r.get("keywords")) for r in detector.rules]
    assert any("НОВОЕ_СЛОВО" in k for k in kws), "изменённое содержимое не перечитано"
    assert not any("БЫЛОЕ_СЛОВО" in k for k in kws)


def test_detector_reload_handles_removed_file(detection_dir):
    _write(detection_dir, "временное", 1, "X")
    detector = TypeDetector()
    assert any(r["id"] == "временное" for r in detector.rules)

    (detection_dir / "временное.toml").unlink()
    detector.reload()
    assert not any(r["id"] == "временное" for r in detector.rules)


# ── CashTypeCollector ──────────────────────────────────────────────────

def test_cash_type_collector_reload_refreshes_detector(detection_dir):
    _write(detection_dir, "правило", 1, "СТАРОЕ")
    collector = CashTypeCollector()
    assert any("СТАРОЕ" in str(r.get("keywords")) for r in collector._detector.rules)

    _write(detection_dir, "правило", 1, "СВЕЖЕЕ")
    collector.reload()

    kws = [str(r.get("keywords")) for r in collector._detector.rules]
    assert any("СВЕЖЕЕ" in k for k in kws), "reload() коллектора не обновил детектор"


# ── реестр и InfoCollector ─────────────────────────────────────────────

def test_registry_returns_fresh_instance_after_invalidation():
    first = registry.get_collector("cash_type")
    assert isinstance(first, CashTypeCollector)

    registry.invalidate_collectors()
    second = registry.get_collector("cash_type")

    assert first is not second, "реестр вернул закэшированный экземпляр"


def test_info_collector_reload_picks_up_new_detection_rule(detection_dir):
    """Главный сценарий: как в settings_dialog при сохранении настроек."""
    _write(detection_dir, "для_проверки", 1, "МАРКЕР_ДО")
    info = InfoCollector()
    info.reload()

    before = info._collectors["cash_type"]
    assert any(
        "МАРКЕР_ДО" in str(r.get("keywords")) for r in before._detector.rules
    )

    _write(detection_dir, "для_проверки", 1, "МАРКЕР_ПОСЛЕ")
    info.reload()

    after = info._collectors["cash_type"]
    kws = [str(r.get("keywords")) for r in after._detector.rules]
    assert any("МАРКЕР_ПОСЛЕ" in k for k in kws), (
        "правка detection/*.toml не вступила в силу после reload(): "
        "реестр вернул закэшированный коллектор со старым TypeDetector"
    )
    assert before is not after


def test_info_collector_reload_keeps_section_map_intact(detection_dir):
    info = InfoCollector()
    info.reload()
    before = set(info._collectors)
    info.reload()
    assert set(info._collectors) == before


def test_invalidate_collectors_is_exposed():
    """Функция сброса должна быть публичной и объяснять, зачем она."""
    import inspect

    assert callable(registry.invalidate_collectors)
    doc = inspect.getdoc(registry.invalidate_collectors) or ""
    assert "detection" in doc and "CashTypeCollector" in doc, (
        "докстринг должен объяснять, что сброс нужен для применения правок "
        "detection/*.toml"
    )
