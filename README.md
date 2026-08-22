# CashControl

Десктопное приложение для удалённого управления кассовыми терминалами (SetRetail):
подключение по SSH, встроенный VNC-просмотр, редактор PostgreSQL, выполнение команд.

## Возможности

- **Вкладки касс** — одновременная работа с несколькими терминалами, смена IP на лету
- **Встроенный VNC** — pure-Python RFB-клиент с переключением битности (8/16/32 бита)
  и внешним вьюером
- **Информация о кассе** — параллельный сбор данных (ОС, CPU, ПО, оборудование) с
  ленивой загрузкой коллекторов; расширяется TOML-коллекторами
- **Чекер проблем** — автоматическая диагностика типовых неисправностей при подключении
- **Редактор БД** — просмотр и редактирование таблиц PostgreSQL с SQL-подсветкой
- **Команды** — встроенные (TOML) и пользовательские (JSON/Python) команды,
  hot-reload без перезапуска
- **Горячие клавиши** — Ctrl+V встроенный VNC, Ctrl+Shift+V внешний VNC, Ctrl+S SSH,
  Ctrl+W WinSCP, Ctrl+R рестарт ПО, Ctrl+Shift+R перезагрузка кассы

## Требования

- Windows 10/11
- Python **3.12–3.13**
- [uv](https://docs.astral.sh/uv/) (рекомендуется) или pip

## Запуск из исходников

```bat
git clone https://github.com/debrozer-sketch/CashControl.git
cd CashControl

uv venv --python 3.12 .venv
uv pip install -e .

.venv\Scripts\python -m cashcontrol.main
```

или через pip:

```bat
py -3.12 -m venv .venv
.venv\Scripts\activate
pip install -e .
python -m cashcontrol.main
```

При первом запуске откроется мастер настройки: логины/пароли SSH и БД,
пути к KiTTY / WinSCP / VNC-вьюеру (можно найти автоматически).

## Сборка exe

Сборка выполняется через [Nuitka](https://nuitka.net/) (входит в dev-зависимости):

```bat
uv sync
build.bat
```

Готовая сборка появляется в `dist\`. Установщик — `CashControl.iss` (Inno Setup).

## Структура проекта

```
src/cashcontrol/
  core/          SSH, БД, сессии, команды, безопасность
  gui/           окна, вкладки, тулбар, VNC, диалоги, темы
  infrastructure/ конфиг, пути, загрузчики модулей, обновления, аудит-лог
collectors/      TOML-коллекторы информации о кассе
commands/        пользовательские команды (TOML/Python)
docs/patch.md    история изменений (показывается в «О программе»)
tests/           тесты
```

## Тесты

```bat
pytest tests -v
```
