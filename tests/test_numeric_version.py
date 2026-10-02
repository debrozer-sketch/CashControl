"""Числовая часть версии в сборщике.

`AssemblyVersion` и `AssemblyFileVersion` требуют строго `a.b.c.d`, и `csc`
отказывается компилировать нечисловую строку с CS0647. Метка версии при этом
может быть любой: сборка `Vova_Edition` падала именно на этом, и ошибка
всплывала только на машине сборки.

Тест живёт здесь, а не рядом со скриптом, потому что `testpaths` в
`pyproject.toml` указывает только на `tests/`.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parent.parent / "scripts" / "build_dist.py"
)


def _numeric_version():
    spec = importlib.util.spec_from_file_location("build_dist_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.numeric_version


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        # Обычный релизный номер: точки сохраняются. Раньше цифры сдвигались
        # вместе, и 3.8.6 превращалось в 386.0.0.0 — это уже другая версия.
        ("3.8.6", "3.8.6.0"),
        ("3.8.5", "3.8.5.0"),
        # Метка с буквами и разделителями: цифры всё равно читаются.
        ("3.8.6-beta", "3.8.6.0"),
        ("v9.99.100-test", "9.99.100.0"),
        ("2024.1", "2024.1.0.0"),
        # Метка вообще без цифр.
        ("Vova_Edition", "0.0.0.0"),
        ("Vova Edition", "0.0.0.0"),
        ("", "0.0.0.0"),
        # Одна цифра дополняется нулями.
        ("7", "7.0.0.0"),
        # Лишние части отбрасываются: AssemblyVersion принимает четыре.
        ("1.2.3.4.5", "1.2.3.4"),
        # Переполнение ограничено, иначе csc отвергнет сборку.
        ("999999.1.1", "65535.1.1.0"),
    ],
)
def test_numeric_version(label, expected):
    assert _numeric_version()(label) == expected


@pytest.mark.parametrize(
    "label",
    ["3.8.6", "Vova_Edition", "0", "2024.1", "999999.1.1"],
)
def test_always_four_numbers(label):
    """Ровно четыре числа через три точки: иначе атрибут не соберётся."""
    result = _numeric_version()(label)
    parts = result.split(".")
    assert len(parts) == 4, f"{label!r} дал {result!r}"
    assert all(part.isdigit() for part in parts), f"{label!r} дал {result!r}"
    assert all(int(part) <= 65535 for part in parts), f"{label!r} дал {result!r}"


def test_launcher_template_no_longer_uses_the_label():
    """Метка не должна попадать в атрибуты сборки ни через одну подстановку."""
    source = SCRIPT.read_text(encoding="utf-8")
    assert 'AssemblyFileVersion("{version}"' not in source, (
        "в шаблоне лаунчера снова появилась подстановка метки: нечисловая "
        "версия уронит сборку с CS0647"
    )
    assert 'AssemblyVersion("{version}"' not in source
