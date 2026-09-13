# CashControl — документация по коду v3.8.1

Полное описание архитектуры, модулей, классов, функций и связей приложения управления
кассами SetRetail.

---

## Оглавление

1. [Обзор системы](#1-обзор-системы)
2. [Технологический стек](#2-технологический-стек)
3. [Архитектурные принципы](#3-архитектурные-принципы)
4. [Структура репозитория](#4-структура-репозитория)
5. [Точка входа и жизненный цикл](#5-точка-входа-и-жизненный-цикл)
6. [Подсистема `core` — транспорт, команды, типы, информация, безопасность](#6-подсистема-core)
7. [Подсистема `infrastructure` — конфиг, пути, загрузчики, логирование](#7-подсистема-infrastructure)
8. [Подсистема `gui` — главное окно и каркас](#8-подсистема-gui)
9. [Диалоги и виджеты GUI](#9-диалоги-и-виджеты-gui)
10. [Встроенный SSH-терминал (пакет builtin)](#10-встроенный-ssh-терминал-пакет-builtin)
11. [Потоки данных GUI ↔ core](#11-потоки-данных-gui--core)
12. [Тестирование и сборка](#12-тестирование-и-сборка)

---

## 1. Обзор системы

CashControl — десктопное Windows-приложение для удалённого управления кассами POS
на базе SetRetail (TinyCore / Ubuntu) по сети. Возможности:

- **SSH-терминал** — внешний (KiTTY) или встроенный (пакет `builtin/terminal`, запускается
  отдельным процессом) + WinSCP для файлового обмена;
- **Встроенный файловый менеджер** — SFTP/SCP (`builtin/file_manager`, in-process окно,
  fallback, если WinSCP недоступен);
- **Встроенный VNC-просмотрщик** (RFB 3.x, чистый Python) для экранных касс;
- **Редактор PostgreSQL** (встроенный `builtin/db_viewer`) — таблицы, SQL-консоль, CSV;
- **Сбор информации о кассе** — 14 секций (тип кассы, ОС, процессор, ПО, ФР,
  сканеры, весы, банковский терминал, клавиатура, DNS, Loymax, QRID, подключение);
- **Диагностика** — Python-проверки и декларативные TOML-правила, список «Проблем»;
- **Команды** — предопределённые и пользовательские (TOML/Python), hot-reload;
- **Типы касс** — TOML-описания (POS/touch/SCO/SCO3) с наследованием `extends`
  и авто-детектом по XML/файлам/командам;
- **Виртуальная клавиатура** экранных касс (отправка нажатий через `xdotool` по SSH);
- **Безопасность** — пароли шифруются Fernet, мастер-ключ защищён DPAPI Windows;
  SSH host keys проверяются по схеме TOFU.

Приложение графически построено на **PySide6 + qasync** (Qt event loop как asyncio),
сетевой слой — `asyncssh` и `asyncpg`. Единый фасад сессии скрывает транспорты
от GUI, что позволяет тестам подставлять моки.

---

## 2. Технологический стек

Из `pyproject.toml`:

| Слой | Библиотека | Назначение |
|---|---|---|
| GUI | `PySide6>=6.7,<6.9` | Qt-виджеты |
| GUI | `PySide6-Fluent-Widgets>=1.7` | Fluent-компоненты (кнопки, тулбары, вкладки, диалоги) |
| GUI | `qasync>=0.27` | интеграция asyncio с Qt event loop |
| Сеть | `asyncssh>=2.17` | SSH-подключения, SCP, PTY |
| БД | `asyncpg>=0.30` | асинхронный PostgreSQL-клиент `core.db` |
| БД | `psycopg2-binary>=2.9` | синхронный PostgreSQL для `builtin/db_viewer` (в QThread) |
| Данные | `pydantic>=2.9` | модели конфигурации и типов касс |
| Безопасность | `cryptography>=43` | Fernet-шифрование паролей |
| Безопасность | `pywin32>=306; win32` | DPAPI (Windows) для мастер-ключа |
| Инфраструктура | `defusedxml>=0.7` | безопасный XML-парсинг |
| Инфраструктура | `numpy>=1.26` | конвертация пикселей VNC |
| Терминал | `pyte>=0.8,<1` | VT-эмуляция в `builtin/terminal` |
| Dev | `pytest`, `pytest-asyncio`, `pytest-qt`, `ruff>=0.7` | тесты и линтер |

Требования: **Python >=3.12, <3.14**. Точка входа (console script):

```toml
[project.scripts]
cashcontrol = "cashcontrol.main:main"
```

---

## 3. Архитектурные принципы

1. **Фасад сессии (ADR-004)**. `CashSession(SessionInterface)` — единственная точка
   доступа к SSH- и БД-транспортам. GUI и коллекторы **никогда** не импортируют
   `ssh.py`/`db.py` напрямую.
2. **Синглтоны** через `__new__`/`instance()`: `ConfigManager`, `EncryptionManager`,
   `CashTypeRegistry` (`get_cash_type_registry()`), `PortMapper`, `AliasManager`,
   логгеры, `HistoryManager`, `NotificationManager`, `Prefetcher`.
3. **DI конфигурации**: `config: ConfigManager | None = None` принимается параметром
   конструкторами `CashSession`, `SSHSession`, `DBSession`, `PasswordManager`,
   `InfoCollector` — тесты подставляют конфиг без состояния.
4. **TOFU (Trust On First Use)** для SSH host keys: первый контакт — ключ
   записывается в `data/known_hosts`; последующие — сверка; несовпадение —
   отказ с аудитом (possible MITM).
5. **Шифрование паролей**: в `settings.json` лежат только зашифрованные строки
   (`ssh_passwords_encrypted`, `db_passwords_encrypted`); расшифровка — только
   в рантайме через `PasswordManager`.
6. **Волоночная модель CLI / изоляция тяжёлого кода**: встроенный SSH-терминал
   и DB Viewer работают в **отдельном процессе/потоках**, чтобы не блокировать
   qasync-цикл приложения.
7. **Hot-reload**: команды (`ActionsRegistry.reload_commands`), GUI-модули
   (`module_loader` MetaPath finder из `modules/`), типы касс (`registry.reload`),
   детектор, TOML-правила. Небольшие изменения применяются без пересборки exe.
8. **Двухфазный сбор информации**: волна 1 — `cash_type` (последовательно, от него
   зависят другие); волна 2 — остальные секции параллельно с таймаутом 10 с.
   Секции доставляются в GUI по мере готовности (streaming).
9. **Асинхронность**: весь сетевой слой async; GUI-поток синхронный, сетевые
   операции запускаются через `asyncio.ensure_future`/`create_task`.

---

## 4. Структура репозитория

```
CashControl4/
├─ pyproject.toml               # метаданные, зависимости, ruff, pytest, entry point
├─ CashControl.iss              # Inno Setup: per-user инсталлятор
├─ README.md                    # обзор и инструкции
├─ build_dist.py→ (scripts/)    # сборка дистрибутива
├─ commands/                    # пользовательские команды (*.toml) + диагностика-правила
│  ├─ _builtin_*.toml           #   встроенные команды (cpu, dns, os, ФР, loymax, reboot, restart)
│  └─ ssh_old_password.toml     #   декларативное правило-диагностика
├─ collectors/                  # пользовательские TOML-коллекторы и правила
├─ detection/                   # пользовательские правила детекта типа кассы
├─ src/cashcontrol/             # приложение (py-пакет)
│  ├─ main.py                   # точка входа
│  ├─ actions_registry.py       # реестр действий
│  ├─ core/                     # транспорт, команды, типы, информация, безопасность
│  ├─ infrastructure/           # конфиг, пути, загрузчики, аудит
│  ├─ gui/                      # окна, вкладки, диалоги, темы, виджеты
│  └─ builtin/                  # встроенное ПО: terminal/, db_viewer/, vnc/, file_manager/, *launcher.py
├─ data/                        # рантайм-данные (settings.json, known_hosts, aliases.json, …)
├─ tests/                       # тесты (pytest)
└─ docs/                        # документация (patch.md, ARCHITECTURE.md, screenshots/)
```

Директория `data/` в сборке наполняется при первом запуске; она исключена из
инсталлятора (см. `CashControl.iss`), чтобы не затирать пользовательские данные.

### 4.1 Дерево пакета `src/cashcontrol`

```
src/cashcontrol/
├─ __init__.py            # __app_name__, __version__
├─ main.py                # main(): логирование → hot-modules → qasync → окно/визард
├─ actions_registry.py    # Action, ActionResult, ActionsRegistry
├─ core/
│  ├─ session_interface.py    # ExecResult, SessionInterface (ABC)
│  ├─ session.py              # CashSession — фасад SSH+DB
│  ├─ ssh.py                  # SSHSession, CommandResult, TOFU, SCP
│  ├─ db.py                   # DBSession (asyncpg)
│  ├─ commands.py             # CommandExecutor (simple/multi-step/cash_restart)
│  ├─ aliases/alias_manager.py# AliasManager, data/aliases.json
│  ├─ security/encryption.py  # EncryptionManager (Fernet+DPAPI)
│  ├─ security/password_manager.py # перебор и кэш паролей
│  ├─ cash_types/
│  │  ├─ models.py            # CashTypeDefinition (pydantic)
│  │  ├─ merge.py             # deep_merge, resolve_extends
│  │  ├─ registry.py          # CashTypeRegistry (bundled + overlay)
│  │  ├─ detector.py          # TypeDetector (правила detection/*.toml)
│  │  ├─ strategies/__init__.py # xml_keywords, regex_file, shell
│  │  └─ bundled/             # pos.toml, touch.toml, sco.toml, sco3.toml
│  └─ info/
│     ├─ info_manager.py      # InfoCollector, InfoSection, CashInfoSnapshot
│     ├─ registry.py          # ленивый реестр коллекторов
│     ├─ rules.py             # DiagnosticCheck, ProblemChecker
│     ├─ toml_rules.py        # TomlRule, TomlRuleChecker
│     └─ collectors/          # 16+ коллекторов (см. §6.6)
├─ infrastructure/
│  ├─ config_manager.py       # ConfigManager, Pydantic-модели настроек
│  ├─ path_resolver.py        # корень приложения и все пути data/soft/commands/...
│  ├─ command_loader.py       # загрузка команд TOML/Python → Action
│  ├─ module_loader.py        # MetaPath finder горячей замены GUI-модулей
│  └─ audit_logger.py         # get_logger, get_audit_logger, audit_log
├─ gui/
   ├─ main_window.py          # MainWindow — каркас, хоткеи, геометрия
   ├─ sidebar.py              # боковая панель (настройки, команды, логи, о прогр.)
   ├─ tab_manager.py          # TabManager — «дирижёр» вкладок
   ├─ tab_bar.py              # CashTabBar — вкладки с индикатором пинга
   ├─ session_manager.py      # реестр сессий, пинг, VNC-процессы, персистентность
   ├─ cash_session_widget.py  # контент вкладки кассы
   ├─ toolbar.py              # Toolbar + CashToolbar (действия и внешние инструменты)
   ├─ status_bar.py           # сворачиваемая панель «История / Уведомления»
   ├─ history_manager.py      # HistoryManager (вкладка/сессия-per-session)
   ├─ notification_manager.py # NotificationManager
   ├─ prefetch.py             # «прогрев» TCP-маршрута при hover
   ├─ theme_engine.py         # ThemeEngine (синглтон QSS)
   ├─ theme_helper.py         # семантические цвета
   ├─ dialogs/                # диалоги и настройки (см. §9)
   └─ widgets/                # info_section_widget, virtual_keyboard
└─ builtin/
   ├─ ssh_terminal_launcher.py# запуск терминала отдельным процессом
   ├─ file_manager_launcher.py# запуск встроенного файлового менеджера (см. §8.13)
   ├─ terminal/               # вендоренный SSH-терминал (см. §10)
   ├─ vnc/
   │  └─ vnc_preview.py       # встроенный VNC (RFB 3.x, см. §8.9)
   ├─ db_viewer/              # встроенный клиент PostgreSQL (см. §9.4)
   └─ file_manager/           # встроенный SFTP/SCP менеджер (см. §8.13)
```

---

## 5. Точка входа и жизненный цикл

### 5.1 `src/cashcontrol/main.py`

```python
def main() -> None:
```
Последовательность запуска:

1. `setup_logger()` — файловый + консольный логгер;
2. `audit_log(action_type="system", action_name="app_start")`;
3. `module_loader.install()` — **до всех импортов GUI** (hot-подмена модулей);
4. `ConfigManager()` — синглтон настроек;
5. `QApplication` → `qasync.QEventLoop(app)` + `asyncio.set_event_loop(loop)`;
6. `ThemeEngine.instance().apply(theme)` — тема до создания окон;
7. Если `config.is_first_launch` — `CashControlSetupWizard(config).exec()`
   (через `QTimer.singleShot(0, ...)` — после старта цикла), при отмене — `sys.exit(0)`;
8. Иначе `MainWindow().show()` (глобальная ссылка `_main_window` против GC);
9. `with loop: loop.run_forever()`; на выходе — аудит `app_exit`.

Хендлер необработанных async-исключений `_install_async_exception_handler(loop)`:
`ConnectionResetError`/`BrokenPipeError` игнорируются, остальные — в лог (ERROR)
и аудит `async_error`.

### 5.2 Жизненный цикл вкладки кассы

1. **Создание**: `+` / Ctrl+T → `AddCashDialog` → `TabManager.add_tab(ip)`
   → новый `CashSessionWidget(ip)` в `QStackedWidget`, ключ регистрируется в
   `SessionManager`, вкладка в `CashTabBar` с серой точкой, стартует TCP-пинг.
2. **Подключение**: `start_connecting()` → `connect_coro()`:
   `CashSession.connect()` (SSH) → `CashTypeCollector.collect` → при `db.enabled`
   `setup_db()` + параллельная `_connect_db_notified` (`session.db_connect_task`)
   → `load_info()` → `InfoCollector.collect_all` (секции по сигналу `_section_ready`).
3. **Работа**: активная вкладка — постоянный пинг, тулбар адаптируется под
   `cash_type`, фоновая пересборка каждые `ttl*0.8` (stale-while-revalidate),
   VNC-подключение/полноэкранный режим, выполнение команд через `ActionsRegistry`.
4. **Смена IP**: двойной клик / контекстное меню вкладки → `start_ip_edit()`
   → `TabManager.change_tab_ip(old, new)` → перевешивание ключей в `SessionManager`
   (`move_vnc`) + `await sw.reconnect_to(new_ip)` (жёсткий `session.abort()`).
5. **Закрытие**: `close_tab(ip)` → остановка пинга, `kill_vnc`, `widget.cleanup()`
   (остановка VNC-воркеров), `deleteLater`, сохранение списка IP в JSON.
6. **Восстановление**: `MainWindow.showEvent` → `restore_sessions()` → вкладки
   без коннекта → подключение **волнами** по `asyncio.Semaphore(3)`, чтобы
   мёртвый хост не блокировал всех.

---

## 6. Подсистема `core`

### 6.1 `core/session_interface.py` — интерфейс сессии

Фасадный интерфейс (ADR-004): скрывает SSH/DB/VNC за единым API.

```python
@dataclass
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str
    @property ok -> bool            # exit_code == 0

class SessionInterface(ABC):
    async connect() -> bool
    async disconnect() -> None
    async ping() -> bool            # «лёгкая» проверка живости, без аутентификации
    async exec(command: str, timeout: float = 30.0) -> ExecResult
    async upload(local: Path|str, remote: str) -> bool
    async download(remote: str, local: Path|str) -> bool
```

`Path` — под `TYPE_CHECKING`.

### 6.2 `core/session.py` — `CashSession` (фасад)

Единственная реализация `SessionInterface`, совмещающая SSH- и DB-транспорт.

**Конструктор**: `CashSession(ip, config: ConfigManager | None = None)`.

**Атрибуты**:
- `_ssh: SSHSession`, `_db: DBSession | None`;
- `_is_connected`, `_db_connected`, `_error_message`;
- `cash_type: str = "unknown"`, `cash_type_source: str = "unknown"`;
- `db_connect_task: asyncio.Task | None` — фоновая задача автоподключения БД
  (коллекторы с фичами `*_from_db` ждут её через `await session.db_connect_task`).

**Свойства**: `ip`, `host` (алиас `ip`), `ssh`, `db`, `is_connected`,
`ssh_connected`, `db_connected`, `error_message`.

**Ключевые методы**:

| Метод | Сигнатура | Поведение |
|---|---|---|
| `connect` | `async connect(connect_db=False) -> bool` | `asyncio.wait_for(ssh.connect(), connect_timeout)`; при `connect_db=True` — определяет имя БД по типу кассы (`definition.connection.db.database` или `"sco_v3"`), `setup_db` + `connect_db`. Ошибки → `False` + `_error_message` |
| `setup_db` | `setup_db(database) -> None` | создаёт `DBSession(ip, port, database)` без соединения |
| `connect_db` | `async connect_db() -> bool` | `await db.connect()` |
| `disconnect` | `async disconnect() -> None` | graceful: ssh + db (с `suppress`), сброс `db_connect_task` |
| `abort` | `async abort() -> None` | жёсткий `ssh.abort()` (для смены IP) |
| `run` | `async run(cmd, timeout) -> (exit_code, stdout, stderr)` | старое кортеж-API |
| `exec` | `async exec(cmd, timeout) -> ExecResult` | не подключён → `ExecResult(-1, "", "Not connected")`; ошибки → `(-1,"",str(e))` |
| `ping` | `async ping(timeout=1.5) -> bool` | TCP-проба порта 22 через `asyncio.open_connection` |
| `upload`/`download` | `async …` | декорация `ssh.upload_file/download_file` с логированием |
| `reboot` | `async reboot() -> bool` | `exec("reboot -f || reboot", timeout=15)`; обрыв SSH во время рестарта = успех |
| `__aenter__`/`__aexit__` | async CM | disconnect при выходе |

**Принцип**: коллекторы получают только фасад; расшаривается один SSH-транспорт
и опционально один БД-транспорт.

### 6.3 `core/ssh.py` — `SSHSession`

Транспорт на `asyncssh` с автоперебором паролей, TOFU, SCP и лимитом каналов.

```python
@dataclass
class CommandResult:
    stdout: str; stderr: str; exit_code: int; success: bool
    @property output   # stdout + stderr

class SSHConnectionError(Exception)
SERVER_HOST_KEY_ALGS = ["ssh-ed25519", "ecdsa-sha2-nistp256", "rsa-sha2-512", "rsa-sha2-256", "ssh-rsa"]
```

**`SSHSession(host, port=None, config=None)`**:

- Атрибуты: `host`, `port`, `login`, `timeout` (из конфига), `_conn`,
  `_password_manager`, `_successful_password`, `_channel_semaphore = Semaphore(4)`
  (лимит одновременных каналов против `ChannelOpenError`).
- `connect() -> None` — **TOFU-алгоритм**:
  1. `first_contact = not _is_host_known()`; `verify_host_key = not first_contact`;
  2. перебор паролей из `PasswordManager.get_passwords_for_ip(host, "ssh")`;
  3. при успехе: если `first_contact` — `_record_host_key()`, **закрыть** это
     соединение и переподключиться тем же паролем уже с проверкой ключа;
  4. `cache_success(host, password)`, аудит `ssh_connect` с `attempts=`;
  5. `PermissionDenied/PasswordChangeRequired` → следующий пароль;
     `HostKeyNotVerifiable` → аудит «host key mismatch (possible MITM)» + ошибка;
     `TimeoutError` → break; прочие → break.
- Внутренности: `_known_hosts_entry()` — файл `{data_dir}/known_hosts`, выражение
  `[host]:port` (если порт ≠ 22); `_record_host_key()` — берёт
  `conn.get_server_host_key()` и дописывает публичный ключ.
- `execute(command, timeout=None, check=False) -> CommandResult` — под семафором и
  `asyncio.wait_for`; `_decode()` — utf-8, при сбое cp1251 с `errors="replace"`.
- `upload_file/download_file` — через `asyncssh.scp`.
- `disconnect()/abort()` — graceful close / синхронный жёсткий abort.
- `successful_password` — для внешних лаунчеров KiTTY/WinSCP.

### 6.4 `core/db.py` — `DBSession`

Асинхронный клиент PostgreSQL на `asyncpg`.

```python
class DBConnectionError(Exception)

class DBSession(host, port=None, database=None, config=None):
```

- `database` обязателен явно («no global default»).
- `connect()` — перебор паролей `get_passwords_for_ip(host, "db")`;
  `asyncpg.InvalidPasswordError` → следующий пароль; `TimeoutError` → break.
- `execute(query, *args, timeout=None) -> list[Any]` — fetch под
  `asyncio.Lock` (asyncpg не поддерживает конкурентные запросы на одном
  `Connection`). Возвращает строки (в отличие от SSH-`execute`).
- `_execute(fetch_method, query, args, timeout, use_lock)` — общая логика.

**Отличия от SSH**: нет TOFU; вместо семафора — `Lock`; пароли `"db"` с
fallback на SSH-пароли; креды из секции `connection` (`db_login`, `db_port`, …).

### 6.5 `core/security`

#### `encryption.py` — `EncryptionManager` (синглтон через `__new__`)

- Мастер-ключ `data/.keystore`: на Windows — Fernet-ключ запечатан DPAPI
  (`win32crypt.CryptProtectData`, entropy `b"CashControl.keystore.v1"`),
  устаревший plaintext base64 мигрируется при первой загрузке. Файл скрытый
  (атрибуты HIDDEN/NORMAL через `SetFileAttributesW`).
- Повреждённый keystore → громкая ошибка (не пересоздаётся молча — иначе пароли
  станут нечитаемыми).
- `encrypt(plaintext) -> str` (base64-ascii), `decrypt(ciphertext) -> str`;
  пары list-вариантов `encrypt_passwords/decrypt_passwords` — convenience-функции.
- В `decrypt_list` повреждённый токен пропускается с warning.

#### `password_manager.py` — `PasswordManager`

- `get_passwords_for_ip(ip, password_type="ssh") -> Iterator[str]` — выбирает
  зашифрованный список из конфига, расшифровывает; для `"db"` при отсутствии
  БД-паролей — fallback на SSH-пароли. Порядок: кэш успеха `f"{ip}:{type}"`
  первым, затем остальные.
- `cache_success(ip, password, password_type)`; `clear_cache(ip=None)`;
  `get_cache_stats()`.

### 6.6 `core/commands.py` — `CommandExecutor`

Программный исполнитель предопределённых команд (в отличие от команд-файлов):

```python
@dataclass
class CommandExecutionResult:
    success: bool; output: str; error: str | None
    steps_completed: int = 0; steps_total: int = 1

class CommandExecutor:
    async execute_simple(session, command, timeout=30) -> CommandExecutionResult
    async execute_multi_step(session, commands: list[str], timeout=30) -> ...
    async execute_cash_restart(session) -> ...   # "cash restart", timeout 60; обрыв SSH = успех
```

- Многошаговые: префикс `-` в начале команды = «не останавливаться при ошибке».
- Аудит: `execute_simple` (команда обрезается до 100 символов),
  `execute_multi_step` (`partial` при неполном выполнении),
  `execute_cash_restart` (`action_type="cash_operation"`).

### 6.7 `core/cash_types` — типы касс

TOML-система описаний типов (bundled: `pos`, `touch`, `sco`, `sco3`) +
пользовательский overlay `{app}/cash_types/*.toml`.

- **`models.py`**: `CashTypeDefinition` (pydantic): `id, name, aliases, icon,
  extends, features_mode ("union"|"replace"), os_hints, connection: Connection{d.b},
  features: set[str], extra`. `from_toml()`, `merged_dict()` (для наследования).
- **`merge.py`**: `deep_merge(base, override)`; `resolve_extends(raw)` — разрешение
  цепочек `extends`; цикл → `ExtendsCycleError`; `features_mode="replace"`
  заменяет набор фич, иначе — объединение.
- **`registry.py`**: `CashTypeRegistry` — `load()/reload()`, `types`, `resolve(value)`,
  `match_substring(value)`, `get(value)`, `has(value)`. Синглтон
  `get_cash_type_registry()`. `has_feature(source, feature)` (принимает сессию
  или строку); `known_type_ids()`.
- **`detector.py`**: `TypeDetector` — правила `detection/*.toml` (bundled +
  overlay) по убыванию приоритета; `async detect(session, cache) -> str | None`.
  Стратегии из `strategies.STRATEGIES`; ошибка правила — warn и continue.
- **`strategies/__init__.py`**:
  - `xml_keywords` — безопасный XML-парсинг (`defusedxml`), атрибуты
    `moduleType/type/cashType/registerType/cashRegisterType` + теги/тексты,
    кандидаты → `registry.resolve`/`match_substring`;
  - `regex_file` — `re.search` по содержимому файла, значение из named-group
    `type`/первой группы/всего match → `_map_value`;
  - `shell` — SSH-команда, первая строка stdout → `_map_value`.
  - `_read_file(session, path, cache)` — кэширует содержимое файлов.

Defaults: `pos` — фичи `keyboard, customer_display, qrid, fiscal_register,
barcode_from_xml, scales_from_xml, drawer_close`, БД выключена;
`sco3 extends=sco` + фичи `db, payment_ranks, barcode_from_db, scales_from_db`,
БД `sco_v3`.

### 6.8 `core/info` — сбор информации и диагностика

#### `info_manager.py`

```python
enum CollectionStatus(StrEnum): PENDING, LOADING, COMPLETE, TIMEOUT, ERROR, SKIPPED
@dataclass InfoField:  key, label, value, alias_key=None, builtin_value=""
@dataclass InfoSection: name, status=PENDING, data: dict, fields: list[InfoField], error
@dataclass CashInfoSnapshot: host; атрибуты-секции; get_section(name)

ALL_SECTIONS = [cash_type, os, cpu, software, fiscal_printer, customer_display,
                scanners, scales, keyboard, bank_terminal, dns, loymax, qrid, connection]
SECTION_TITLES / SECTION_GROUPS / GROUP_TITLES  # русские заголовки для UI
```

**`InfoCollector(config=None)`**:
- `TASK_TIMEOUT = 10.0`; кэш `{host: (monotonic, snapshot)}` с `general.info_cache_ttl`;
- `register(collector)` — дополнительные коллекторы;
- `_build_collectors()` — lazy-импорт базовых коллекторов по секциям +
  TOML-коллекторы из `{app}/collectors/*.toml` (через `TomlCollector`);
- `async collect_all(session, force=False, on_section_ready=None) -> CashInfoSnapshot`:
  1. проверка кэша (TTL);
  2. **Wave 1** — `cash_type` последовательно, с `on_section_ready`;
  3. **Wave 2** — остальные параллельно (`asyncio.as_completed`) под
     `wait_for(TASK_TIMEOUT)`; таймаут → `TIMEOUT`, исключение → `ERROR`;
  4. кэширование по `session.host`.
- `_collect_one()` — вызывает коллектор; если в данных `*_skipped == "1"` →
  `SKIPPED`; из полей строит `InfoField`-список или генерирует из dict (исключая
  суффиксы `_error`, `_skipped`, `_raw`).

#### `registry.py` — ленивый реестр коллекторов

`_COLLECTOR_SPECS: dict[str, (module, class)]` (16 записей);
`get_collector(name)` — `importlib.import_module` + кэш;
`resolve_section(ui_section) -> canonical` (алиасы `os→os_info`, `cpu→cpu_info`,
`dns→dns_info`, `software→cash_software`, `scanners→barcode_scanner`);
`get_collector_for_section(section)`.

#### `collectors/` — набор коллекторов

Все следуют контракту `async collect(session) -> dict[str, ...]`. Источник —
SSH-команды или БД через `session.db` (для фич `*_from_db` ждут
`session.db_connect_task`):

| Модуль | Коллектор | Что собирает |
|---|---|---|
| `cash_type.py` | `CashTypeCollector` | тип через `TypeDetector` (пишет в `session.cash_type`/`cash_type_source`), `sw_version`, `sw_path` |
| `os_info.py` | `OSInfoCollector` | тип ОС (маркеры `/etc/sysconfig/tcedir`, `/etc/lsb-release`), версия, ядро, hostname |
| `cpu_info.py` | `CPUInfoCollector` | `cpu_model`, `cpu_cores` |
| `connection.py` | `ConnectionCollector` | `ssh_password_used` (пароль), `_fields=[]` — секция скрыта в UI, доступна правилам |
| `fiscal_printer.py` / `fiscal_register.py` | | парсинг `ComProxy.ini` → человекочитаемый порт (`COM{n+1}`, `USB (PIRIT)`, `USB`) |
| `bank_terminal.py` | `BankTerminalCollector` | `pinpad.ini` — `ComPort`, `EnableUSB` (два базовых пути) |
| `barcode_scanner.py` | `BarcodeScannerCollector` | XML или БД `hw_property` (`HARDWARE_SCANNER`); маппинг `usb_id_mapping.json`, проверка `/sys/bus/usb/devices`; `alias_key` для справочника |
| `scales.py` | ScalesCollector | аналогично (`HARDWARE_SCALES`, XML `scales-*-config.xml`) |
| `keyboard.py` | `KeyboardCollector` | `keyboard-config.xml`, `localizedName` |
| `customer_display.py` | `CustomerDisplayCollector` | `customerDisplay-firich-config.xml` |
| `dns_info.py` | `DNSInfoCollector` | `nameserver` из `/etc/resolv.conf` |
| `loymax.py` | `LoymaxCollector` | `loymax.properties` (`loymax.login`, учёт cp1251 через `od -tx1 -An`) |
| `qrid.py` | `QRIDCollector` | `bank-gazprom_sbp-config.xml`, `cashLinkQrId` (с namespace и fallback) |
| `payment_ranks.py` | `PaymentRanksCollector` | psql `sales_management_properties` (`paymentTypeRanks`); только при фиче |
| `drawer_close.py` | `DrawerCloseCollector` | psql `retailOnlyDrawerClose` |
| `_usb_mapper.py` | функции | `load_usb_mapping`, `invalidate_cache`, `lookup_device_by_path`, `check_usb_connected`, `format_port_as_com`; синглтон-кэш |
| `_port_mapper.py` | `PortMapper` | `get_port(device_type, os_type, fallback)`, `get_device_info`, `get_all_devices`; `get_port_mapper()` |
| `_toml_collector.py` | `TomlCollector` | из TOML `[collector]` + `[[fields]]`: команды с таймаутом 10 с и fallback-значениями |

#### Диагностика

- **`rules.py`**: `DiagnosticCheck(ABC)` — `id`, `applies_to(cash_type)`,
  `check(snapshot, cash_type) -> ProblemIssue | None`.
  Реализации: `BankUsbModeCheck` (`bank_usb_mode`), `PaymentRanksCheck`
  (сверка с `_REFERENCE_PAYMENT_RANKS`), `DrawerCloseCheck`
  (`retailOnlyDrawerClose`). `ProblemChecker.check(...) -> list[ProblemIssue]`
  прогоняет Python-проверки + TOML-правила; сбой одной проверки не ломает анализ.
- **`toml_rules.py`**: декларативные правила из `collectors/*.toml`.
  `TomlRule(section, key, op, value, message, severity="warning", cash_types=None,
  label=None, source="")`. Операции `_ALLOWED_OPS = {"==", "!=", ">", ">=", "<",
  "<=", "contains", "is_null", "not_null"}`; пустые/нуллабл-значения
  `_NULLISH = {"", "-", "—", "nan", "none"}`. `applies_to()` принимает id/алиас
  или фичу (`has_feature`). В `message` подставляется `{value}` фактического
  значения. `TomlRuleChecker.load(directory)` читает `get_collectors_dir()`.
  Пример на диске: `ssh_old_password.toml` — `connection.ssh_password_used ==
  "324012"` → «Старый пароль!».

### 6.9 `core/aliases/alias_manager.py`

Пользовательские имена устройств. Файл `data/aliases.json`
(`{"version":1, "aliases": {...}}`). `AliasManager.instance()` (синглтон):
`resolve(key, fallback)`, `has_alias`, `set_alias`, `delete_alias`, `get_all`;
статический `usb_key(vid, pid) -> "usb:{vid}:{pid}"`.

### 6.10 `actions_registry.py` и `actions/`

```python
@dataclass Action:
    name, description, category, handler: Callable,
    requires_confirmation=False, show_output=True, input_prompt=None,
    timeout=30, cash_types=None, source=None, is_builtin=False

@dataclass ActionResult: success: bool, message: str, details=None, error=None

class ActionsRegistry:
    ensure_loaded()            # ленивая загрузка
    _load_all()                # CommandLoader(get_commands_dir()).load_all()
    reload_commands()          # builtin переживают hot-reload
    async execute_action(action_name, session, **kwargs) -> ActionResult
    get_action / get_all_actions / get_actions_by_category
```

`actions/` — историческая заглушка; фактическая загрузка — `CommandLoader`
из `commands/`.

---

## 7. Подсистема `infrastructure`

### 7.1 `config_manager.py` — `ConfigManager`

Синглтон через `__new__`. Файл `data/settings.json` (JSON), секции — Pydantic:

- `ConnectionSettings`: `ssh_login="tc"`, `ssh_passwords_encrypted: list[str]`,
  `ssh_port=22`, `db_login="postgres"`, `db_passwords_encrypted`, `db_port=5432`,
  `vnc_port=5900`, `timeout=10.0`, `ping_interval=5.0`, `connect_timeout=15.0`,
  `ssh_timeout=10.0`.
- `ProgramsSettings`: пути и шаблоны аргументов внешних клиентов;
  `get_ssh_client()/get_vnc_client()/get_winscp()` — дефолт
  `{soft_dir}/{exe}` (`kitty.exe`, `vncviewer_new.exe`, `WinSCP.exe`).
- `GeneralSettings`: `max_tabs=10`, `info_cache_ttl=300`, `use_builtin_terminal`,
  `use_builtin_db_viewer`, `theme="auto"`, `language="ru"`, `history_mode="session"`,
  `log_level="INFO"`, `setup_completed=False`.
- `VncPreviewSettings`: `quality="Auto"`, `color_level="rgb222"`.
- `BuiltinSettings` (встроенное ПО, правится в разделе «Программы» настроек):
  `file_manager_start_dir="/"`, `vnc_start_mode="window"|"fullscreen"`,
  `vnc_default_depth=32` (8/16/32).
- `Settings` — агрегирует все секции (с `default_factory`).

Методы: `settings`, `is_first_launch` (`not setup_completed`), `reload()`,
`update(section, **fields)` (изменение + `save()`), `save()` — атомарная запись
`model_dump_json(indent=2, exclude_none=True)`; при битой загрузке — warn + дефолты.

### 7.2 `path_resolver.py`

Определение корня приложения:

- `_is_production()` (lru_cache): `sys.frozen` / `__compiled__` / наличие
  `version.txt`+`modules` рядом с exe; `_add_runtime_dll_dirs(root)` — native
  зависимости из `runtime/lib`.
- `get_app_root()`: dev — `Path(__file__).resolve().parents[3]`; production —
  рядом с exe.
- Стандартные пути: `get_data_dir()`, `get_logs_dir()`, `get_soft_dir()`,
  `get_commands_dir()`, `get_collectors_dir()`, `get_cash_types_dir()`,
  `get_detection_dir()`, `get_sessions_file()` (`data/sessions.json`),
  `get_config_file()` (`data/settings.json`), `get_keystore_file()`
  (`data/.keystore`), `get_port_mapping_file()`, `get_usb_mapping_file()`.
  Директории создаются (`mkdir(parents=True)`).

### 7.3 `command_loader.py` — `CommandLoader`

Единый загрузчик команд из `commands/`:

- **TOML** (`.toml`): метаданные в секции `[command]` (`name, description,
  category, cash_types, timeout, requires_confirmation, show_output`), шаги
  `steps: []`. Генерирует `handler(session, **kwargs)`: последовательное
  выполнение `session.ssh.execute`, аккумуляция `$ cmd` + вывод;
  поддержка `ignore_disconnect` — при обрыве SSH «Соединение закрыто кассой —
  команда отправлена».
- **Python** (`.py`): блок `# [command]` (парсится как TOML до первой
  непрокомментированной строки), обязательная сигнатура
  `async def execute(session, **kwargs)`; модуль загружается через
  `importlib.util.spec_from_file_location` под именем
  `cashcontrol.commands.{stem}`; опциональный `INPUT_PROMPT`; оборачивание
  `asyncio.wait_for(fn(session, **kwargs), timeout)`.
- `_quote_toml_value()` — авто-кавычки для значений.
- Свойство `errors`.

> Примечание: `command_editor.py` (см. §9.2) на текущий момент пишет `.json`
> и мета-комментарии `# description:`, которые `CommandLoader` не читает
> (он читает `.toml` и блок `# [command]`).

### 7.4 `module_loader.py` — hot-подмена GUI-модулей

Механизм полевых hotfix без пересборки exe:

- `_HOT_PACKAGE_PREFIXES` — переопределяемые префиксы: `cashcontrol.gui.toolbar`,
  `cashcontrol.builtin.vnc.vnc_preview`, `cashcontrol.builtin.db_viewer`,
  `cashcontrol.builtin.file_manager`,
  `cashcontrol.gui.dialogs`, `cashcontrol.gui.widgets`.
- `install()` — идемпотентно, только в production; вставляет `_ModulesFinder`
  в `sys.meta_path[0]`. **Обязательно до импорта управляемых модулей**.
- `_ModulesFinder.find_spec()` ищет `<modules_dir>/<rel>.py` или
  `<rel>/__init__.py`; не найдено — `None` (обычный импорт).
- `get_class(qualified_name, class_name) -> type` — с понятной ошибкой.

Использование: `TabManager._init_toolbar()` создаёт тулбар через
`get_class("cashcontrol.gui.toolbar", "CashToolbar")`.

### 7.5 `audit_logger.py`

Два канала:

- `get_logger(name="cashcontrol")` — файл `logs/app_YYYYMMDD.log` (DEBUG,
  формат `asctime | LEVEL | name | message`) + StreamHandler (INFO, ANSI-цвета);
- `get_audit_logger()` — `logs/audit.log`, формат `asctime | message`,
  `propagate=False`;
- `audit_log(action_type, action_name, target="", result="", detail="", **extra)`
  — строковая сериализация; ошибки логирования глушатся (`except: pass`).

Все значимые события (SSH/DB-подключения с `attempts=`, выполнение команд
(`command[:100]`), cash_restart; async-ошибки, действия UI, шифрование паролей)
идут через `audit_log`.

---

## 8. Подсистема `gui` — главное окно и каркас

### Карта связей (диаграмма)

```
main.py ──► MainWindow
              ├─ ActionsRegistry (cashcontrol.actions_registry)
              ├─ SidebarPanel
              ├─ TabManager
              │    ├─ SessionManager        (реестр сессий, пинг, VNC-процессы)
              │    ├─ CashTabBar            (вкладки + точка-статус пинга)
              │    ├─ CashToolbar           (через module_loader.get_class)
              │    └─ QStackedWidget[CashSessionWidget…]
              │          ├─ VncPreviewWidget
              │          ├─ InfoGroupWidget (секции информации)
              │          └─ core: CashSession, InfoCollector, ProblemChecker
              └─ CashStatusBar
                   ├─ HistoryManager      (синглтон)
                   └─ NotificationManager (синглтон)
```

### 8.1 `main_window.py` — `MainWindow(QMainWindow)`

- Заголовок `CashControl v3.8.1` (из `cashcontrol/__init__.py`), min 960×640.
- Сборка: `QHBoxLayout` → **SidebarPanel** + вертикальный разделитель (1px) +
  колонка (TabManager + CashStatusBar).
- Владеет `ActionsRegistry` (`self._registry`).
- **Хоткеи** (по коду клавиши, работает на любой раскладке):
  `Ctrl+T` — добавить кассу; через тулбар активной вкладки:
  `Ctrl+S` SSH, `Ctrl+W` WinSCP, `Ctrl+D` PostgreSQL, `Ctrl+R` рестарт ПО,
  `Ctrl+Shift+R` ребут, `F5` обновить инфо, `F6` PostgreSQL, `F7` клавиатура,
  `F8` команды; `Ctrl+V` — встроенный VNC, `Ctrl+Shift+V` — внешний VNC.
- `showEvent` → `_post_show_init` (загрузка команд после показа) +
  `restore_sessions()`. `closeEvent` → `cleanup()` (убить VNC-процессы),
  `save_sessions()`, аудит `app_close`.
- Геометрия окна — в `QSettings("MainWindow")`.
- QSS: `styles/fluent_tabs.qss` (три кандидата-каталога prod/dev).

### 8.2 `sidebar.py` — `SidebarPanel(QWidget)`

Вертикальная панель 48px, кнопки-иконки: Настройки (`SettingsDialog`),
Редактор команд (`CommandEditorDialog`), → stretch → Журнал действий
(`LogsViewerDialog`, немодальный), О программе (`HelpDialog` с
`WA_DeleteOnClose`, защита от GC). Все обработчики пишут аудит
`action_type="ui"`.

### 8.3 `tab_manager.py` — `TabManager(QWidget)`

Сигнал: `active_tab_changed = Signal(object)` (активный IP или `None`).

- Собирает `CashTabBar` + скрытый `CashToolbar` + `QStackedWidget`
  (placeholder-лейбл либо `CashSessionWidget`).
- `add_tab(ip, connect=True)`: трим, дедупликация, лимит `max_tabs`
  (`InfoBar.warning`), создание виджета, регистрация в `SessionManager`,
  подписка `info_loaded → _on_session_info_loaded` (обновление тулбара),
  `_start_ping`, аудит `tab_open`.
- `close_tab(ip)`: стоп пинга, `kill_vnc`, `cleanup()`, `deleteLater`,
  `save_sessions()`.
- `change_tab_ip(old, new)`: дедупликация, перевешивание ключа в
  `SessionManager`, `tab_bar.update_route_key`, `move_vnc`, `save_sessions`,
  `ensure_future(reconnect_to(new_ip))`.
- `restore_sessions()` / `_connect_in_waves()` — восстановление вкладок с
  `Semaphore(3)`.
- `cleanup()` / `save_sessions()` — делегируют.

### 8.4 `tab_bar.py` — `CashTabBar(QWidget)`

Обёртка над `qfluentwidgets.TabBar` (movable, max width 220, кнопка «+»,
крестик по hover, скролл колесом, средняя кнопка = закрыть).

Сигналы: `tab_add_requested`, `tab_close_requested(str ip)`,
`tab_selected(str ip)`, `tab_ip_changed(str old, str new)`,
`tab_refresh_requested(str ip)`, `tab_copy_ip_requested(str ip)`.

- `set_ping_status(ip, status)` — иконка-«точка»:
  `{"ok": "success", "slow": "warning", "timeout": "error", "unknown":
  "text_tertiary"}` (цвета из `theme_helper`).
- Контекстное меню вкладки: «Закрыть», «Изменить IP», «Обновить данные»,
  «Копировать IP». Двойной клик → редактирование IP.

### 8.5 `session_manager.py` — `SessionManager(QObject)`

Сигналы: `ping_status_changed(str ip, str status)`, `session_added`,
`session_removed`.

- Реестр `_sessions: dict[ip, CashSessionWidget]`, свойство `active_ip`.
- **Пинг**: `start_ping/stop_ping`; `_ping_loop(ip)` — каждые
  `connection.ping_interval` сек; `_do_ping` — `socket.create_connection((host, 22),
  timeout=1.5)` в `run_in_executor`; `None→timeout`, `<300мс→ok`, иначе `slow`.
- **VNC-процессы**: `kill_vnc(ip)` (terminate → wait(3) → kill),
  `kill_all_vnc()`, `move_vnc(old, new)`.
- **Персистентность**: `save_sessions()` — JSON-список IP в `sessions.json`;
  `restore_sessions()`.
- `cleanup()` → `kill_all_vnc()`.

### 8.6 `cash_session_widget.py` — `CashSessionWidget(QWidget)`

Сигналы: `info_loaded(str cash_type)`, `connection_state_changed(str ip,
str status)`, `_section_ready(object)` (внутренний).

Секции → группы UI: `_SECTION_TO_GROUP`
(`system`: cash_type/os/cpu/software; `equipment`: fiscal_printer/customer_display/
scanners/scales/keyboard/bank_terminal; `other`: dns/loymax/qrid);
`_GROUP_TITLES` (Касса / Оборудование / Прочее / Проблемы).

**Layout**: горизонтальный `QSplitter` (VncPreviewWidget min-width 300 |
инфо-панель 400:600) + нижняя VNC-панель 40px (Подключить / Отключить /
Полный экран + статус-лейбл). Инфо-панель — QScrollArea из `InfoGroupWidget`.

**Жизненный цикл подключения** — `connect_coro()`:
1. `CashSession(ip).connect(connect_db=False)`;
2. неудача → `connection_state_changed("timeout")` + кнопка «Переподключить»;
3. успех → история `HistoryEntry("Подключение", ...)`, `vnc_widget.set_session()`,
   если был `_vnc_resume` — `connect_vnc()`;
4. `CashTypeCollector().collect(session)` → при `db.enabled` — `setup_db` +
   параллельная задача `_connect_db_notified` (в `session.db_connect_task`);
5. `load_info()`.

**Сбор информации**:
- `maybe_refresh_in_background()` — фоновый ре-коллект, если с момента
  загрузки > `ttl*0.8` (stale-while-revalidate);
- `_collect_info(force)`: `_show_skeletons()` → `InfoCollector().collect_all(
  session, force, on_section_ready=lambda s: self._section_ready.emit(s))` —
  ключевой мост «секция готова → слот `_render_section` в GUI-потоке»;
- `_render_section(section)`: статусы `TIMEOUT/ERROR` → `show_timeout/show_error`;
  билдеры строк по имени секции (с проверкой фич через `has_feature(...)`);
- `_check_problems(snapshot)` → группа «Проблемы» через `ProblemChecker`.

**Публичный VNC API**: `connect_vnc()`, `open_vnc_external()`;
`reconnect_to(new_ip)` — `session.abort()` (жёсткий обрыв), смена IP,
`start_connecting()`; `cleanup()`/`closeEvent` каскад.

### 8.7 `toolbar.py` — `Toolbar` и `CashToolbar`

- **`Toolbar`**: кнопки «+», обновление, настройки (+ сигналы
  `add_cash_requested`, `refresh_requested`, `settings_requested`).
- **`CashToolbar`** (per-tab; центр запуска внешних инструментов):
  - кнопки: Рестарт (`restart_cash`), Ребут (`reboot_cash`),
    VNC, SSH, WinSCP, PostgreSQL, клавиатура (видна только при фиче
    `keyboard`), обновление данных, Команды;
  - `_make_labeled_btn()` — кнопка 32×32 + подпись 9px;
  - `update_for_cash_type()` — видимость клавиатуры;
  - Hover-prefetch: `installEventFilter` → `schedule_tcp(active_ip, ssh_port)`;
  - `_launch_program(exe, args_template, name)` — шаблон с переменными
    `{host} {port} {login} {db_port} {db_login} {display}`, `subprocess.Popen`;
  - `_on_ssh`: если `should_use_builtin_ssh(path)` → встроенный терминал
    (см. §8.8), иначе KiTTY `[exe, "login@ip", -pw <password>
    -auto-store-sshkey]` (пароль из `session.ssh.successful_password`,
    запуск в daemon-потоке с `creationflags=0x08000000`);
  - `_on_winscp`: если `should_use_builtin_files(path)` (путь не задан или файл
    отсутствует) → встроенный файловый менеджер `open_file_manager(...)` (см.
    §8.13), иначе WinSCP: протокол `sftp` (ubuntu) / `scp` (tinycore),
    URI `proto://login:password@ip/`, `/hostkey=*`, `/rawsettings AuthKI=0 …`;
  - `_on_postgres`: путь не задан → встроенный `PostgresToolWindow(host, port,
    user, passwords)` (проверка psycopg2); иначе внешний клиент;
  - `_on_commands_clicked`: `registry.reload_commands()`, QMenu из
    `get_all_actions()` (сортировка по description), подтверждение при
    `requires_confirmation`, пункт «Тип кассы: выбрать вручную…»
    (`__select_cash_type__`);
  - `_on_keyboard`: `find_layout_for_keyboard(keyboard_model)` →
    `VirtualKeyboardWindow(session, layout_stem)`.

### 8.8 `builtin/ssh_terminal_launcher.py` — запуск встроенного терминала

Терминал живёт в **отдельном процессе** со своим `QApplication`/qasync-циклом
(изоляция от пингов и коллекторов приложения). Модуль разрешает корень
терминала относительно себя: `Path(__file__).resolve().parent / "terminal"`
(в dev — `src/cashcontrol/builtin/terminal`, в сборке —
`runtime\app\cashcontrol\builtin\terminal`).

```python
builtin_terminal_root() -> Path                  # Path(__file__).parent / "terminal"
should_use_builtin_ssh(client_path) -> bool      # путь не задан или файла нет
terminal_python() -> str                         # pythonw, если рядом есть
build_terminal_command(host, port, login, password_stdin) -> list[str]
launch_builtin_terminal(host, port, login, password, parent=None) -> Popen | None
```

Механика `launch_builtin_terminal`:
- `Popen([pythonw, main.py, --host, --port, --login, (*--password-stdin)],
  cwd=builtin_terminal_root(), creationflags=_CREATE_NO_WINDOW, stdin=PIPE,
  stdout=DEVNULL, stderr=файл logs/ssh_terminal_child_stderr.log)`;
- **пароль — первой строкой в stdin** (не светится в списке процессов);
- возвращает Popen и не ждёт завершения; аудит `action_type="tool",
  action_name="ssh_client"`.

### 8.9 `builtin/vnc/vnc_preview.py` — встроенный VNC

RFB 3.x-клиент на чистых сокетах + потоки. GUI-поток держит `QImage`,
сеть изолирована в фоновый поток.

- `_DepthPreset` / `_DEPTH_PRESETS`: 8 бит (палитра 256), 16 бит (RGB565,
  shifts 11/5/0), 32 бит (RGB True Color, дефолт). `_DEFAULT_DEPTH_IDX = 2`.
- Маски колеса `_WHEEL_UP_MASK=8`, `_WHEEL_DOWN_MASK=16`.
- `_X11VNC_CMD` — bash-скрипт для внешнего полноэкранного VNC: поиск x11vnc,
  определение `DISPLAY` через `w -h`, `sudo killall x11vnc`,
  `nohup x11vnc -display $DISP -forever -shared -bg -listen 0.0.0.0
  -rfbport 5900 -nopw`. `_VNC_START_DELAY = 5.0`.
- `_QT_KEYSYM` — карта Qt-клавиш → keysym X11; `_qt_to_keysym(key, text, mods)`.
- Состояния `_ConnState`: `DISCONNECTED/CONNECTING/CONNECTED/ERROR`;
  команды `_Cmd`: `DISCONNECT/KEY_EVENT/POINTER_EVENT/FULL_UPDATE/SET_DEPTH`.

**`_VNCWorker(threading.Thread)`** — сетевая машина:
- `run()`: `_connect → _handshake (RFB 3.x, SecurityType None/inline) →
  on_connected(w,h) → send_pixel_format → send_encodings (CopyRect/Raw/
  DesktopSize) → request_update → main_loop`.
- `_main_loop`: drain командноны очереди, keep-alive инкрементальные запросы
  (0.2 с), чтение сообщений (update/colormap/bell/cut-text);
- конвертация `_to_rgba32(raw, w, h, bpp)` через numpy (32bpp байт-в-байт,
  16bpp bit-replication, 8bpp из палитры);
- ограничения: `MAX_FRAMEBUFFER_PIXELS=64_000_000`, `MAX_SERVER_TEXT=1_048_576`.

**`EmbeddedVNCWidget(QWidget)`** — сигнал `state_changed(str, str)`:
- всё общение worker→GUI через **очередь событий + `_WorkerEventBridge`
  (QueuedConnection)** — потокобезопасно, события старых поколений
  отбрасываются по `_generation`;
- `_paint_timer` 16 мс (пакетная `_apply_updates`), `_retire_timer` 50 мс
  (безопасный reap потоков, `join(timeout=0)`);
- `connect_vnc/disconnect_vnc/set_depth(idx)`; `is_connected`;
- клавиатура/мышь → `_Cmd.KEY_EVENT/POINTER_EVENT` (`_send_key/_send_pointer`).

### 8.10 `history_manager.py` и `notification_manager.py`

- **`HistoryEntry`**: `timestamp, action_name, result, details, ip`.
- **`HistoryManager(QObject)`** (синглтон `instance()`): мапа
  `_memory[ip] → list`; режимы `history_mode` (`session` — в памяти,
  `persistent` — JSONL batched: накопление, flush по таймеру 500 мс или 10
  строкам, файлы `data/history/{ip_escaped}.jsonl`). Сигнал
  `entry_added(str ip, HistoryEntry)`. `get(ip, limit=100)`.
- **`NotificationManager(QObject)`**: легких уведомлений вместо Toast.
  Сигнал `notification_added(object)`; `notify(message, level)`,
  `get_all()`, `clear()`.

### 8.11 `prefetch.py`

Hover-«прогрев» TCP-маршрута: `schedule_tcp(ip, port=22)` с троттлингом
`_THROTTLE_S = 3.0`; `asyncio.open_connection(ip, port)` c `wait_for(1.0)`.
Синглтон `get_prefetcher()`.

### 8.12 `theme_engine.py` и `theme_helper.py`

- **`ThemeEngine(QObject)`** (синглтон): `apply(theme: "light"|"dark"|"auto")`
  → `setTheme` + `_apply_stylesheet()`; сигнал `theme_changed`; `current()`.
  Генерирует QSS: общий блок (QToolTip, QSplitter::handle, QMenu, QMessageBox,
  QDialog) + блок темы (окно, панели, таблицы, кнопки, табы).
- **`theme_helper.py`**: `color(name) -> str` — пары `(light_hex, dark_hex)`
  по семантическим именам (фоны `bg_*`, текст `text_*`, границы `border_*`,
  акцент, статусы `success/error/warning/info`, `separator`, кнопки, `vnc_bg`).
  Неизвестное имя → `#ff00ff` (маркер). `colors(*names)`, `styled(template)`.

### 8.13 `builtin/file_manager_launcher.py` и `builtin/file_manager/`

- **`file_manager_launcher.py`**: интеграция встроенного файлового менеджера.
  - `should_use_builtin_files(winscp_path) -> bool` — встроенный менеджер, если
    внешний WinSCP не задан или файл отсутствует (fallback, как у VNC/SSH);
  - `open_file_manager(host, port, login, password, start_dir, protocol,
    parent=None)` — открывает (или поднимает) окно `RemoteFilesWindow`
    in-process; по одному окну на (host, port), сигнал `destroyed` чистит реестр;
  - менеджер работает **в процессе** приложения: свой asyncio-loop на воркер-потоке
    (`gui/runtime.py → AsyncExecutor`), поэтому не делит (и не тормозит) qasync-loop.
- **`file_manager/`** — копия standalone-пакета (без импортов `cashcontrol.*`):
  `models.py` (файлы/трансферы/ошибки), `backends.py` (SFTP-реализация на
  `asyncssh` + host key store), `service.py` (очередь трансферов, конфликты),
  `gui/` — `window.py` (многооконный CashSCP, F2–F8/Ctrl+L и т.д.), `session.py`,
  `runtime.py` (AsyncExecutor, локальный FS), `widgets.py`, `dialogs.py`.
  Модули входят в hot-список (см. §7.4) и overlay `modules/`.

---

## 9. Диалоги и виджеты GUI

### 9.1 `dialogs/`

| Модуль | Класс | Назначение |
|---|---|---|
| `add_cash_dialog.py` | `AddCashDialog` | ввод IP/hostname (regex, октеты ≤255), замена запятых на точки; `get_ip()` |
| `alias_editor.py` | `AliasEditorDialog(alias_key, current_value, builtin_value)` | «Справочник оборудования»; `set_alias/resolve` через `AliasManager` |
| `command_editor.py` | `CommandEditorDialog` | «Конструктор команд»: список + форма (тип `ssh`/`python`); шаблон `_PY_TEMPLATE`; поля: name, description, type, timeout, confirm, show_output |
| `command_result_dialog.py` | `CommandResultDialog(result: ActionResult)` | отображение `success/message/details.output/error` |
| `help_content.py` / `help_css.py` / `help_dialog.py` | `HelpDialog` | справочник: дерево разделов (`_TREE`) + HTML; `_page_changelog` конвертирует `docs/patch.md` |
| `logs_viewer.py` | `LogsViewerDialog` + `_LogPanel` | вкладки «app_*.log» и «audit*.log», фильтр по уровню, поиск, подсветка, автопрокрутка |
| `settings/settings_dialog.py` | `SettingsDialog` | меню (Подключение/Программы/Общие/Логи) + `QStackedWidget`; `_save_all()` → `config.save()` + аудит `update_settings` |
| `settings/tab_connection.py` | `TabConnection` | SSH (логин, порт, пароли — TextEdit с кнопками «Показать»/«Очистить»), PostgreSQL, VNC (порт, quality, color_level) |
| `settings/tab_general.py` | `TabGeneral` | тема/язык/режим истории; лимиты max_tabs/cache_ttl/timeout; применяет тему сразу |
| `settings/tab_logs.py` | `TabLogs` | уровень логирования, открыть папку, очистить логи |
| `settings/tab_programs.py` | `TabPrograms` | пути к KiTTY/WinSCP/VNC/PostgreSQL + шаблоны аргументов; SSH-карточка с описанием встроенного терминала и горячих клавиш; скрытые поля `ssh/winscp_args_template`, `vnc/db_args_template` |

Важно для `tab_programs.py`: скрытое поле `self.ssh_args_template` создаётся
**до** `return card` — иначе `load()/save()` упадут с `AttributeError`
(зафиксированный баг в 3.8.0).

Формат шаблонов аргументов (дефолты из `save()`):
- `ssh_args_template`: `-- ssh -o StrictHostKeyChecking=no … -p {port} {login}@{host}`;
- `vnc_args_template`: `{host}:{display}`;
- `winscp_args_template`: `/open scp://{login}@{host}:{port}`;
- `db_args_template`: `-h {host} -p {db_port} -U {db_login}`.

### 9.2 `setup_wizard/` — мастер первого запуска

`CashControlSetupWizard(QWizard)` (ModernStyle, min 680×580). Страницы:
`WelcomePage → ConnectionPage → ConnectionTestPage → ProgramsPage →
FinishPage`.

- `ConnectionPage` — SSH (login/port/passwords) + PostgreSQL (login/port/passwords);
  `registerField("ssh_login", …)` и т.д.; `isComplete()` — непустой SSH-логин.
- `ConnectionTestPage` — поле IP, кнопка «Проверить»; `_do_test_async(ip)`:
  **сначала сохраняет креды в ConfigManager** (иначе `CashSession` их не
  увидит), затем `CashSession(ip).connect()` + `setup_db("postgres")` +
  `connect_db()`; `cleanupPage()` отменяет незавершённую задачу.
- `ProgramsPage` — пути KiTTY/VNC/WinSCP с кнопками «Обзор…»/«По умолчанию»/
  «Автопоиск» (из `get_soft_dir()`).
- `FinishPage` — сводка введённого.
- `wizard._on_finished()` — шифрует пароли (`encrypt_passwords`),
  `config.update("connection", …)`, `update("general", setup_completed=True)`.

> Наблюдение: `ProgramsPage` не регистрирует полей мастера; выбранные пути
> в `_on_finished()` не сохраняются (потенциальная точка доработки).

### 9.3 `widgets/`

#### `info_section_widget.py` — `InfoGroupWidget(QFrame)`

Группа «title + поля-key:value» с прогрессивным наполнением:
- `show_loading()` — скелетон-полосы; `show_timeout()`, `show_error()`;
- `add_items(fields)` — копит и перерисовывает RichText-тело;
- значения с `alias_key` — ссылки `href="alias:{key}"` → контекстное меню
  «Изменить название / Добавить в справочник / Сбросить к умолчанию»
  (через `AliasEditorDialog`, `get_alias_manager()`);

#### `virtual_keyboard.py` — клавиатура экранных касс

- Раскладки: `LAYOUTS` (`csi_hengyu_s84e 7×8`, `vioteh_kb66 6×11`,
  `hengyu_s78d 7×8`), JSON в `data/keyboard_layouts/`.
- `find_layout_for_keyboard(model)` — нормализация + совпадение модели по
  фрагментам (`_LAYOUT_ALIASES`) или fuzzy по stem.
- `build_xdotool_cmd(key_seq)` — `Ctrl+Alt+Shift+Win+Клавиша` →
  `DISPLAY=:0 xdotool key --clearmodifiers <клавиша>`;
- `_KeyButton` — авто-подбор размера шрифта (22pt → вниз по `boundingRect`);
- `_ButtonSettingsDialog` — подпись + запись горячей клавиши (eventFilter,
  спец-сканкоды Numpad; QTimer 500 мс = конец записи);
- `KeyboardEditorWindow` — конструктор раскладок (двойной клик — настройка,
  ПКМ — очистка), `save_layout`;
- `VirtualKeyboardWindow` — операторская клавиатура (on-top):
  `_ensure_xdotool()` — проверка/установка xdotool по SSH
  (`which … || tce-load -i xdotool.tcz …`), нажатия → `session.ssh.execute(
  build_xdotool_cmd(action), timeout=5)` фоном.

### 9.4 `builtin/db_viewer/` — встроенный клиент PostgreSQL

**Архитектура**: работает напрямую через **psycopg2**, НЕ через `core.db`.
Соединения — в `QThread` (`_Worker`, паттерн «job»). Параметры подключения
(host/port/user/passwords/database) передаются извне (вызывающей строной).

| Модуль | Класс | Назначение |
|---|---|---|
| `widget.py` | `PostgresToolWidget`, `PostgresToolWindow` | главный виджет: `_TablesPanel` + QTabWidget таблиц + выдвижная `_SqlConsole` (анимация maximumHeight, Ctrl+L); статус-бар с прогрессом |
| `tables_panel.py` | `_TablesPanel` | комбо БД + список таблиц/вью (иконки по типу), свойства таблицы (имя/тип/строки/размер/колонки/комментарий), debounce 220 мс, контекст-меню |
| `data_panel.py` | `_DataPanel` | открытая таблица: фильтр + локальный поиск по странице + грид + пагинация (размеры 50/100/200/500/Все), правки (bulk UPDATE), delete, экспорт CSV/JSON, импорт CSV |
| `data_grid.py` | `_DataGrid` | QTableWidget с dirty-трекингом (желтая подсветка правок), контекст-меню (копировать/строка/NULL/открыть в консоли), PK-защита |
| `sql_console.py` | `_SqlConsole`, `_SqlEdit`, `_SqlHighlighter`, `_Completer` | консоль: выполнение (Ctrl+Enter), история, закладки, экспорт CSV/JSON, автодополнение (Ctrl+Space, `tbl.col`), результат — в _DataGrid |
| `sql.py` | функции | SQL-запросы: список БД/таблиц/колонок, строка-формирование `SELECT`, pagination + ORDER BY, `_build_where`, `_export_rows` |
| `storage.py` | `_DbError`, `_data_dir`, `_load_json/_save_json`, `_toast`, `_Busy` | JSON-хранилище истории/закладок, тосты, счётчик занятости |
| `formatting.py` | `_fmt`, `_kind`, `_parse_value`, `_EDITABLE`, `_human`, `_qi/_qtable`, `_mono` | формат значений классификация типов, парсинг ввода, человеческие ошибки |
| `constants.py` | `_PAGE_SIZES`, `_HISTORY_LIMIT=100`, `_MAX_CONSOLE_ROWS=500` | константы |
| `workers.py` | `_ConnFactory`, `_Worker(QThread)` | фабрика соединений (перебор паролей, `connect_timeout=5`, `application_name='CashControl'`), jobs с `done/failed` сигналами и `cancel()` |
| `csv_import.py` | `_CsvImportDialog` | превью 15 строк, кодировка/разделитель/заголовки, маппинг колонок; импорт — `INSERT … VALUES %s` батчами по 500 через `execute_values` |

При редактировании значения парсятся `_parse_value(text, coltype)` (русские
bool-синонимы «да»/«нет», datetime по fromisoformat, JSON через `json.loads`);
идентификаторы экранируются `pgsql.Identifier`.

---

## 10. Встроенный SSH-терминал (пакет builtin)

Вендоренная подсистема в `src/cashcontrol/builtin/terminal/`, запускается
**отдельным процессом** (см. §8.8). Зависимости: `asyncssh`, `pyte`,
`PySide6`, `qasync`. Имеет собственный README/run.bat/requirements.txt и
стиль (исключён из ruff).

### 10.1 Поток данных

```
данные:  SSH → asyncssh → PtyStream._read_loop → _decode (utf8/cp1251)
         → _emit_output (порциями 4096, GC-off при флуде) → emulator.feed(text)
         → outputReceived.emit() → TerminalWidget.note_data → _dirty → repaint

ввод:    TerminalWidget.keyPressEvent → _encode_key → dataToWrite.emit(seq)
         → session.write → PtyStream.write_sync → proc.stdin
```

### 10.2 `main.py`

- `main()`: логирование (в файл `logs/ssh_terminal_<date>.log` при pythonw),
  чтение пароля из stdin (`--password-stdin`), QApplication + qasync-цикл,
  **хак события установки** `asyncio.set_event_loop(qasync …)` — без этого
  `ensure_future` в `session.start()` планируется в «голом» ProactorEventLoop
  и терминал «зависает» (исправленный баг);
- флаги: `--host`, `--port`, `--login`, `--name`, `--password-stdin`;
  при `--host` — автоподключение `window.new_connection(profile)`.

### 10.3 `core/connection.py` — SSH-соединение (TOFU)

- `_SERVER_HOST_KEY_ALGS` — кортеж алгоритмов (ed25519/ecdsa/rsa + серты);
- `_TofuSSHClient(asyncssh.SSHClient)` — `validate_host_public_key` делегирует
  `owner._trust_new_host_key`;
- `SSHConnection(host, port, username, _password, _client_keys,
  _known_hosts_path, _connect_timeout, _keepalive_interval)`:
  - `connect()` под `asyncio.Lock`; `is_connected`;
  - `acquire()` — вернуть живое соединение (переподключение при смерти);
  - `_connect_inner()`: `known_hosts=b""` (отключён встроенный матчер — только
    наш `_TofuSSHClient`), `agent_path=None`, ретраи ×2 с `sleep(1.5*attempt)`,
    `HostKeyNotVerifiable` — без ретрая;
  - `_trust_new_host_key`: запись `[{addr}] :{port} <openssh-public>`;
    известен → True; «тот же префикс, другой ключ» → **False** (TOFU mismatch);
    иначе — дописать и True;
  - `close()` — навсегда (реконнект запрещён), `disconnect`-стиль не сохранён.

### 10.4 `core/pty.py` — PTY-канал

- `PtyStream(conn, rows, cols, term_type)"xterm-256color", on_output, on_closed)`:
  - `start()` — `conn.create_process(term_type=…, term_size=(cols, rows),
    encoding=None)`; `encoding=None` → байты декодируем сами;
  - `_read_loop()` — единственный читатель: `proc.stdout.read(8192)`, `_decode`,
    `_emit_output`; stderr приходит внутри PTY (SSH сливает в stdout);
  - `write_sync(data)` — «быстрая запись без drain», `.encode("utf-8")`;
  - `resize(rows, cols)` — `change_terminal_size(cols, rows)` (ширина, высота);
  - `_decode()` — utf-8; при `UnicodeDecodeError`: если хвост — незавершённый
    multibyte (`_is_truncated_tail` — ведущий 0xC2..0xF4 + continuation bytes)
    → сохранить в `_partial_utf8`; иначе — cp1251 с replace;
  - **GC-guard**: `_gc_acquire()/_gc_release()` — полный sweep `gc.disable()`
    на время флуда крупного чанка (при scrollback 1.6M+ Char паузы 50–100 мс);
  - `_emit_output`: порции по 4096 с `await asyncio.sleep(0)` между ними —
    терминал «плавно догоняет» поток.

### 10.5 `core/session.py` — `TerminalSession`

Связка `SSHConnection` + `PtyStream` + `TerminalEmulator`. Одна вкладка =
одна сессия = одно SSH-соединение + PTY.

Сигналы: `statusChanged(str)`, `connected()`, `disconnected(str)`,
`connectionFailed(str)`, `outputReceived()`.

- `start()` → statusChanged «Подключение…» + `ensure_future(_connect_and_open_pty)`;
- `_connect_and_open_pty()`: SSHConnection(profile, known_hosts_path=
  `store.known_hosts_path`, настройки из `store.settings`) → `connect()`
  → `connected.emit()` → `store.push_recent(profile)` → PtyStream(
  `acquire()`) → `pty.start()`;
- `_on_output(text)`: дамп потока (если включён) → `emulator.feed(text)` →
  `outputReceived.emit()`;
- `write(data)`, `resize_pty`, `start_stream_dump/stop_stream_dump`
  (диагностика `session_dump.log`), `_handle_title` (OSC → statusChanged);
- `close()` — аккуратное; `abort()` — быстрое (ensure_future `_abort_pty`/
  `_close_quietly` с `wait_for(3.0)`, чтобы `finally` читателя не вызвал
  `_on_pty_closed` после удаления QObject).

### 10.6 `data/profiles.py`

- `_app_data_dir()` — `<проект>/data/app/` (portable, система не засоряется);
- `HostProfile(name, host, username="root", port=22, password=None,
  color_tag="none", last_connected=None)`; `profile_id="host:port:username"`;
- `AppSettings(font_size=10.0, font_family=None, scrollback_lines=10000,
  copy_on_select=True, keepalive_interval=15.0, connect_timeout=15.0,
  theme="dark", cursor_keys_mode="auto", term_type="xterm")`;
- `_JsonStore(filename)` — атомарная запись (`*.tmp` → `replace`);
- `ProfileStore` — `profiles.json`: `all_profiles/upsert/delete/push_recent/
  recent_ids`, `settings`, `known_hosts_path`.

### 10.7 `data/snippets.py`

`Snippet(name, command, description, tags, send_with_enter=True,
scope="global"|"profile:host:port")`. `SnippetStore.search(query, scope)` —
поиск с приоритетом: имя → теги → тело команды; учёт скоупа. Дефолтный
сниппет `usb → lsusb`.

### 10.8 `terminal/emulator.py` — VT-эмуляция (pyte + апгрейды)

Ядро терминала без Qt. Принимает `str`, хранит экраны, отдаёт `list[Char]`
на строку, кодирует ввод/мышь в escape.

- **`_FastScreen(pyte.screens.Screen)`** — быстрый `draw()`: строит `Char`
  позиционным конструктором (без `attrs._replace`), кэш атрибутов на ran,
  ширина символов через `wcwidth`, wide-символы + пустой заполнитель,
  combining → NFC-нормализация.
- **`_ProxyScreen`** — форвардит события активному экрану и перехватывает
  приватные режимы `{"set_mode","reset_mode","write_process_input",
  "set_title","set_icon_name","bell"}`; `_keypad_application_on/off`.
  Жёсткий `assert` на поля `Char._fields` (ломается при изменении pyte).
- **`TerminalEmulator(cols=80, rows=24, scrollback_lines, on_title, on_bell,
  on_write_process)`**:
  - primary + alternate `_FastScreen`, `in_alternate`, scrollback
    `deque(maxlen)`, `scroll_offset`, `application_cursor_keys` (DECCKM),
    `bracketed_paste` (2004), `mouse_mode` (0/9/1000/1002/1003),
    `mouse_encoding` (x11/utf8/sgr/urxvt);
  - **KEYPAD-патч**: `stream.escape["=" / ">"]` → keypad application on/off
    (пересоздание диспатчеров pyte);
  - `feed()` c фолбэком `_feed_resilient()` — бинарный поиск мусорной
    escape-последовательности, обычный текст не теряется;
  - `scrollback`-патчи: `_patch_primary_index()` (уход строки с низа → в
    scrollback), `_patch_responses()` (DA/DSR — `write_process_input` на
    экранах);
  - `_handle_private_mode`: 1049/47 → alt-screen (+save/restore курсора для
    1049), 1 → DECCKM, 2004 → bracketed paste, 9/1000/1002/1003 → мышь,
    1005/1006/1015 → кодировка мыши;
  - `mouse_bytes(MouseEvent) -> str | None` — X10, SGR (1006, release → кнопка
    3 с `m`), utf8 (1005), urxvt (1015);
  - `wrap_paste(text)` — bracketed paste `\x1b[200~…\x1b[201~`;
  - `line_at(index)` — в alt — строка экрана; иначе лента scrollback|primary
    с нормализацией ширины; `total_lines()`; `cursor_xy()`;
  - `scroll_view(delta)/scroll_to(offset)`; `clear_scrollback()`; `reset()` (RIS).

Пример протокола: `color_to_hex(color, palette)` — pyte-имя цвета → `#rrggbb`
(«default» → None, `bright*` → палитра 8–15).

### 10.9 `ui/terminal_widget.py` — рендерер

- `TerminalColors` — Catppuccin Mocha: bg `#1e1e2e`, fg `#cdd6f4`,
  cursor `#f5e0dc`, selection `#45475a`, base16.
- **Сигналы**: `dataToWrite(str)`, `sizeChanged(rows, cols)`, `titleChanged`,
  `closed(int)`, `bellRung()`, `cursorModeChanged(str)`.
- **Сниппет-попап**: `_ensure_snippet_popup` (лениво), `_update_snippet_popup`
  (накопление слова, Backspace, пробел сбрасывает), `_position_snippet_popup`
  (под курсором), `_insert_snippet_inline` (лось `\x7f * n` для уже ушедших
  символов слова + `wrap_paste` + `\r` при send_with_enter).
- **Клавиатура** (`keyPressEvent` → `_encode_key`):
  - Ctrl+Shift+C/V, Shift+Insert/Ctrl+Insert;
  - Shift+PgUp/PgDn — локальная прокрутка (на `rows-1`);
  - режим стрелок: `app = forced_cursor_mode or (application_cursor_keys or
    application_keypad)`; таблицы `_KEYMAP_BASE`/`_KEYMAP_APP_CURSOR`;
  - модификаторы на спецклавиши → `CSI 1;mA`, Alt → `\x1b`+out;
  - Backspace → `\x7f`, Ctrl+Backspace → `\x08`, Enter → `\r` (Keypad+app →
    `\x1bOM`), Tab → `\t`, Esc → `\x1b`, Ctrl+пробел → `\x00`;
  - Ctrl+буква → `chr(ord()-96)`, спецсимволы `@[\]^_` → `\x00\x1b…`;
  - Alt+текст → `\x1b` + текст.
- **Мыш**: click в скроллбар (`_SCROLLBAR_W=8`); захват мыши при
  `mouse_mode != 0` (шлёт события кнопок 64/65 колеса, drag с маской 32,
  release сброс); ПКМ при захвате — хосту, Shift+ПКМ — контекст-меню,
  при выделении — копировать (PuTTY-стиль), иначе — вставить; средняя —
  вставить; двойной клик — слово + копировать.
- **Рендер** (`paintEvent`/`_paint_contents`): батч-рисовка — группа подряд
  идущих ячеек с одним `_style_key` = один fillRect + один drawText; кеш
  стилей и hex-палитры; `_style_colors` — selected, bold → `_brighter`,
  reverse; **блок-курсор** с миганием 500 мс (`_blink_timer`), виден только
  при `scroll_offset == 0`; свой полупрозрачный скроллбар (низ = живой экран);
  в alt-режиме — без scrollback.
- **Крут repaint**: `_KEYS_PER_SECOND=30` (таймер ~33 мс, single-shot),
  `note_data()` → `_dirty=True`; `_delayed_repaint()` снимает флаг.

### 10.10 `ui/main_window.py` — окно терминала

- `_TabBarWithMenu` — closable/movable/document mode, контекст-меню
  (Переименовать / Дублировать / Закрыть).
- `MainWindow`: `store=ProfileStore()`, `snippets=SnippetStore()`,
  `_sessions: dict[widget, TerminalSession]`; вкладки + `KeyHintBar` снизу.
- Хоткеи: Ctrl+N/Ctrl+T — новое; Ctrl+W — закрыть; Ctrl+Tab/Ctrl+Shift+Tab —
  вкладки; Ctrl++/Ctrl+=/Ctrl+-/Ctrl+0 — шрифт; Ctrl+Alt+M — главное меню;
  Ctrl+Alt+D — дамп потока.
- **Системное меню окна (PuTTY-стиль)**: `ctypes.windll.user32.GetSystemMenu/
  AppendMenuW` + пункты с id `_SYS_MENU_MARKER=0x0F00`; `nativeEvent` ловит
  `WM_SYSCOMMAND` и диспатчит через `QTimer.singleShot(0, …)`.
- `new_connection(profile=None)`: `ConnectDialog` → `TerminalSession` +
  `TerminalWidget(emulator=session.emulator)` (виджет делит эмулятор сессии);
  связи `dataToWrite→session.write`, `sizeChanged→resize_pty`,
  `titleChanged→_on_title`, `outputReceived→widget.note_data`;
  `session.start()`.
- `_on_conn_failed` — модальный `QMessageBox` **только через
  `QTimer.singleShot(0, …)`** (вложенный Qt-loop блокировал бы qasync).
- **Красивая repaint-связка**: `_ensure_repaint_timer()` → QTimer 33 мс →
  `_poll_sessions()` → для каждой вкладки `if w._dirty: QWidget.update(w);
  w._dirty=False`. Это и есть основной рендер-мост между рабочим потоком
  чтения SSH и отрисовкой.

### 10.11 Остальные модули терминала

- **`ui/connect_dialog.py`** — `ConnectDialog(store)`: хостовые поля +
  выбор профиля; `accept()` собирает `HostProfile`, при `check_save` —
  `store.upsert`.
- **`ui/settings_dialog.py`** — `SettingsDialog`: шрифт, размер (6–28),
  scrollback (1000–100000), copy_on_select, term_type.
- **`ui/snippet_manager.py`** — `SnippetManagerDialog` + `_SnippetEditDialog`:
  CRUD сниппетов.
- **`ui/snippet_popup.py`** — `SnippetPopup(QFrame)` (Tool|Frameless|
  AlwaysOnTop, `WA_ShowWithoutActivating`): список ≤8, фильтр имя>теги>тело,
  Tab/Enter — применить, Esc — закрыть; сигналы `activated`, `dismissed`;
  `handle_key()` возвращает True, если клавиша обработана (в PTY не слать).
- **`ui/keyhint_bar.py`** — `KeyHintBar`: строка `^N`, `^W`, `^SV`, …
  кликабельные пункты.

---

## 11. Потоки данных GUI ↔ core

### Сверху вниз (GUI → core)

- `CashSession` — SSH/DB; `InfoCollector.collect_all(session, …)`;
  `CashTypeCollector`; `ProblemChecker.check(snapshot, cash_type)`;
  `ActionsRegistry.execute_action(action_name, session, **kwargs)`;
  `PasswordManager` (пароли SSH/DB для внешних инструментов и терминала);
  `ConfigManager` (настройки); `CommandLoader` (команды);
  `SessionManager._do_ping` (TCP-проба).

### Снизу вверх (core → GUI)

- `InfoSection` через `on_section_ready` → Qt-сигнал `_section_ready` →
  `InfoGroupWidget`;
- `ActionResult` → `CommandResultDialog`;
- исключения/уведомления → `NotificationManager` → статус-бар;
- история действий → `HistoryManager` → статус-бар;
- `ping_status_changed` → цветная точка на вкладке;
- `VNC worker → очередь событий → _WorkerEventBridge → GUI`.

### Изоляция тяжёлых подсистем

| Подсистема | Механизм | Почему |
|---|---|---|
| Встроенный SSH-терминал | отдельный процесс (`Popen` + `pythonw`) | собственный qasync-цикл, изоляция от пингов |
| VNC | фоновый поток `_VNCWorker` + событийная очередь | сеть не блокирует GUI-или qasync |
| DB Viewer | `QThread` `_Worker` с signals | синхронный psycopg2 вне цикла |
| пинг касс | `run_in_executor` / asyncio-task | не блокирует ввод |

---

## 12. Тестирование и сборка

### Тесты (`tests/`, pytest, `asyncio_mode = "auto"`)

- `test_builtin_pty_decode.py` — декодирование PTY-потока;
- `test_builtin_tofu.py` — TOFU-логика; 
- `test_cash_types.py` — registry/merge/detector;
- `test_session_facade.py` — `CashSession` с моками;
- `test_ssh_terminal_launcher.py` — построение команд запуска;
- `test_toml_rules.py` — декларативные правила;
- `test_xml_parse_reference.py` — эталонный XML-парсинг.

Типовые команды:

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\ruff.exe check src tests
.venv\Scripts\python.exe -m ruff format --check src cashcontrol  # при необходимости
```

### Сборка

- Dev-запуск: `python -m cashcontrol` (пакет в `src/`) или консольный скрипт;
- Дистрибутив: `scripts/build_dist.py` — собирает `dist/CashControl/`
  (приложение вместе с встроенным ПО `builtin/`, копирует `commands/`,
  `collectors/`, `cash_types/`, `detection/`, `docs/`, `version.txt`,
  `icon.ico`); из `builtin/terminal` в dist не попадают dev-файлы
  (README/requirements/run.bat), логи и `data/app`;
  **не включает** `data/` и `logs/` (пустые корневые каталоги при сборке);
  исключает KiTTY-мусор из `soft/` (`SshHostKeys`, `Sessions`, `Proxies`,
  `reinstall`) и `*/.7z`;
- Инсталлятор: `CashControl.iss` (Inno Setup 6, UTF-8 с BOM) — per-user
  установка в `{localappdata}\Programs\CashControl`, `PrivilegesRequired=lowest`,
  `Excludes: *.pyc, soft\SshHostKeys, soft\Sessions, soft\Proxies,
  soft\reinstall`; деинсталлятор удаляет `logs`, сохраняет `data`;
- Важно: **не добавлять** `data`/`logs` в `Excludes` инсталлятора — Inno
  матчит имена на любой глубине и выбросит Python-пакет
  `builtin/terminal\data\*.py` (в инсталляторе —
  `runtime\app\cashcontrol\builtin\terminal\data`).
  Сборка идёт с пустыми корневыми `data/`; установщик сам создаст их.

### Рантайм-каталоги (после запуска)

```
data/settings.json        # настройки (пароли — зашифрованы)
data/.keystore            # мастер-ключ Fernet (DPAPI)
data/known_hosts          # SSH host keys (TOFU)
data/aliases.json         # псевдонимы оборудования
data/sessions.json        # список открытых вкладок
data/history/*.jsonl      # история (режим persistent)
data/keyboard_layouts/    # раскладки виртуальной клавиатуры
data/port_mapping.json    # маппинг портов оборудования
data/usb_id_mapping.json  # VID/PID → модели
logs/app_YYYYMMDD.log     # лог приложения
logs/audit.log            # журнал действий
runtime\app\cashcontrol\builtin\terminal\data\app/  # профили/сниппеты/host keys терминала
runtime\app\cashcontrol\builtin\terminal\logs/    # логи терминала + stderr дочерних процессов
```

---

*Документ актуален для v3.8.1. Статью об изменениях см. в `docs/patch.md`.*