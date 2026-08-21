# Анализ проекта CashControl3

> Сгенерировано: 2026-06-13
> Проанализировано: 60 Python-файлов, ~8 500 строк

---

## 🔴 Критические проблемы

### 1. Дублирование классов в `command_editor.py`

**Файл:** `src/cashcontrol/gui/dialogs/command_editor.py`

В одном файле находятся две полные копии классов `_CommandForm` и `CommandEditorDialog`:

| Класс | Первая копия (строки) | Вторая копия (строки) | Статус |
|---|---|---|---|
| `_CommandForm` | 63–251 | 506–693 | Вторая **перезаписывает** первую |
| `CommandEditorDialog` | 253–501 | 698–950 | Вторая **перезаписывает** первую |

- Первые копии (строки 63–501) — **100% мёртвый код** — никогда не могут быть вызваны.
- Вторые копии — реально используемые (импортируются `sidebar.py:75`).
- Реализации немного отличаются (первая использует `self._ssh_edit`/`self._py_edit`, вторая — `self._cmds`/`self._py`; первая имеет `set_editable(v)`, вторая — `set_edit_mode(on)`).
- **Причина:** вероятно, неудачный copy-paste рефакторинг или слияние; старая версия осталась вместо замены.

### 2. Параметр `user` в `audit_log()` не используется

**Файл:** `src/cashcontrol/infrastructure/audit_logger.py:114-121`

```python
def audit_log(
    action_type: str,
    action_name: str,
    result: str,
    target: str | None = None,
    user: str | None = None,   # ← параметр принимается, но не используется
    error_message: str | None = None,
    **extra: Any,
) -> None:
```

Параметр `user` передаётся в сигнатуру функции (и некоторые вызывающие могут его передавать), но **нигде не используется** в теле функции. Если аудит должен логировать пользователя — это недостающий функционал. Если нет — параметр нужно удалить.

---

## 🟡 Мёртвый код

### 3. Класс `Toolbar` в `toolbar.py`

**Файл:** `src/cashcontrol/gui/toolbar.py:46-71`

Класс `Toolbar` (верхняя панель с кнопками "Добавить кассу", "Обновить", "Настройки") определён, но **нигде не импортируется и не инстанцируется** во всём проекте. Используется только `CashToolbar` (панель для каждой вкладки, начиная со строки 143).

### 4. `_PING_DOTS` продублирован в двух файлах

**Файл:** `src/cashcontrol/gui/session_manager.py:27-32`
**Файл:** `src/cashcontrol/gui/tab_bar.py:13-18`

Оба файла определяют идентичные словари:

```python
_PING_DOTS = {
    "ok": "\U0001f7e2",       # 🟢
    "slow": "\U0001f7e1",     # 🟡
    "timeout": "\U0001f534",  # 🔴
    "unknown": "\u26aa",      # ⚪
}
```

- `session_manager.py` определяет, но не использует (файл использует строковые ключи "ok", "slow", "timeout", "unknown" напрямую в логике пинга).
- `tab_bar.py` использует для отображения иконок ping-dot на вкладках.
- Копия в `session_manager.py` — мёртвая, её нужно удалить.

### 5. Статический метод `_wait_task_done`

**Файл:** `src/cashcontrol/gui/session_manager.py:113-116`

```python
@staticmethod
async def _wait_task_done(task: asyncio.Task) -> None:
    with contextlib.suppress(asyncio.CancelledError, Exception):
        await task
```

Метод определён, но **никогда не вызывается**.

### 6. Импорт `Callable` в `theme_engine.py`

**Файл:** `src/cashcontrol/gui/theme_engine.py:20`

```python
if TYPE_CHECKING:
    from collections.abc import Callable
```

`Callable` импортируется внутри `TYPE_CHECKING`, но единственное использование — в подсказке типа `_tc: Callable[[str], str]` на строке 55. Так как `from __future__ import annotations` делает все аннотации строками, этот импорт не используется в рантайме. Функционально корректно, но `Callable` можно импортировать на уровне модуля или удалить, если аннотации — строки.

---

## 🔵 Неиспользуемые импорты

### 7. `notification_manager.py:1` — `import sys`

**Файл:** `src/cashcontrol/gui/notification_manager.py`

`import sys` присутствует, но `sys` нигде не используется.

### 8. Импорты в `toolbar.py`

**Файл:** `src/cashcontrol/gui/toolbar.py`

- `QFrame` (строка 20) — используется как возвращаемый тип `self.sep()`. Импорт валиден.
- `Path` (строка 13) — используется в файле.

Значимых неиспользуемых импортов нет. Импорты в порядке.

### 9. Импорт в `tab_manager.py`

**Файл:** `src/cashcontrol/gui/tab_manager.py:7`

`Qt` импортируется из `PySide6.QtCore` и используется в `Qt.AlignmentFlag`. Всё в порядке.

---

## 🟠 Запахи кода и проблемы качества

### 10. Повторяющиеся inline-импорты

В нескольких файлах модули импортируются внутри методов, а не на уровне модуля:

- `command_editor.py`: `from cashcontrol.gui.theme_helper import color as _tc` встречается **5 раз** внутри методов (строки 147, 166, 572, 589, 630)
- `cash_session_widget.py`: `import asyncio` на строке 155 внутри `_on_tab_refresh_requested` — избыточно, `asyncio` уже импортирован на строке 19
- `sidebar.py`: `from PySide6.QtCore import Qt` внутри `_on_about` (строка 87) — `Qt` можно импортировать на уровне модуля
- `main_window.py`: inline-импорты в `_connect_update_signals`, `_on_update_server_status`, `_on_updates_applied`, `_on_update_failed` — здесь это оправдано ленивой загрузкой

### 11. `actions_registry.py`: Непоследовательное определение builtin

**Файл:** `src/cashcontrol/actions_registry.py:180-181`

```python
builtin = len([a for a in self._actions.values() if a.category == "builtin"])
```

Подсчёт действий идёт по `category == "builtin"`, но у `Action` также есть отдельное поле `is_builtin: bool`. Эти два механизма независимы — действие может иметь `category="builtin"`, но `is_builtin=False`, или наоборот. Метод `__repr__` будет показывать некорректные числа.

### 12. `config_manager.py`: Поле `connection.update_server` удалено, но остались ссылки

Код миграции в `_load()` (строки 275-283) обрабатывает переход с `update_server` на `update`. Проблемы нет, но старые имена полей в комментариях могут запутать.

### 13. `main.py`: `is_first_launch` проверяет наличие файла

**Файл:** `src/cashcontrol/main.py:133`

`config.is_first_launch` проверяет, существует ли `settings.json`. Если файл удалить — мастер настройки запустится снова. Это поведение задумано, но стоит помнить.

### 14. `main_window.py`: `_on_restart_required` использует `import sys as _sys` внутри метода

**Файл:** `src/cashcontrol/main_window.py:234`

Модуль `sys` импортируется внутри тела метода, а не на уровне модуля. `sys` нужен для `_sys.executable` в пути перезапуска через `os.execv`.

---

## 🟢 Наблюдения (действий не требуется)

- **Использование Loguru:** Чисто и единообразно. Ротируемые файловые обработчики, отдельный аудит-трейл, консольный вывод в dev-режиме. Хорошая практика.
- **Паттерн синглтон QObject:** `NotificationManager`, `HistoryManager`, `ConfigManager` — все корректно реализованы.
- **Тема оформления:** Грамотно спроектирована через `ThemeEngine` и `theme_helper` с цветовой палитрой. Чистое разделение.
- **VNC:** Полноценная реализация протокола RFB на чистом Python + numpy. Хорошая архитектура с worker-потоком.
- **Async SSH:** Используется `asyncio` с `qasync` event loop. Чистое управление задачами с поддержкой отмены.
- **Русский интерфейс:** Все строки для пользователя на русском. Комментарии смешанные (русские и английские).
- **Использование эмодзи:** Активно используются в кнопках, статусах и логах. Единообразно.

---

## 📋 Сводка

| Категория | Кол-во | Ключевые позиции |
|---|---|---|
| **Критические ошибки** | 2 | Дублирование классов в command_editor.py; неиспользуемый параметр `user` в audit_log |
| **Мёртвый код** | 4 | Класс `Toolbar`, дубликат `_PING_DOTS`, `_wait_task_done`, мёртвая копия в command_editor.py |
| **Неиспользуемые импорты** | 1 | `import sys` в notification_manager.py |
| **Запахи кода** | 5 | Inline-импорты, непоследовательное определение builtin |
| **Файлы-сироты** | 0 | — |
| **Всего файлов** | 60 Python-файлов | ~8 500 строк кода |

### Рекомендованные действия (по приоритету):

1. **Удалить дублирующийся код** в `command_editor.py` — удалить строки 63–501 (первая копия), оставить строки 506–950.
2. **Удалить неиспользуемый параметр `user`** из `audit_log()` или реализовать логирование пользователя.
3. **Удалить `_PING_DOTS`** из `session_manager.py` (не используется там).
4. **Удалить `_wait_task_done`** из `session_manager.py`.
5. **Удалить класс `Toolbar`** из `toolbar.py`.
6. **Удалить `import sys`** из `notification_manager.py`.
7. **Перенести повторяющиеся inline-импорты** на уровень модуля, где это возможно.