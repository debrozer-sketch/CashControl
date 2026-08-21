"""
installer.py — Async POS software installation on a cash register.

Performs the full reinstallation process step by step:
1. Upload .tar archive to /home/tc/storage/ via SCP
2. Stop POS software (cash stop + killall java)
3. Drop databases (pos/touch: 5 DBs, sco3: 6 DBs + terminate connections)
4. Clean /home/tc/storage/crystal-cash/
5. Extract archive into crystal-cash/
6. Fix permissions (sco3 only: chown)
7. Reboot (cash reboot)

Each step emits a signal so the UI can show real-time progress.

Usage:
    from cashcontrol.core.reinstall.installer import Installer, InstallStep

    installer = Installer(session, archive_path, cash_type)
    installer.step_started.connect(on_step_start)
    installer.step_log.connect(on_log_line)
    installer.step_finished.connect(on_step_done)
    installer.install_finished.connect(on_done)
    await installer.run()
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal

if TYPE_CHECKING:
    from pathlib import Path


class InstallStep(Enum):
    """Installation steps."""
    UPLOAD = "upload"
    STOP_SOFTWARE = "stop_software"
    DROP_DATABASES = "drop_databases"
    CLEAN_DIRECTORY = "clean_directory"
    EXTRACT_ARCHIVE = "extract_archive"
    FIX_PERMISSIONS = "fix_permissions"
    REBOOT = "reboot"


_STEP_LABELS = {
    InstallStep.UPLOAD:           "📤 Загрузка архива на кассу",
    InstallStep.STOP_SOFTWARE:    "⏹ Остановка ПО",
    InstallStep.DROP_DATABASES:   "🗑 Удаление баз данных",
    InstallStep.CLEAN_DIRECTORY:  "🧹 Очистка каталога crystal-cash",
    InstallStep.EXTRACT_ARCHIVE:  "📦 Распаковка архива",
    InstallStep.FIX_PERMISSIONS:  "🔧 Настройка прав доступа",
    InstallStep.REBOOT:           "🔄 Перезагрузка кассы",
}

# Databases to drop per cash type
_DBS_COMMON = ["cash", "cards", "catalog", "discount", "user"]
_DBS_SCO3_EXTRA = ["sco_v3"]

# Remote paths
_REMOTE_STORAGE = "/home/tc/storage"
_REMOTE_CRYSTAL = "/home/tc/storage/crystal-cash"


@dataclass
class StepResult:
    """Result of a single installation step."""
    step: InstallStep
    success: bool
    message: str
    details: str = ""


@dataclass
class InstallResult:
    """Final result of the full installation."""
    success: bool
    message: str
    steps: list[StepResult]
    aborted_at: InstallStep | None = None


class Installer(QObject):
    """
    Async installer that performs POS software reinstallation.

    Signals:
        step_started(step_name, step_label, step_number, total_steps)
        step_log(message)          — log line for current step
        step_finished(step_name, success, message)
        progress_updated(current, total)  — for upload progress
        install_finished(InstallResult)
    """

    step_started = Signal(str, str, int, int)
    step_log = Signal(str)
    step_finished = Signal(str, bool, str)
    progress_updated = Signal(int, int)
    install_finished = Signal(object)

    def __init__(
        self,
        session,
        archive_path: Path,
        cash_type: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._archive_path = archive_path
        self._cash_type = cash_type
        self._steps_results: list[StepResult] = []

    def _get_steps(self) -> list[InstallStep]:
        """Return ordered list of steps for current cash type."""
        steps = [
            InstallStep.UPLOAD,
            InstallStep.STOP_SOFTWARE,
            InstallStep.DROP_DATABASES,
            InstallStep.CLEAN_DIRECTORY,
            InstallStep.EXTRACT_ARCHIVE,
        ]
        if self._cash_type == "sco3":
            steps.append(InstallStep.FIX_PERMISSIONS)
        steps.append(InstallStep.REBOOT)
        return steps

    async def run(self) -> InstallResult:
        """Execute the full installation process."""
        steps = self._get_steps()
        total = len(steps)

        for i, step in enumerate(steps):
            label = _STEP_LABELS.get(step, step.value)
            self.step_started.emit(step.value, label, i + 1, total)

            try:
                result = await self._execute_step(step)
            except Exception as e:
                result = StepResult(
                    step=step,
                    success=False,
                    message=f"Неожиданная ошибка: {e}",
                )

            self._steps_results.append(result)
            self.step_finished.emit(step.value, result.success, result.message)

            if not result.success:
                # Check if this is a critical failure
                if step in (
                    InstallStep.UPLOAD,
                    InstallStep.CLEAN_DIRECTORY,
                    InstallStep.EXTRACT_ARCHIVE,
                ):
                    final = InstallResult(
                        success=False,
                        message=f"Установка прервана на шаге: {label}\n{result.message}",
                        steps=self._steps_results,
                        aborted_at=step,
                    )
                    self.install_finished.emit(final)
                    return final
                # Non-critical — continue (e.g. dropdb, killall java)

        final = InstallResult(
            success=True,
            message="Установка завершена. Касса перезагружается.",
            steps=self._steps_results,
        )
        self.install_finished.emit(final)
        return final

    async def _execute_step(self, step: InstallStep) -> StepResult:
        """Dispatch to the appropriate step handler."""
        handlers = {
            InstallStep.UPLOAD: self._step_upload,
            InstallStep.STOP_SOFTWARE: self._step_stop,
            InstallStep.DROP_DATABASES: self._step_drop_dbs,
            InstallStep.CLEAN_DIRECTORY: self._step_clean,
            InstallStep.EXTRACT_ARCHIVE: self._step_extract,
            InstallStep.FIX_PERMISSIONS: self._step_fix_perms,
            InstallStep.REBOOT: self._step_reboot,
        }
        handler = handlers.get(step)
        if not handler:
            return StepResult(step=step, success=False, message="Неизвестный шаг")
        return await handler()

    # ── Step implementations ───────────────────────────────────────────────

    async def _ssh(self, cmd: str, timeout: int = 30, ignore_error: bool = False) -> tuple[bool, str, str]:
        """Execute SSH command, log it, return (success, stdout, stderr)."""
        self.step_log.emit(f"$ {cmd}")
        try:
            result = await self._session.ssh.execute(cmd, timeout=timeout)
            if result.stdout.strip():
                self.step_log.emit(result.stdout.strip())
            if result.stderr.strip():
                self.step_log.emit(f"⚠ {result.stderr.strip()}")
            if not result.success and not ignore_error:
                return False, result.stdout, result.stderr
            return True, result.stdout, result.stderr
        except Exception as e:
            self.step_log.emit(f"❌ {e}")
            if ignore_error:
                return True, "", str(e)
            return False, "", str(e)

    async def _step_upload(self) -> StepResult:
        """Upload .tar archive via SSH stdin streaming with progress.

        Instead of SCP (which writes atomically with no progress) or SFTP
        (not available on TinyCore), we stream the file via:
            cat > /path/to/file
        This works on any SSH server and allows exact byte-level progress.
        """
        import time

        local_path = self._archive_path
        remote_path = f"{_REMOTE_STORAGE}/{local_path.name}"
        total_bytes = local_path.stat().st_size
        total_mb = total_bytes / (1024 * 1024)

        self.step_log.emit(f"Файл: {local_path.name} ({total_mb:.1f} MB)")
        self.step_log.emit(f"Назначение: {remote_path}")

        try:
            conn = self._session.ssh._conn
            if conn is None:
                return StepResult(
                    step=InstallStep.UPLOAD,
                    success=False,
                    message="SSH соединение не установлено",
                )

            start_time = time.monotonic()
            CHUNK_SIZE = 64 * 1024  # 64 KB chunks

            # Open a remote process: cat > file
            process = await conn.create_process(
                f"cat > {remote_path}",
                encoding=None,  # binary mode
            )

            bytes_sent = 0
            last_report = start_time

            with open(local_path, "rb") as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    process.stdin.write(chunk)
                    await process.stdin.drain()
                    bytes_sent += len(chunk)

                    # Report progress every ~1 second
                    now = time.monotonic()
                    if now - last_report >= 1.0:
                        last_report = now
                        self.progress_updated.emit(bytes_sent, total_bytes)
                        int(bytes_sent * 100 / total_bytes)

            # Close stdin to signal EOF
            process.stdin.write_eof()
            await process.stdin.drain()

            # Wait for process to finish
            await asyncio.wait_for(process.wait(), timeout=10)

            # Final progress — 100%
            self.progress_updated.emit(total_bytes, total_bytes)

            elapsed_total = time.monotonic() - start_time
            avg_speed = total_mb / elapsed_total if elapsed_total > 0 else 0
            self.step_log.emit(f"✅ Загрузка завершена за {int(elapsed_total)} сек ({avg_speed:.1f} MB/s)")

            return StepResult(
                step=InstallStep.UPLOAD,
                success=True,
                message=f"Архив загружен ({total_mb:.0f} MB, {int(elapsed_total)} сек)",
            )
        except Exception as e:
            return StepResult(
                step=InstallStep.UPLOAD,
                success=False,
                message=f"Ошибка загрузки: {e}",
            )

    async def _step_stop(self) -> StepResult:
        """Stop POS software."""
        ok1, _, _ = await self._ssh("cash stop", timeout=15)
        # killall java — may fail if no java running, that's OK
        ok2, _, _stderr2 = await self._ssh("killall java", timeout=10, ignore_error=True)
        if not ok2:
            self.step_log.emit("(killall java — процесс не найден, это нормально)")

        self.step_log.emit("⏳ Ожидание 3 сек...")
        await asyncio.sleep(3)

        if not ok1:
            return StepResult(
                step=InstallStep.STOP_SOFTWARE,
                success=False,
                message="Не удалось остановить ПО (cash stop)",
            )

        return StepResult(
            step=InstallStep.STOP_SOFTWARE,
            success=True,
            message="ПО остановлено",
        )

    async def _step_drop_dbs(self) -> StepResult:
        """Drop databases."""
        errors: list[str] = []

        # SCO3: terminate active connections to sco_v3 first
        if self._cash_type == "sco3":
            self.step_log.emit("Завершение подключений к sco_v3...")
            await self._ssh(
                'psql -h localhost -p 5432 -U postgres -c '
                '"SELECT pg_terminate_backend(pid) FROM pg_stat_activity '
                "WHERE datname = 'sco_v3';\"",
                timeout=10,
                ignore_error=True,
            )

        # Drop databases
        dbs = list(_DBS_COMMON)
        if self._cash_type == "sco3":
            dbs.extend(_DBS_SCO3_EXTRA)

        for db_name in dbs:
            ok, _, stderr = await self._ssh(
                f"dropdb -h localhost -p 5432 -U postgres {db_name}",
                timeout=15,
                ignore_error=True,
            )
            if not ok or ("error" in stderr.lower() and "does not exist" not in stderr.lower()):
                if "does not exist" in stderr.lower():
                    self.step_log.emit(f"  ℹ БД '{db_name}' не существует — пропуск")
                else:
                    errors.append(f"{db_name}: {stderr.strip()}")

        self.step_log.emit("⏳ Ожидание 2 сек...")
        await asyncio.sleep(2)

        if errors:
            details = "\n".join(errors)
            return StepResult(
                step=InstallStep.DROP_DATABASES,
                success=True,  # non-critical
                message=f"БД удалены (с предупреждениями: {len(errors)})",
                details=details,
            )

        return StepResult(
            step=InstallStep.DROP_DATABASES,
            success=True,
            message=f"Удалено БД: {len(dbs)}",
        )

    async def _step_clean(self) -> StepResult:
        """Clean crystal-cash directory."""
        self.step_log.emit(f"Очистка {_REMOTE_CRYSTAL}/...")

        # Create dir if not exists, then remove contents
        ok, _, stderr = await self._ssh(
            f"rm -rf {_REMOTE_CRYSTAL}/* {_REMOTE_CRYSTAL}/.[!.]* 2>/dev/null; "
            f"mkdir -p {_REMOTE_CRYSTAL}",
            timeout=30,
        )

        if not ok:
            return StepResult(
                step=InstallStep.CLEAN_DIRECTORY,
                success=False,
                message=f"Ошибка очистки: {stderr.strip()}",
            )

        return StepResult(
            step=InstallStep.CLEAN_DIRECTORY,
            success=True,
            message="Каталог очищен",
        )

    async def _step_extract(self) -> StepResult:
        """Extract archive on the cash register."""
        archive_name = self._archive_path.name
        remote_tar = f"{_REMOTE_STORAGE}/{archive_name}"

        self.step_log.emit(f"Распаковка {remote_tar} → {_REMOTE_CRYSTAL}/")

        ok, _stdout, stderr = await self._ssh(
            f"tar xf {remote_tar} -C {_REMOTE_CRYSTAL}",
            timeout=120,  # large archives may take a while
        )

        if not ok:
            return StepResult(
                step=InstallStep.EXTRACT_ARCHIVE,
                success=False,
                message=f"Ошибка распаковки: {stderr.strip()}",
            )

        # Verify extraction produced files
        _ok_check, stdout_check, _ = await self._ssh(
            f"ls {_REMOTE_CRYSTAL}/ | head -5",
            timeout=10,
            ignore_error=True,
        )
        if stdout_check.strip():
            self.step_log.emit(f"Содержимое: {stdout_check.strip()}")

        # Clean up uploaded archive to save space
        await self._ssh(f"rm -f {remote_tar}", timeout=10, ignore_error=True)
        self.step_log.emit("Временный архив удалён")

        return StepResult(
            step=InstallStep.EXTRACT_ARCHIVE,
            success=True,
            message="Архив распакован",
        )

    async def _step_fix_perms(self) -> StepResult:
        """Fix permissions for sco3 (chown)."""
        ok, _, stderr = await self._ssh(
            f"sudo chown -R tc:users {_REMOTE_CRYSTAL}",
            timeout=30,
        )

        if not ok:
            return StepResult(
                step=InstallStep.FIX_PERMISSIONS,
                success=False,
                message=f"Ошибка chown: {stderr.strip()}",
            )

        return StepResult(
            step=InstallStep.FIX_PERMISSIONS,
            success=True,
            message="Права доступа настроены",
        )

    async def _step_reboot(self) -> StepResult:
        """Reboot the cash register via cash reboot."""
        self.step_log.emit("Отправка cash reboot...")

        # Send reboot — timeout/disconnect errors are expected and OK
        await self._ssh("cash reboot", timeout=5, ignore_error=True)

        self.step_log.emit("⏳ Ожидание 3 сек...")
        await asyncio.sleep(3)

        self.step_log.emit("✅ Касса перезагружается")

        return StepResult(
            step=InstallStep.REBOOT,
            success=True,
            message="Касса перезагружается",
        )