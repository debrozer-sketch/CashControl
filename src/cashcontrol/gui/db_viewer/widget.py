"""CashControl DB viewer: widget."""
from __future__ import annotations

import re

from PySide6.QtCore import QPropertyAnimation, Qt, QTimer
from PySide6.QtGui import (
    QKeySequence,
    QShortcut,
)
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    ToolButton,
)

from cashcontrol.gui.db_viewer.data_panel import _DataPanel
from cashcontrol.gui.db_viewer.sql import _SQL_COMPLETION, _SQL_DATABASES
from cashcontrol.gui.db_viewer.sql_console import _SqlConsole
from cashcontrol.gui.db_viewer.storage import _Busy, _icon, _toast
from cashcontrol.gui.db_viewer.tables_panel import _TablesPanel
from cashcontrol.gui.db_viewer.workers import _ConnFactory, _Worker


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
