"""CashControl DB viewer: csv_import."""
from __future__ import annotations

import csv

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    ComboBox,
    LineEdit,
    PushButton,
)


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

