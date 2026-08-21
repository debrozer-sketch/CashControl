# Code Quality Analysis — CashControl v3

> Generated: comprehensive audit of all Python source files

---

## CRITICAL / HIGH Severity

### 🔴 Блокирующие баги

| Файл | Строка | Проблема |
|------|--------|----------|
| `commands/Поправить_FITO.py` | 21–22 | **`NameError`**: `import asyncio` стоит **после** `await asyncio.sleep(2)` — импорт недостижим, команда всегда падает |
| `commands/Удалить_зависший_чек.py` | 52 | **Блокировка event loop**: `msg.exec()` — синхронный Qt диалог внутри `async def`, фризит приложение |
| `core/db.py` | 219 | **Bare `raise` вне `except`**: после логирования не-PostgresError исключения будет `RuntimeError: No active exception to re-raise` |
| `gui/vnc_preview.py` | 545–567 | **`QMetaObject.invokeMethod` с raw string**: сигнатура требует `Q_ARG`, Python str передаётся неявно — методы `_on_error_main` и др. могут не вызываться |
| `gui/vnc_preview.py` | 872–877 | **`Path("")` → каталог `"."`**: если VNC клиент не настроен, `exe_path=""`, `Path("").exists()` всегда `True` — упадёт в `Popen(".")` |
| `gui/info_section_widget.py` | 190–198 | **`.replace()` по всему HTML**: при замене значения поля заменяется ВСЕ вхождения текста во всём HTML — если два поля показывают одинаковое значение, оба ломаются |

### 🔴 Опасные архитектурные проблемы

| Файл | Строка | Проблема |
|------|--------|----------|
| `infrastructure/audit_logger.py` | 237–255 | **Анти-слой**: `infrastructure` импортирует `cashcontrol.gui.*` — циклические импорты, нарушение слоёв |
| `core/ssh.py` | 120 | **Security**: `known_hosts=None` — отключена верификация host key (MITM) |
| `gui/tab_bar.py` | 132–134 | **Fragile**: прямой доступ к `self._bar.itemMap` — приватный атрибут `qfluentwidgets`, сломается при обновлении библиотеки |
| `gui/cash_session_widget.py` | 728–753 | **Сильная связанность**: `reconnect_to` лезет в `_conn`, `_is_connected`, `_ip` других классов — хрупко |

### 🔴 Мёртвый / вводящий в заблуждение код

| Файл | Строка | Проблема |
|------|--------|----------|
| `core/reinstall/installer.py` | 267 | **Значение не присвоено**: `int(bytes_sent * 100 / total_bytes)` вычисляет процент, но никуда не сохраняет |
| `core/reinstall/iso_extractor.py` | 164, 256 | **Мёртвый параметр**: `progress_callback` объявлен, но нигде не вызывается |
| `core/security/password_manager.py` | 180–183 | **Заглушка**: `_reset_singleton()` — пустой `pass`, хотя имя намекает на функциональность |
| `core/reinstall/archive_scanner.py` | 51 | Мёртвый `_PLAIN_TAR_RE` — нигде не используется |
| `gui/session_manager.py` | 106–109 | Мёртвый `_wait_task_done` — нигде не вызывается |

### 🔴 Команды пользователей

| Файл | Строка | Проблема |
|------|--------|----------|
| `scripts/sync_version.py` | 7–12 | **I/O на уровне модуля**: чтение/запись файлов при импорте, нет `if __name__ == "__main__"` |
| `scripts/sync_version.py` | 7–8 | `version.txt` читается при импорте — `FileNotFoundError` если файла нет |

---

## MEDIUM Severity

### 🟡 Безопасность и надёжность

| Файл | Строка | Проблема |
|------|--------|----------|
| `core/mover/steps/qrid.py` | 95–107 | **Sed injection**: `/` не экранируется в delimiter'е sed — сломает команду если QRID содержит `/` |
| `gui/dialogs/tab_logs.py` | 124 | **Платформозависимость**: `os.startfile` — только Windows, упадёт на Linux/macOS |
| `gui/widgets/virtual_keyboard.py` | 344–401 | **Жёстко зашитые scan codes**: `0x4E/0x4A/0x37/0x35` — не портабельны между клавиатурами |
| `gui/widgets/virtual_keyboard.py` | 416–454 | **Monkey-patching**: прямая замена `mousePressEvent` — ломает Qt event system |

### 🟡 Логические ошибки

| Файл | Строка | Проблема |
|------|--------|----------|
| `core/mover/executor.py` | 273–387 | **Дублирование DB запросов**: `_get_shop_info` и `_detect_touch_subtype` дважды делают одно и то же |
| `core/mover/steps/run_commands.py` | 42 | **No-op**: `ctx.cash_type.lower()` — результат не присвоен, строка ничего не делает |
| `gui/dialogs/command_editor.py` | 488–508 | **Сбой удаления**: если файл не удалился, item из списка всё равно убирается (UI не соответствует диску) |
| `gui/dialogs/logs_viewer.py` | 259–271 | **Регистр**: поиск выделяет case-sensitive, но фильтр case-insensitive — несоответствие |
| `gui/dialogs/mover_editor_dialog.py` | 788–811 | **Fragile reorder**: сопоставление шагов по тексту метки — если метки совпадают, reorder ломается |

### 🟡 Дублирование кода

| Файл | Строка | Проблема |
|------|--------|----------|
| `gui/toolbar.py` | 370–493 | Код `_launch_kitty` и `_launch_winscp` — ~85% идентичны |
| `gui/dialogs/settings/tab_connection.py` | 223–271 | `_show_ssh_passwords` / `_show_db_passwords` и `_clear_*` — дубликаты |
| `core/info/collectors/barcode_scanner.py` | 86–100 | USB alias построение идентично `scales.py:85–99` |
| `gui/dialogs/help_dialog.py` | 55–220 | CSS для light/dark — 80% дублирования |

### 🟡 Производительность

| Файл | Строка | Проблема |
|------|--------|----------|
| `gui/cash_session_widget.py` | 76–77, 149, etc | `from ...theme_helper import color as _tc` повторяется **8 раз** в разных методах |
| `gui/db_viewer_widget.py` | 1382–1437, 1657–1688 | **Блокировка UI**: синхронные psycopg2 соединения на главном потоке |

### 🟡 Архитектура и стиль

| Файл | Строка | Проблема |
|------|--------|----------|
| `core/ssh.py` | 157, 268 + `db.py` мн. | **`logger.bind()` несовместим**: `get_logger()` возвращает stdlib `Logger`, у которого нет `.bind()` — `AttributeError` |
| `gui/vnc_preview.py` | 17–27 | **11 полей в tuple**: `_DEPTH_PRESETS` — доступ по числовому индексу, крайне хрупко |
| `core/info/collectors/__init__.py` | 7–17 | **Заброшенные exports**: только 4 из 15+ коллекторов реэкспортируются — вводят в заблуждение |
| `gui/theme_engine.py` | 55–248 | `_build_qss` — **193 строки** с двумя QSS блоками ~70 строк каждый. QSS должен быть во внешних файлах |
| `gui/main_window.py` | 96, 101–131 | Шорткаты лезут в приватные методы `CashToolbar._on_*` |

### 🟡 Тесты

| Файл | Строка | Проблема |
|------|--------|----------|
| `tests/__init__.py` | — | Тестов нет — всего 1 пустой `__init__.py` |

---

## LOW Severity

### 🟢 Импорты

| Файл | Строка | Проблема |
|------|--------|----------|
| `gui/tab_manager.py` | 155 | `import asyncio` внутри метода — уже импортирован наверху (строка 5) |
| `gui/tab_manager.py` | 247 | `from PySide6.QtWidgets import QMessageBox` — уже импортирован (строка 11) |
| `gui/sidebar.py` | 87 | `from PySide6.QtCore import Qt` — уже импортирован (строка 5) |
| `gui/theme_engine.py` | 56 | `from qfluentwidgets import isDarkTheme` — уже импортирован (строка 17) |
| `gui/status_bar.py` | 220, 230–234 | Множественные локальные импорты `QMessageBox`, `get_history_manager` и др. |
| `gui/dialogs/settings/settings_dialog.py` | 73, 80, 86 | `from qfluentwidgets import MessageBox` 3 раза локально |

### 🟢 Мёртвый код / unused

| Файл | Строка | Проблема |
|------|--------|----------|
| `gui/theme_helper.py` | 128–130 | `html_color(name)` — никогда не используется, просто wrapper |
| `infrastructure/path_resolver.py` | 116–122, 145–147 | `get_collectors_dir()`, `get_usb_mapping_file()` — не используются|
| `infrastructure/path_resolver.py` | 234–238 | `ensure_mover_dirs()` — не вызывается |
| `gui/dialogs/command_editor.py` | 45 | `_LABEL_W = 150` — не используется |
| `core/info/collectors/_toml_collector.py` | 36 | `_fallbacks` вычисляется, но не используется |

### 🟢 Стиль и поддерживаемость

| Файл | Строка | Проблема |
|------|--------|----------|
| `core/ssh.py` | 229–238 | `_decode()` определена внутри `execute()` — создаётся заново на каждый вызов |
| `core/info/collectors/dns_info.py` | 22 | Regex компилируется каждый вызов — вынести `re.compile()` на уровень модуля |
| `gui/status_bar.py` | 75 | `mousePressEvent` переопределён через lambda — monkey-patch |
| `gui/notification_manager.py` | 51–53 | `__init__` идёт ПОСЛЕ методов, которые используют `self._notifications` |
| `core/info/collectors/os_info.py` | 91, `cash_type.py:136` | `import re` / `import xml.etree.ElementTree` внутри методов |
| `core/commands.py` | 196–202 | Чрезмерно широкие `except` — `execute_cash_restart` ловит всё |
| `core/info/rules.py` | 56 | `except Exception: pass` — тихое проглатывание ошибок валидации |

### 🟢 Баги на грани

| Файл | Строка | Проблема |
|------|--------|----------|
| `core/info/collectors/fiscal_printer.py` | 79 | `"usbPIRIT" in raw` — чувствительно к регистру |
| `core/info/collectors/bank_terminal.py` | 98–99 | `"86"` — магическое число, не названо константой |
| `core/info/collectors/cash_type.py` | 128–143 | Повторное чтение XML ради `sw_version` — данные уже есть у `CashSoftwareCollector` |
| `gui/dialogs/logs_viewer.py` | 203–217 | Двойной `re.match` в фильтре — первый результат отбрасывается |

---

## Наблюдения по модулям

### `gui/vnc_preview.py` (807 строк)
- **Самый критичный** — 2 High-бага (invokeMethod, Path(""))
- `_DEPTH_PRESETS` как tuple с 11 полями — крайне хрупко, нужен NamedTuple/dataclass
- `_apply_updates` держит `_fb_lock` на время QPainter — блокирует worker

### `gui/db_viewer_widget.py` (1572 строк) 🏆 Самый большой файл
- Синхронные psycopg2 вызовы на главном потоке — фризит UI
- `SQLHighlighter` — O(n*k) по ключевым словам, можно одним regex
- В целом перенасыщен: смесь SQL редактора, просмотрщика таблиц, консоли

### `gui/toolbar.py` (608 строк)
- Дубликаты в `_launch_kitty` / `_launch_winscp` — вынести общий helper
- Тройная навигация по parent hierarchy — `_require_active_tab`, `_get_main_window`, `_get_active_session_widget`

### `core/ssh.py` + `core/db.py`
- `logger.bind()` несовместим с Loguru/stdlib — **везде** где используется `.bind()`, будет `AttributeError`
- `db.py:219` — критический баг с bare `raise`
- SSH host key verification отключена

### `infrastructure/audit_logger.py`
- **Главное нарушение слоёв**: infrastructure → gui импорт. Нужно через DI или callback

### `commands/` (пользовательские команды)
- `Поправить_FITO.py` — гарантированный `NameError` на строке 22
- `Удалить_зависший_чек.py` — блокирует asyncio event loop

### `scripts/sync_version.py`
- Не используется как скрипт — **все операции на импорт**, нет `if __name__ == "__main__"`
- Опасный дизайн

---

## Статистика

| Уровень | Количество |
|---------|-----------|
| 🔴 **High** | 18 |
| 🟡 **Medium** | ~25 |
| 🟢 **Low** | ~25 |

**Топ-5 что чинить в первую очередь:**
1. `commands/Поправить_FITO.py:21` — переместить `import asyncio` наверх (иначе команда не работает)
2. `core/db.py:219` — исправить bare `raise` (вызывает `RuntimeError`)
3. `gui/vnc_preview.py:545` — переделать `invokeMethod` с `Q_ARG` или прямым вызовом (VNC нестабилен)
4. `gui/vnc_preview.py:872` — защита от `Path("")` (падение при пустом пути VNC)
5. `infrastructure/audit_logger.py:237` — убрать зависимость `infrastructure → gui`
