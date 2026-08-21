"""
reinstall_progress_dialog.py — Диалог прогресса установки ПО.

Показывает пошаговый процесс установки с:
- Прогресс-баром (по шагам)
- Лейблом текущего шага
- Текстовым логом выполнения (все команды и результаты)
- Итоговым статусом

Модальный — нельзя закрыть пока установка идёт.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import PushButton, SubtitleLabel

from cashcontrol.core.reinstall.installer import Installer, InstallResult
from cashcontrol.gui.theme_helper import color as _tc

if TYPE_CHECKING:
    from pathlib import Path


class ReinstallProgressDialog(QDialog):
    """Модальный диалог прогресса установки ПО на кассу."""

    def __init__(
        self,
        session,
        archive_path: Path,
        cash_type: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._archive_path = archive_path
        self._cash_type = cash_type
        self._finished = False

        self.setWindowTitle("Установка ПО")
        self.setMinimumSize(600, 450)
        self.resize(650, 500)

        self._init_ui()

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Title
        title = SubtitleLabel(f"📦 Установка ПО на {self._session.host}", self)
        root.addWidget(title)

        # Archive info
        info_lbl = QLabel(
            f"Архив: <b>{self._archive_path.name}</b> | "
            f"Тип: <b>{self._cash_type}</b>",
            self,
        )
        info_lbl.setTextFormat(Qt.TextFormat.RichText)
        info_lbl.setStyleSheet(f"color: {_tc('text_secondary')}; font-size: 12px;")
        root.addWidget(info_lbl)

        # Progress bar
        self._progress_bar = QProgressBar(self)
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(True)
        self._progress_bar.setFormat("%v%")
        root.addWidget(self._progress_bar)

        # Current step label
        self._step_label = QLabel("Подготовка...", self)
        self._step_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        root.addWidget(self._step_label)

        # Log area
        self._log = QPlainTextEdit(self)
        self._log.setReadOnly(True)
        log_font = QFont("Consolas", 9)
        log_font.setStyleHint(QFont.StyleHint.Monospace)
        self._log.setFont(log_font)
        self._log.setStyleSheet(
            f"background: {_tc('bg_code')}; color: {_tc('text_code')}; "
            f"border: 1px solid {_tc('border_primary')}; border-radius: 4px;"
        )
        root.addWidget(self._log, stretch=1)

        # Status label (shown after completion)
        self._status_label = QLabel("", self)
        self._status_label.setStyleSheet("font-size: 13px; font-weight: 600;")
        self._status_label.hide()
        root.addWidget(self._status_label)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        self._btn_close = PushButton("Закрыть", self)
        self._btn_close.setEnabled(False)
        self._btn_close.clicked.connect(self.accept)
        btn_row.addWidget(self._btn_close)

        root.addLayout(btn_row)

    def start(self) -> None:
        """Start the installation process."""
        self._installer = Installer(
            session=self._session,
            archive_path=self._archive_path,
            cash_type=self._cash_type,
            parent=self,
        )

        # Connect signals
        self._installer.step_started.connect(self._on_step_started)
        self._installer.step_log.connect(self._on_log)
        self._installer.step_finished.connect(self._on_step_finished)
        self._installer.install_finished.connect(self._on_install_finished)
        self._installer.progress_updated.connect(self._on_progress_updated)
        self._total_steps = 0
        self._current_step = 0
        self._uploading = False

        # Run as async task
        self._install_task = asyncio.ensure_future(self._run_install())

    async def _run_install(self) -> None:
        """Run the installer asynchronously."""
        try:
            await self._installer.run()
        except Exception as e:
            self._on_log(f"❌ Критическая ошибка: {e}")
            self._on_install_finished(InstallResult(
                success=False,
                message=f"Критическая ошибка: {e}",
                steps=[],
            ))

    def _on_step_started(self, step_name: str, label: str, step_num: int, total: int) -> None:
        """Called when a step begins."""
        self._step_label.setText(f"[{step_num}/{total}] {label}")
        self._total_steps = total
        self._current_step = step_num
        self._uploading = (step_name == "upload")

        # Update progress bar — during upload it will be overridden by _on_progress_updated
        if not self._uploading:
            progress = int((step_num - 1) / total * 100)
            self._progress_bar.setValue(progress)
            self._progress_bar.setFormat(f"Шаг {step_num}/{total}")

        # Add separator in log
        self._on_log(f"\n{'─' * 50}")
        self._on_log(f"▶ {label} ({step_num}/{total})")
        self._on_log(f"{'─' * 50}")

    def _on_log(self, message: str) -> None:
        """Append a line to the log."""
        self._log.appendPlainText(message)
        # Auto-scroll to bottom
        cursor = self._log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._log.setTextCursor(cursor)

    def _on_progress_updated(self, bytes_sent: int, total_bytes: int) -> None:
        """Called during file upload with transfer progress.

        Updates the last line in the log instead of appending a new one.
        """
        if total_bytes <= 0:
            return
        pct = int(bytes_sent * 100 / total_bytes)
        sent_mb = bytes_sent / (1024 * 1024)
        total_mb = total_bytes / (1024 * 1024)
        self._progress_bar.setValue(pct)
        self._progress_bar.setFormat(f"📤 {sent_mb:.0f}/{total_mb:.0f} MB ({pct}%)")

        import time
        # Build progress text
        elapsed = getattr(self, '_upload_start', None)
        if elapsed is None:
            self._upload_start = time.monotonic()
            elapsed = 0
        else:
            elapsed = time.monotonic() - self._upload_start

        speed = sent_mb / elapsed if elapsed > 0 else 0
        remaining = (total_bytes - bytes_sent) / (bytes_sent / elapsed) if bytes_sent > 0 and elapsed > 0 else 0
        remaining_str = f" | ~{int(remaining)} сек" if remaining > 1 else ""

        progress_text = f"📤 {pct}%  ({sent_mb:.1f}/{total_mb:.1f} MB | {speed:.1f} MB/s{remaining_str})"

        # Replace last line in log (or append if first call)
        cursor = self._log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock, QTextCursor.MoveMode.KeepAnchor)
        selected = cursor.selectedText()

        if selected.startswith("📤"):
            # Replace existing progress line
            cursor.removeSelectedText()
            cursor.insertText(progress_text)
        else:
            # First progress line — append
            self._log.appendPlainText(progress_text)

        # Scroll to bottom
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._log.setTextCursor(cursor)

    def _on_step_finished(self, step_name: str, success: bool, message: str) -> None:
        """Called when a step completes."""
        icon = "✅" if success else "❌"
        self._on_log(f"{icon} {message}")
        # Reset progress bar format after upload
        if step_name == "upload":
            self._uploading = False
            self._upload_start = None
            self._progress_bar.setFormat(f"Шаг {self._current_step}/{self._total_steps}")

    def _on_install_finished(self, result: InstallResult) -> None:
        """Called when entire installation completes."""
        self._finished = True

        # Update progress to 100%
        if result.success:
            self._progress_bar.setValue(100)
            self._progress_bar.setFormat("✅ Готово")
            self._step_label.setText("✅ Установка завершена")
            self._status_label.setText(
                "Касса перезагружается. Подождите ~1 минуту."
            )
            self._status_label.setStyleSheet(
                f"font-size: 13px; font-weight: 600; color: {_tc('success')};"
            )
        else:
            self._step_label.setText("❌ Установка прервана")
            self._status_label.setText(result.message)
            self._status_label.setStyleSheet(
                f"font-size: 13px; font-weight: 600; color: {_tc('error')};"
            )

        self._status_label.show()
        self._btn_close.setEnabled(True)

    def closeEvent(self, event) -> None:
        """Prevent closing while installation is running."""
        if not self._finished:
            event.ignore()
        else:
            super().closeEvent(event)