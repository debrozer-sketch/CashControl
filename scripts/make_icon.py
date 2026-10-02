"""Сборка многоразмерной иконки icon.ico из исходного рисунка.

В репозитории лежит `icon.ico` с единственным изображением 256×256.
Windows для панели задач, Проводника и списка установленных программ
просит 16/24/32/48/64/128/256. Когда в файле только 256, система сама
уменьшает картинку, и в мелких местах иконка выглядит размытой либо не
показывается вовсе.

Скрипт пересобирает оба места (`icon.ico` в корне и
`src/cashcontrol/gui/resources/icon.ico`), добавляя недостающие размеры
сглаженным уменьшением. Записи в контейнере ICO хранятся как PNG —
Windows так понимает, и файл остаётся небольшим.

Запуск:  python scripts/make_icon.py
"""

from __future__ import annotations

import os
import struct
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QIcon, QImage

ROOT = Path(__file__).resolve().parent.parent
TARGETS = (
    ROOT / "icon.ico",
    ROOT / "src" / "cashcontrol" / "gui" / "resources" / "icon.ico",
)
SIZES = (16, 24, 32, 48, 64, 128, 256)


def load_largest(path: Path) -> QImage:
    """Самое большое изображение из файла .ico."""
    icon = QIcon(str(path))
    sizes = icon.availableSizes()
    if not sizes:
        raise SystemExit(f"в {path.name} нет ни одного изображения")
    biggest = max(sizes, key=lambda s: s.width())
    image = icon.pixmap(biggest).toImage().convertToFormat(QImage.Format.Format_ARGB32)
    if image.isNull():
        raise SystemExit(f"не удалось декодировать {path.name}")
    return image


def _png_bytes(image: QImage, tmp: Path, name: str) -> bytes:
    target = tmp / name
    if not image.save(str(target), "PNG"):
        raise SystemExit(f"не удалось закодировать PNG для {name}")
    return target.read_bytes()


def build(source: Path) -> bytes:
    original = load_largest(source)
    if original.width() < max(SIZES):
        raise SystemExit(
            f"исходник всего {original.width()}px, а нужен {max(SIZES)}px"
        )

    with tempfile.TemporaryDirectory(prefix="cashcontrol_icon_") as raw:
        tmp = Path(raw)
        entries: list[tuple[int, bytes]] = []
        for size in SIZES:
            scaled = original.scaled(
                size,
                size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            entries.append((size, _png_bytes(scaled, tmp, f"{size}.png")))

    header = struct.pack("<HHH", 0, 1, len(entries))
    directory = bytearray()
    body = bytearray()
    offset = 6 + 16 * len(entries)
    for size, data in entries:
        dim = 0 if size >= 256 else size
        directory += struct.pack(
            "<BBBBHHII",
            dim,
            dim,
            0,
            0,
            1,
            32,
            len(data),
            offset,
        )
        body += data
        offset += len(data)
    return header + bytes(directory) + bytes(body)


def main() -> int:
    if not TARGETS[0].is_file():
        raise SystemExit(f"нет исходной иконки: {TARGETS[0]}")
    # Без экземпляра приложения Qt работа с изображениями обрывает процесс.
    app = QGuiApplication([])
    del app
    payload = build(TARGETS[0])
    for target in TARGETS:
        target.write_bytes(payload)
        print(f"  {target.relative_to(ROOT)}: {len(payload)} байт, размеры {SIZES}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
