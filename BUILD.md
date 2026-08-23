# CashControl — Build & Release

## Сборка portable-версии

Требуется только [uv](https://docs.astral.sh/uv/) и интернет при первой сборке
(скачивается embedded Python ~11 МБ, кэшируется в `.build_cache/`).

```
build.bat
```

или вручную:

```
uv run python scripts/build_dist.py
```

Результат — `dist\CashControl\`: одна переносимая папка.

```
CashControl.cmd          ← запуск (pythonw + app/main)
version.txt, icon.ico
docs/ data/ logs/ commands/ collectors/ soft/ cash_types/ detection/ modules/
runtime/
  python/                ← embedded CPython + stdlib
  lib/site-packages.zip  ← чисто-Python зависимости
  lib/<pkg>/             ← пакеты с расширениями (PySide6, numpy, ...)
  app/cashcontrol/       ← код программы (.py)
```

Проверка сборки: перенести/переименовать папку → запустить `CashControl.exe`.
Пользовательские данные (`data/`) создаются при первом запуске и уезжают
вместе с папкой.

## Инсталлятор (опционально)

Требуется [Inno Setup 6](https://jrsoftware.org/isinfo.php).

```
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" CashControl.iss
```

Результат: `dist\installer\CashControl-setup-<версия>.exe` (~70 МБ).

Особенности:
- установка per-user в `{localappdata}\Programs\CashControl` — без прав
  администратора, `data/` остаётся доступной для записи;
- ярлыки: «Пуск» + рабочий стол (галочка);
- обновление поверх старой версии — тот же AppId, данные сохраняются;
- деинсталляция удаляет программу, но оставляет `data/` (настройки);
- `data/` и `logs/` никогда не попадают в payload инсталлятора
  (Excludes + purge в build_dist.py) — пароли из тестовой среды не утекут.

## Разработка

```
uv sync                                        # зависимости (CPython 3.12)
uv run python -m cashcontrol.main              # запуск из исходников
uv run pytest -q                               # тесты
uv run ruff check src tests                    # линт (должен быть чистым)
uv run python scripts/sync_version.py          # версия из version.txt → pyproject/__init__
```

## Версия и релиз

1. Правится `version.txt`, затем `uv run python scripts/sync_version.py`.
2. Коммит + push в ветку.
3. Публикуемых «апдейтеров» больше нет — распространение = копирование папки.
   Старые Nuitka/Inno-сценарии удалены (история в git).

## Горячие правки в установленной версии

Код лежит `.py` файлами в `runtime/app/cashcontrol/`. Точечный фикс можно
внести прямо там; для GUI-модулей из hot-списка (toolbar, vnc_preview,
db_viewer, dialogs, widgets) — положить файл в `modules/<путь>` поверх,
оригинал не трогая. Перечитывается при следующем запуске.
