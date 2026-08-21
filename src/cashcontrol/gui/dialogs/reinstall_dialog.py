"""
reinstall_dialog.py — Диалог управления переустановкой кассового ПО.

Предоставляет:
- Просмотр доступных архивов по типу кассы (pos, sco3, touch)
- Извлечение архива из ISO-образа
- Удаление ненужных архивов
- Информацию о текущей кассе (тип, версия)

Открывается кнопкой «Переустановка» в тулбаре.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread
from PySide6.QtCore import Signal as QSignal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    CardWidget,
    FluentIcon,
    PrimaryPushButton,
    PushButton,
    SubtitleLabel,
    ToolButton,
)

from cashcontrol.core.reinstall.archive_scanner import ArchiveInfo, ArchiveScanner
from cashcontrol.core.reinstall.iso_extractor import (
    ExtractResult,
    ISOExtractor,
    parse_iso_name,
)
from cashcontrol.gui.theme_helper import color as _tc
from cashcontrol.infrastructure.audit_logger import audit_log, get_logger
from cashcontrol.infrastructure.path_resolver import (
    REINSTALL_CASH_TYPES,
    get_reinstall_dir,
)

logger = get_logger()

_TYPE_LABELS = {
    "pos": "POS (кассы)",
    "sco3": "SCO v3 (самообслуживание)",
    "touch": "Touch (тач-кассы)",
}


class _ExtractWorker(QThread):
    """Background thread for ISO extraction to keep UI responsive."""

    finished = QSignal(object)  # ExtractResult

    def __init__(self, extractor: ISOExtractor, iso_path: Path, parent=None) -> None:
        super().__init__(parent)
        self._extractor = extractor
        self._iso_path = iso_path

    def run(self) -> None:
        try:
            result = self._extractor.extract(self._iso_path)
        except Exception as e:
            result = ExtractResult(
                success=False,
                message=f"Неожиданная ошибка: {e}",
            )
        self.finished.emit(result)


class ReinstallDialog(QDialog):
    """Диалог управления архивами ПО для переустановки на кассах."""

    def __init__(
        self,
        active_cash_type: str | None = None,
        active_session=None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._scanner = ArchiveScanner()
        self._extractor = ISOExtractor()
        self._active_cash_type = active_cash_type
        self._active_session = active_session  # CashSession for installation

        self.setWindowTitle("Переустановка ПО — управление архивами")
        self.setMinimumSize(700, 500)
        self.resize(780, 560)

        self._init_ui()
        self._refresh_table()

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # ── Header ──
        header = QHBoxLayout()
        title = SubtitleLabel("📦 Архивы кассового ПО", self)
        header.addWidget(title)
        header.addStretch()

        # Открыть папку
        btn_open_folder = ToolButton(FluentIcon.FOLDER, self)
        btn_open_folder.setToolTip("Открыть папку с архивами")
        btn_open_folder.setFixedSize(32, 32)
        btn_open_folder.clicked.connect(self._open_folder)
        header.addWidget(btn_open_folder)
        root.addLayout(header)

        # ── Info card (active cash) ──
        if self._active_cash_type:
            info_card = CardWidget(self)
            info_layout = QHBoxLayout(info_card)
            info_layout.setContentsMargins(12, 8, 12, 8)
            type_label = _TYPE_LABELS.get(self._active_cash_type, self._active_cash_type)
            info_lbl = QLabel(
                f"🖥 Активная касса — тип: <b>{type_label}</b>",
                info_card,
            )
            info_lbl.setTextFormat(Qt.TextFormat.RichText)
            info_layout.addWidget(info_lbl)
            info_layout.addStretch()
            root.addWidget(info_card)

        # ── Filter by type ──
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Тип кассы:", self))
        self._type_combo = QComboBox(self)
        self._type_combo.addItem("Все типы", "all")
        for ct in REINSTALL_CASH_TYPES:
            self._type_combo.addItem(_TYPE_LABELS.get(ct, ct), ct)

        # Auto-select active cash type
        if self._active_cash_type:
            for i in range(self._type_combo.count()):
                if self._type_combo.itemData(i) == self._active_cash_type:
                    self._type_combo.setCurrentIndex(i)
                    break

        self._type_combo.currentIndexChanged.connect(self._refresh_table)
        filter_row.addWidget(self._type_combo)
        filter_row.addStretch()

        # Extract from ISO button
        self._btn_extract = PrimaryPushButton(FluentIcon.DOWNLOAD, "Извлечь из ISO", self)
        self._btn_extract.clicked.connect(self._on_extract_iso)
        filter_row.addWidget(self._btn_extract)

        root.addLayout(filter_row)

        # ── Archives table ──
        self._table = QTableWidget(self)
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels([
            "Тип", "Версия", "Размер", "Дата", "",
        ])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        self._table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 160)
        self._table.setColumnWidth(2, 90)
        self._table.setColumnWidth(3, 130)
        self._table.setColumnWidth(4, 80)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        root.addWidget(self._table, stretch=1)

        # ── Status bar ──
        self._status = QLabel("", self)
        self._status.setStyleSheet(f"color: {_tc('text_secondary')}; font-size: 11px;")
        root.addWidget(self._status)

        # ── Buttons ──
        btn_row = QHBoxLayout()

        # Install button (left side, prominent)
        self._btn_install = PrimaryPushButton(FluentIcon.PLAY, "Установить на кассу", self)
        self._btn_install.setEnabled(False)
        self._btn_install.clicked.connect(self._on_install)
        btn_row.addWidget(self._btn_install)

        btn_row.addStretch()

        btn_refresh = PushButton(FluentIcon.SYNC, "Обновить", self)
        btn_refresh.clicked.connect(self._refresh_table)
        btn_row.addWidget(btn_refresh)

        btn_close = PushButton("Закрыть", self)
        btn_close.clicked.connect(self.accept)
        btn_row.addWidget(btn_close)

        root.addLayout(btn_row)

        # Enable install button when row selected
        self._table.itemSelectionChanged.connect(self._on_selection_changed)

        # Store current archives list for index lookup
        self._current_archives: list[ArchiveInfo] = []

    def _refresh_table(self) -> None:
        """Refresh the archives table based on current filter."""
        selected_type = self._type_combo.currentData()

        if selected_type == "all":
            all_archives = self._scanner.scan_all()
            archives: list[ArchiveInfo] = []
            for ct_list in all_archives.values():
                archives.extend(ct_list)
            # Sort all by version descending
            archives.sort(key=lambda a: a.version_tuple, reverse=True)
        else:
            archives = self._scanner.scan_type(selected_type)

        self._current_archives = archives
        self._table.setRowCount(len(archives))

        # Stronger row selection highlighting
        self._table.setStyleSheet(
            f"QTableWidget::item:selected {{"
            f"  background-color: {_tc('accent')};"
            f"  color: {_tc('text_on_accent')};"
            f"}}"
        )

        for row, arch in enumerate(archives):
            # Type
            type_item = QTableWidgetItem(_TYPE_LABELS.get(arch.cash_type, arch.cash_type))
            self._table.setItem(row, 0, type_item)

            # Version
            ver_item = QTableWidgetItem(arch.display_name)
            ver_item.setFont(self._table.font())
            self._table.setItem(row, 1, ver_item)

            # Size
            size_item = QTableWidgetItem(f"{arch.size_mb} MB")
            size_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(row, 2, size_item)

            # Date
            date_str = arch.modified.strftime("%d.%m.%Y %H:%M")
            date_item = QTableWidgetItem(date_str)
            self._table.setItem(row, 3, date_item)

            # Delete button
            btn_del = QPushButton("Удалить", self._table)
            btn_del.setFixedHeight(26)
            btn_del.setToolTip("Удалить архив")
            btn_del.setStyleSheet(
                f"color: {_tc('error')}; background: transparent; border: 1px solid {_tc('error')};"
                f"border-radius: 4px; padding: 2px 8px; font-size: 11px;"
            )
            btn_del.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_del.clicked.connect(lambda _checked=False, a=arch: self._on_delete(a))
            self._table.setCellWidget(row, 4, btn_del)

        # Status
        total = len(archives)
        type_str = _TYPE_LABELS.get(selected_type, "всех типов") if selected_type != "all" else "всех типов"
        if selected_type == "all":
            self._status.setText(f"Архивов: {total}")
        else:
            self._status.setText(f"Архивов ({type_str}): {total}")

    def _on_extract_iso(self) -> None:
        """Open file dialog to select an ISO and extract the archive."""
        iso_path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите ISO-образ кассового ПО",
            "",
            "ISO образы (*.iso);;Все файлы (*.*)",
        )
        if not iso_path:
            return

        iso_file = Path(iso_path)

        # Preview what we'll extract
        info = parse_iso_name(iso_file.name)
        if info:
            type_label = _TYPE_LABELS.get(info.cash_type, info.cash_type)
            confirm = QMessageBox.question(
                self,
                "Извлечение из ISO",
                f"Файл: {iso_file.name}\n\n"
                f"Тип кассы: {type_label}\n"
                f"Версия ПО: {info.version}\n"
                f"ОС: {info.os_info}\n\n"
                f"Извлечь архив в {info.cash_type}/{iso_file.stem}.tar?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if confirm != QMessageBox.StandardButton.Yes:
                return
        else:
            QMessageBox.warning(
                self,
                "Неизвестный формат",
                f"Не удалось определить тип кассы и версию из имени файла:\n"
                f"{iso_file.name}\n\n"
                f"Ожидаемый формат: SR-ВЕРСИЯ-ТИП-ОС.iso\n"
                f"Пример: SR-10.4.24.0-pos-ubuntu22_v2.8.2.iso",
            )
            return

        # Extract with progress indicator
        self._status.setText(f"⏳ Извлечение из {iso_file.name}...")
        self._btn_extract.setEnabled(False)

        # Progress dialog — indeterminate spinner
        self._progress = QProgressDialog(
            f"Извлечение архива из ISO...\n{iso_file.name}",
            None,  # no cancel button
            0, 0,  # min=max=0 → indeterminate (spinning)
            self,
        )
        self._progress.setWindowTitle("Извлечение")
        self._progress.setWindowModality(Qt.WindowModality.WindowModal)
        self._progress.setMinimumDuration(0)
        self._progress.setAutoClose(False)
        self._progress.show()

        # Run extraction in background thread
        self._extract_worker = _ExtractWorker(self._extractor, iso_file, self)
        self._extract_worker.finished.connect(
            lambda result, name=iso_file.name: self._on_extract_finished(result, name)
        )
        self._extract_worker.start()

    def _on_extract_finished(self, result: ExtractResult, iso_name: str) -> None:
        """Called when background extraction completes."""
        # Close progress dialog
        if hasattr(self, '_progress') and self._progress:
            self._progress.close()
            self._progress = None

        self._btn_extract.setEnabled(True)

        if result.success:
            self._status.setText(f"✅ {result.message}")
            audit_log(
                action_type="reinstall",
                action_name="extract_iso",
                target=iso_name,
                result="success",
                details=f"version={result.version}, type={result.cash_type}",
            )
            QMessageBox.information(self, "Успешно", result.message)
            self._refresh_table()
        else:
            self._status.setText(f"❌ {result.message}")
            audit_log(
                action_type="reinstall",
                action_name="extract_iso",
                target=iso_name,
                result="error",
                details=result.message,
            )
            QMessageBox.warning(self, "Ошибка извлечения", result.message)

    def _on_selection_changed(self) -> None:
        """Enable/disable install button based on selection."""
        has_selection = len(self._table.selectedItems()) > 0
        has_session = self._active_session is not None
        self._btn_install.setEnabled(has_selection and has_session)

    def _on_install(self) -> None:
        """Start installation of selected archive on the active cash register."""
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            QMessageBox.warning(self, "Выберите архив", "Выделите строку с архивом для установки")
            return

        row_idx = rows[0].row()
        if row_idx >= len(self._current_archives):
            return

        archive = self._current_archives[row_idx]

        if not self._active_session:
            QMessageBox.warning(
                self, "Нет подключения",
                "Нет активной сессии. Подключитесь к кассе и попробуйте снова."
            )
            return

        if not self._active_session.is_connected:
            QMessageBox.warning(
                self, "Нет подключения",
                "Сессия отключена. Подключитесь к кассе и попробуйте снова."
            )
            return

        # Confirm
        type_label = _TYPE_LABELS.get(archive.cash_type, archive.cash_type)
        confirm = QMessageBox.warning(
            self,
            "⚠ Переустановка ПО",
            f"Вы собираетесь переустановить ПО на кассе {self._active_session.host}!\n\n"
            f"Архив: {archive.path.name}\n"
            f"Тип: {type_label}\n"
            f"Версия: {archive.version}\n\n"
            f"Это действие:\n"
            f"• Остановит кассовое ПО\n"
            f"• Удалит все базы данных\n"
            f"• Удалит текущее ПО\n"
            f"• Установит новую версию\n"
            f"• Перезагрузит кассу\n\n"
            f"Продолжить?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        # Open progress dialog
        from cashcontrol.gui.dialogs.reinstall_progress_dialog import ReinstallProgressDialog

        progress_dlg = ReinstallProgressDialog(
            session=self._active_session,
            archive_path=archive.path,
            cash_type=archive.cash_type,
            parent=self,
        )
        progress_dlg.setModal(True)
        progress_dlg.start()
        progress_dlg.show()

    def _on_delete(self, archive: ArchiveInfo) -> None:
        """Delete an archive after confirmation."""
        confirm = QMessageBox.question(
            self,
            "Удаление архива",
            f"Удалить архив {archive.path.name}?\n"
            f"Тип: {_TYPE_LABELS.get(archive.cash_type, archive.cash_type)}\n"
            f"Размер: {archive.size_mb} MB\n\n"
            f"Это действие необратимо.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return

        if self._scanner.delete_archive(archive):
            audit_log(
                action_type="reinstall",
                action_name="delete_archive",
                target=f"{archive.cash_type}/{archive.path.name}",
                result="success",
            )
            self._status.setText(f"Архив {archive.path.name} удалён")
            self._refresh_table()
        else:
            QMessageBox.warning(self, "Ошибка", "Не удалось удалить файл")

    def _open_folder(self) -> None:
        """Open reinstall directory in Explorer."""
        import subprocess

        folder = get_reinstall_dir()
        if folder.exists():
            subprocess.Popen(["explorer", str(folder)])
        else:
            QMessageBox.warning(self, "Ошибка", f"Папка не найдена: {folder}")