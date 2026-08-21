"""
mover_progress_dialog.py — Диалог прогресса выполнения Mover-сценария.

Показывает пошаговый процесс с:
- Прогресс-баром (по шагам)
- Лейблом текущего шага
- Текстовым логом выполнения
- Итоговым статусом

Модальный — нельзя закрыть пока выполнение идёт.
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

from cashcontrol.core.mover.executor import (
    ExecutionReport,
    MoverExecutor,
    MoverParams,
)
from cashcontrol.gui.theme_helper import color as _tc

if TYPE_CHECKING:
    from cashcontrol.core.mover.scenario import Scenario


class MoverProgressDialog(QDialog):
    """Модальный диалог прогресса выполнения Mover-сценария."""

    def __init__(
        self,
        session,
        scenario: Scenario,
        params: MoverParams,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._scenario = scenario
        self._params = params
        self._finished = False
        self._report: ExecutionReport | None = None
        self._task: asyncio.Task | None = None

        self.setWindowTitle("Mover — выполнение")
        self.setMinimumSize(650, 500)
        self.resize(700, 550)

        self._init_ui()

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Title
        title = SubtitleLabel(
            f"📦 Mover — {self._session.host}", self
        )
        root.addWidget(title)

        # Info line
        cash_type = getattr(self._session, "cash_type", "?")
        info = QLabel(
            f"Сценарий: {self._scenario.name}  •  Тип кассы: {cash_type}",
            self,
        )
        info.setStyleSheet(f"color: {_tc('text_secondary')}; font-size: 12px;")
        root.addWidget(info)

        # Progress bar
        self._progress_bar = QProgressBar(self)
        self._progress_bar.setRange(0, 0)  # indeterminate initially
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setFixedHeight(6)
        root.addWidget(self._progress_bar)

        # Current step label
        self._step_label = QLabel("Подготовка...", self)
        self._step_label.setStyleSheet("font-size: 13px; font-weight: 500;")
        root.addWidget(self._step_label)

        # Log area
        self._log = QPlainTextEdit(self)
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Consolas", 10))
        self._log.setStyleSheet(
            f"background: {_tc('surface')}; "
            f"color: {_tc('text_primary')}; "
            f"border: 1px solid {_tc('border')}; "
            f"border-radius: 4px; "
            f"padding: 8px;"
        )
        root.addWidget(self._log, stretch=1)

        # Bottom buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._status_label = QLabel("", self)
        self._status_label.setStyleSheet(
            f"color: {_tc('text_secondary')}; font-size: 12px;"
        )
        btn_row.addWidget(self._status_label, stretch=1)

        self._btn_close = PushButton("Закрыть", self)
        self._btn_close.setEnabled(False)
        self._btn_close.clicked.connect(self.accept)
        btn_row.addWidget(self._btn_close)

        root.addLayout(btn_row)

    # ── Execution ─────────────────────────────────────

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._finished:
            self._task = asyncio.ensure_future(self._run_execution())

    def closeEvent(self, event) -> None:
        if not self._finished:
            if self._task and not self._task.done():
                self._task.cancel()
            event.ignore()
            return
        super().closeEvent(event)

    def keyPressEvent(self, event) -> None:
        # Block Escape while running
        if event.key() == Qt.Key.Key_Escape and not self._finished:
            return
        super().keyPressEvent(event)

    async def _run_execution(self) -> None:
        """Run the Mover scenario and update UI."""
        executor = MoverExecutor(
            self._session, self._scenario, self._params
        )

        try:
            self._report = await executor.run(
                progress=self._on_progress,
            )
        except Exception as e:
            self._append_log(f"\n❌ Критическая ошибка: {e}")
            self._report = None

        self._on_finished()

    async def _on_progress(self, message: str) -> None:
        """Progress callback from executor."""
        self._append_log(message)

        # Update step label with the latest significant message
        if message.startswith("▶"):
            self._step_label.setText(message.lstrip("▶ "))
        elif message.startswith("✅") or message.startswith("❌"):
            self._step_label.setText(message)

    def _append_log(self, text: str) -> None:
        """Append text to log area."""
        self._log.appendPlainText(text)
        # Auto-scroll to bottom
        cursor = self._log.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self._log.setTextCursor(cursor)

    def _on_finished(self) -> None:
        """Called when execution completes."""
        self._finished = True
        self._btn_close.setEnabled(True)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(100)

        if self._report and self._report.success:
            self._step_label.setText("✅ Выполнение завершено")
            self._step_label.setStyleSheet(
                "font-size: 13px; font-weight: 500; color: #27ae60;"
            )
            self._status_label.setText(
                f"Успешно: {self._report.successful_steps}/"
                f"{self._report.executed_steps} шагов"
            )
        elif self._report:
            self._step_label.setText("⚠ Завершено с ошибками")
            self._step_label.setStyleSheet(
                "font-size: 13px; font-weight: 500; color: #e74c3c;"
            )
            self._status_label.setText(
                f"Ошибки: {self._report.failed_steps}, "
                f"Успешно: {self._report.successful_steps}/"
                f"{self._report.executed_steps}"
            )
        else:
            self._step_label.setText("❌ Выполнение прервано")
            self._step_label.setStyleSheet(
                "font-size: 13px; font-weight: 500; color: #e74c3c;"
            )

    @property
    def report(self) -> ExecutionReport | None:
        """Get execution report after dialog closes."""
        return self._report