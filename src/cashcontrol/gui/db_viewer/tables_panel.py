"""CashControl DB viewer: tables_panel."""
from __future__ import annotations

from typing import ClassVar

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QFont,
)
from PySide6.QtWidgets import (
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    ComboBox,
    SearchLineEdit,
)

from cashcontrol.gui.db_viewer.formatting import _qtable
from cashcontrol.gui.db_viewer.sql import _SQL_TABLES
from cashcontrol.gui.db_viewer.storage import _DbError, _icon, _toast
from cashcontrol.gui.db_viewer.workers import _Worker


class _TablesPanel(QWidget):
    openTable = Signal(str, str, str)   # database, schema, table

    _KIND_ICON: ClassVar[dict[str, str]] = {'r': 'GRID', 'p': 'GRID', 'v': 'VIEW', 'm': 'ALBUM'}

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
        name, _kind = it.data(Qt.UserRole)
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

