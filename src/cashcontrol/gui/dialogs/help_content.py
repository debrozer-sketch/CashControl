"""
help_content.py — HTML content pages for HelpDialog.
"""

from __future__ import annotations

from cashcontrol.gui.dialogs.help_css import get_css
from cashcontrol.infrastructure.path_resolver import get_app_root


def _screenshot(name: str, caption: str = "") -> str:
    from cashcontrol.gui.theme_helper import color as _tc
    path = get_app_root() / "docs" / "screenshots" / f"{name}.png"
    if path.exists():
        uri = path.as_uri()
        cap = f"<p style='color:{_tc('text_secondary')};font-size:11px;margin:2px 0 12px 0;'>{caption}</p>" if caption else ""
        return (
            f"<p><img src='{uri}' style='max-width:100%;border:1px solid {_tc('border_primary')};"
            f"border-radius:6px;'/></p>{cap}"
        )
    return (
        f"<p style='background:{_tc('bg_warning')};border:1px dashed {_tc('warning_border')};border-radius:4px;"
        f"padding:6px 10px;color:{_tc('warning_text')};font-size:11px;'>"
        f"Скриншот: <code>docs/screenshots/{name}.png</code></p>"
    )


# ── Content pages ──────────────────────────────────────────────────────────


def _page_overview() -> str:
    return get_css() + f"""
<h1>CashControl — обзор программы</h1>
{_screenshot("overview_main", "Главное окно CashControl")}
<p>CashControl — десктопное приложение для <b>удалённого управления кассовыми аппаратами</b>,
работающими под управлением TinyCore Linux (POS, SCO, SCO3) и Ubuntu.</p>

<p>Программа позволяет:</p>
<ul>
  <li>Просматривать информацию о кассе: ОС, оборудование, периферия</li>
  <li>Подключаться по VNC — удалённый просмотр экрана кассы</li>
  <li>Запускать SSH-терминал (KiTTY) и WinSCP с автоматическим вводом пароля</li>
  <li>Редактировать базу данных PostgreSQL через встроенный DB Viewer</li>
  <li>Выполнять пользовательские скрипты и команды</li>
  <li>Переустанавливать кассовое ПО</li>
</ul>

<div class="note">Программа не требует установки на кассу — весь функционал
реализован через SSH-соединение и не изменяет конфигурацию кассы без явной
команды пользователя.</div>
"""


def _page_tabs() -> str:
    return get_css() + f"""
<h1>Вкладки касс</h1>
{_screenshot("tabs_overview", "Панель вкладок с тремя подключенными кассами")}

<p>Каждая касса открывается в отдельной вкладке. Панель вкладок находится
в верхней части окна, под боковой панелью.</p>

<h2>Управление вкладками</h2>
<table>
  <tr><th>Действие</th><th>Как</th></tr>
  <tr><td><b>Добавить кассу</b></td><td>Кнопка <b>+</b> или <b>Ctrl+T</b></td></tr>
  <tr><td><b>Закрыть вкладку</b></td><td>Контекстное меню вкладки или <b>Ctrl+W</b></td></tr>
  <tr><td><b>Переименовать IP</b></td><td>Двойной щелчок по заголовку вкладки</td></tr>
  <tr><td><b>Переключиться</b></td><td>Клик по вкладке</td></tr>
  <tr><td><b>Обновить данные</b></td><td>Клик по вкладке <b>с колёсиком</b> мыши</td></tr>
</table>

<h2>Индикаторы</h2>
<ul>
  <li><b>Точка слева</b> — статус ping:
    <span style='color:#2E7D32;'>&#9679; жив</span>,
    <span style='color:#B71C1C;'>&#9679; недоступен</span>,
    <span style='color:#FFB300;'>&#9679; проверка</span></li>
  <li><b>Иконка</b> — тип кассы (POS/SCO/SCO3/Touch)</li>
</ul>

<h2>Диалог добавления кассы</h2>
{_screenshot("add_cash_dialog", "Диалог добавления новой кассы")}
<p>Введите IP-адрес кассы и нажмите «Добавить». SSH-подключение устанавливается
автоматически. Если касса недоступна — отобразится кнопка «Повторить».</p>
"""


def _page_toolbar() -> str:
    return get_css() + f"""
<h1>Панель инструментов</h1>
{_screenshot("toolbar", "Панель инструментов кассы")}

<p>Отображается над содержимым вкладки при наличии хотя бы одной кассы.
Кнопки меняют состояние в зависимости от типа кассы (POS/SCO/SCO3).</p>

<h2>Кнопки управления</h2>
<table>
  <tr><th>Кнопка</th><th>Действие</th><th>Примечание</th></tr>
  <tr><td><b>Рестарт</b></td><td>Перезапуск кассового ПО</td><td>Без перезагрузки ОС</td></tr>
  <tr><td><b>Ребут</b></td><td>Полная перезагрузка кассы</td><td>Требует подтверждения</td></tr>
  <tr><td><b>VNC</b></td><td>Внешний VNC-клиент</td><td>Встроенный: Ctrl+V</td></tr>
  <tr><td><b>SSH</b></td><td>KiTTY с автологином</td><td>Ctrl+S</td></tr>
  <tr><td><b>WinSCP</b></td><td>Файловый менеджер</td><td>Ctrl+W</td></tr>
  <tr><td><b>БД</b></td><td>PostgreSQL (внешний или встроенный)</td><td>Ctrl+D</td></tr>
  <tr><td><b>Клавиатура</b></td><td>Виртуальная клавиатура</td><td>Только для POS</td></tr>
  <tr><td><b>Обновить</b></td><td>Обновить данные кассы</td><td>Переподключение</td></tr>
  <tr><td><b>Команды</b></td><td>Пользовательские команды</td><td>Меню</td></tr>
</table>

<h2>Горячие клавиши</h2>
<table>
  <tr><th>Комбинация</th><th>Действие</th></tr>
  <tr><td><b>Ctrl+T</b></td><td>Новая вкладка (добавить кассу)</td></tr>
  <tr><td><b>Ctrl+V</b></td><td>Встроенный VNC</td></tr>
  <tr><td><b>Ctrl+Shift+V</b></td><td>Внешний VNC (полноэкранный)</td></tr>
  <tr><td><b>Ctrl+S</b></td><td>SSH (KiTTY)</td></tr>
  <tr><td><b>Ctrl+W</b></td><td>WinSCP</td></tr>
  <tr><td><b>Ctrl+D</b></td><td>Редактор БД</td></tr>
  <tr><td><b>Ctrl+R</b></td><td>Перезапуск ПО</td></tr>
  <tr><td><b>Ctrl+Shift+R</b></td><td>Перезагрузка кассы</td></tr>
</table>

<h2>Контекстное меню команд (правая кнопка на кнопке «Команды»)</h2>
{_screenshot("commands_menu", "Меню команд")}
<p>Открывает меню со списком пользовательских команд. Команды можно создавать
через <b>Редактор команд</b> (кнопка «Редактор команд» в боковой панели).</p>
"""


def _page_settings_connection() -> str:
    return get_css() + f"""
<h1>Настройки → Подключение</h1>
{_screenshot("settings_connection", "Диалог настроек подключения")}

<p>Открывается кнопкой <b>«Настройки»</b> в боковой панели.</p>

<h2>SSH Подключение</h2>
<table>
  <tr><th>Поле</th><th>Описание</th><th>По умолчанию</th></tr>
  <tr><td><b>Логин</b></td><td>Имя пользователя для SSH</td><td>tc</td></tr>
  <tr><td><b>Порт</b></td><td>TCP-порт SSH</td><td>22</td></tr>
  <tr><td><b>Пароли</b></td><td>Список паролей, по одному на строку</td><td>—</td></tr>
</table>
<div class="note">Программа перебирает пароли по порядку и кэширует успешный для каждого IP.
При следующем подключении к той же кассе сначала пробуется кэшированный пароль.</div>

<p>Кнопки управления паролями:</p>
<ul>
  <li><b>Показать</b> — расшифровать и показать сохранённые пароли для редактирования</li>
  <li><b>Очистить</b> — удалить все сохранённые пароли (с подтверждением)</li>
</ul>

<h2>PostgreSQL База данных</h2>
<table>
  <tr><th>Поле</th><th>Описание</th><th>По умолчанию</th></tr>
  <tr><td><b>Логин</b></td><td>Пользователь PostgreSQL</td><td>postgres</td></tr>
  <tr><td><b>Порт</b></td><td>TCP-порт PostgreSQL</td><td>5432</td></tr>
  <tr><td><b>Пароли</b></td><td>Пароли БД (если не заданы — используются SSH пароли)</td><td>—</td></tr>
</table>

<h2>VNC</h2>
<table>
  <tr><th>Поле</th><th>Описание</th><th>По умолчанию</th></tr>
  <tr><td><b>Порт VNC</b></td><td>Базовый порт VNC-сервера на кассе</td><td>5900</td></tr>
</table>

<div class="tip">Пароли хранятся в зашифрованном виде в файле настроек.
Ключ шифрования генерируется при первом запуске и хранится в системном хранилище Windows.</div>
"""


def _page_settings_programs() -> str:
    return get_css() + f"""
<h1>Настройки → Программы</h1>
{_screenshot("settings_programs", "Диалог настроек программ")}

<p>Пути к внешним утилитам. Открывается кнопкой <b>«Настройки»</b> в боковой панели.</p>

<h2>SSH Клиент (KiTTY)</h2>
<p>Путь к <code>kitty.exe</code>. Если не задан — используется <code>soft/kitty.exe</code>
рядом с программой. KiTTY подключается автоматически: программа передаёт хост, порт,
логин и пароль через аргументы командной строки.</p>
{_screenshot("kitty_window", "KiTTY с автоматическим подключением")}

<h2>VNC Клиент</h2>
<p>Путь к VNC-клиенту (<code>vncviewer.exe</code> от TightVNC, UltraVNC или RealVNC)
и шаблон аргументов.</p>
<p>Переменные для аргументов:</p>
<table>
  <tr><th>Переменная</th><th>Значение</th></tr>
  <tr><td><code>{{host}}</code></td><td>IP кассы</td></tr>
  <tr><td><code>{{display}}</code></td><td>Номер дисплея (обычно 0)</td></tr>
  <tr><td><code>{{port}}</code></td><td>SSH порт</td></tr>
</table>
<p>Примеры аргументов:</p>
<ul>
  <li>TightVNC: <code>{{host}}:{{display}}</code></li>
  <li>UltraVNC: <code>{{host}}::5900</code></li>
</ul>

<h2>WinSCP</h2>
<p>Путь к <code>WinSCP.exe</code>. Протокол и аргументы подставляются автоматически:
SCP для TinyCore, SFTP для Ubuntu. Пароль берётся из настроек подключения.</p>

<h2>PostgreSQL Клиент</h2>
<p>Внешний DB-клиент (psql, DBeaver, pgAdmin). Если <b>не задан</b> — открывается
встроенный <b>DB Viewer</b>. Если задан — запускается указанный exe с аргументами.</p>
<p>Переменные для аргументов:</p>
<table>
  <tr><th>Переменная</th><th>Значение</th></tr>
  <tr><td><code>{{host}}</code></td><td>IP кассы</td></tr>
  <tr><td><code>{{db_port}}</code></td><td>Порт PostgreSQL</td></tr>
  <tr><td><code>{{db_login}}</code></td><td>Логин PostgreSQL</td></tr>
</table>
<div class="tip">Чтобы всегда использовать встроенный DB Viewer — оставьте поле «Путь» пустым.</div>
"""


def _page_settings_general() -> str:
    return get_css() + f"""
<h1>Настройки → Общие</h1>
{_screenshot("settings_general", "Диалог общих настроек")}

<h2>Тема оформления</h2>
<p>Светлая, тёмная или системная (следует настройкам Windows).
Изменение применяется сразу после сохранения.</p>

<h2>Автоматические обновления</h2>
<table>
  <tr><th>Параметр</th><th>Описание</th></tr>
  <tr><td><b>Включить</b></td><td>Проверять наличие новой версии</td></tr>
  <tr><td><b>Путь к обновлениям</b></td><td>Сетевой путь UNC, например <code>\\\\server\\share\\CashControl</code></td></tr>
  <tr><td><b>Проверять при запуске</b></td><td>Автопроверка при старте программы</td></tr>
  <tr><td><b>Интервал проверки</b></td><td>Часов между автоматическими проверками</td></tr>
</table>
<div class="note">Кнопка <b>Проверить сейчас</b> запускает немедленную проверку,
не дожидаясь расписания.</div>

<h2>Параметры подключения</h2>
<table>
  <tr><th>Параметр</th><th>Описание</th><th>По умолчанию</th></tr>
  <tr><td><b>Таймаут</b></td><td>Секунд до отказа от попытки подключения</td><td>10</td></tr>
</table>
"""


def _page_db_viewer() -> str:
    return get_css() + f"""
<h1>Встроенный редактор БД</h1>
{_screenshot("db_viewer_main", "Главное окно DB Viewer")}

<p>Открывается кнопкой <b>БД</b> на панели инструментов, если в настройках программ
не задан внешний PostgreSQL-клиент.</p>

<h2>Дерево баз данных (левая панель)</h2>
<p>Отображает все доступные базы данных на кассе. Разворачивайте узлы чтобы
увидеть схемы и таблицы. Двойной щелчок по таблице — открыть в новой вкладке.</p>
<ul>
  <li><b>ПКМ → Обновить</b> — перечитать структуру базы</li>
  <li><b>ПКМ → Использовать</b> — выбрать БД для SQL-консоли</li>
</ul>

<h2>Просмотр таблицы</h2>
{_screenshot("db_table_view", "Таблица с данными")}
<table>
  <tr><th>Элемент</th><th>Описание</th></tr>
  <tr><td><b>Поиск</b></td><td>Поиск по выбранной колонке. Локально — фильтрует строки без запроса к БД; На сервере — новый SELECT с WHERE ILIKE</td></tr>
  <tr><td><b>Лимит</b></td><td>Количество загружаемых строк. «Все» — без ограничений</td></tr>
  <tr><td><b>Назад / Далее</b></td><td>Постраничная навигация (при ограниченном лимите)</td></tr>
  <tr><td><b>Редактирование ячейки</b></td><td>Двойной щелчок по ячейке — начать редактирование. Изменённые ячейки подсвечиваются жёлтым</td></tr>
  <tr><td><b>Сохранить изменения</b></td><td>Применить все правки как UPDATE-запросы</td></tr>
  <tr><td><b>Отмена правок</b></td><td>Откатить несохранённые изменения</td></tr>
  <tr><td><b>Удалить строки</b></td><td>Удалить выделенные строки (DELETE с подтверждением)</td></tr>
</table>
<div class="warn">Удаление нельзя отменить. Всегда требуется подтверждение.</div>

<p>Контекстное меню таблицы (ПКМ):</p>
<ul>
  <li><b>Экспорт CSV / JSON</b> — сохранить данные в файл</li>
  <li><b>Импорт CSV</b> — загрузить данные из CSV с настройкой соответствия колонок</li>
</ul>

<h2>SQL Консоль</h2>
{_screenshot("db_sql_console", "SQL консоль")}
<ul>
  <li>Вкладка <b>SQL</b> всегда первая и не закрывается</li>
  <li><b>F5</b> или <b>Ctrl+Enter</b> — выполнить запрос</li>
  <li><b>Ctrl+Пробел</b> — автодополнение имён таблиц и колонок</li>
  <li>История запросов — выпадающий список вверху</li>
</ul>
<div class="warn">DELETE и UPDATE без WHERE требуют дополнительного подтверждения.
DROP DATABASE/TABLE — двойного подтверждения со вводом слова «УДАЛИТЬ».</div>
"""


def _page_command_editor() -> str:
    return get_css() + f"""
<h1>Редактор команд</h1>
{_screenshot("command_editor", "Редактор команд")}

<p>Открывается кнопкой <b>«Редактор команд»</b> в боковой панели. Позволяет создавать
SSH-команды и Python-скрипты для выполнения на кассе.</p>

<h2>Типы команд</h2>
<table>
  <tr><th>Тип</th><th>Описание</th><th>Файл</th></tr>
  <tr><td><b>SSH-команды</b></td><td>Список shell-команд, выполняются последовательно по SSH</td><td>.json</td></tr>
  <tr><td><b>Python-скрипт</b></td><td>Полноценный async Python-скрипт с доступом к сессии</td><td>.py</td></tr>
</table>

<h2>SSH-команды</h2>
<p>Каждая строка — отдельная shell-команда. Выполняются по порядку,
при первой ошибке — остановка. Файл сохраняется в <code>commands/*.json</code>.</p>

<h2>Python-скрипты</h2>
<p>Позволяют реализовать сложную логику: условия, циклы, обработку результатов.
Файл сохраняется в <code>commands/*.py</code>.</p>
<p>Обязательная сигнатура:</p>
<pre><code>async def execute(session, **kwargs):
    result = await session.ssh.execute("uptime")
    return result.stdout.strip()</code></pre>
<p>Доступно внутри скрипта:</p>
<table>
  <tr><th>Объект</th><th>Описание</th></tr>
  <tr><td><code>session.ssh</code></td><td>SSH-соединение</td></tr>
  <tr><td><code>session.ssh.execute("cmd")</code></td><td>Выполнить команду, вернёт объект с .stdout, .stderr</td></tr>
  <tr><td><code>session.ip</code></td><td>IP-адрес кассы</td></tr>
</table>
<div class="warn">Скрипт выполняется только если содержит строку
<code>async def execute(session</code> — произвольный код вне функции игнорируется.</div>

<h2>Создание команды</h2>
<ul>
  <li>Нажмите <b>+</b> чтобы создать новую команду</li>
  <li>Выберите тип: SSH-команды или Python-скрипт</li>
  <li>Задайте имя, описание и тело команды</li>
</ul>

<h2>Параметры команды</h2>
<table>
  <tr><th>Параметр</th><th>Описание</th></tr>
  <tr><td><b>Описание</b></td><td>Отображается в меню команд</td></tr>
  <tr><td><b>Требует подтверждения</b></td><td>Показывать ли диалог подтверждения перед выполнением</td></tr>
  <tr><td><b>Показывать результат</b></td><td>Показывать ли окно с результатом после выполнения</td></tr>
  <tr><td><b>Запрос ввода</b></td><td>Показывать ли поле для ввода пользователем перед выполнением (например, номер заказа)</td></tr>
</table>
"""


def _page_logs() -> str:
    return get_css() + f"""
<h1>Журнал действий</h1>
{_screenshot("logs_viewer", "Просмотр журнала")}

<p>Открывается кнопкой <b>«Журнал действий»</b> в боковой панели. Окно не модальное —
можно держать открытым параллельно с работой.</p>

<h2>Что записывается</h2>
<ul>
  <li>Подключения к кассам (SSH, БД)</li>
  <li>Запуск внешних инструментов (VNC, SSH, WinSCP, БД)</li>
  <li>Выполнение команд и их результат</li>
  <li>Изменения в настройках</li>
  <li>Операции с базой данных (UPDATE, DELETE, SQL-запросы)</li>
  <li>Запуск и завершение программы</li>
</ul>

<h2>Фильтрация</h2>
<p>Можно фильтровать по типу события, IP кассы и временному диапазону.</p>

<h2>Расположение файла</h2>
<p>Журнал сохраняется в файл в папке данных программы.
Путь отображается в строке заголовка просмотрщика.</p>
"""


def _page_notifications() -> str:
    return get_css() + """
<h1>Уведомления</h1>

<p>Программа показывает всплывающие уведомления в правом нижнем углу окна.</p>

<table>
  <tr><th>Цвет</th><th>Тип</th><th>Значение</th></tr>
  <tr><td style='background:#1565C0;color:white;padding:4px 8px;'>Синий</td><td><b>Информация</b></td><td>Нейтральное событие (запущена программа)</td></tr>
  <tr><td style='background:#2E7D32;color:white;padding:4px 8px;'>Зелёный</td><td><b>Успех</b></td><td>Операция выполнена успешно</td></tr>
  <tr><td style='background:#BF360C;color:white;padding:4px 8px;'>Оранжевый</td><td><b>Предупреждение</b></td><td>Операция выполнена частично или требует внимания</td></tr>
  <tr><td style='background:#B71C1C;color:white;padding:4px 8px;'>Красный</td><td><b>Ошибка</b></td><td>Операция не выполнена, требуется действие</td></tr>
</table>

<p>Уведомления исчезают автоматически через 4–7 секунд.
Нажмите <b>×</b> чтобы закрыть досрочно.</p>

<div class="tip">Все события из уведомлений также записываются в <b>Журнал действий</b>
с полным текстом ошибки.</div>
"""


def _page_first_start() -> str:
    return get_css() + f"""
<h1>Первый запуск</h1>

<h2>Порядок настройки</h2>
<p>При первом запуске выполните следующие шаги:</p>

<h3>1. Настройки подключения</h3>
<p>Откройте боковую панель → <b>Подключение</b> и заполните:</p>
<ul>
  <li>SSH: логин (<code>tc</code> для TinyCore) и пароли касс</li>
  <li>PostgreSQL: логин (<code>postgres</code>) и пароли БД</li>
</ul>
{_screenshot("first_start_connection", "Заполнение настроек подключения")}

<h3>2. Настройки программ</h3>
<p>Откройте <b>Программы</b> и укажите пути к:</p>
<ul>
  <li><code>kitty.exe</code> — SSH-клиент</li>
  <li><code>vncviewer.exe</code> — VNC-клиент</li>
  <li><code>WinSCP.exe</code> — файловый менеджер</li>
</ul>
<div class="tip">Если положить <code>kitty.exe</code> в папку <code>soft/</code>
рядом с программой — путь задавать не нужно.</div>

<h3>3. Добавить кассу</h3>
<p>Нажмите <b>+</b> на панели вкладок и введите IP-адрес кассы.
Программа автоматически подключится и покажет информацию.</p>
{_screenshot("first_start_add_cash", "Добавление первой кассы")}

<h2>Структура папок программы</h2>
<table>
  <tr><th>Папка/файл</th><th>Содержимое</th></tr>
  <tr><td><code>soft/</code></td><td>kitty.exe, vncviewer.exe и другие утилиты</td></tr>
  <tr><td><code>commands/</code></td><td>JSON-файлы пользовательских команд</td></tr>
  <tr><td><code>data/</code></td><td>Настройки, сессии, журнал</td></tr>
  <tr><td><code>docs/screenshots/</code></td><td>Скриншоты для справочника</td></tr>
</table>
"""


def _page_about() -> str:
    try:
        from cashcontrol import __app_name__, __version__
    except ImportError:
        __app_name__ = "CashControl"
        __version__ = "—"
    return get_css() + f"""
<h1>О программе</h1>

<h2>{__app_name__} v{__version__}</h2>
<p>Инструмент удалённого управления кассовыми аппаратами для ИТ-специалистов
и системных администраторов ритейла.</p>

<h2>Поддерживаемые типы касс</h2>
<ul>
  <li>TinyCore Linux (POS, SCO, SCO3)</li>
  <li>Ubuntu (в разработке)</li>
</ul>

<h2>Технологии</h2>
<table>
  <tr><th>Компонент</th><th>Библиотека</th></tr>
  <tr><td>GUI</td><td>PySide6 + PyQt-Fluent-Widgets</td></tr>
  <tr><td>SSH</td><td>asyncssh</td></tr>
  <tr><td>PostgreSQL</td><td>asyncpg + psycopg2</td></tr>
  <tr><td>Шифрование</td><td>cryptography (Fernet)</td></tr>
  <tr><td>Настройки</td><td>pydantic</td></tr>
</table>

<h2>Добавление скриншотов в справочник</h2>
<p>Скриншоты для каждого раздела хранятся в папке <code>docs/screenshots/</code>.
Чтобы добавить скриншот:</p>
<ol>
  <li>Сделайте снимок нужного экрана</li>
  <li>Сохраните как <code>.png</code> с именем согласно таблице ниже</li>
  <li>Положите в <code>docs/screenshots/</code> рядом с программой</li>
  <li>Справочник автоматически покажет картинку при следующем открытии</li>
</ol>

<h2>Имена файлов скриншотов</h2>
<table>
  <tr><th>Файл</th><th>Где показывается</th></tr>
  <tr><td><code>overview_main.png</code></td><td>Обзор → главное окно</td></tr>
  <tr><td><code>tabs_overview.png</code></td><td>Вкладки → панель вкладок</td></tr>
  <tr><td><code>add_cash_dialog.png</code></td><td>Вкладки → диалог добавления</td></tr>
  <tr><td><code>toolbar.png</code></td><td>Панель инструментов</td></tr>
  <tr><td><code>commands_menu.png</code></td><td>Панель инструментов → команды</td></tr>
  <tr><td><code>settings_connection.png</code></td><td>Настройки → Подключение</td></tr>
  <tr><td><code>settings_programs.png</code></td><td>Настройки → Программы</td></tr>
  <tr><td><code>settings_general.png</code></td><td>Настройки → Общие</td></tr>
  <tr><td><code>db_viewer_main.png</code></td><td>DB Viewer → главное окно</td></tr>
  <tr><td><code>db_table_view.png</code></td><td>DB Viewer → просмотр таблицы</td></tr>
  <tr><td><code>db_sql_console.png</code></td><td>DB Viewer → SQL консоль</td></tr>
  <tr><td><code>command_editor.png</code></td><td>Редактор команд</td></tr>
  <tr><td><code>logs_viewer.png</code></td><td>Журнал действий</td></tr>
  <tr><td><code>first_start_connection.png</code></td><td>Первый запуск → подключение</td></tr>
  <tr><td><code>first_start_add_cash.png</code></td><td>Первый запуск → добавление кассы</td></tr>
</table>
"""


def _page_changelog() -> str:
    patch_file = get_app_root() / "docs" / "patch.md"
    if not patch_file.exists():
        return get_css() + "<h1>Обновления</h1><p>Файл patch.md не найден.</p>"

    try:
        text = patch_file.read_text(encoding="utf-8")
    except Exception as e:
        return get_css() + f"<h1>Обновления</h1><p>Ошибка чтения patch.md: {e}</p>"

    import re
    lines = text.splitlines()
    html_lines = []
    in_ul = False
    in_code = False

    for line in lines:
        if line.strip().startswith("```"):
            if in_code:
                html_lines.append("</code></pre>")
                in_code = False
            else:
                if in_ul:
                    html_lines.append("</ul>")
                    in_ul = False
                html_lines.append("<pre><code>")
                in_code = True
            continue
        if in_code:
            html_lines.append(line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
            continue

        if line.startswith("## "):
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            html_lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("# "):
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            html_lines.append(f"<h1>{line[2:]}</h1>")
        elif line.startswith("### "):
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            html_lines.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("---"):
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            html_lines.append("<hr/>")
        elif line.startswith("- "):
            if not in_ul:
                html_lines.append("<ul>")
                in_ul = True
            item = line[2:]
            item = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", item)
            item = re.sub(r"`(.+?)`", r"<code>\1</code>", item)
            html_lines.append(f"  <li>{item}</li>")
        elif line.strip() == "":
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            html_lines.append("")
        else:
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            formatted = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", line)
            formatted = re.sub(r"`(.+?)`", r"<code>\1</code>", formatted)
            html_lines.append(f"<p>{formatted}</p>")

    if in_ul:
        html_lines.append("</ul>")

    body = "\n".join(html_lines)
    return get_css() + body


# ── Tree structure ─────────────────────────────────────────────────────────


_TREE = [
    ("Первый запуск",      _page_first_start),
    ("Обзор программы",    _page_overview),
    ("Вкладки касс",       _page_tabs),
    ("Панель инструментов", _page_toolbar),
    ("Настройки", None, [
        ("Подключение",    _page_settings_connection),
        ("Программы",      _page_settings_programs),
        ("Общие",          _page_settings_general),
    ]),
    ("Редактор БД",        _page_db_viewer),
    ("Редактор команд",    _page_command_editor),
    ("Журнал действий",    _page_logs),
    ("Уведомления",        _page_notifications),
    ("О программе",        _page_about),
    ("Обновления",          _page_changelog),
]
