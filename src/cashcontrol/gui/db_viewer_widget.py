# -*- coding: utf-8 -*-
"""CashControl — PostgreSQL клиент. Вариант C «Компакт» (один файл).

Контракт:  from cashcontrol.gui.db_viewer_widget import PostgresToolWindow
           win = PostgresToolWindow(host, port, user, passwords, database, parent); win.show()

Однооконный минимализм: слева — комбо баз, поиск и список таблиц; в центре —
грид с серверными фильтром/сортировкой/пагинацией и редактированием по PK;
консоль — выдвижная панель (кнопка или Ctrl+L). Минимум кликов для типовой
задачи «посмотреть/поправить данные»: импорт CSV с маппингом и превью, экспорт
CSV/JSON, история+закладки запросов (data/*.json), оценка числа строк
(reltuples). Все запросы БД — в QThread-воркерах, отменяемых при закрытии.
Зависимости: PySide6 + psycopg2-binary + qfluentwidgets.
"""
from __future__ import annotations
import csv, json, re, sys, tempfile, time
from datetime import date, datetime, time as dtime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import psycopg2
from psycopg2 import sql as pgsql
from psycopg2 import extras as pgextras
from PySide6.QtCore import Qt, QThread, QTimer, QPropertyAnimation, Signal, QPoint, QSize
from PySide6.QtGui import (QBrush, QColor, QFont, QFontDatabase, QGuiApplication,
                           QKeySequence, QShortcut, QSyntaxHighlighter,
                           QTextCharFormat, QTextCursor)
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QDialog, QFileDialog,
                               QFormLayout, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QListWidget, QListWidgetItem, QMainWindow, QMenu,
                               QMessageBox, QPlainTextEdit, QProgressBar,
                               QSplitter, QStackedWidget, QStatusBar, QStyle,
                               QTableWidget, QTabWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)
from qfluentwidgets import (ComboBox, FluentIcon, InfoBar, InfoBarPosition,
                            LineEdit, PushButton, SearchLineEdit, ToolButton)

try:
    from cashcontrol.gui.theme_helper import color as _tc
except Exception:
    def _tc(name):
        raise KeyError(name)

_PAGE_SIZES = (50, 100, 200, 500)
_HISTORY_LIMIT = 100
_MAX_CONSOLE_ROWS = 500


def _c(name, fallback='#616161'):
    try:
        return _tc(name)
    except Exception:
        return fallback


def _qi(n):
    return '"' + str(n).replace('"', '""') + '"'


def _qtable(s, t):
    return f'{_qi(s)}.{_qi(t)}'


def _mono():
    f = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    f.setPointSize(QFontDatabase.systemFont(QFontDatabase.GeneralFont).pointSize())
    return f


def _fmt(v):
    if v is None:
        return 'NULL'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, datetime):
        try:
            return v.astimezone().strftime('%Y-%m-%d %H:%M:%S')
        except Exception:
            return v.strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(v, dtime):
        return v.strftime('%H:%M:%S')
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray, memoryview)):
        return '\\x' + bytes(v).hex()
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _kind(t):
    t = t.lower()
    if t.endswith('[]'):
        return 'other'
    if t.startswith(('smallint', 'integer', 'bigint', 'int2', 'int4', 'int8',
                     'oid', 'serial', 'bigserial', 'smallserial')):
        return 'int'
    if t.startswith(('numeric', 'decimal', 'money')):
        return 'num'
    if t.startswith(('real', 'double precision', 'float4', 'float8')):
        return 'float'
    if t.startswith('bool'):
        return 'bool'
    if t.startswith(('date', 'time', 'timestamp')):
        return 'time'
    if t.startswith('json'):
        return 'json'
    return 'text'


_EDITABLE = ('int', 'num', 'float', 'bool', 'time', 'json', 'text')


def _parse_value(text, coltype):
    s = text.strip()
    if not s or s.upper() == 'NULL':
        return None
    k = _kind(coltype)
    try:
        if k == 'int':
            return int(s)
        if k == 'num':
            return Decimal(s)
        if k == 'float':
            return float(s)
        if k == 'bool':
            low = s.lower()
            if low in ('true', 't', '1', 'yes', 'да'):
                return True
            if low in ('false', 'f', '0', 'no', 'нет'):
                return False
            raise ValueError(f'ожидалось true/false, а не «{text}»')
        if k == 'time':
            return datetime.fromisoformat(s.replace('Z', '+00:00'))
        if k == 'json':
            return json.loads(s)
    except (ValueError, InvalidOperation) as e:
        raise ValueError(f'«{text}» не разобрать как {coltype}: {e}')
    return text


def _human(e):
    diag = getattr(e, 'diag', None)
    msg = (diag.message_primary or diag.message_detail) if diag else ''
    s = (msg or str(e)).strip()
    s = re.sub(r'\s+', ' ', s)
    return s[:300] + '…' if len(s) > 300 else (s or e.__class__.__name__)


class _DbError(Exception):
    pass


def _data_dir():
    base = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) \
        else Path(__file__).resolve().parents[3]
    try:
        d = base / 'data'
        d.mkdir(parents=True, exist_ok=True)
        return d
    except OSError:
        return Path(tempfile.gettempdir()) / 'cashcontrol'


def _load_json(name, default):
    try:
        with open(_data_dir() / name, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return default


def _save_json(name, obj):
    try:
        with open(_data_dir() / name, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
    except Exception:
        pass


def _icon(name):
    try:
        ic = getattr(FluentIcon, name, None)
        if ic is not None:
            return ic.icon()
    except Exception:
        pass
    return QApplication.style().standardIcon(QStyle.SP_FileIcon)


def _toast(widget, kind, text):
    fn = getattr(InfoBar, kind, None)
    if fn:
        fn(title='', content=text, parent=widget.window(),
           position=InfoBarPosition.TOP_RIGHT, duration=4000)


class _Busy:
    def __init__(self, progress):
        self._n, self._p = 0, progress

    def start(self):
        self._n += 1
        self._p.show()

    def stop(self):
        self._n = max(0, self._n - 1)
        if self._n == 0:
            self._p.hide()


class _ConnFactory:  # Соединение psycopg2; пароли перебираются до первого успеха.

    def __init__(self, host, port, user, passwords, database):
        self.host, self.port, self.user = host, int(port), user
        self.passwords = list(passwords or [])
        self.database = database or 'postgres'

    def connect(self, database=None):
        db = database or self.database
        last = None
        for pw in self.passwords:
            try:
                return psycopg2.connect(host=self.host, port=self.port,
                                        user=self.user, password=pw, dbname=db,
                                        connect_timeout=5,
                                        application_name='CashControl',
                                        client_encoding='UTF8')
            except psycopg2.Error as e:
                last = e
        raise _DbError(f'Нет соединения с {self.user}@{self.host}:{self.port}/{db}: '
                       + (_human(last) if last else 'нет паролей'))


class _Worker(QThread):  # Выполняет fn(conn, worker) в отдельном потоке; отменяем при закрытии.
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, factory, fn, database=None, parent=None):
        super().__init__(parent)
        self._factory, self._fn, self._database = factory, fn, database

    def run(self):
        conn = None
        try:
            conn = self._factory.connect(self._database)
            res = self._fn(conn, self)
            if not self.isInterruptionRequested():
                self.done.emit(res)
        except Exception as e:
            if not self.isInterruptionRequested():
                self.failed.emit(_human(e))
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def cancel(self, wait_ms=1500):
        self.requestInterruption()
        self.wait(wait_ms)
        if self.isRunning():
            self.terminate()
            self.wait(500)


# # Каталог-запросы (портированы из pgweb/pkg/statements/sql/*.sql)

_SQL_DATABASES = "SELECT datname FROM pg_database WHERE NOT datistemplate ORDER BY 1"
_SQL_TABLES = """SELECT c.relname AS name, c.relkind AS kind, c.reltuples::bigint AS est
    FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
    WHERE n.nspname=%s AND c.relkind IN ('r','p','v','m') ORDER BY c.relname"""
_SQL_COLUMNS = """SELECT a.attname AS name, format_type(a.atttypid,a.atttypmod) AS type,
    NOT a.attnotnull AS nullable, COALESCE(pg_get_expr(ad.adbin,ad.adrelid),'') AS default_value,
    COALESCE(col_description(a.attrelid,a.attnum),'') AS comment
    FROM pg_attribute a LEFT JOIN pg_attrdef ad ON a.attrelid=ad.adrelid AND a.attnum=ad.adnum
    WHERE a.attrelid=%s::regclass AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum"""
_SQL_PK = """SELECT a.attname FROM pg_index i
    JOIN pg_attribute a ON a.attrelid=i.indrelid AND a.attnum=ANY(i.indkey)
    WHERE i.indrelid=%s::regclass AND i.indisprimary
    ORDER BY array_position(i.indkey,a.attnum)"""
_SQL_ESTIMATED = """SELECT reltuples::bigint FROM pg_class c
    JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname=%s AND c.relname=%s"""
_SQL_COMPLETION = """SELECT n.nspname,c.relname,a.attname FROM pg_class c
    JOIN pg_namespace n ON n.oid=c.relnamespace
    JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
    WHERE n.nspname NOT IN ('pg_catalog','information_schema')
      AND c.relkind IN ('r','p','v','m') ORDER BY 1,2,a.attnum"""


def _load_meta(conn, worker, schema, table):
    if worker is not None and worker.isInterruptionRequested():
        raise _DbError('отменено')
    qname = _qtable(schema, table)
    cur = conn.cursor()
    cur.execute(_SQL_COLUMNS, (qname,))
    columns = [dict(zip(('name', 'type', 'nullable', 'default', 'comment'), r))
               for r in cur.fetchall()]
    cur.execute(_SQL_PK, (qname,))
    pk = [r[0] for r in cur.fetchall()]
    cur.execute(_SQL_ESTIMATED, (schema, table))
    estimated = cur.fetchone()[0] or 0
    return {'columns': columns, 'pk': pk, 'estimated': max(0, int(estimated))}


# # Серверный фильтр (pgweb-style): whitelisted операторы, pgsql.Literal

_IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_$]*')


def _split(text):
    parts, cur, in_q = [], '', False
    for ch in text:
        if ch == "'":
            in_q = not in_q
            cur += ch
        elif ch == ',' and not in_q:
            parts.append(cur)
            cur = ''
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    return parts


def _parse_literal(raw):
    s = raw.strip()
    if not s:
        raise ValueError('пустое значение')
    if s.startswith("'") and s.endswith("'"):
        return s[1:-1].replace("''", "'")
    if s.upper() == 'NULL':
        return None
    if s.upper() == 'TRUE':
        return True
    if s.upper() == 'FALSE':
        return False
    if re.fullmatch(r'-?\d+', s):
        return int(s)
    if re.fullmatch(r'-?\d+\.\d+([eE][+-]?\d+)?', s):
        return float(s)
    return s


def _build_where(filter_text, columns):
    """'id > 10, name LIKE \'A%\'' → AND-цепочка pgsql-условий.

    Операторы: = != > < >= <= LIKE ILIKE IN IS NULL. Колонки — только из
    каталога (квотируются), значения — pgsql.Literal (экранирование).
    """
    names = {c['name'] for c in columns}
    parts = []
    for raw in _split(filter_text):
        s = raw.strip()
        if not s:
            continue
        m = _IDENT_RE.match(s)
        if not m:
            raise ValueError(f'Некорректный фильтр: «{raw}»')
        col = m.group(0)
        if col not in names:
            raise ValueError(f'Колонка «{col}» не найдена в таблице')
        rest = s[m.end():].strip()
        if rest.upper() == 'IS NULL':
            parts.append(pgsql.SQL('{} IS NULL').format(pgsql.Identifier(col)))
            continue
        opm = re.match(r'^(<=|>=|!=|<>|=|>|<|LIKE|ILIKE|IN)(.*)$', rest,
                       re.I | re.S)
        if not opm:
            raise ValueError(f'Неизвестный оператор в «{raw}» (разрешены: '
                             '= != > < >= <= LIKE ILIKE IN IS NULL)')
        op, val = opm.group(1).upper(), opm.group(2).strip()
        ident = pgsql.Identifier(col)
        if op == 'IN':
            if not (val.startswith('(') and val.endswith(')')):
                raise ValueError(f'IN требует список в скобках: «{raw}»')
            items = [_parse_literal(x) for x in _split(val[1:-1])]
            if not items:
                raise ValueError(f'Пустой список IN: «{raw}»')
            parts.append(pgsql.SQL('{} IN ({})').format(
                ident, pgsql.SQL(', ').join(pgsql.Literal(v) for v in items)))
        elif op in ('LIKE', 'ILIKE'):
            parts.append(pgsql.SQL('{} {} {}').format(
                ident, pgsql.SQL(op), pgsql.Literal(_parse_literal(val))))
        else:
            parts.append(pgsql.SQL('{} {} {}').format(
                ident, pgsql.SQL('!=' if op == '<>' else op),
                pgsql.Literal(_parse_literal(val))))
    if not parts:
        raise ValueError('пустой фильтр')
    return pgsql.SQL(' AND ').join(parts)


def _sel_query(schema, table, columns, where, order, limit=None, offset=None):
    cols = pgsql.SQL(', ').join(pgsql.Identifier(c['name']) for c in columns)
    q = pgsql.SQL('SELECT {cols} FROM {t}').format(
        cols=cols, t=pgsql.SQL('{}.{}').format(pgsql.Identifier(schema),
                                               pgsql.Identifier(table)))
    if where is not None:
        q = q + pgsql.SQL(' WHERE ') + where
    if order is not None:
        q = q + pgsql.SQL(' ORDER BY {} {}').format(
            pgsql.Identifier(order[0]), pgsql.SQL(order[1]))
    if limit is not None:
        q = q + pgsql.SQL(' LIMIT %s OFFSET %s')
    return q


def _load_page(conn, worker, schema, table, limit, offset, order, filter_text):
    meta = _load_meta(conn, worker, schema, table)
    where = _build_where(filter_text, meta['columns']) if filter_text.strip() \
        else None
    cur = conn.cursor()
    cur.execute(_sel_query(schema, table, meta['columns'], where, order,
                           limit, offset), (limit, offset))
    rows = []
    while True:
        batch = cur.fetchmany(200)
        if not batch:
            break
        rows.extend(batch)
        if worker is not None and worker.isInterruptionRequested():
            raise _DbError('отменено')
    if where is not None:
        cur.execute(pgsql.SQL('SELECT count(*) FROM {t}').format(
            t=pgsql.SQL('{}.{}').format(pgsql.Identifier(schema),
                                        pgsql.Identifier(table)))
            + pgsql.SQL(' WHERE ') + where)
        count = int(cur.fetchone()[0])
    else:
        count = meta['estimated']
    return {'meta': meta, 'rows': rows, 'count': count}


# # Экспорт / импорт

def _csv_cell(v):
    if v is None:
        return ''
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, (datetime, date, dtime, bytes, bytearray, memoryview)):
        return _fmt(v)
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _json_value(v):
    if isinstance(v, Decimal):
        try:
            return float(v)
        except Exception:
            return str(v)
    if isinstance(v, (bytes, bytearray, memoryview)):
        return '\\x' + bytes(v).hex()
    if isinstance(v, (datetime, date, dtime)):
        return _fmt(v)
    return v


def _export_rows(conn, worker, schema, table, columns, where, order, path, fmt):
    cur = conn.cursor()
    cur.execute(_sel_query(schema, table, columns, where, order))
    n = 0
    if fmt == 'csv':
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f, delimiter=';')
            w.writerow([c['name'] for c in columns])
            while True:
                batch = cur.fetchmany(1000)
                if not batch:
                    break
                for r in batch:
                    w.writerow([_csv_cell(v) for v in r])
                n += len(batch)
                if worker is not None and worker.isInterruptionRequested():
                    raise _DbError('отменено')
    else:
        names = [c['name'] for c in columns]
        with open(path, 'w', encoding='utf-8') as f:
            f.write('[')
            first = True
            while True:
                batch = cur.fetchmany(1000)
                if not batch:
                    break
                for r in batch:
                    f.write(('' if first else ',\n') + json.dumps(
                        {nm: _json_value(v) for nm, v in zip(names, r)},
                        ensure_ascii=False))
                    first = False
                n += len(batch)
                if worker is not None and worker.isInterruptionRequested():
                    raise _DbError('отменено')
            f.write(']')
    return n


# # Грид данных

class _DataGrid(QTableWidget):
    dirtyChanged = Signal(bool)
    openInConsole = Signal(str)

    _FIXED_COL_W = 150      # ширина колонки при >9 колонок
    _STRETCH_MAX_COLS = 9   # до этого количества — равномерный stretch

    def __init__(self, parent=None):
        super().__init__(parent)
        self._columns, self._pk, self._dirty = [], [], {}
        self._loading, self._readonly = False, False
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setEditTriggers(QAbstractItemView.DoubleClicked |
                             QAbstractItemView.EditKeyPressed |
                             QAbstractItemView.SelectedClicked)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(26)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.setWordWrap(False)
        self.setFont(_mono())
        self.itemChanged.connect(self._on_item_changed)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def set_model(self, columns, pk, rows, readonly=False):
        self._loading = True
        try:
            self._columns, self._pk, self._dirty = columns, list(pk), {}
            self._readonly = readonly
            self.setColumnCount(len(columns))
            self.setHorizontalHeaderLabels([c['name'] for c in columns])
            # ≤9 колонок — равномерно делят ширину окна; больше — фиксированная
            # ширина с горизонтальной прокруткой (иначе всё сжимается в кашу)
            hdr = self.horizontalHeader()
            if len(columns) > self._STRETCH_MAX_COLS:
                hdr.setSectionResizeMode(QHeaderView.Interactive)
                for c in range(len(columns)):
                    self.setColumnWidth(c, self._FIXED_COL_W)
            else:
                hdr.setSectionResizeMode(QHeaderView.Stretch)
            self.setRowCount(len(rows))
            for r, row in enumerate(rows):
                for c, col in enumerate(columns):
                    v = row[c]
                    it = QTableWidgetItem(_fmt(v))
                    it.setData(Qt.UserRole, v)
                    editable = (not readonly and c not in self._pk
                                and _kind(col['type']) in _EDITABLE)
                    if not editable:
                        it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                    if v is None:
                        it.setForeground(QBrush(QColor(_c('text_secondary'))))
                        f = it.font()
                        f.setItalic(True)
                        it.setFont(f)
                    self.setItem(r, c, it)
            self.dirtyChanged.emit(False)
        finally:
            self._loading = False

    def clear_model(self):
        self._loading = True
        try:
            self.setRowCount(0)
            self.setColumnCount(0)
            self._columns, self._pk, self._dirty = [], [], {}
            self.dirtyChanged.emit(False)
        finally:
            self._loading = False

    @property
    def dirty(self):
        return bool(self._dirty)

    def _on_item_changed(self, item):
        if self._loading or self._readonly:
            return
        r, c = item.row(), item.column()
        if item.text() == _fmt(item.data(Qt.UserRole)):
            self._dirty.pop((r, c), None)
            self._mark(r, c, False)
        else:
            self._dirty[(r, c)] = item.data(Qt.UserRole)
            self._mark(r, c, True)
        self.dirtyChanged.emit(bool(self._dirty))

    def _mark(self, r, c, dirty):
        it = self.item(r, c)
        if it is None:
            return
        if dirty:
            col = QColor(_c('warning', '#f57c00'))
            col.setAlpha(55)
            it.setBackground(QBrush(col))
        else:
            it.setBackground(QBrush())

    def edits(self):
        out = []
        for (r, c), _old in sorted(self._dirty.items()):
            it = self.item(r, c)
            out.append((r, c, _parse_value(it.text() if it else '',
                                           self._columns[c]['type'])))
        return out

    def set_cell_value(self, r, c, value):
        it = self.item(r, c)
        if it is None:
            return
        it.setData(Qt.UserRole, value)
        it.setText(_fmt(value))
        if value is None:
            it.setForeground(QBrush(QColor(_c('text_secondary'))))
            f = it.font()
            f.setItalic(True)
            it.setFont(f)
        self._dirty[(r, c)] = value
        self._mark(r, c, True)
        self.dirtyChanged.emit(True)

    def _menu(self, pos):
        menu = QMenu(self)
        act_cell = menu.addAction('Копировать ячейку')
        act_row = menu.addAction('Копировать строку')
        act_null = menu.addAction('Установить NULL')
        act_null.setEnabled(self.currentItem() is not None and not self._readonly)
        menu.addSeparator()
        act_sel = menu.addAction('Открыть в консоли как SELECT')
        a = menu.exec(self.viewport().mapToGlobal(pos))
        if a == act_cell and self.currentItem():
            QGuiApplication.clipboard().setText(self.currentItem().text())
        elif a == act_row and self.currentRow() >= 0:
            r = self.currentRow()
            QGuiApplication.clipboard().setText('\t'.join(
                self.item(r, c).text() for c in range(self.columnCount())))
        elif a == act_null:
            for rg in self.selectedRanges():
                for r in range(rg.topRow(), rg.bottomRow() + 1):
                    for c in range(rg.leftColumn(), rg.rightColumn() + 1):
                        if c in self._pk or _kind(self._columns[c]['type']) \
                                not in _EDITABLE:
                            continue
                        it = self.item(r, c)
                        if it is not None and it.data(Qt.UserRole) is not None:
                            self.set_cell_value(r, c, None)
        elif a == act_sel:
            self.openInConsole.emit(
                'SELECT * FROM ' + _qtable(self._schema, self._table) + ' LIMIT 200;')

    def set_source(self, schema, table):
        self._schema, self._table = schema, table


# # Центральная панель данных: грид + фильтр + пагинация

class _DataPanel(QWidget):  # Открытая таблица: фильтр-строка, грид, пагинация, действия.

    def __init__(self, factory, database, schema, table, parent=None):
        super().__init__(parent)
        self._factory, self.database, self.schema, self.table = \
            factory, database, schema, table
        self._meta, self._page, self._order, self._filter_text = \
            None, 1, None, ''
        self._total, self._worker = 0, None

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)
        bar = QHBoxLayout()
        self._filter_edit = SearchLineEdit(self)
        self._filter_edit.setPlaceholderText(
            "Фильтр: id > 10, name LIKE 'Клиент%' (= != > < >= <= LIKE ILIKE IN IS NULL)")
        self._filter_edit.setClearButtonEnabled(True)
        self._filter_edit.returnPressed.connect(self.apply_filter)
        self._btn_filter = PushButton('Применить', self)
        self._btn_filter.clicked.connect(self.apply_filter)
        self._btn_reset = PushButton('Сброс', self)
        self._btn_reset.clicked.connect(self.reset_filter)
        bar.addWidget(self._filter_edit, 1)
        bar.addWidget(self._btn_filter)
        bar.addWidget(self._btn_reset)
        bar.addSpacing(10)
        self._btn_import = ToolButton(_icon('ADD'), self)
        self._btn_import.setToolTip('Импорт CSV')
        self._btn_import.clicked.connect(self.import_csv)
        self._btn_exp_csv = ToolButton(_icon('DOCUMENT'), self)
        self._btn_exp_csv.setToolTip('Экспорт CSV')
        self._btn_exp_csv.clicked.connect(lambda: self.export('csv'))
        self._btn_exp_json = ToolButton(_icon('CODE'), self)
        self._btn_exp_json.setToolTip('Экспорт JSON')
        self._btn_exp_json.clicked.connect(lambda: self.export('json'))
        self._btn_delete = ToolButton(_icon('DELETE'), self)
        self._btn_delete.setToolTip('Удалить выбранные строки')
        self._btn_delete.clicked.connect(self.delete_selected)
        self._btn_cancel = PushButton('Отменить', self)
        self._btn_cancel.setEnabled(False)
        self._btn_cancel.clicked.connect(self.cancel_edits)
        self._btn_save = PushButton('Сохранить', self)
        self._btn_save.setEnabled(False)
        self._btn_save.clicked.connect(self.save_edits)
        for b in (self._btn_import, self._btn_exp_csv, self._btn_exp_json,
                  self._btn_delete, self._btn_cancel, self._btn_save):
            bar.addWidget(b)
        root.addLayout(bar)

        # Локальный поиск по загруженной странице (как в оригинальном редакторе)
        bar2 = QHBoxLayout()
        self._search_edit = SearchLineEdit(self)
        self._search_edit.setPlaceholderText(
            'Поиск по странице (Enter / ввод — фильтрация строк)')
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.textChanged.connect(self._local_search)
        self._search_col = ComboBox(self)
        self._search_col.addItem('Все колонки')
        self._search_col.setMinimumWidth(140)
        self._search_col.currentIndexChanged.connect(
            lambda _: self._local_search(self._search_edit.text()))
        self._btn_unhide = ToolButton(_icon('DELETE'), self)
        self._btn_unhide.setToolTip('Показать все строки (сбросить поиск)')
        self._btn_unhide.clicked.connect(self._reset_local_search)
        bar2.addWidget(QLabel('Поиск:', self))
        bar2.addWidget(self._search_edit, 1)
        bar2.addWidget(self._search_col)
        bar2.addWidget(self._btn_unhide)
        root.addLayout(bar2)

        self._grid = _DataGrid(self)
        self._grid.set_source(schema, table)
        self._grid.dirtyChanged.connect(self._on_dirty)
        root.addWidget(self._grid, 1)

        pag = QHBoxLayout()
        self._btn_prev = ToolButton(_icon('LEFT_ARROW'), self)
        self._btn_prev.setToolTip('Предыдущая страница')
        self._btn_prev.clicked.connect(lambda: self._go_page(self._page - 1))
        self._lbl_page = QLabel('—', self)
        self._btn_next = ToolButton(_icon('RIGHT_ARROW'), self)
        self._btn_next.setToolTip('Следующая страница')
        self._btn_next.clicked.connect(lambda: self._go_page(self._page + 1))
        self._combo_size = ComboBox(self)
        self._combo_size.addItems([str(n) for n in _PAGE_SIZES])
        self._combo_size.setCurrentIndex(1)
        self._combo_size.currentIndexChanged.connect(self._on_size_changed)
        self._lbl_total = QLabel('', self)
        self._lbl_progress = QProgressBar(self)
        self._lbl_progress.setRange(0, 0)
        self._lbl_progress.setFixedSize(80, 10)
        self._lbl_progress.hide()
        pag.addWidget(self._btn_prev)
        pag.addWidget(self._lbl_page)
        pag.addWidget(self._btn_next)
        pag.addSpacing(8)
        pag.addWidget(QLabel('Строк на странице:', self))
        pag.addWidget(self._combo_size)
        pag.addSpacing(8)
        pag.addWidget(self._lbl_total)
        pag.addStretch(1)
        pag.addWidget(self._lbl_progress)
        root.addLayout(pag)
        self._grid.horizontalHeader().sectionClicked.connect(self._on_sort)

    # --- загрузка ---

    def open(self):
        self._busy(True)
        self._worker = _Worker(self._factory,
                               lambda conn, worker: _load_page(
                                   conn, worker, self.schema, self.table,
                                   self.page_size, 0, self._order,
                                   self._filter_text),
                               database=self.database, parent=self)
        self._worker.done.connect(self._on_loaded)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _busy(self, on):
        self._lbl_progress.setVisible(on)

    def _on_loaded(self, payload):
        self._busy(False)
        self._meta = payload['meta']
        readonly = not payload['meta']['pk']
        self._grid.set_model(payload['meta']['columns'], payload['meta']['pk'],
                             payload['rows'], readonly=readonly)
        self._total = payload['count']
        # обновить список колонок локального поиска
        combo, cols = self._search_col, payload['meta']['columns']
        combo.blockSignals(True)
        current = combo.currentText()
        combo.clear()
        combo.addItem('Все колонки')
        combo.addItems(cols)
        if current and current != 'Все колонки' and current in cols:
            combo.setCurrentText(current)
        else:
            combo.setCurrentIndex(0)
        combo.blockSignals(False)
        self._update_pagination()
        self._btn_import.setEnabled(not readonly)
        self._btn_delete.setEnabled(not readonly)

    def _local_search(self, q: str) -> None:
        """Скрыть строки текущей страницы, не совпадающие с запросом."""
        q = (q or '').strip().lower()
        grid = self._grid
        if not q:
            for ri in range(grid.rowCount()):
                grid.setRowHidden(ri, False)
            return
        col_name = self._search_col.currentText()
        if col_name and col_name != 'Все колонки' and self._meta:
            cols = self._meta.get('columns', [])
            ci = cols.index(col_name) if col_name in cols else -1
        else:
            ci = -1
        for ri in range(grid.rowCount()):
            if ci >= 0:
                it = grid.item(ri, ci)
                match = bool(it and q in it.text().lower())
            else:
                match = any(
                    (it := grid.item(ri, c_i)) and q in it.text().lower()
                    for c_i in range(grid.columnCount())
                )
            grid.setRowHidden(ri, not match)

    def _reset_local_search(self) -> None:
        self._search_edit.clear()
        self._search_col.setCurrentIndex(0)
        for ri in range(self._grid.rowCount()):
            self._grid.setRowHidden(ri, False)

    def _on_failed(self, msg):
        self._busy(False)
        self._grid.clear_model()
        self._update_pagination()
        _toast(self, 'error', f'Не удалось загрузить {self.table}: {msg}')

    @property
    def page_size(self):
        return int(self._combo_size.currentText())

    def reload(self):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
        self._grid.clear_model()
        self.open()

    # --- фильтр / сортировка / пагинация ---

    def apply_filter(self):
        self._filter_text = self._filter_edit.text().strip()
        self._page = 1
        if self._filter_text and self._meta is not None:
            try:
                _build_where(self._filter_text, self._meta['columns'])
            except ValueError as e:
                _toast(self, 'warning', str(e))
                return
        self.reload()

    def reset_filter(self):
        self._filter_edit.clear()
        self._filter_text = ''
        self._page = 1
        self.reload()

    def _on_sort(self, section):
        if not self._meta:
            return
        name = self._meta['columns'][section]['name']
        if self._order and self._order[0] == name:
            new = None if self._order[1] == 'DESC' else 'DESC'
        else:
            new = 'ASC'
        self._order = (name, new) if new else None
        hdr = self._grid.horizontalHeader()
        if self._order:
            hdr.setSortIndicatorShown(True)
            hdr.setSortIndicator(section, Qt.AscendingOrder if new == 'ASC'
                                 else Qt.DescendingOrder)
        else:
            hdr.setSortIndicatorShown(False)
        self.reload()

    def _go_page(self, p):
        pages = max(1, -(-self._total // self.page_size))
        self._page = max(1, min(pages, p))
        self.reload()

    def _on_size_changed(self):
        self._page = 1
        self.reload()

    def _update_pagination(self):
        pages = max(1, -(-self._total // self.page_size)) if self._total else 1
        self._lbl_page.setText(f'Стр. {self._page} / {pages}')
        if self._filter_text:
            self._lbl_total.setText(f'Найдено строк: {self._total}')
        elif self._meta:
            self._lbl_total.setText(f'Строк (оценка): {self._total}')
        else:
            self._lbl_total.setText('')
        self._btn_prev.setEnabled(self._page > 1)
        self._btn_next.setEnabled(self._page < pages)

    # --- редактирование / удаление ---

    def _on_dirty(self, dirty):
        self._btn_save.setEnabled(dirty and bool(self._meta and self._meta['pk']))
        self._btn_cancel.setEnabled(dirty)

    def cancel_edits(self):
        if self._grid.dirty:
            self._grid.set_model(self._meta['columns'], self._meta['pk'],
                                 self._last_rows, readonly=not self._meta['pk'])
            self._on_dirty(False)

    @property
    def _last_rows(self):
        return [[self._grid.item(r, c).data(Qt.UserRole)
                 for c in range(self._grid.columnCount())]
                for r in range(self._grid.rowCount())]

    def save_edits(self):
        try:
            edits = self._grid.edits()
        except ValueError as e:
            _toast(self, 'warning', f'Не удалось сохранить: {e}')
            return
        if not edits:
            self._on_dirty(False)
            return
        columns = self._meta['columns']
        pk_idx = [next(i for i, c in enumerate(columns) if c['name'] == p)
                  for p in self._meta['pk']]
        rows = {}
        for (r, c, v) in edits:
            key = tuple(self._last_rows[r][i] for i in pk_idx)
            rows.setdefault(key, []).append((c, v))
        self._run_write('update', rows)

    def delete_selected(self):
        if not self._meta or not self._meta['pk']:
            return
        rows = sorted({i.row() for i in self._grid.selectedItems()})
        if not rows:
            _toast(self, 'warning', 'Выберите строки для удаления')
            return
        if QMessageBox.question(self, 'Удаление',
                                f'Удалить {len(rows)} строк(и) из '
                                f'{_qtable(self.schema, self.table)}?') \
                != QMessageBox.Yes:
            return
        pk = self._meta['pk']
        idx = {p: next(i for i, c in enumerate(self._meta['columns'])
                       if c['name'] == p) for p in pk}
        key_rows = [[self._grid.item(r, idx[p]).data(Qt.UserRole) for p in pk]
                    for r in rows]
        self._run_write('delete', key_rows)

    def _run_write(self, kind, payload):
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
        schema, table = self.schema, self.table
        columns = list(self._meta['columns'])
        pk = list(self._meta['pk'])

        def job(conn, worker):
            t = pgsql.SQL('{}.{}').format(pgsql.Identifier(schema),
                                          pgsql.Identifier(table))
            cur = conn.cursor()
            n = 0
            if kind == 'update':
                for key, cells in payload.items():
                    sets = pgsql.SQL(', ').join(
                        pgsql.SQL('{} = %s').format(
                            pgsql.Identifier(columns[c]['name']))
                        for c, v in cells)
                    cond = pgsql.SQL(' AND ').join(
                        pgsql.SQL('{} = %s').format(pgsql.Identifier(p))
                        for p in pk)
                    cur.execute(pgsql.SQL(
                        'UPDATE {t} SET {sets} WHERE {cond}')
                        .format(t=t, sets=sets, cond=cond),
                        [v for c, v in cells] + list(key))
                    n += cur.rowcount
            else:
                for key in payload:
                    cond = pgsql.SQL(' AND ').join(
                        pgsql.SQL('{} = %s').format(pgsql.Identifier(p))
                        for p in pk)
                    cur.execute(pgsql.SQL('DELETE FROM {t} WHERE {cond}')
                                .format(t=t, cond=cond), list(key))
                    n += cur.rowcount
            conn.commit()
            return n

        self._busy(True)
        w = _Worker(self._factory, job, database=self.database, parent=self)

        def on_done(n):
            self._busy(False)
            _toast(self, 'success',
                   ('Обновлено' if kind == 'update' else 'Удалено') + f': {n} строк')
            self.reload()
        w.done.connect(on_done)
        w.failed.connect(lambda m: (self._busy(False),
                                    _toast(self, 'error', f'Ошибка: {m}')))
        self._worker = w
        w.start()

    # --- экспорт / импорт ---

    def export(self, fmt):
        if not self._meta:
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Экспорт',
                                              f'{self.table}.{fmt}', f'*.{fmt}')
        if not path:
            return
        where = None
        if self._filter_text:
            try:
                where = _build_where(self._filter_text, self._meta['columns'])
            except ValueError:
                where = None
        columns = self._meta['columns']

        def job(conn, worker):
            return _export_rows(conn, worker, self.schema, self.table, columns,
                                where, self._order, path, fmt)
        self._busy(True)
        w = _Worker(self._factory, job, database=self.database, parent=self)
        w.done.connect(lambda n: (self._busy(False),
                                  _toast(self, 'success', f'Экспортировано строк: {n}')))
        w.failed.connect(lambda m: (self._busy(False),
                                    _toast(self, 'error', f'Экспорт не удался: {m}')))
        w.start()

    def import_csv(self):
        if not self._meta or not self._meta['pk']:
            return
        dlg = _CsvImportDialog(self, self._meta['columns'])
        if dlg.exec() != QDialog.Accepted:
            return
        opts = dlg.result_options()

        def job(conn, worker):
            mapped = [(j, t) for j, t in enumerate(opts['mapping'])
                      if t is not None]
            ins = pgsql.SQL('INSERT INTO {t} ({cols}) VALUES %s').format(
                t=pgsql.SQL('{}.{}').format(pgsql.Identifier(self.schema),
                                            pgsql.Identifier(self.table)),
                cols=pgsql.SQL(', ').join(
                    pgsql.Identifier(self._meta['columns'][t]['name'])
                    for j, t in mapped))
            cur = conn.cursor()
            rows = []
            with open(opts['path'], encoding=opts['encoding'], newline='') as f:
                reader = csv.reader(f, delimiter=opts['delimiter'])
                for i, line in enumerate(reader):
                    if i == 0 and opts['has_header']:
                        continue
                    rows.append(tuple(None if j >= len(line) or line[j].strip() == ''
                                      else line[j] for j, t in mapped))
                    if len(rows) >= 500:
                        pgextras.execute_values(cur, ins, rows)
                        rows = []
                        if worker is not None and worker.isInterruptionRequested():
                            raise _DbError('отменено')
            if rows:
                pgextras.execute_values(cur, ins, rows)
            conn.commit()
            return cur.rowcount
        self._busy(True)
        w = _Worker(self._factory, job, database=self.database, parent=self)
        w.done.connect(lambda n: (self._busy(False),
                                  _toast(self, 'success', f'Импортировано строк: {n}'),
                                  self.reload()))
        w.failed.connect(lambda m: (self._busy(False),
                                    _toast(self, 'error', f'Импорт не удался: {m}')))
        w.start()


# # Диалог импорта CSV (превью + маппинг колонок)

class _CsvImportDialog(QDialog):
    def __init__(self, parent, target_columns):
        super().__init__(parent)
        self.setWindowTitle('Импорт CSV')
        self.resize(760, 560)
        self._targets, self._mapping_combos, self._map_rows = \
            target_columns, [], []
        lay = QVBoxLayout(self)
        form = QFormLayout()
        row = QHBoxLayout()
        self._file_edit = LineEdit(self)
        self._file_edit.setPlaceholderText('Файл CSV…')
        btn = PushButton('Обзор…', self)
        btn.clicked.connect(self._browse)
        row.addWidget(self._file_edit, 1)
        row.addWidget(btn)
        form.addRow('Файл:', row)
        self._enc = ComboBox(self)
        self._enc.addItems(['utf-8', 'cp1251', 'utf-8-sig'])
        self._delim = ComboBox(self)
        self._delim.addItems([';', ',', '\t'])
        self._header = ComboBox(self)
        self._header.addItems(['да', 'нет'])
        form.addRow('Кодировка:', self._enc)
        form.addRow('Разделитель:', self._delim)
        form.addRow('Первая строка — заголовки:', self._header)
        lay.addLayout(form)
        self._preview = QTableWidget(self)
        self._preview.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._preview.setMaximumHeight(240)
        self._preview.verticalHeader().setVisible(False)
        lay.addWidget(QLabel('Предпросмотр (первые 15 строк):'))
        lay.addWidget(self._preview)
        self._map_widget = QWidget(self)
        self._map_lay = QVBoxLayout(self._map_widget)
        self._map_lay.setContentsMargins(0, 0, 0, 0)
        self._map_lay.addWidget(QLabel('Соответствие колонок:'))
        lay.addWidget(self._map_widget, 1)
        btns = QHBoxLayout()
        btns.addStretch(1)
        self._btn_ok = PushButton('Импортировать', self)
        self._btn_ok.setEnabled(False)
        self._btn_ok.clicked.connect(self.accept)
        btns.addWidget(self._btn_ok)
        lay.addLayout(btns)
        self._file_edit.textChanged.connect(self._load_preview)
        self._delim.currentIndexChanged.connect(self._load_preview)
        self._enc.currentIndexChanged.connect(self._load_preview)

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, 'CSV файл', '', '*.csv')
        if path:
            self._file_edit.setText(path)

    def _load_preview(self):
        path = self._file_edit.text().strip()
        if not path:
            return
        try:
            with open(path, encoding=self._enc.currentText(), newline='') as f:
                rows = [line for i, line in enumerate(
                    csv.reader(f, delimiter=self._delim.currentText())) if i < 15]
        except Exception as e:
            self._preview.clear()
            self._preview.setRowCount(1)
            self._preview.setColumnCount(1)
            self._preview.setItem(0, 0, QTableWidgetItem(f'Ошибка чтения: {e}'))
            self._btn_ok.setEnabled(False)
            return
        ncols = max((len(r) for r in rows), default=0)
        self._preview.setColumnCount(ncols)
        self._preview.setRowCount(len(rows))
        for r, line in enumerate(rows):
            for c in range(ncols):
                self._preview.setItem(r, c, QTableWidgetItem(
                    line[c] if c < len(line) else ''))
        for w in self._map_rows:
            w.deleteLater()
        self._map_rows, self._mapping_combos = [], []
        first_is_header = self._header.currentText() == 'да'
        for c in range(ncols):
            row_w = QWidget(self._map_widget)
            h = QHBoxLayout(row_w)
            h.setContentsMargins(0, 2, 0, 2)
            src = (rows[0][c] if rows and first_is_header and c < len(rows[0])
                   else f'колонка {c + 1}')
            h.addWidget(QLabel(f'{src}:'))
            combo = ComboBox(row_w)
            combo.addItem('— пропустить —', None)
            for i, col in enumerate(self._targets):
                combo.addItem(col['name'], i)
            if first_is_header:
                for i, col in enumerate(self._targets):
                    if col['name'] == src:
                        combo.setCurrentIndex(i + 1)
            h.addWidget(combo, 1)
            self._map_lay.addWidget(row_w)
            self._map_rows.append(row_w)
            self._mapping_combos.append(combo)
        self._btn_ok.setEnabled(True)

    def result_options(self):
        return {'path': self._file_edit.text().strip(),
                'encoding': self._enc.currentText(),
                'delimiter': self._delim.currentText(),
                'has_header': self._header.currentText() == 'да',
                'mapping': [cb.currentData() for cb in self._mapping_combos]}


# # SQL-консоль (выдвижная): подсветка, автокомплит, история, закладки

_SQL_KEYWORDS = ('SELECT FROM WHERE GROUP BY ORDER HAVING LIMIT OFFSET JOIN LEFT '
                 'RIGHT INNER OUTER FULL CROSS ON AND OR NOT NULL AS DISTINCT '
                 'INSERT INTO VALUES UPDATE SET DELETE CREATE TABLE INDEX VIEW '
                 'DROP ALTER BEGIN COMMIT ROLLBACK TRANSACTION CASE WHEN THEN '
                 'ELSE END UNION ALL EXISTS IN LIKE ILIKE BETWEEN IS TRUE FALSE '
                 'CAST RETURNING WITH RECURSIVE ASC DESC PRIMARY KEY FOREIGN '
                 'REFERENCES UNIQUE CHECK DEFAULT USING INTERSECT EXCEPT OVER '
                 'PARTITION FILTER').split()
_SQL_TYPES = ('INT INTEGER BIGINT SMALLINT SERIAL TEXT VARCHAR CHAR BOOLEAN BOOL '
              'NUMERIC DECIMAL REAL DOUBLE FLOAT DATE TIME TIMESTAMP UUID JSON '
              'JSONB BYTEA MONEY INET INTERVAL').split()
_SQL_FUNCS = ('COUNT SUM AVG MIN MAX COALESCE NULLIF NOW CURRENT_DATE '
              'CURRENT_TIMESTAMP UPPER LOWER LENGTH SUBSTRING TRIM ROUND ABS '
              'GREATEST LEAST ARRAY_AGG STRING_AGG GENERATE_SERIES TO_CHAR '
              'TO_DATE TO_TIMESTAMP EXTRACT').split()


class _SqlHighlighter(QSyntaxHighlighter):
    def __init__(self, doc):
        super().__init__(doc)
        kw = QTextCharFormat()
        kw.setForeground(QColor('#7c4dff'))
        kw.setFontWeight(QFont.Bold)
        ty = QTextCharFormat()
        ty.setForeground(QColor('#0077b6'))
        fn = QTextCharFormat()
        fn.setForeground(QColor('#0b7285'))
        st = QTextCharFormat()
        st.setForeground(QColor(_c('success', '#2e7d32')))
        nm = QTextCharFormat()
        nm.setForeground(QColor(_c('warning', '#f57c00')))
        cm = QTextCharFormat()
        cm.setForeground(QColor(_c('text_secondary')))
        cm.setFontItalic(True)
        op = QTextCharFormat()
        op.setForeground(QColor(_c('text_secondary')))
        self._rules = ([(re.compile(rf'\b{w}\b', re.I), kw) for w in _SQL_KEYWORDS]
                       + [(re.compile(rf'\b{w}\b', re.I), ty) for w in _SQL_TYPES]
                       + [(re.compile(rf'\b{w}\b', re.I), fn) for w in _SQL_FUNCS]
                       + [(re.compile(r"'(?:[^']|'')*'"), st),
                          (re.compile(r'\b\d+(\.\d+)?\b'), nm),
                          (re.compile(r'--[^\n]*'), cm),
                          (re.compile(r'/\*.*?\*/', re.S), cm),
                          (re.compile(r'[+\-*/%=<>()\[\];,.]'), op)])

    def highlightBlock(self, text):
        for rx, fmt in self._rules:
            for m in rx.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


class _SqlEdit(QPlainTextEdit):
    executeRequested = Signal()
    completeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFont(_mono())
        self._hist, self._hist_pos = [], -1

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and \
                e.modifiers() & Qt.ControlModifier:
            self.executeRequested.emit()
        elif e.key() == Qt.Key_Space and e.modifiers() & Qt.ControlModifier:
            self.completeRequested.emit()
        elif e.key() in (Qt.Key_Up, Qt.Key_Down) and self._hist:
            if self._hist_pos < 0 and e.key() == Qt.Key_Up and not self.toPlainText():
                self._hist_pos = len(self._hist)
            if self._hist_pos >= 0:
                self._hist_pos += -1 if e.key() == Qt.Key_Up else 1
                self._hist_pos = max(-1, min(len(self._hist) - 1, self._hist_pos))
                if self._hist_pos >= 0:
                    self.setPlainText(self._hist[self._hist_pos])
                else:
                    self.clear()
                self.moveCursor(QTextCursor.End)
        else:
            super().keyPressEvent(e)

    def set_history(self, hist):
        self._hist, self._hist_pos = list(hist), -1


class _Completer(QWidget):
    def __init__(self, editor):
        super().__init__(editor, Qt.ToolTip | Qt.FramelessWindowHint)
        self._editor, self._tables, self._columns = editor, [], {}
        self._list = QListWidget(self)
        self._list.setFont(_mono())
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self._list)
        self._list.itemActivated.connect(self._apply)
        self._list.itemClicked.connect(self._apply)
        self.hide()

    def set_data(self, tables, columns):
        self._tables, self._columns = list(tables), columns

    def _span(self, text, pos):
        start = pos
        while start > 0 and (text[start - 1].isalnum()
                             or text[start - 1] in '_.$'):
            start -= 1
        return start, pos

    def show_for(self):
        text = self._editor.toPlainText()
        start, pos = self._span(text, self._editor.textCursor().position())
        word = text[start:pos]
        if '.' in word:
            tbl, prefix = word.rsplit('.', 1)
            tbl = tbl.strip().strip('"')
            cols = self._columns.get(tbl)
            if cols is None:
                for k, v in self._columns.items():
                    if k.endswith('.' + tbl):
                        cols = v
                        break
            cands = [c for c in (cols or []) if c.lower().startswith(prefix.lower())]
        else:
            cands = [t for t in self._tables if t.lower().startswith(word.lower())]
            if not word:
                cands = self._tables[:200]
            cands += [k for k in _SQL_KEYWORDS + _SQL_FUNCS
                      if k.lower().startswith(word.lower())]
        if not cands:
            self.hide()
            return
        self._list.clear()
        self._list.addItems(cands[:300])
        self._list.setCurrentRow(0)
        self.move(self._editor.mapToGlobal(self._editor.cursorRect().bottomLeft()))
        self.resize(max(self.sizeHint().width(), 220),
                    min(self._list.count() * 22 + 8, 320))
        self.show()
        self.raise_()

    def _apply(self, item):
        self.hide()
        tc = self._editor.textCursor()
        text = self._editor.toPlainText()
        start, pos = self._span(text, tc.position())
        tc.setPosition(start)
        tc.setPosition(pos, QTextCursor.KeepAnchor)
        tc.insertText(item.text())
        self._editor.setTextCursor(tc)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key_Up, Qt.Key_Down):
            self._list.setCurrentRow(max(0, min(
                self._list.count() - 1,
                self._list.currentRow() + (-1 if e.key() == Qt.Key_Up else 1))))
        elif e.key() in (Qt.Key_Enter, Qt.Key_Return, Qt.Key_Tab):
            if self._list.currentItem():
                self._apply(self._list.currentItem())
        elif e.key() == Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(e)


class _SqlConsole(QWidget):  # Выдвижная консоль: редактор + результат + история/закладки в меню.

    def __init__(self, factory, parent=None):
        super().__init__(parent)
        self._factory = factory
        self._database = factory.database
        self._hist = _load_json('query_history.json', [])
        self._bookmarks = _load_json('saved_queries.json', {})
        self._worker, self._result_columns, self._result_rows = None, [], []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        bar = QHBoxLayout()
        self._btn_run = PushButton('▶ Выполнить', self)
        self._btn_run.setToolTip('Ctrl+Enter')
        self._btn_run.clicked.connect(self.execute)
        self._btn_hist = ToolButton(_icon('HISTORY'), self)
        self._btn_hist.setToolTip('История запросов')
        self._btn_hist.clicked.connect(self._history_menu)
        self._btn_book = ToolButton(_icon('BOOK_SHELF'), self)
        self._btn_book.setToolTip('Закладки')
        self._btn_book.clicked.connect(self._bookmark_menu)
        self._btn_exp_csv = ToolButton(_icon('DOCUMENT'), self)
        self._btn_exp_csv.setToolTip('Экспорт результата CSV')
        self._btn_exp_csv.clicked.connect(lambda: self._export('csv'))
        self._btn_exp_json = ToolButton(_icon('CODE'), self)
        self._btn_exp_json.setToolTip('Экспорт результата JSON')
        self._btn_exp_json.clicked.connect(lambda: self._export('json'))
        self._btn_copy = ToolButton(_icon('COPY'), self)
        self._btn_copy.setToolTip('Копировать результат в буфер')
        self._btn_copy.clicked.connect(self._copy_result)
        self._btn_clear = ToolButton(_icon('BROOM'), self)
        self._btn_clear.setToolTip('Очистить редактор')
        self._lbl_status = QLabel('', self)
        bar.addWidget(self._btn_run)
        for b in (self._btn_hist, self._btn_book):
            bar.addWidget(b)
        bar.addSpacing(8)
        for b in (self._btn_exp_csv, self._btn_exp_json, self._btn_copy,
                  self._btn_clear):
            bar.addWidget(b)
        bar.addSpacing(8)
        bar.addWidget(self._lbl_status, 1)
        bar.addWidget(QLabel('Ctrl+Enter — выполнить', self))
        lay.addLayout(bar)
        self._editor = _SqlEdit(self)
        self._btn_clear.clicked.connect(self._editor.clear)
        self._editor.setPlaceholderText(
            'SQL-запрос…\nПримеры:\n  SELECT * FROM public.customers LIMIT 50;\n'
            '  UPDATE public.customers SET active = false WHERE id = 1;')
        self._highlighter = _SqlHighlighter(self._editor.document())
        self._editor.executeRequested.connect(self.execute)
        self._editor.completeRequested.connect(self._complete)
        self._editor.set_history(self._hist)
        self._completer = _Completer(self._editor)
        self._editor.cursorPositionChanged.connect(self._completer.hide)
        lay.addWidget(self._editor, 2)
        self._result_bar = QHBoxLayout()
        self._lbl_result = QLabel('', self)
        self._result_bar.addWidget(self._lbl_result)
        self._result_bar.addStretch(1)
        self._lbl_res_progress = QProgressBar(self)
        self._lbl_res_progress.setRange(0, 0)
        self._lbl_res_progress.setFixedSize(80, 10)
        self._lbl_res_progress.hide()
        self._result_bar.addWidget(self._lbl_res_progress)
        lay.addLayout(self._result_bar)
        self._result = _DataGrid(self)
        self._result.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._result.horizontalHeader().setSectionsClickable(False)
        lay.addWidget(self._result, 3)

    def set_database(self, db):
        self._database = db
        self._lbl_status.setText(f'База: {db}')

    def execute(self, sql=None):
        if self._worker and self._worker.isRunning():
            return
        if sql is None:
            sql = self._editor.toPlainText().strip()
            self._editor._hist_pos = -1
        if not sql:
            return
        if sql != self._editor.toPlainText():
            self._editor.setPlainText(sql)
        self._push_history(sql)
        self._lbl_res_progress.show()
        self._btn_run.setEnabled(False)

        def job(conn, worker):
            t0 = time.monotonic()
            cur = conn.cursor()
            cur.execute(sql)
            if cur.description is None:
                conn.commit()
                return {'kind': 'ok', 'rowcount': cur.rowcount,
                        'duration': time.monotonic() - t0}
            rows = []
            while len(rows) < _MAX_CONSOLE_ROWS:
                batch = cur.fetchmany(200)
                if not batch:
                    break
                rows.extend(batch)
                if worker is not None and worker.isInterruptionRequested():
                    raise _DbError('отменено')
            total = len(rows)
            if total == _MAX_CONSOLE_ROWS:
                cur.fetchall()
                total = cur.rowcount if cur.rowcount and cur.rowcount > total \
                    else total
            return {'kind': 'rows', 'columns': [d[0] for d in cur.description],
                    'rows': rows, 'total': total,
                    'duration': time.monotonic() - t0}

        self._worker = _Worker(self._factory, job, database=self._database,
                               parent=self)

        def on_done(res):
            self._lbl_res_progress.hide()
            self._btn_run.setEnabled(True)
            if res['kind'] == 'ok':
                self._result.clear_model()
                self._result_columns, self._result_rows = [], []
                self._lbl_result.setText(
                    f'OK · затронуто строк: {res["rowcount"]} · '
                    f'{res["duration"]:.2f} с')
            else:
                cols = [{'name': n, 'type': ''} for n in res['columns']]
                self._result.set_model(cols, [], res['rows'], readonly=True)
                self._result_columns, self._result_rows = cols, res['rows']
                self._lbl_result.setText(
                    f'Строк: {res["total"]} (показано {len(res["rows"])}) · '
                    f'{res["duration"]:.2f} с')
        self._worker.done.connect(on_done)

        def on_fail(msg):
            self._lbl_res_progress.hide()
            self._btn_run.setEnabled(True)
            self._lbl_result.setText(f'Ошибка: {msg}')
            _toast(self, 'error', msg)
        self._worker.failed.connect(on_fail)
        self._worker.start()

    def _push_history(self, sql):
        if self._hist and self._hist[0] == sql:
            return
        self._hist.insert(0, sql)
        del self._hist[_HISTORY_LIMIT:]
        self._editor.set_history(self._hist)
        _save_json('query_history.json', self._hist)

    def set_completion_data(self, tables, columns):
        self._completer.set_data(tables, columns)

    def _complete(self):
        if self._completer._tables:
            self._completer.show_for()

    def _history_menu(self):
        menu = QMenu(self)
        if not self._hist:
            menu.addAction('История пуста').setEnabled(False)
        for sql in self._hist[:30]:
            a = menu.addAction(sql[:80].replace('\n', '⏎'))
            a.setData(sql)
        a = menu.exec(self._btn_hist.mapToGlobal(self._btn_hist.rect().bottomLeft()))
        if a and a.data():
            self._editor.setPlainText(a.data())

    def _bookmark_menu(self):
        menu = QMenu(self)
        for name, sql in self._bookmarks.items():
            a = menu.addAction(name)
            a.setData(('run', sql))
        menu.addSeparator()
        act_save = menu.addAction('Сохранить текущий SQL…')
        act_mng = menu.addAction('Управление закладками…')
        a = menu.exec(self._btn_book.mapToGlobal(self._btn_book.rect().bottomLeft()))
        if a is None:
            return
        if a == act_save:
            self._save_bookmark()
        elif a == act_mng:
            self._manage_bookmarks()
        elif a.data():
            self._editor.setPlainText(a.data()[1])
            if a.data()[0] == 'run':
                self.execute()

    def _save_bookmark(self):
        sql = self._editor.toPlainText().strip()
        if not sql:
            return
        name, ok = QInputDialog.getText(self, 'Закладка', 'Имя закладки:')
        if ok and name.strip():
            self._bookmarks[name.strip()] = sql
            _save_json('saved_queries.json', self._bookmarks)
            _toast(self, 'success', f'Закладка «{name.strip()}» сохранена')

    def _manage_bookmarks(self):
        dlg = QDialog(self)
        dlg.setWindowTitle('Закладки')
        dlg.resize(420, 320)
        lay = QVBoxLayout(dlg)
        lst = QListWidget(dlg)
        lst.addItems(list(self._bookmarks))
        lay.addWidget(lst, 1)
        btns = QHBoxLayout()
        btn_del = PushButton('Удалить', dlg)
        btn_close = PushButton('Закрыть', dlg)
        btns.addStretch(1)
        btns.addWidget(btn_del)
        btns.addWidget(btn_close)
        lay.addLayout(btns)

        def delete():
            it = lst.currentItem()
            if it:
                self._bookmarks.pop(it.text(), None)
                _save_json('saved_queries.json', self._bookmarks)
                lst.takeItem(lst.row(it))
        btn_del.clicked.connect(delete)
        btn_close.clicked.connect(dlg.accept)
        dlg.exec()

    def _export(self, fmt):
        if not self._result_rows:
            _toast(self, 'warning', 'Нет результата для экспорта')
            return
        path, _ = QFileDialog.getSaveFileName(self, 'Экспорт',
                                              f'query_result.{fmt}', f'*.{fmt}')
        if not path:
            return

        def job(conn, worker):
            columns, rows = self._result_columns, self._result_rows
            if fmt == 'csv':
                with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                    w = csv.writer(f, delimiter=';')
                    w.writerow([c['name'] for c in columns])
                    for r in rows:
                        w.writerow([_csv_cell(v) for v in r])
            else:
                names = [c['name'] for c in columns]
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(json.dumps(
                        [{nm: _json_value(v) for nm, v in zip(names, r)}
                         for r in rows], ensure_ascii=False))
            return len(rows)
        self._lbl_res_progress.show()
        w = _Worker(self._factory, job, database=self._database, parent=self)
        w.done.connect(lambda n: (self._lbl_res_progress.hide(),
                                  _toast(self, 'success', f'Экспортировано строк: {n}')))
        w.failed.connect(lambda m: (self._lbl_res_progress.hide(),
                                    _toast(self, 'error', m)))
        w.start()

    def _copy_result(self):
        if not self._result_rows:
            return
        QGuiApplication.clipboard().setText('\n'.join(
            '\t'.join(_csv_cell(v) for v in r) for r in self._result_rows))
        _toast(self, 'success', 'Результат скопирован в буфер')


# # Левая панель: комбо баз + поиск + список таблиц

class _TablesPanel(QWidget):
    openTable = Signal(str, str, str)   # database, schema, table

    _KIND_ICON = {'r': 'GRID', 'p': 'GRID', 'v': 'VIEW', 'm': 'ALBUM'}

    def __init__(self, factory, parent=None):
        super().__init__(parent)
        self._factory = factory
        self._database = factory.database
        self._schema = 'public'
        self._tables = []               # (name, kind)
        self._worker = None
        self._info_seq = 0
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(6)
        self._db_combo = ComboBox(self)
        self._db_combo.setMinimumWidth(140)
        self._db_combo.currentTextChanged.connect(self._on_db)
        lay.addWidget(self._db_combo)
        self._search = SearchLineEdit(self)
        self._search.setPlaceholderText('Поиск таблиц…')
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_search)
        lay.addWidget(self._search)
        self._list = QListWidget(self)
        self._list.setFont(QFont('Segoe UI', 10))
        self._list.setIconSize(QSize(16, 16))
        self._list.setTextElideMode(Qt.ElideRight)
        self._list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._list.setUniformItemSizes(True)
        self._list.setStyleSheet(
            'QListWidget { border: 1px solid rgba(128,128,128,0.35);'
            ' border-radius: 6px; padding: 2px; }'
            'QListWidget::item { padding: 4px 6px; }')
        self._list.itemDoubleClicked.connect(self._on_activate)
        self._list.itemClicked.connect(self._on_click)
        self._list.setContextMenuPolicy(Qt.CustomContextMenu)
        self._list.customContextMenuRequested.connect(self._menu)
        lay.addWidget(self._list, 1)

        self._info = QLabel('<i>Клик по таблице — свойства</i>', self)
        self._info.setWordWrap(True)
        self._info.setTextFormat(Qt.RichText)
        self._info.setFixedHeight(92)
        self._info.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self._info.setStyleSheet(
            'color: palette(mid); font-size: 12px;'
            'border-top: 1px solid rgba(128,128,128,0.35); padding-top: 6px;')
        lay.addWidget(self._info)
        # отложенная загрузка свойств: не спамим подключениями при пробеге по списку
        self._info_worker = None
        self._info_target = None
        self._info_timer = QTimer(self)
        self._info_timer.setSingleShot(True)
        self._info_timer.setInterval(220)
        self._info_timer.timeout.connect(self._load_info)

    def set_databases(self, dbs):
        self._db_combo.blockSignals(True)
        self._db_combo.clear()
        self._db_combo.addItems(dbs)
        if self._database in dbs:
            self._db_combo.setCurrentText(self._database)
        self._db_combo.blockSignals(False)
        self._load_tables()

    def _on_db(self, db):
        if db:
            self._database = db
            self._load_tables()

    def _load_tables(self):
        schema = self._schema

        def job(conn, worker):
            cur = conn.cursor()
            cur.execute(_SQL_TABLES, (schema,))
            return [(r[0], r[1]) for r in cur.fetchall()]

        def on_done(items):
            self._tables = items
            self._apply_search()
        w = _Worker(self._factory, job, database=self._database, parent=self)
        w.done.connect(on_done)
        w.failed.connect(lambda m: _toast(self, 'error', m))
        self._worker = w
        w.start()

    def _apply_search(self):
        q = self._search.text().strip().lower()
        self._list.clear()
        for name, kind in self._tables:
            if q and q not in name.lower():
                continue
            it = QListWidgetItem(_icon(self._KIND_ICON.get(kind, 'GRID')), name)
            it.setToolTip(f'{self._schema}.{name} · '
                          f'{_KIND_LABEL_C.get(kind, kind)}')
            it.setData(Qt.UserRole, (name, kind))
            self._list.addItem(it)

    def _on_click(self, it):
        name, kind = it.data(Qt.UserRole)
        # мгновенный лёгкий отклик без обращения к БД
        self._info_target = (name, kind)
        kind_s = _KIND_LABEL_C.get(kind, kind)
        self._info.setText(f'<b>{self._schema}.{name}</b> '
                           f'<span style="color:gray">({kind_s})</span><br>'
                           f'<i>Загрузка…</i>')
        self._info_timer.start()  # дебаунс 220 мс

    def _load_info(self):
        """Свойства таблицы: строки/колонки/размер (асинхронно)."""
        if not self._info_target:
            return
        name, kind = self._info_target
        self._info_seq += 1
        seq = self._info_seq
        schema = self._schema

        def job(conn, worker):
            cur = conn.cursor()
            cur.execute(
                "SELECT c.reltuples::bigint,"
                " pg_size_pretty(pg_total_relation_size(c.oid)),"
                " COALESCE(obj_description(c.oid, 'pg_class'), '')"
                " FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace"
                " WHERE n.nspname=%s AND c.relname=%s",
                (schema, name))
            row = cur.fetchone()
            if row is None:
                raise _DbError(f'{schema}.{name} не найдена в pg_class')
            est, size, comment = row
            cur.execute(
                "SELECT count(*) FROM information_schema.columns"
                " WHERE table_schema=%s AND table_name=%s",
                (schema, name))
            ncols = cur.fetchone()[0]
            return est, size, ncols, comment

        def on_done(res):
            if seq != self._info_seq:
                return  # устаревший ответ — игнорируем
            est, size, ncols, comment = res
            est_s = f'{est:,}'.replace(',', ' ') if est and est > 0 else '—'
            kind_s = _KIND_LABEL_C.get(kind, kind)
            html = (f'<b>{schema}.{name}</b> <span style="color:gray">'
                    f'({kind_s})</span><br>'
                    f'Строк (оценка): {est_s} · Колонок: {ncols}<br>'
                    f'Размер: {size}')
            if comment:
                html += f'<br><i>{comment}</i>'
            self._info.setText(html)

        def on_fail(m):
            if seq != self._info_seq:
                return
            self._info.setText(
                f'<b>{schema}.{name}</b><br>'
                f'<span style="color:#c62828">Ошибка метаданных: {m}</span>')

        w = _Worker(self._factory, job, database=self._database, parent=self)
        w.done.connect(on_done)
        w.failed.connect(on_fail)
        self._info_worker = w   # отдельный атрибут — не трогаем загрузчик списка
        w.start()

    def refresh(self):
        self._load_tables()

    def cancel(self):
        if self._worker:
            self._worker.cancel()
        self._info_timer.stop()
        if self._info_worker:
            self._info_worker.requestInterruption()

    def _on_activate(self, it):
        name, kind = it.data(Qt.UserRole)
        self.openTable.emit(self._database, self._schema, name)

    def _menu(self, pos):
        it = self._list.itemAt(pos)
        if it is None:
            return
        name, _kind = it.data(Qt.UserRole)
        menu = QMenu(self)
        act_open = menu.addAction('Открыть')
        act_console = menu.addAction('Открыть в консоли (SELECT)')
        act_refresh = menu.addAction('Обновить список')
        a = menu.exec(self._list.viewport().mapToGlobal(pos))
        if a == act_open:
            self.openTable.emit(self._database, self._schema, name)
        elif a == act_console:
            self.console_sql.emit(
                f'SELECT * FROM {_qtable(self._schema, name)} LIMIT 200;')
        elif a == act_refresh:
            self._load_tables()

    console_sql = Signal(str)


_KIND_LABEL_C = {'r': 'таблица', 'p': 'таблица (секц.)', 'v': 'представление',
                 'm': 'мат. представление'}


# # Главный виджет и окно (контракт: PostgresToolWidget / PostgresToolWindow)

class PostgresToolWidget(QWidget):
    def __init__(self, host, port, user, passwords, database=None,
                 parent=None):
        super().__init__(parent)
        self._factory = _ConnFactory(host, port, user, passwords, database)
        self._current_db = self._factory.database
        self._server_version = ''
        self._connected, self._closing = False, False
        self._workers = []
        self.setWindowTitle('PostgreSQL клиент')
        self.resize(1120, 700)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        top = QHBoxLayout()
        top.setContentsMargins(12, 8, 12, 8)
        top.addWidget(QLabel('PostgreSQL клиент'))
        top.addStretch(1)
        self._btn_refresh = ToolButton(_icon('SYNC'), self)
        self._btn_refresh.setToolTip('Обновить список таблиц')
        self._btn_refresh.clicked.connect(self._refresh_tables)
        top.addWidget(self._btn_refresh)
        self._btn_console = ToolButton(_icon('CODE'), self)
        self._btn_console.setToolTip('Консоль (Ctrl+L)')
        self._btn_console.setCheckable(True)
        self._btn_console.setChecked(False)
        self._btn_console.clicked.connect(self._toggle_console)
        top.addWidget(self._btn_console)
        root.addLayout(top)

        self._split = QSplitter(Qt.Horizontal, self)
        self._tables_panel = _TablesPanel(self._factory, self._split)
        self._tables_panel.openTable.connect(self._open_table)
        self._tables_panel.console_sql.connect(self._open_console_sql)
        self._split.addWidget(self._tables_panel)

        self._tabs = QTabWidget(self)
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._empty = QLabel('Выберите таблицу слева', self)
        self._empty.setAlignment(Qt.AlignCenter)
        self._center = QStackedWidget(self._split)
        self._center.addWidget(self._empty)
        self._center.addWidget(self._tabs)
        self._split.addWidget(self._center)
        self._split.setStretchFactor(0, 0)
        self._split.setStretchFactor(1, 1)
        self._split.setSizes([260, 860])
        root.addWidget(self._split, 1)

        # консоль — выдвижная панель
        self._console = _SqlConsole(self._factory, self)
        self._console.set_database(self._current_db)
        self._console.setMaximumHeight(0)
        root.addWidget(self._console)

        self._status = QStatusBar(self)
        self._lbl_conn = QLabel('Подключение…', self)
        self._status.addWidget(self._lbl_conn)
        self._busy_progress = QProgressBar(self)
        self._busy_progress.setRange(0, 0)
        self._busy_progress.setFixedSize(90, 12)
        self._busy_progress.hide()
        self._status.addPermanentWidget(self._busy_progress)
        root.addWidget(self._status)
        self._busy = _Busy(self._busy_progress)
        self._anim = QPropertyAnimation(self._console, b'maximumHeight', self)
        self._anim.setDuration(180)
        QShortcut(QKeySequence('Ctrl+L'), self, activated=self._toggle_console)
        QTimer.singleShot(0, self._connect)

    # --- подключение ---

    def _connect(self):
        if self._connected or self._closing:
            return
        self._busy.start()
        self._lbl_conn.setText('Подключение…')

        def job(conn, worker):
            cur = conn.cursor()
            cur.execute(_SQL_DATABASES)
            dbs = [r[0] for r in cur.fetchall()]
            cur.execute('SELECT version()')
            return {'dbs': dbs, 'version': cur.fetchone()[0]}

        def on_done(res):
            self._busy.stop()
            self._connected = True
            self._server_version = res['version'].split(' on ')[0]
            self._tables_panel.set_databases(res['dbs'])
            self._update_conn_label()
            self._load_completion_data()
            _toast(self, 'success',
                   f'Подключено: {self._current_db} ({self._server_version})')

        def on_fail(msg):
            self._busy.stop()
            self._lbl_conn.setText(f'Ошибка подключения: {msg}')
            _toast(self, 'error', f'Не удалось подключиться: {msg}')

        w = _Worker(self._factory, job, parent=self)
        w.done.connect(on_done)
        w.failed.connect(on_fail)
        self._track(w)
        w.start()

    def _update_conn_label(self):
        f = self._factory
        ver = re.sub(r'^PostgreSQL\s+', '', self._server_version)
        self._lbl_conn.setText(
            f'{f.user}@{f.host}:{f.port} / {self._current_db} · {ver}')

    def _load_completion_data(self):
        def job(conn, worker):
            cur = conn.cursor()
            cur.execute(_SQL_COMPLETION)
            tables, columns = [], {}
            for nsp, rel, att in cur.fetchall():
                qn = f'{nsp}.{rel}'
                if qn not in columns:
                    tables.append(qn)
                    columns[qn] = []
                if len(columns[qn]) < 200:
                    columns[qn].append(att)
            return {'tables': tables, 'columns': columns}
        w = _Worker(self._factory, job, database=self._current_db, parent=self)
        w.done.connect(lambda d: self._console.set_completion_data(
            d['tables'], d['columns']))
        w.failed.connect(lambda m: None)
        self._track(w)
        w.start()

    # --- таблицы / консоль ---

    def _open_table(self, database, schema, table):
        # уже открыта — просто активируем вкладку
        for i in range(self._tabs.count()):
            p = self._tabs.widget(i)
            if (p.database, p.schema, p.table) == (database, schema, table):
                self._center.setCurrentWidget(self._tabs)
                self._tabs.setCurrentIndex(i)
                return
        panel = _DataPanel(self._factory, database, schema, table, self)
        idx = self._tabs.addTab(panel, table)
        self._tabs.setTabToolTip(idx, f'{schema}.{table} @ {database}')
        self._center.setCurrentWidget(self._tabs)
        self._tabs.setCurrentIndex(idx)
        panel.open()

    def _close_tab(self, idx: int) -> None:
        panel = self._tabs.widget(idx)
        if panel is None:
            return
        if panel._worker:
            panel._worker.cancel()
        self._tabs.removeTab(idx)
        panel.deleteLater()
        if self._tabs.count() == 0:
            self._center.setCurrentWidget(self._empty)

    def _refresh_tables(self):
        if self._connected:
            self._tables_panel.refresh()

    def _open_console_sql(self, sql):
        self._console._editor.setPlainText(sql)
        self._toggle_console(force_open=True)
        self._console._editor.setFocus()

    def _toggle_console(self, force_open=None):
        want = force_open if force_open is not None \
            else self._btn_console.isChecked()
        self._btn_console.setChecked(want)
        self._anim.stop()
        self._anim.setStartValue(self._console.maximumHeight())
        self._anim.setEndValue(300 if want else 0)
        self._anim.start()
        if not want:
            self._console._editor.clearFocus()

    def _track(self, w):
        self._workers.append(w)
        self._busy.start()
        w.finished.connect(lambda: self._untrack(w))

    def _untrack(self, w):
        if w in self._workers:
            self._workers.remove(w)
        self._busy.stop()

    def shutdown(self):
        self._closing = True
        self._tables_panel.cancel()
        for w in self._workers:
            w.cancel()
        self._workers.clear()
        for i in range(self._tabs.count()):
            panel = self._tabs.widget(i)
            if panel and panel._worker:
                panel._worker.cancel()
        if self._console._worker:
            self._console._worker.cancel()

    def closeEvent(self, e):
        self.shutdown()
        super().closeEvent(e)


class PostgresToolWindow(QMainWindow):  # Окно-обёртка над PostgresToolWidget (контракт интеграции).

    def __init__(self, host, port, user, passwords, database=None, parent=None):
        super().__init__(parent)
        self._widget = PostgresToolWidget(host=host, port=port, user=user,
                                          passwords=passwords,
                                          database=database, parent=self)
        self.setCentralWidget(self._widget)
        self.setWindowTitle('PostgreSQL клиент')
        self.resize(1120, 700)

    @property
    def widget(self):
        return self._widget

    def closeEvent(self, e):
        self._widget.shutdown()
        super().closeEvent(e)
