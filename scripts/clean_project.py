#!/usr/bin/env python3
"""
clean_project.py — очистка проекта CashControl от мусора.

Удаляет:
  - все папки __pycache__ и файлы *.pyc
  - папку dist/ (артефакты старых сборок)
  - папку data/update_backups/ (временные бэкапы обновлений)
  - data/local_manifest.json (пересоздаётся при запуске)
  - make_backup.py (устаревший скрипт)
  - корневые дубликаты gui/, core/, actions/, infrastructure/, __init__.py
    (если они вдруг появятся снова)

Оставляет нетронутым:
  - data/settings.json, data/sessions.json, data/keyboard_layouts/,
    data/port_mapping.json, data/usb_id_mapping.json  (пользовательские данные)
  - src/  — весь исходный код
  - commands/, docs/, modules/  — контент
  - build.bat, make_master.bat, update_manifest.bat, scripts/
  - pyproject.toml, uv.lock, CashControl.iss, icon.ico, version.txt

Использование:
    python scripts/clean_project.py
    python scripts/clean_project.py --dry-run   # показать что будет удалено
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

# Корень проекта — папка на уровень выше scripts/
PROJECT_ROOT = Path(__file__).parent.parent.resolve()


# ── Что удалять ───────────────────────────────────────────────────────────────

# Папки которые удаляются полностью (если существуют)
REMOVE_DIRS = [
    "dist",                       # артефакты сборки Nuitka
    "data/update_backups",        # временные бэкапы обновлений
    # Корневые дубликаты (остатки старой структуры)
    "gui",
    "core",
    "actions",
    "infrastructure",
]

# Файлы которые удаляются (если существуют)
REMOVE_FILES = [
    "make_backup.py",             # устаревший скрипт
    "data/local_manifest.json",   # пересоздаётся при запуске
    "__init__.py",                # корневой дубликат
]


def clean(dry_run: bool = False) -> None:
    removed = []
    skipped = []

    def _rm_dir(rel: str) -> None:
        p = PROJECT_ROOT / rel
        if p.exists() and p.is_dir():
            if dry_run:
                print(f"  [DRY] rmdir  {rel}/")
            else:
                shutil.rmtree(p)
                print(f"  ✅ rmdir  {rel}/")
            removed.append(rel + "/")
        else:
            skipped.append(rel + "/")

    def _rm_file(rel: str) -> None:
        p = PROJECT_ROOT / rel
        if p.exists() and p.is_file():
            if dry_run:
                print(f"  [DRY] rm     {rel}")
            else:
                p.unlink()
                print(f"  ✅ rm     {rel}")
            removed.append(rel)
        else:
            skipped.append(rel)

    def _rm_pycache() -> None:
        """Рекурсивно удалить все __pycache__ и *.pyc."""
        count = 0
        for cache_dir in PROJECT_ROOT.rglob("__pycache__"):
            if cache_dir.is_dir():
                if dry_run:
                    print(f"  [DRY] rmdir  {cache_dir.relative_to(PROJECT_ROOT)}/")
                else:
                    shutil.rmtree(cache_dir)
                count += 1
        for pyc in PROJECT_ROOT.rglob("*.pyc"):
            if pyc.is_file():
                if dry_run:
                    print(f"  [DRY] rm     {pyc.relative_to(PROJECT_ROOT)}")
                else:
                    pyc.unlink()
                count += 1
        if dry_run:
            print(f"  [DRY] __pycache__ / *.pyc: {count} объектов")
        else:
            print(f"  ✅ __pycache__ / *.pyc: удалено {count} объектов")
        removed.append(f"__pycache__ ({count})")

    print()
    print("=" * 56)
    print("  CashControl — очистка проекта")
    print(f"  Корень: {PROJECT_ROOT}")
    if dry_run:
        print("  РЕЖИМ: DRY RUN (ничего не удаляется)")
    print("=" * 56)
    print()

    print("📁 Папки:")
    for d in REMOVE_DIRS:
        _rm_dir(d)

    print()
    print("📄 Файлы:")
    for f in REMOVE_FILES:
        _rm_file(f)

    print()
    print("🗑  Кэш Python:")
    _rm_pycache()

    print()
    print("=" * 56)
    if dry_run:
        print(f"  DRY RUN: будет удалено {len(removed)} объектов")
    else:
        print(f"  ✅ Готово. Удалено: {len(removed)}  |  Не найдено: {len(skipped)}")
    print("=" * 56)
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Очистка проекта CashControl")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Показать что будет удалено, не удалять"
    )
    args = parser.parse_args()
    clean(dry_run=args.dry_run)