"""
Project backup script — создаёт полный бэкап проекта.

Создаёт ZIP-архив с исходниками + экспортирует весь код в .md файлы
для передачи в следующий чат при поэтапной разработке.

Формат бэкапа:
    backup_YYYY-MM-DD_HH-MM-SS.zip — ZIP с исходниками
    all_python_code.md — весь Python код
    all_styles.md — все QSS стили
    all_json.md — все JSON файлы
    all_toml.md — все TOML файлы

Игнорируются: venv/, __pycache__/, .git/, *.pyc, *.pyo, .md, .txt, картинки

Usage:
    python scripts/backup_project.py
"""

from __future__ import annotations

import sys
import zipfile
from datetime import datetime
from pathlib import Path


def get_project_root() -> Path:
    """Получить корень проекта (где pyproject.toml)."""
    script_dir = Path(__file__).parent
    return script_dir.parent.resolve()


def should_ignore(path: Path, ignore_patterns: list[str]) -> bool:
    """Проверить, нужно ли игнорировать файл/папку."""
    path_str = str(path)
    for pattern in ignore_patterns:
        if pattern in path_str:
            return True
    return False


def create_zip_backup(project_root: Path, output_dir: Path) -> Path:
    """
    Создать ZIP-архив проекта.

    Args:
        project_root: Корень проекта
        output_dir: Куда сохранить архив

    Returns:
        Путь к созданному архиву
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    zip_path = output_dir / f"backup_{timestamp}.zip"

    ignore_patterns = [
        "__pycache__",
        ".git",
        ".pyc",
        ".pyo",
        "venv",
        "env",
        "ENV",
        ".build",
        ".dist",
        ".onefile-build",
        "*.egg-info",
    ]

    print(f"Creating ZIP backup: {zip_path.name}")

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in project_root.rglob("*"):
            if should_ignore(item, ignore_patterns):
                continue

            if item.is_file():
                arcname = item.relative_to(project_root)
                zf.write(item, arcname)
                print(f"  + {arcname}")

    print(f"✓ ZIP backup created: {zip_path}")
    return zip_path


def export_code_to_markdown(project_root: Path, output_dir: Path) -> None:
    """
    Экспортировать весь код проекта в .md файлы.

    Создаёт отдельные файлы для Python, QSS, JSON, TOML.
    """
    ignore_patterns = [
        "__pycache__",
        ".git",
        "venv",
        "env",
        ".md",  # Игнорируем .md файлы
        ".txt",  # Игнорируем .txt
    ]

    # Python код
    python_md = output_dir / "all_python_code.md"
    python_files = []

    # QSS стили
    qss_md = output_dir / "all_styles.md"
    qss_files = []

    # JSON файлы
    json_md = output_dir / "all_json.md"
    json_files = []

    # TOML файлы
    toml_md = output_dir / "all_toml.md"
    toml_files = []

    # Сканируем проект
    for item in project_root.rglob("*"):
        if should_ignore(item, ignore_patterns):
            continue

        if not item.is_file():
            continue

        # Определяем тип файла
        if item.suffix == ".py":
            python_files.append(item)
        elif item.suffix == ".qss":
            qss_files.append(item)
        elif item.suffix == ".json":
            json_files.append(item)
        elif item.suffix == ".toml":
            toml_files.append(item)

    # Экспорт Python
    if python_files:
        with open(python_md, "w", encoding="utf-8") as f:
            f.write("# Python Code — CashControl\n\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write("---\n\n")

            for py_file in sorted(python_files):
                rel_path = py_file.relative_to(project_root)
                f.write(f"## File: {rel_path}\n\n")
                f.write("```python\n")
                try:
                    content = py_file.read_text(encoding="utf-8")
                    f.write(content)
                except Exception as e:
                    f.write(f"# Error reading file: {e}\n")
                f.write("\n```\n\n---\n\n")

        print(f"✓ Exported {len(python_files)} Python files to {python_md.name}")

    # Экспорт QSS
    if qss_files:
        with open(qss_md, "w", encoding="utf-8") as f:
            f.write("# QSS Styles — CashControl\n\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write("---\n\n")

            for qss_file in sorted(qss_files):
                rel_path = qss_file.relative_to(project_root)
                f.write(f"## File: {rel_path}\n\n")
                f.write("```css\n")
                try:
                    content = qss_file.read_text(encoding="utf-8")
                    f.write(content)
                except Exception as e:
                    f.write(f"/* Error reading file: {e} */\n")
                f.write("\n```\n\n---\n\n")

        print(f"✓ Exported {len(qss_files)} QSS files to {qss_md.name}")

    # Экспорт JSON
    if json_files:
        with open(json_md, "w", encoding="utf-8") as f:
            f.write("# JSON Files — CashControl\n\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write("---\n\n")

            for json_file in sorted(json_files):
                rel_path = json_file.relative_to(project_root)
                f.write(f"## File: {rel_path}\n\n")
                f.write("```json\n")
                try:
                    content = json_file.read_text(encoding="utf-8")
                    f.write(content)
                except Exception as e:
                    f.write(f"// Error reading file: {e}\n")
                f.write("\n```\n\n---\n\n")

        print(f"✓ Exported {len(json_files)} JSON files to {json_md.name}")

    # Экспорт TOML
    if toml_files:
        with open(toml_md, "w", encoding="utf-8") as f:
            f.write("# TOML Files — CashControl\n\n")
            f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write("---\n\n")

            for toml_file in sorted(toml_files):
                rel_path = toml_file.relative_to(project_root)
                f.write(f"## File: {rel_path}\n\n")
                f.write("```toml\n")
                try:
                    content = toml_file.read_text(encoding="utf-8")
                    f.write(content)
                except Exception as e:
                    f.write(f"# Error reading file: {e}\n")
                f.write("\n```\n\n---\n\n")

        print(f"✓ Exported {len(toml_files)} TOML files to {toml_md.name}")


def main() -> int:
    """Main entry point."""
    project_root = get_project_root()
    output_dir = project_root

    print("=" * 60)
    print("CashControl — Project Backup")
    print("=" * 60)
    print(f"Project root: {project_root}")
    print()

    # Создаём ZIP бэкап
    zip_path = create_zip_backup(project_root, output_dir)
    print()

    # Экспортируем код в markdown
    export_code_to_markdown(project_root, output_dir)
    print()

    print("=" * 60)
    print("✓ Backup completed successfully!")
    print("=" * 60)
    print()
    print(f"ZIP archive: {zip_path.name}")
    print("Markdown exports:")
    print("  - all_python_code.md")
    print("  - all_styles.md")
    print("  - all_json.md")
    print("  - all_toml.md")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())