"""CashControl DB viewer: data_panel."""
from __future__ import annotations

import csv

from psycopg2 import extras as pgextras
from psycopg2 import sql as pgsql
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    ComboBox,
    PushButton,
    SearchLineEdit,
    ToolButton,
)

from cashcontrol.gui.db_viewer.constants import _PAGE_SIZES
from cashcontrol.gui.db_viewer.csv_import import _CsvImportDialog
from cashcontrol.gui.db_viewer.data_grid import _DataGrid
from cashcontrol.gui.db_viewer.formatting import _qtable
from cashcontrol.gui.db_viewer.sql import _build_where, _export_rows, _load_page
from cashcontrol.gui.db_viewer.storage import _DbError, _icon, _toast
from cashcontrol.gui.db_viewer.workers import _Worker


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
                                   self.page_size, (self._page - 1) * self.page_size,
                                   self._order, self._filter_text),
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

