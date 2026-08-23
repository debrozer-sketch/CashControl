"""CashControl DB viewer: data_grid."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QGuiApplication,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMenu,
    QTableWidget,
    QTableWidgetItem,
)

from cashcontrol.gui.db_viewer.formatting import (
    _EDITABLE,
    _c,
    _fmt,
    _kind,
    _mono,
    _parse_value,
    _qtable,
)


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

