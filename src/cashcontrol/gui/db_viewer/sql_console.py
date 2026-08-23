"""CashControl DB viewer: sql_console."""
from __future__ import annotations

import csv
import json
import re
import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QSyntaxHighlighter,
    QTextCharFormat,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QMenu,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    PushButton,
    ToolButton,
)

from cashcontrol.gui.db_viewer.constants import _HISTORY_LIMIT, _MAX_CONSOLE_ROWS
from cashcontrol.gui.db_viewer.data_grid import _DataGrid
from cashcontrol.gui.db_viewer.formatting import _c, _mono
from cashcontrol.gui.db_viewer.sql import _csv_cell, _json_value
from cashcontrol.gui.db_viewer.storage import _DbError, _icon, _load_json, _save_json, _toast
from cashcontrol.gui.db_viewer.workers import _Worker

_SQL_KEYWORDS = ['SELECT', 'FROM', 'WHERE', 'GROUP', 'BY', 'ORDER', 'HAVING', 'LIMIT', 'OFFSET', 'JOIN', 'LEFT', 'RIGHT', 'INNER', 'OUTER', 'FULL', 'CROSS', 'ON', 'AND', 'OR', 'NOT', 'NULL', 'AS', 'DISTINCT', 'INSERT', 'INTO', 'VALUES', 'UPDATE', 'SET', 'DELETE', 'CREATE', 'TABLE', 'INDEX', 'VIEW', 'DROP', 'ALTER', 'BEGIN', 'COMMIT', 'ROLLBACK', 'TRANSACTION', 'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'UNION', 'ALL', 'EXISTS', 'IN', 'LIKE', 'ILIKE', 'BETWEEN', 'IS', 'TRUE', 'FALSE', 'CAST', 'RETURNING', 'WITH', 'RECURSIVE', 'ASC', 'DESC', 'PRIMARY', 'KEY', 'FOREIGN', 'REFERENCES', 'UNIQUE', 'CHECK', 'DEFAULT', 'USING', 'INTERSECT', 'EXCEPT', 'OVER', 'PARTITION', 'FILTER']
_SQL_TYPES = ['INT', 'INTEGER', 'BIGINT', 'SMALLINT', 'SERIAL', 'TEXT', 'VARCHAR', 'CHAR', 'BOOLEAN', 'BOOL', 'NUMERIC', 'DECIMAL', 'REAL', 'DOUBLE', 'FLOAT', 'DATE', 'TIME', 'TIMESTAMP', 'UUID', 'JSON', 'JSONB', 'BYTEA', 'MONEY', 'INET', 'INTERVAL']
_SQL_FUNCS = ['COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'COALESCE', 'NULLIF', 'NOW', 'CURRENT_DATE', 'CURRENT_TIMESTAMP', 'UPPER', 'LOWER', 'LENGTH', 'SUBSTRING', 'TRIM', 'ROUND', 'ABS', 'GREATEST', 'LEAST', 'ARRAY_AGG', 'STRING_AGG', 'GENERATE_SERIES', 'TO_CHAR', 'TO_DATE', 'TO_TIMESTAMP', 'EXTRACT']


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

