"""
db_viewer_widget.py — встроенный PostgreSQL редактор CashControl.

Открывается как отдельное окно когда пользователь нажимает «PostgreSQL клиент»,
и путь к внешнему клиенту не задан.
"""

from __future__ import annotations

import contextlib
import csv
import json
from typing import Any

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cashcontrol.gui.db_viewer_components import (
    _C,
    _PSYCOPG2_OK,
    _build_style,
    CellChange,
    logger,
    pgsql,
    psycopg2,
    QueryWorker,
    SQLCodeEditor,
    SQLCompleter,
    SQLHighlighter,
)
from cashcontrol.gui.notification_manager import get_notification_manager
from cashcontrol.infrastructure.audit_logger import audit_log


# ── Table data widget ─────────────────────────────────────────────────────────


class DataTableWidget(QWidget):
    """Виджет просмотра и редактирования таблицы."""

    status_message = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.table_name  = ""
        self.schema_name = "public"
        self.columns: list[str] = []
        self.primary_keys: list[str] = []
        self.changes: dict[tuple, CellChange] = {}
        self.current_offset = 0
        self.current_limit  = 0  # 0 = все
        self.total_rows = 0
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        tb = QHBoxLayout()
        tb.setSpacing(6)

        tb.addWidget(QLabel("Поиск:"))

        self.search_column = QComboBox()
        self.search_column.setMinimumWidth(130)
        self.search_column.setToolTip("Колонка для поиска")
        tb.addWidget(self.search_column)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Введите текст…")
        self.search_input.setClearButtonEnabled(True)
        self.search_input.setMinimumWidth(160)
        self.search_input.setMaximumWidth(240)
        self.search_input.setToolTip("Текст для поиска (Enter — выполнить)")
        self.search_input.returnPressed.connect(self._on_search)
        tb.addWidget(self.search_input)

        self.search_mode = QComboBox()
        self.search_mode.addItems(["Локально", "На сервере"])
        self.search_mode.setMinimumWidth(110)
        self.search_mode.setToolTip(
            "Локально — скрывает несовпадающие строки в таблице\n"
            "На сервере — новый запрос с WHERE ILIKE")
        tb.addWidget(self.search_mode)

        btn_search = QPushButton("Найти")
        btn_search.setToolTip("Выполнить поиск (Enter)")
        btn_search.setMinimumWidth(70)
        btn_search.clicked.connect(self._on_search)
        tb.addWidget(btn_search)

        btn_reset = QPushButton("Сбросить")
        btn_reset.setObjectName("flat")
        btn_reset.setToolTip("Сбросить фильтр и перезагрузить таблицу")
        btn_reset.setMinimumWidth(80)
        btn_reset.clicked.connect(self._on_reset_filter)
        tb.addWidget(btn_reset)

        tb.addStretch()

        tb.addWidget(QLabel("Лимит:"))
        self.limit_combo = QComboBox()
        self.limit_combo.addItems(["Все", "100", "500", "1000", "Последние 100"])
        self.limit_combo.setMinimumWidth(120)
        self.limit_combo.setToolTip(
            "Все — загрузить все строки\n"
            "Последние 100 — последние по ctid")
        self.limit_combo.currentTextChanged.connect(self._on_limit_changed)
        tb.addWidget(self.limit_combo)

        layout.addLayout(tb)

        self.table = QTableWidget()
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSortingEnabled(True)
        self.table.horizontalHeader().setSectionsMovable(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self.table.verticalHeader().setDefaultSectionSize(24)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.cellChanged.connect(self._on_cell_changed)
        layout.addWidget(self.table, 1)

        bb = QHBoxLayout()
        bb.setSpacing(6)

        self.btn_prev = QPushButton("◀ Назад")
        self.btn_prev.setObjectName("flat")
        self.btn_prev.setToolTip("Предыдущая страница")
        self.btn_prev.setMinimumWidth(80)
        self.btn_prev.clicked.connect(self._prev_page)
        self.btn_prev.setEnabled(False)
        bb.addWidget(self.btn_prev)

        self.page_label = QLabel("—")
        self.page_label.setStyleSheet(f"color: {_C.TEXT_MUTE}; font-size: 12px;")
        bb.addWidget(self.page_label)

        self.btn_next = QPushButton("Далее ▶")
        self.btn_next.setObjectName("flat")
        self.btn_next.setToolTip("Следующая страница")
        self.btn_next.setMinimumWidth(80)
        self.btn_next.clicked.connect(self._next_page)
        self.btn_next.setEnabled(False)
        bb.addWidget(self.btn_next)

        bb.addStretch()

        self.row_count_label = QLabel("")
        self.row_count_label.setStyleSheet(f"color: {_C.TEXT_MUTE}; font-size: 12px;")
        bb.addWidget(self.row_count_label)

        self.btn_delete = QPushButton("Удалить строки")
        self.btn_delete.setObjectName("danger")
        self.btn_delete.setToolTip("Удалить выделенные строки из таблицы (с подтверждением)")
        self.btn_delete.setMinimumWidth(130)
        self.btn_delete.clicked.connect(self._delete_selected)
        bb.addWidget(self.btn_delete)

        self.btn_cancel = QPushButton("Отмена правок")
        self.btn_cancel.setObjectName("flat")
        self.btn_cancel.setToolTip("Отменить несохранённые изменения ячеек")
        self.btn_cancel.setMinimumWidth(120)
        self.btn_cancel.clicked.connect(self._cancel_changes)
        self.btn_cancel.setEnabled(False)
        bb.addWidget(self.btn_cancel)

        self.btn_save = QPushButton("Сохранить изменения")
        self.btn_save.setToolTip("Применить изменения ячеек в базе данных (UPDATE)")
        self.btn_save.setMinimumWidth(160)
        self.btn_save.clicked.connect(self._save_changes)
        self.btn_save.setEnabled(False)
        bb.addWidget(self.btn_save)

        layout.addLayout(bb)

    @staticmethod
    def _reset_item_bg(item: QTableWidgetItem) -> None:
        if item is not None:
            item.setData(Qt.ItemDataRole.BackgroundRole, None)

    def load_data(self, rows: list[tuple], columns: list[str], total: int | None = None) -> None:
        self.table.setSortingEnabled(False)
        self.table.blockSignals(True)
        self.columns  = columns
        self.total_rows = total or len(rows)
        self.changes.clear()

        self.search_column.clear()
        self.search_column.addItem("Все колонки")
        self.search_column.addItems(columns)

        self.table.setRowCount(len(rows))
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(columns)

        for ri, row in enumerate(rows):
            for ci, val in enumerate(row):
                item = QTableWidgetItem("" if val is None else str(val))
                item.setData(Qt.ItemDataRole.UserRole, val)
                self.table.setItem(ri, ci, item)

        self._fit_columns()
        self._update_pagination()
        self.table.blockSignals(False)
        self.table.setSortingEnabled(True)
        self._update_buttons()
        self.row_count_label.setText(f"{len(rows)} строк")

    def _fit_columns(self) -> None:
        if not self.columns:
            return
        avail = max(600, self.table.viewport().width() - 20)
        w = max(80, avail // len(self.columns))
        for i in range(len(self.columns)):
            self.table.setColumnWidth(i, w)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        if self.columns and not self.changes:
            self._fit_columns()

    def _on_cell_changed(self, row: int, col: int) -> None:
        item = self.table.item(row, col)
        if not item:
            return
        old_val = item.data(Qt.ItemDataRole.UserRole)
        new_val = item.text()
        old_str = "" if old_val is None else str(old_val)
        if new_val == old_str:
            self.changes.pop((row, col), None)
            self._reset_item_bg(item)
            self._update_buttons()
            return

        pk = self._get_row_pk(row)
        if not pk and self.primary_keys:
            self.status_message.emit("⚠  Невозможно определить первичный ключ")
            return

        self.table.setSortingEnabled(False)

        self.changes[(row, col)] = CellChange(
            row=row, column=col, column_name=self.columns[col],
            old_value=old_val, new_value=new_val, primary_key=pk,
        )
        item.setBackground(QColor(_C.MODIFIED))
        self._update_buttons()

    def _get_row_pk(self, row: int) -> dict[str, Any]:
        pk: dict[str, Any] = {}
        for pk_col in self.primary_keys:
            if pk_col in self.columns:
                idx  = self.columns.index(pk_col)
                item = self.table.item(row, idx)
                if item:
                    pk[pk_col] = item.data(Qt.ItemDataRole.UserRole)
        return pk

    def _update_buttons(self) -> None:
        has = bool(self.changes)
        self.btn_save.setEnabled(has)
        self.btn_cancel.setEnabled(has)
        if not has:
            self.table.setSortingEnabled(True)

    def _update_pagination(self) -> None:
        lim = self.current_limit
        if lim == 0:
            self.page_label.setText(f"Всего: {self.total_rows}")
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
            return
        if lim < 0:
            self.page_label.setText(f"Последние {abs(lim)} (всего: {self.total_rows})")
            self.btn_prev.setEnabled(False)
            self.btn_next.setEnabled(False)
            return
        page  = (self.current_offset // lim) + 1
        pages = max(1, (self.total_rows + lim - 1) // lim)
        self.page_label.setText(f"{page}/{pages} ({self.total_rows})")
        self.btn_prev.setEnabled(self.current_offset > 0)
        self.btn_next.setEnabled(self.current_offset + lim < self.total_rows)

    def _prev_page(self) -> None:
        if self.current_limit <= 0:
            return
        self.current_offset = max(0, self.current_offset - self.current_limit)
        self.status_message.emit(f"offset:{self.current_offset}")

    def _next_page(self) -> None:
        if self.current_limit <= 0:
            return
        self.current_offset += self.current_limit
        self.status_message.emit(f"offset:{self.current_offset}")

    def _on_limit_changed(self, text: str) -> None:
        if text == "Все":
            self.current_limit = 0
        elif text == "Последние 100":
            self.current_limit = -100
        else:
            try:
                self.current_limit = int(text)
            except ValueError:
                self.current_limit = 0
        self.current_offset = 0
        self.status_message.emit("reload")

    def _on_search(self) -> None:
        q = self.search_input.text().strip()
        if not q:
            return
        col = self.search_column.currentText()
        if self.search_mode.currentText() == "Локально":
            self._local_search(q, col)
        else:
            self.status_message.emit(f"search:{col}:{q}")

    def _local_search(self, q: str, col: str) -> None:
        ql = q.lower()
        for ri in range(self.table.rowCount()):
            match = False
            if col == "Все колонки":
                for ci in range(self.table.columnCount()):
                    it = self.table.item(ri, ci)
                    if it and ql in it.text().lower():
                        match = True
                        break
            else:
                ci = self.columns.index(col) if col in self.columns else -1
                if ci >= 0:
                    it = self.table.item(ri, ci)
                    match = bool(it and ql in it.text().lower())
            self.table.setRowHidden(ri, not match)

    def _on_reset_filter(self) -> None:
        self.search_input.clear()
        for ri in range(self.table.rowCount()):
            self.table.setRowHidden(ri, False)
        self.status_message.emit("reload")

    def _save_changes(self) -> None:
        if self.changes:
            self.status_message.emit(f"save:{json.dumps(self._changes_payload())}")

    def _changes_payload(self) -> list[dict]:
        grouped: dict[tuple, dict] = {}
        for change in self.changes.values():
            key = tuple(sorted(change.primary_key.items()))
            if key not in grouped:
                grouped[key] = {"primary_key": change.primary_key, "updates": {}}
            grouped[key]["updates"][change.column_name] = change.new_value
        return list(grouped.values())

    def clear_changes(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.blockSignals(True)
        for (row, col) in self.changes:
            it = self.table.item(row, col)
            if it:
                self._reset_item_bg(it)
                it.setData(Qt.ItemDataRole.UserRole, it.text())
        self.changes.clear()
        self.table.blockSignals(False)
        self.table.setSortingEnabled(True)
        self._update_buttons()

    def _cancel_changes(self) -> None:
        self.table.setSortingEnabled(False)
        self.table.blockSignals(True)
        for (row, col), change in self.changes.items():
            it = self.table.item(row, col)
            if it:
                it.setText("" if change.old_value is None else str(change.old_value))
                self._reset_item_bg(it)
        self.changes.clear()
        self.table.blockSignals(False)
        self.table.setSortingEnabled(True)
        self._update_buttons()

    def _delete_selected(self) -> None:
        rows = {it.row() for it in self.table.selectedItems()}
        if not rows:
            QMessageBox.information(self, "Удаление", "Выберите строки")
            return
        pks = [pk for r in rows if (pk := self._get_row_pk(r))]
        if not pks:
            QMessageBox.warning(self, "Ошибка", "Невозможно определить первичный ключ")
            return

        reply = QMessageBox.warning(
            self, "Подтверждение удаления",
            f"Удалить {len(pks)} строк из таблицы «{self.table_name}»?\nОтменить нельзя.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.status_message.emit(f"delete:{json.dumps(pks)}")

    def _show_context_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction("📄 Экспорт CSV").triggered.connect(self._export_csv)
        menu.addAction("📋 Экспорт JSON").triggered.connect(self._export_json)
        menu.addSeparator()
        menu.addAction("📥 Импорт CSV").triggered.connect(
            lambda: self.status_message.emit("import_csv"))
        menu.exec(self.table.mapToGlobal(pos))

    def _export_csv(self) -> None:
        fn, _ = QFileDialog.getSaveFileName(
            self, "Экспорт CSV", f"{self.table_name}.csv", "CSV (*.csv)")
        if not fn:
            return
        try:
            with open(fn, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(self.columns)
                for ri in range(self.table.rowCount()):
                    w.writerow([
                        (self.table.item(ri, ci).text()
                         if self.table.item(ri, ci) else "")
                        for ci in range(self.table.columnCount())
                    ])
            self.status_message.emit(f"✅ Экспорт: {fn}")
            logger.info(f"[DB] CSV export: {fn} ({self.table_name})")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

    def _export_json(self) -> None:
        fn, _ = QFileDialog.getSaveFileName(
            self, "Экспорт JSON", f"{self.table_name}.json", "JSON (*.json)")
        if not fn:
            return
        try:
            data = []
            for ri in range(self.table.rowCount()):
                row = {}
                for ci, col in enumerate(self.columns):
                    it = self.table.item(ri, ci)
                    row[col] = it.text() if it else None
                data.append(row)
            with open(fn, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.status_message.emit(f"✅ Экспорт: {fn}")
            logger.info(f"[DB] JSON export: {fn} ({self.table_name})")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))


# ── SQL console ───────────────────────────────────────────────────────────────


class SQLConsoleWidget(QWidget):
    execute_query = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(6)

        tb = QHBoxLayout()
        tb.addWidget(QLabel("История:"))
        self.history_combo = QComboBox()
        self.history_combo.setMinimumWidth(260)
        self.history_combo.currentTextChanged.connect(
            lambda t: self.editor.setPlainText(t) if t else None)
        tb.addWidget(self.history_combo)
        tb.addStretch()

        self.btn_run = QPushButton("▶ Выполнить  F5")
        self.btn_run.setShortcut(QKeySequence(Qt.Key.Key_F5))
        self.btn_run.clicked.connect(self._execute)
        tb.addWidget(self.btn_run)

        btn_clear = QPushButton("Очистить")
        btn_clear.setObjectName("flat")
        btn_clear.setToolTip("Очистить результаты запроса")
        btn_clear.setMinimumWidth(80)
        btn_clear.clicked.connect(self._clear)
        tb.addWidget(btn_clear)
        layout.addLayout(tb)

        splitter = QSplitter(Qt.Orientation.Vertical)

        self.editor = SQLCodeEditor()
        self.completer = SQLCompleter(self)
        self.editor.set_completer(self.completer)
        self.editor.setPlaceholderText("Введите SQL… (Ctrl+Enter — выполнить)")
        self.editor.setFont(QFont("Consolas", 11))
        self.editor.setMaximumHeight(160)
        self._hl = SQLHighlighter(self.editor.document())
        self.editor.installEventFilter(self)
        splitter.addWidget(self.editor)

        result_w = QWidget()
        rl = QVBoxLayout(result_w)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(2)

        self.result_label = QLabel("Результат:")
        self.result_label.setStyleSheet(f"color: {_C.TEXT_MUTE}; font-size: 12px;")
        rl.addWidget(self.result_label)

        self.result_table = QTableWidget()
        self.result_table.setAlternatingRowColors(True)
        self.result_table.setSortingEnabled(True)
        self.result_table.horizontalHeader().setStretchLastSection(True)
        self.result_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive)
        rl.addWidget(self.result_table, 1)

        self.error_label = QLabel()
        self.error_label.setStyleSheet(
            f"background:{_C.ERROR_BG}; color:{_C.DANGER}; "
            f"padding: 8px; border-radius: 4px; font-size: 12px;")
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        rl.addWidget(self.error_label)

        splitter.addWidget(result_w)
        splitter.setSizes([130, 300])
        layout.addWidget(splitter, 1)

    def eventFilter(self, obj, e) -> bool:
        if obj is self.editor and e.type() == QEvent.Type.KeyPress:
            ctrl = Qt.KeyboardModifier.ControlModifier
            if e.modifiers() == ctrl and e.key() == Qt.Key.Key_Return:
                self._execute()
                return True
        return super().eventFilter(obj, e)

    def _execute(self) -> None:
        q = self.editor.toPlainText().strip()
        if q:
            self.error_label.hide()
            self.execute_query.emit(q)

    def _clear(self) -> None:
        self.result_table.clear()
        self.result_table.setRowCount(0)
        self.result_table.setColumnCount(0)
        self.error_label.hide()
        self.result_label.setText("Результат:")

    def show_results(self, rows: list[tuple], cols: list[str], elapsed: float) -> None:
        self.result_table.setSortingEnabled(False)
        self.error_label.hide()
        self.result_label.setText(f"✅ {len(rows)} строк  |  {elapsed:.3f} с")
        self.result_table.setRowCount(len(rows))
        self.result_table.setColumnCount(len(cols))
        self.result_table.setHorizontalHeaderLabels(cols)
        for ri, row in enumerate(rows):
            for ci, val in enumerate(row):
                self.result_table.setItem(ri, ci,
                    QTableWidgetItem("" if val is None else str(val)))
        self.result_table.setSortingEnabled(True)

    def show_status(self, rowcount: int, elapsed: float) -> None:
        self.error_label.hide()
        self.result_table.clear()
        self.result_table.setRowCount(0)
        self.result_label.setText(f"✅ Затронуто строк: {rowcount}  |  {elapsed:.3f} с")

    def show_error(self, msg: str) -> None:
        self.error_label.setText(f"❌  {msg}")
        self.error_label.show()
        self.result_label.setText("Ошибка")

    def update_history(self, history: list[str]) -> None:
        self.history_combo.clear()
        self.history_combo.addItem("")
        for q in reversed(history):
            self.history_combo.addItem(q)


# ── Import CSV dialog ─────────────────────────────────────────────────────────


class ImportCSVDialog(QDialog):
    def __init__(self, columns: list[str], parent=None) -> None:
        super().__init__(parent)
        self.columns = columns
        self.csv_data: list[list[str]] = []
        self.csv_headers: list[str] = []
        self._combos: dict[str, QComboBox] = {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setWindowTitle("Импорт CSV")
        self.setMinimumSize(500, 400)
        layout = QVBoxLayout(self)

        fl = QHBoxLayout()
        self.file_edit = QLineEdit()
        self.file_edit.setReadOnly(True)
        fl.addWidget(self.file_edit)
        btn = QPushButton("Обзор…")
        btn.clicked.connect(self._browse)
        fl.addWidget(btn)
        layout.addLayout(fl)

        self.preview = QTableWidget()
        self.preview.setMaximumHeight(110)
        layout.addWidget(self.preview)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(scroll.Shape.NoFrame)
        map_w = QWidget()
        self._map_layout = QFormLayout(map_w)
        scroll.setWidget(map_w)
        layout.addWidget(scroll, 1)

        self._ok_btn = QPushButton("Импортировать")
        self._ok_btn.setEnabled(False)
        self._ok_btn.clicked.connect(self.accept)
        layout.addWidget(self._ok_btn)

    def _browse(self) -> None:
        fn, _ = QFileDialog.getOpenFileName(
            self, "Выберите CSV", "", "CSV (*.csv);;All files (*)")
        if not fn:
            return
        self.file_edit.setText(fn)
        self._show_preview(fn)

    def _show_preview(self, path: str) -> None:
        try:
            with open(path, encoding="utf-8") as f:
                reader = csv.reader(f)
                rows = list(reader)
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))
            return
        if not rows:
            return
        self.csv_headers = rows[0]
        self.csv_data = rows[1:]
        self.preview.setRowCount(min(5, len(self.csv_data)))
        self.preview.setColumnCount(len(self.csv_headers))
        self.preview.setHorizontalHeaderLabels(self.csv_headers)
        for ri, row in enumerate(self.csv_data[:5]):
            for ci, val in enumerate(row):
                self.preview.setItem(ri, ci, QTableWidgetItem(val))
        self._create_mapping()

    def _create_mapping(self) -> None:
        while self._map_layout.count():
            item = self._map_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._combos.clear()
        if not self.csv_headers:
            return
        for col in self.columns:
            cmb = QComboBox()
            cmb.addItem("—")
            cmb.addItems(self.csv_headers)
            if col in self.csv_headers:
                cmb.setCurrentText(col)
            self._combos[col] = cmb
            self._map_layout.addRow(QLabel(f"{col}:"), cmb)
        self._ok_btn.setEnabled(True)

    def get_mapping(self) -> dict[str, str]:
        return {col: cb.currentText()
                for col, cb in self._combos.items()
                if cb.currentText() != "—"}

    def get_data(self) -> list[list[str]]:
        return self.csv_data


# ── Main tool widget ──────────────────────────────────────────────────────────


class PostgresToolWidget(QWidget):
    """
    Основной виджет DB Viewer.
    Используется внутри PostgresToolWindow.
    """
    connection_changed = Signal(bool)
    status_changed     = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.connection_params: dict | None = None
        self.current_database:  str | None  = None
        self._workers: list[QueryWorker] = []  # track all active workers
        self._query_history: list[str] = []
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.setStyleSheet(_build_style())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(2)

        hdr = QLabel("🗄  Базы данных")
        hdr.setStyleSheet(
            f"font-weight: 700; font-size: 13px; "
            f"color: {_C.PRIMARY}; padding: 6px 4px 4px 4px;")
        ll.addWidget(hdr)

        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.itemExpanded.connect(self._on_item_expanded)
        self.tree.itemDoubleClicked.connect(self._on_item_dbl)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._tree_ctx_menu)
        ll.addWidget(self.tree, 1)
        splitter.addWidget(left)

        self.tabs = QTabWidget()
        self.tabs.setTabsClosable(True)
        self.tabs.setMovable(True)
        self.tabs.tabCloseRequested.connect(self._close_tab)

        self.console = SQLConsoleWidget()
        self.console.execute_query.connect(self._execute_console)
        self.tabs.addTab(self.console, "📝 SQL")
        self.tabs.tabBar().setTabButton(
            0, self.tabs.tabBar().ButtonPosition.RightSide, None)
        splitter.addWidget(self.tabs)
        splitter.setSizes([220, 700])

        layout.addWidget(splitter, 1)

        sb = QFrame()
        sb.setFrameShape(QFrame.Shape.StyledPanel)
        sb.setFixedHeight(26)
        sb.setStyleSheet(f"""
            QFrame {{ background: {_C.PRIMARY}; border-radius: 3px; }}
            QLabel {{ color: white; padding: 2px 8px;
                      background: transparent; font-size: 12px; }}
        """)
        sbl = QHBoxLayout(sb)
        sbl.setContentsMargins(4, 0, 4, 0)
        self.status_label = QLabel("Нет подключения")
        sbl.addWidget(self.status_label)
        sbl.addStretch()
        layout.addWidget(sb)

    def _track_worker(self, w: QueryWorker) -> None:
        w.finished.connect(lambda *_: self._drop_worker(w))
        w.error.connect(lambda *_: self._drop_worker(w))
        self._workers.append(w)

    def _drop_worker(self, w: QueryWorker) -> None:
        if w in self._workers:
            self._workers.remove(w)
        with contextlib.suppress(Exception):
            w.deleteLater()

    def set_connection(self, host: str, port: int = 5432,
                       user: str = "postgres",
                       password: str | list = "",
                       database: str | None = None) -> None:
        if not _PSYCOPG2_OK:
            get_notification_manager().notify(
                "DB Viewer: отсутствует psycopg2: Выполните: pip install psycopg2-binary",
                level="error",
            )
            self._set_status("❌ psycopg2 не установлен")
            logger.error("[DB] psycopg2 not installed — run: pip install psycopg2-binary")
            return
        passwords = password if isinstance(password, list) else [password]
        last_err  = None
        for pwd in passwords:
            params = dict(host=host, port=port, user=user,
                          password=pwd, database=database or "postgres")
            try:
                conn = psycopg2.connect(**params, connect_timeout=3)
                conn.close()
                self.connection_params = params
                self.current_database  = database
                self._load_databases()
                self._load_autocomplete()
                self.connection_changed.emit(True)
                self._set_status(f"✅ {user}@{host}:{port}")
                audit_log(action_type="tool", action_name="db_connect",
                          target=host, result="success")
                logger.info(f"[DB] Connected to {host}:{port} as {user}")
                return
            except Exception as e:
                last_err = e
        self._set_status("❌ Ошибка авторизации")
        audit_log(action_type="tool", action_name="db_connect",
                  target=host, result="failure",
                  error_message=str(last_err))
        logger.error(f"[DB] Connection failed to {host}: {last_err}")
        err_short = str(last_err).split("\n")[0][:120]
        get_notification_manager().notify(f"БД: не удалось подключиться к {host}: {err_short}", level="error")
        self.connection_changed.emit(False)

    def _load_databases(self) -> None:
        if not self.connection_params:
            return
        params = {**self.connection_params, "database": "postgres"}
        self._busy(True)
        w = QueryWorker(params, "SELECT datname FROM pg_database "
                        "WHERE datistemplate=false ORDER BY datname")
        w.finished.connect(self._on_dbs_loaded)
        w.error.connect(self._on_error)
        self._track_worker(w)
        w.start()

    def _on_dbs_loaded(self, rows, cols, _elapsed) -> None:
        self._busy(False)
        self.tree.clear()
        for (db_name,) in rows:
            item = QTreeWidgetItem(self.tree)
            item.setText(0, f"🗄  {db_name}")
            item.setData(0, Qt.ItemDataRole.UserRole, {"type": "database", "name": db_name})
            QTreeWidgetItem(item).setText(0, "⏳")
        self._set_status(
            f"✅ {self.connection_params['user']}@{self.connection_params['host']}"
            f"  |  {len(rows)} БД")

    def _on_item_expanded(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        if item.childCount() == 1 and "⏳" in item.child(0).text(0):
            item.removeChild(item.child(0))
            if data["type"] == "database":
                self._load_schemas(item, data["name"])
            elif data["type"] == "schema":
                self._load_tables(item, data["database"], data["name"])

    def _load_schemas(self, parent: QTreeWidgetItem, db: str) -> None:
        params = {**self.connection_params, "database": db}
        self._busy(True)
        w = QueryWorker(params, """
            SELECT schema_name FROM information_schema.schemata
            WHERE schema_name NOT IN ('information_schema','pg_catalog','pg_toast')
            AND schema_name NOT LIKE 'pg_temp_%'
            AND schema_name NOT LIKE 'pg_toast_temp_%'
            ORDER BY schema_name""")
        w.finished.connect(
            lambda rows, c, t: self._on_schemas(parent, db, rows))
        w.error.connect(self._on_error)
        self._track_worker(w)
        w.start()

    def _on_schemas(self, parent: QTreeWidgetItem, db: str, rows) -> None:
        self._busy(False)
        for (schema,) in rows:
            item = QTreeWidgetItem(parent)
            item.setText(0, f"📁 {schema}")
            item.setData(0, Qt.ItemDataRole.UserRole,
                         {"type": "schema", "name": schema, "database": db})
            QTreeWidgetItem(item).setText(0, "⏳")

    def _load_tables(self, parent: QTreeWidgetItem, db: str, schema: str) -> None:
        params = {**self.connection_params, "database": db}
        self._busy(True)
        w = QueryWorker(params,
            "SELECT table_name, table_type FROM information_schema.tables "
            "WHERE table_schema=%s ORDER BY table_type, table_name", (schema,))
        w.finished.connect(
            lambda rows, c, t: self._on_tables(parent, db, schema, rows))
        w.error.connect(self._on_error)
        self._track_worker(w)
        w.start()

    def _on_tables(self, parent: QTreeWidgetItem, db: str, schema: str, rows) -> None:
        self._busy(False)
        for tbl, ttype in rows:
            is_view = ttype == "VIEW"
            item = QTreeWidgetItem(parent)
            item.setText(0, f"{'👁' if is_view else '📋'} {tbl}")
            item.setData(0, Qt.ItemDataRole.UserRole,
                         {"type": "view" if is_view else "table",
                          "name": tbl, "schema": schema, "database": db})

    def _on_item_dbl(self, item: QTreeWidgetItem, _col: int) -> None:
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data and data["type"] in ("table", "view"):
            self._open_table(data["database"], data["schema"], data["name"])

    def _tree_ctx_menu(self, pos) -> None:
        item = self.tree.itemAt(pos)
        if not item:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if not data:
            return
        menu = QMenu(self)
        if data["type"] == "database":
            menu.addAction("🔄 Обновить").triggered.connect(
                lambda: self._refresh_db_item(item, data["name"]))
            menu.addAction("✅ Использовать").triggered.connect(
                lambda: self._use_db(data["name"]))
        elif data["type"] in ("table", "view"):
            menu.addAction("📋 Открыть").triggered.connect(
                lambda: self._open_table(data["database"], data["schema"], data["name"]))
        menu.exec(self.tree.mapToGlobal(pos))

    def _refresh_db_item(self, item: QTreeWidgetItem, db: str) -> None:
        while item.childCount():
            item.removeChild(item.child(0))
        QTreeWidgetItem(item).setText(0, "⏳")
        item.setExpanded(False)
        item.setExpanded(True)

    def _use_db(self, db: str) -> None:
        self.current_database = db
        self._set_status(f"📌 БД: {db}")

    def _open_table(self, db: str, schema: str, table: str) -> None:
        tab_name = f"📋 {schema}.{table}"
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i) == tab_name:
                self.tabs.setCurrentIndex(i)
                return

        widget = DataTableWidget()
        widget.table_name  = table
        widget.schema_name = schema
        widget.status_message.connect(
            lambda msg: self._handle_table_msg(widget, db, schema, table, msg))

        idx = self.tabs.addTab(widget, tab_name)
        self.tabs.setCurrentIndex(idx)
        logger.info(f"[DB] Opened table {db}/{schema}.{table}")
        audit_log(action_type="tool", action_name="db_open_table",
                  target=f"{db}/{schema}.{table}", result="success")
        self._load_pk(widget, db, schema, table)

    def _load_pk(self, widget: DataTableWidget, db: str, schema: str, table: str) -> None:
        params = {**self.connection_params, "database": db}
        w = QueryWorker(params, """
            SELECT kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name=kcu.constraint_name
                AND tc.table_schema=kcu.table_schema
            WHERE tc.constraint_type='PRIMARY KEY'
            AND tc.table_schema=%s AND tc.table_name=%s
            ORDER BY kcu.ordinal_position""", (schema, table))
        w.finished.connect(
            lambda rows, c, t: self._on_pk(widget, db, schema, table, rows))
        w.error.connect(self._on_error)
        self._track_worker(w)
        w.start()

    def _on_pk(self, widget: DataTableWidget, db: str, schema: str, table: str, rows) -> None:
        widget.primary_keys = [r[0] for r in rows]
        self._load_table_data(widget, db, schema, table)

    def _load_table_data(self, widget: DataTableWidget, db: str, schema: str, table: str,
                         offset: int = 0, where: Any = "", where_params: tuple = ()) -> None:
        params = {**self.connection_params, "database": db}
        lim = widget.current_limit
        base = pgsql.SQL("SELECT * FROM {}.{}").format(
            pgsql.Identifier(schema), pgsql.Identifier(table))

        if lim == 0:
            suffix = ""
            qp: tuple = ()
        elif lim == -100:
            suffix = "ORDER BY ctid DESC LIMIT 100"
            qp = ()
        else:
            suffix = "LIMIT %s OFFSET %s"
            qp = (lim, offset)

        where_sql = None
        if where:
            where_sql = where if isinstance(where, pgsql.Composable) else pgsql.SQL(where)

        if where_sql is not None:
            full = pgsql.SQL("{} WHERE {} {}").format(
                base, where_sql, pgsql.SQL(suffix))
            qp = where_params + qp if lim not in (0, -100) else where_params
        else:
            full = pgsql.SQL("{} {}").format(base, pgsql.SQL(suffix))

        count_q = pgsql.SQL("SELECT COUNT(*) FROM {}.{}").format(
            pgsql.Identifier(schema), pgsql.Identifier(table))

        self._busy(True)
        try:
            conn = psycopg2.connect(**params, connect_timeout=5)
            with conn.cursor() as cur:
                cur.execute(count_q.as_string(conn))
                total = cur.fetchone()[0]
                cur.execute(full.as_string(conn), qp)
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()
            conn.close()
            if lim == -100:
                rows = list(reversed(rows))
            widget.current_offset = offset
            widget.load_data(rows, cols, total)
        except Exception as e:
            self._on_error(str(e))
        finally:
            self._busy(False)

    def _handle_table_msg(self, widget: DataTableWidget,
                          db: str, schema: str, table: str, msg: str) -> None:
        if msg == "reload":
            self._load_table_data(widget, db, schema, table, widget.current_offset)
        elif msg.startswith("offset:"):
            self._load_table_data(widget, db, schema, table, int(msg[7:]))
        elif msg.startswith("search:"):
            _, col, q = msg.split(":", 2)
            if col == "Все колонки":
                conds = [
                    pgsql.SQL("{}::text ILIKE %s").format(pgsql.Identifier(c))
                    for c in widget.columns
                ]
                where_sql = pgsql.SQL(" OR ").join(conds)
                self._load_table_data(
                    widget, db, schema, table, 0,
                    where_sql,
                    tuple(f"%{q}%" for _ in widget.columns))
            else:
                where_sql = pgsql.SQL("{}::text ILIKE %s").format(
                    pgsql.Identifier(col))
                self._load_table_data(
                    widget, db, schema, table, 0,
                    where_sql, (f"%{q}%",))
        elif msg.startswith("save:"):
            self._save_changes(widget, db, schema, table,
                               json.loads(msg[5:]))
        elif msg.startswith("delete:"):
            self._delete_rows(widget, db, schema, table,
                              json.loads(msg[7:]))
        elif msg == "import_csv":
            self._import_csv(widget, db, schema, table)
        elif msg.startswith(("✅", "❌", "⚠")):
            self._set_status(msg)

    def _save_changes(self, widget: DataTableWidget, db: str, schema: str,
                      table: str, changes: list[dict]) -> None:
        params = {**self.connection_params, "database": db}
        try:
            conn = psycopg2.connect(**params, connect_timeout=5)
            for change in changes:
                pk, updates = change["primary_key"], change["updates"]
                set_parts = [pgsql.SQL("{}=%s").format(pgsql.Identifier(c))
                             for c in updates]
                where_parts = [pgsql.SQL("{}=%s").format(pgsql.Identifier(c))
                               for c in pk]
                vals = list(updates.values()) + list(pk.values())
                q = pgsql.SQL("UPDATE {}.{} SET {} WHERE {}").format(
                    pgsql.Identifier(schema), pgsql.Identifier(table),
                    pgsql.SQL(", ").join(set_parts),
                    pgsql.SQL(" AND ").join(where_parts))
                with conn.cursor() as cur:
                    cur.execute(q.as_string(conn), vals)
            conn.commit()
            conn.close()
            widget.clear_changes()
            self._set_status(f"✅ Сохранено {len(changes)} изменений")
            get_notification_manager().notify(f"Сохранено {len(changes)} изменений: {schema}.{table}", level="success")
            audit_log(action_type="edit", action_name="db_save",
                      target=f"{db}/{schema}.{table}", result="success",
                      details=f"{len(changes)} изменений")
            logger.info(f"[DB] Saved {len(changes)} changes to {schema}.{table} on {db}")
        except Exception as e:
            audit_log(action_type="edit", action_name="db_save",
                      target=f"{db}/{schema}.{table}", result="failure",
                      error_message=str(e))
            logger.error(f"[DB] Save error: {e}")
            get_notification_manager().notify(f"Ошибка сохранения: {str(e)[:120]}", level="error")
            self._on_error(str(e))

    def _delete_rows(self, widget: DataTableWidget, db: str, schema: str,
                     table: str, pk_list: list[dict]) -> None:
        params = {**self.connection_params, "database": db}
        try:
            conn = psycopg2.connect(**params, connect_timeout=5)
            deleted = 0
            for pk in pk_list:
                where_parts = [pgsql.SQL("{}=%s").format(pgsql.Identifier(c))
                               for c in pk]
                vals = list(pk.values())
                q = pgsql.SQL("DELETE FROM {}.{} WHERE {}").format(
                    pgsql.Identifier(schema), pgsql.Identifier(table),
                    pgsql.SQL(" AND ").join(where_parts))
                with conn.cursor() as cur:
                    cur.execute(q.as_string(conn), vals)
                    deleted += cur.rowcount
            conn.commit()
            conn.close()
            self._set_status(f"✅ Удалено {deleted} строк")
            get_notification_manager().notify(f"Удалено {deleted} строк: {schema}.{table}", level="success")
            audit_log(action_type="edit", action_name="db_delete",
                      target=f"{db}/{schema}.{table}", result="success",
                      details=f"Удалено {deleted} строк")
            logger.info(f"[DB] Deleted {deleted} rows from {schema}.{table} on {db}")
            self._load_table_data(widget, db, schema, table, widget.current_offset)
        except Exception as e:
            audit_log(action_type="edit", action_name="db_delete",
                      target=f"{db}/{schema}.{table}", result="failure",
                      error_message=str(e))
            logger.error(f"[DB] Delete error: {e}")
            get_notification_manager().notify(f"Ошибка удаления: {str(e)[:120]}", level="error")
            self._on_error(str(e))

    def _import_csv(self, widget: DataTableWidget, db: str, schema: str, table: str) -> None:
        dlg = ImportCSVDialog(widget.columns, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        mapping, data = dlg.get_mapping(), dlg.get_data()
        if not mapping or not data:
            return
        params = {**self.connection_params, "database": db}
        try:
            conn = psycopg2.connect(**params, connect_timeout=5)
            db_cols = list(mapping.values())
            csv_idx = [dlg.csv_headers.index(c) for c in mapping]
            q = pgsql.SQL("INSERT INTO {}.{} ({}) VALUES ({})").format(
                pgsql.Identifier(schema), pgsql.Identifier(table),
                pgsql.SQL(", ").join(pgsql.Identifier(c) for c in db_cols),
                pgsql.SQL(", ").join(pgsql.Placeholder() for _ in db_cols))
            batch = [
                [row[i] if i < len(row) else None for i in csv_idx]
                for row in data
            ]
            inserted = 0
            with conn.cursor() as cur:
                cur.executemany(q.as_string(conn), batch)
                inserted = len(batch)
            conn.commit()
            conn.close()
            self._set_status(f"✅ Импортировано {inserted} строк")
            audit_log(action_type="edit", action_name="db_import_csv",
                      target=f"{db}/{schema}.{table}", result="success",
                      details=f"{inserted} строк")
            logger.info(f"[DB] CSV import: {inserted} rows → {schema}.{table}")
            self._load_table_data(widget, db, schema, table)
        except Exception as e:
            audit_log(action_type="edit", action_name="db_import_csv",
                      target=f"{db}/{schema}.{table}", result="failure",
                      error_message=str(e))
            logger.error(f"[DB] CSV import error: {e}")
            self._on_error(str(e))

    def _execute_console(self, query: str) -> None:
        if not self.connection_params:
            self.console.show_error("Нет подключения")
            return
        query = query.strip()
        qu = query.upper()
        if ("DELETE" in qu or "UPDATE" in qu) and "WHERE" not in qu:
            r = QMessageBox.warning(self, "⚠  Внимание",
                "DELETE/UPDATE без WHERE — это изменит ВСЕ строки!",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                return
        if "DROP DATABASE" in qu or "DROP TABLE" in qu:
            r = QMessageBox.warning(self, "⚠  ОПАСНО",
                f"DROP запрос:\n\n{query[:200]}",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                return
            text, ok = QInputDialog.getText(self, "Подтверждение",
                                             "Введите  УДАЛИТЬ:")
            if not ok or text != "УДАЛИТЬ":
                return

        if query not in self._query_history:
            self._query_history.append(query)
            if len(self._query_history) > 30:
                self._query_history.pop(0)
            self.console.update_history(self._query_history)

        audit_log(action_type="query", action_name="db_sql",
                  target=self.current_database or "?",
                  result="executing",
                  details=query[:200])
        logger.info(f"[DB] SQL: {query[:120]}")

        params = {**self.connection_params}
        if self.current_database:
            params["database"] = self.current_database
        is_select = qu.startswith("SELECT") or qu.startswith("WITH")
        self._busy(True)
        w = QueryWorker(params, query, fetch=is_select)
        w.finished.connect(self._on_console_ok)
        w.error.connect(self._on_console_err)
        self._track_worker(w)
        w.start()

    def _on_console_ok(self, result, cols, elapsed) -> None:
        self._busy(False)
        if cols:
            self.console.show_results(result, cols, elapsed)
        else:
            self.console.show_status(result, elapsed)

    def _on_console_err(self, error: str) -> None:
        self._busy(False)
        self.console.show_error(error)
        logger.error(f"[DB] SQL error: {error}")

    def _load_autocomplete(self) -> None:
        if not self.connection_params:
            return
        try:
            params = {**self.connection_params, "database": "postgres"}
            conn = psycopg2.connect(**params, connect_timeout=3)
            cur  = conn.cursor()
            cur.execute("SELECT datname FROM pg_database "
                        "WHERE datistemplate=false "
                        "AND datname NOT IN ('postgres','template0','template1')")
            dbs = [r[0] for r in cur.fetchall()]
            conn.close()

            tbl_dict: dict[str, list[str]] = {}
            for db in dbs:
                try:
                    p2 = {**self.connection_params, "database": db}
                    conn2 = psycopg2.connect(**p2, connect_timeout=3)
                    c2 = conn2.cursor()
                    c2.execute("""
                        SELECT table_name, column_name
                        FROM information_schema.columns
                        WHERE table_schema='public'
                        ORDER BY table_name, ordinal_position""")
                    for tbl, col in c2.fetchall():
                        tbl_dict.setdefault(tbl, []).append(col)
                    conn2.close()
                except Exception as e:
                    logger.debug(f"[DB] Autocomplete skip db '{db}': {e}")
            self.console.completer.load_schema(tbl_dict)
        except Exception as e:
            logger.warning(f"[DB] Autocomplete load failed: {e}")

    def _close_tab(self, idx: int) -> None:
        if idx > 0:
            self.tabs.removeTab(idx)

    def _busy(self, on: bool) -> None:
        if on:
            QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        else:
            QApplication.restoreOverrideCursor()

    def _set_status(self, text: str) -> None:
        self.status_label.setText(text)
        self.status_changed.emit(text)

    def _on_error(self, error: str) -> None:
        self._busy(False)
        self._set_status(f"❌ {error[:60]}")
        logger.error(f"[DB] Error: {error}")
        QMessageBox.critical(self, "Ошибка БД", error)

    def closeEvent(self, e) -> None:
        for w in list(self._workers):
            if w.isRunning():
                w.cancel()
                w.wait(2000)
        self._workers.clear()
        e.accept()


# ── Window ──────────────────────────────────────────────────────────────────


class PostgresToolWindow(QMainWindow):
    """
    Отдельное окно DB Viewer.
    Открывается из tab_manager._on_postgres() если db_client_path не задан.
    """

    def __init__(self, host: str, port: int = 5432, user: str = "postgres",
                 passwords: list[str] | None = None, database: str | None = None,
                 parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"DB Viewer — {host}")
        self.setMinimumSize(1000, 640)
        self.resize(1200, 720)

        self.tool_widget = PostgresToolWidget(self)
        self.setCentralWidget(self.tool_widget)

        self._setup_menu()

        if host:
            QTimer.singleShot(120, lambda: self.tool_widget.set_connection(
                host=host, port=port, user=user,
                password=passwords or [""],
                database=database,
            ))

    def _setup_menu(self) -> None:
        mb = self.menuBar()
        fm = mb.addMenu("Файл")
        a = fm.addAction("🔌 Подключение…")
        a.setShortcut("Ctrl+N")
        a.triggered.connect(self._manual_connect)
        fm.addSeparator()
        fm.addAction("Выход").setShortcut("Ctrl+Q")
        fm.actions()[-1].triggered.connect(self.close)

    def _manual_connect(self) -> None:
        dlg = QDialog(self)
        dlg.setWindowTitle("Подключение")
        dlg.setMinimumWidth(380)
        form = QFormLayout(dlg)

        host_e = QLineEdit()
        host_e.setPlaceholderText("192.168.x.x")
        port_e = QLineEdit("5432")
        port_e.setMaximumWidth(80)
        user_e = QLineEdit("postgres")
        pwd_e  = QLineEdit()
        pwd_e.setEchoMode(QLineEdit.EchoMode.Password)
        db_e   = QLineEdit()
        db_e.setPlaceholderText("(не обязательно)")

        form.addRow("Хост:",     host_e)
        form.addRow("Порт:",     port_e)
        form.addRow("Логин:",    user_e)
        form.addRow("Пароль:",   pwd_e)
        form.addRow("База данных:", db_e)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(dlg.accept)
        btns.rejected.connect(dlg.reject)
        form.addRow(btns)

        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.tool_widget.set_connection(
                host=host_e.text().strip(),
                port=int(port_e.text() or 5432),
                user=user_e.text().strip() or "postgres",
                password=pwd_e.text(),
                database=db_e.text().strip() or None,
            )
