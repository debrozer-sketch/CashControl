# Recovery report

- events total: 6329
- files touched: 218
- files recovered: 216
- files with no content: 2
- orphan edits (no base): 3
- unparsed reads: 345

## Failed edits (oldString not found at replay time)

### scripts\cc_patcher\packer.py @ 06-20 12:15:43
```
--- OLD ---
from pathlib import Path

RELOAD_RULES
--- NEW ---
from pathlib import Path  # noqa: TC003

RELOAD_RULES
```

### src\cashcontrol\gui\cash_session_widget.py @ 07-02 08:04:36
```
--- OLD ---
from cashcontrol.gui.notification_manager import get_notification_manager
from cashcontrol.gui.vnc_preview import VncPreviewWidget
from cashcontrol.gui.widgets.info_section_widget import InfoSectionWi
--- NEW ---
from cashcontrol.gui.notification_manager import get_notification_manager
from cashcontrol.infrastructure.audit_logger import get_logger

if TYPE_CHECKING:
    from cashcontrol.core.info.info_manager 
```

### src\cashcontrol\gui\cash_session_widget.py @ 07-02 08:04:47
```
--- OLD ---
        # ── Splitter: VNC left, Info right ──
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)

        
--- NEW ---
        # ── Splitter: VNC left, Info right ──
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.setHandleWidth(1)
        splitter.setChildrenCollapsible(False)

        
```

### src\cashcontrol\gui\cash_session_widget.py @ 07-02 08:04:51
```
--- OLD ---
    def _show_skeletons(self) -> None:
        """Show placeholder widgets for all expected sections."""
        self._clear_sections()
        for name in ALL_SECTIONS:
            widget = InfoSecti
--- NEW ---
    def _show_skeletons(self) -> None:
        """Show placeholder widgets for all expected sections."""
        self._clear_sections()
        from cashcontrol.infrastructure.module_loader import get
```

### Old_backup\src\cashcontrol\gui\cash_session_widget.py @ 07-03 07:30:05
```
--- OLD ---
                self.loading_label.setText("✅ SSH подключено")
                self._reconnect_btn_shown = False
--- NEW ---
                self.loading_label.setText("✅ SSH подключено")
                self.connection_state_changed.emit(self._ip, "ok")
                self._reconnect_btn_shown = False
```

### Old_backup\src\cashcontrol\gui\cash_session_widget.py @ 07-03 07:30:07
```
--- OLD ---
                if not success:
                    self.loading_label.setText(f"❌ {self._session.error_message or 'Не удалось подключиться'}")
                    self._show_reconnect_button()
      
--- NEW ---
                if not success:
                    self.connection_state_changed.emit(self._ip, "timeout")
                    self.loading_label.setText(f"❌ {self._session.error_message or 'Не удало
```

### Old_backup\src\cashcontrol\gui\cash_session_widget.py @ 07-03 07:30:10
```
--- OLD ---
            except asyncio.CancelledError:
                logger.debug(f"Connect task cancelled for {self._ip}")
            except Exception as e:
                self.loading_label.setText(f"❌ Ошиб
--- NEW ---
            except asyncio.CancelledError:
                logger.debug(f"Connect task cancelled for {self._ip}")
            except Exception as e:
                self.connection_state_changed.emit(
```

### Old_backup\src\cashcontrol\gui\db_viewer_widget.py @ 07-03 07:31:07
```
--- OLD ---
        self.file_edit = QLineEdit(); self.file_edit.setReadOnly(True)
        fl.addWidget(self.file_edit)
        btn = QPushButton("Обзор…"); btn.clicked.connect(self._browse)
        fl.addWidget(
--- NEW ---
        self.file_edit = QLineEdit()
        self.file_edit.setReadOnly(True)
        fl.addWidget(self.file_edit)
        btn = QPushButton("Обзор…")
        btn.clicked.connect(self._browse)
       
```

### Old_backup\src\cashcontrol\gui\db_viewer_widget.py @ 07-03 07:31:11
```
--- OLD ---
            c = QComboBox(); c.addItem("— Пропустить —"); c.addItems(self.columns)
--- NEW ---
            c = QComboBox()
            c.addItem("— Пропустить —")
            c.addItems(self.columns)
```

### Old_backup\src\cashcontrol\gui\db_viewer_widget.py @ 07-03 07:31:13
```
--- OLD ---
                self.tabs.setCurrentIndex(i); return
--- NEW ---
                self.tabs.setCurrentIndex(i)
                return
```

### Old_backup\src\cashcontrol\core\mover\executor.py @ 07-03 07:31:58
```
--- OLD ---
    async def run(
        self,
        progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> ExecutionReport:
        """
        Execute the scenario on the connected session.

       
--- NEW ---
    async def run(
        self,
        progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> ExecutionReport:
        """
        Execute the scenario on the connected session.

       
```

### Old_backup\src\cashcontrol\gui\cash_session_widget.py @ 07-03 07:32:33
```
--- OLD ---
                # Check if we were cancelled (IP changed while connecting)
                if asyncio.current_task() and asyncio.current_task().cancelled():
                    return
--- NEW ---
                # Check if we were cancelled (IP changed while connecting)
                task = asyncio.current_task()
                if task and task.cancelled():
                    return
```

### Old_backup\src\cashcontrol\gui\db_viewer_widget.py @ 07-03 07:33:00
```
--- OLD ---
        a = fm.addAction("🔌 Подключение…"); a.setShortcut("Ctrl+N")
        a.triggered.connect(self._manual_connect)
--- NEW ---
        a = fm.addAction("🔌 Подключение…")
        a.setShortcut("Ctrl+N")
        a.triggered.connect(self._manual_connect)
```

### Old_backup\src\cashcontrol\gui\db_viewer_widget.py @ 07-03 07:33:00
```
--- OLD ---
        host_e = QLineEdit(); host_e.setPlaceholderText("192.168.x.x")
        port_e = QLineEdit("5432"); port_e.setMaximumWidth(80)
        user_e = QLineEdit("postgres")
        pwd_e  = QLineEdit(
--- NEW ---
        host_e = QLineEdit()
        host_e.setPlaceholderText("192.168.x.x")
        port_e = QLineEdit("5432")
        port_e.setMaximumWidth(80)
        user_e = QLineEdit("postgres")
        pwd_e
```

### Old_backup\src\cashcontrol\gui\vnc_preview.py @ 07-03 07:33:13
```
--- OLD ---
            if   t == _Cmd.DISCONNECT:    self._running = False
            elif t == _Cmd.KEY_EVENT:     self._send_key(cmd[1], cmd[2])
            elif t == _Cmd.POINTER_EVENT: self._send_pointer(cm
--- NEW ---
            if t == _Cmd.DISCONNECT:
                self._running = False
            elif t == _Cmd.KEY_EVENT:
                self._send_key(cmd[1], cmd[2])
            elif t == _Cmd.POINTER_EVENT
```

### Old_backup\src\cashcontrol\gui\vnc_preview.py @ 07-03 07:33:16
```
--- OLD ---
        if   t == 0: self._handle_update()
        elif t == 1: self._handle_colormap()
        elif t == 2: self._cb("on_bell")
--- NEW ---
        if t == 0:
            self._handle_update()
        elif t == 1:
            self._handle_colormap()
        elif t == 2:
            self._cb("on_bell")
```

### Old_backup\src\cashcontrol\gui\vnc_preview.py @ 07-03 07:33:19
```
--- OLD ---
        if   b == Qt.MouseButton.LeftButton:   self._btn_mask |= 1
        elif b == Qt.MouseButton.MiddleButton: self._btn_mask |= 2
        elif b == Qt.MouseButton.RightButton:  self._btn_mask |= 4
--- NEW ---
        if b == Qt.MouseButton.LeftButton:
            self._btn_mask |= 1
        elif b == Qt.MouseButton.MiddleButton:
            self._btn_mask |= 2
        elif b == Qt.MouseButton.RightButton:

```

### Old_backup\src\cashcontrol\gui\vnc_preview.py @ 07-03 07:33:22
```
--- OLD ---
        if   b == Qt.MouseButton.LeftButton:   self._btn_mask &= ~1
        elif b == Qt.MouseButton.MiddleButton: self._btn_mask &= ~2
        elif b == Qt.MouseButton.RightButton:  self._btn_mask &=
--- NEW ---
        if b == Qt.MouseButton.LeftButton:
            self._btn_mask &= ~1
        elif b == Qt.MouseButton.MiddleButton:
            self._btn_mask &= ~2
        elif b == Qt.MouseButton.RightButton
```

### Old_backup\src\cashcontrol\gui\db_viewer_widget.py @ 07-03 07:33:25
```
--- OLD ---
            if it.widget(): it.widget().deleteLater()
--- NEW ---
            if it.widget():
                it.widget().deleteLater()
```

### Old_backup\src\cashcontrol\gui\db_viewer_widget.py @ 07-03 07:33:26
```
--- OLD ---
            if csv_col in self.columns: c.setCurrentText(csv_col)
--- NEW ---
            if csv_col in self.columns:
                c.setCurrentText(csv_col)
```

### Old_backup\src\cashcontrol\gui\dialogs\command_editor.py @ 07-03 07:35:40
```
--- OLD ---
                with contextlib.suppress(Exception): self._file.unlink(missing_ok=True)
--- NEW ---
                with contextlib.suppress(Exception):
                    self._file.unlink(missing_ok=True)
```

### Old_backup\src\cashcontrol\core\info\info_manager.py @ 07-03 07:39:28
```
--- OLD ---
SECTION_GROUPS: dict[str, list[str]] = {
    "system": ["os", "cpu", "software", "cash_type"],
    "equipment": [
        "fiscal_printer",
        "customer_display",
        "scanners",
        "sca
--- NEW ---
SECTION_GROUPS: dict[str, list[str]] = {
    "system": ["os", "cpu", "software", "cash_type"],
    "equipment": [
        "fiscal_printer",
        "customer_display",
        "scanners",
        "sca
```

### Old_backup\src\cashcontrol\gui\cash_session_widget.py @ 07-03 07:39:34
```
--- OLD ---
    async def _collect_info(self, force: bool) -> None:
        """Run collection with progressive rendering via on_section_ready."""
        try:
            self._show_skeletons()
            self.l
--- NEW ---
    async def _collect_info(self, force: bool) -> None:
        """Run collection with progressive rendering via on_section_ready."""
        try:
            cash_type = getattr(self._session, "cash_
```

### Old_backup\src\cashcontrol\gui\dialogs\command_editor.py @ 07-03 07:47:36
```
--- OLD ---
        return None


class CommandEditorDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Конструктор команд")
        self.setMinimu
--- NEW ---
        return None


# ── Главный диалог ───────────────────────────────────────────────────────────
```

### Old_backup\src\cashcontrol\gui\dialogs\command_editor.py @ 07-03 07:47:59
```
--- OLD ---
# ── Главный диалог ───────────────────────────────────────────────────────────
        self._is_new = False
        self._mode = "idle"
        self._build()
        self._refresh_list()
        self
--- NEW ---
        return None
```

### Old_backup\src\cashcontrol\gui\dialogs\command_editor.py @ 07-03 07:48:20
```
--- OLD ---
        return None


        return None


# ── Форма редактирования
--- NEW ---
        return None


# ── Форма редактирования
```

### Old_backup\src\cashcontrol\gui\toolbar.py @ 07-03 07:48:29
```
--- OLD ---
# ── Top toolbar ───────────────────────────────────────────────


class Toolbar(QWidget):
    """Top toolbar with main action buttons."""

    add_cash_requested = Signal()
    settings_requested = S
--- NEW ---
# ── Per-tab toolbar ───────────────────────────────────────────
```

### Old_backup\src\cashcontrol\gui\vnc_preview.py @ 07-03 08:35:14
```
--- OLD ---
    def _recv(self, n: int) -> bytes | None:
        """Accumulate exactly `n` bytes.

        Honours SOCK_TIMEOUT cooperatively: while waiting for more data we keep
        checking `self._running`,
--- NEW ---
    def _recv(self, n: int) -> bytes | None:
        """Accumulate exactly `n` bytes.

        Honours SOCK_TIMEOUT cooperatively: while waiting for more data we keep
        checking `self._running`,
```

### Old_backup\src\cashcontrol\gui\cash_session_widget.py @ 07-03 08:49:19
```
--- OLD ---
    # ── Connection ──────────────────────────────────────────────────────────

    def _connect(self) -> None:
--- NEW ---
    # ── Connection ──────────────────────────────────────────────────────────

    def start_connecting(self) -> asyncio.Task | None:
        self._connect()
        return self._connect_task

    de
```

### _recovered_src\pyproject.toml @ 08-21 09:04:25
```
--- OLD ---
[project.scripts]
cashcontrol = "cashcontrol.main:main"    "defusedxml>=0.7",
--- NEW ---
[project.scripts]
cashcontrol = "cashcontrol.main:main"
```

### _recovered_src\src\cashcontrol\infrastructure\config_manager.py @ 08-21 09:09:06
```
--- OLD ---
class UpdateSettings(BaseModel):
    network_path: str | None = None
--- NEW ---
class UpdateSettings(BaseModel):
    network_path: str | None = None
    enabled: bool = True
```

### _recovered_src\src\cashcontrol\infrastructure\config_manager.py @ 08-21 09:09:13
```
--- OLD ---
import json
from pathlib import Path

from pydantic import BaseModel, Field
--- NEW ---
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
```

### _recovered_src\src\cashcontrol\gui\tab_manager.py @ 08-21 09:21:16
```
--- OLD ---
    def _on_tab_selected(self, ip: str) -> None:
        if not ip:
            self.active_tab_changed.emit(None)
            return
        session = self._session_mgr.get_session(ip)
        if ses
--- NEW ---
    def _on_tab_selected(self, ip: str) -> None:
        if not ip:
            self._session_mgr.active_ip = None
            self.active_tab_changed.emit(None)
            return
        session = s
```

### _recovered_src\src\cashcontrol\infrastructure\config_manager.py @ 08-21 09:22:24
```
--- OLD ---
class UpdateSettings(BaseModel):
    network_path: str | None = None
    enabled: bool = True
--- NEW ---
class UpdateSettings(BaseModel):
    network_path: str | None = None
    enabled: bool = True
    check_on_startup: bool = True
    check_interval_h: int = 24
```

### _recovered_src\src\cashcontrol\infrastructure\config_manager.py @ 08-21 09:25:07
```
--- OLD ---
    def get_vnc_client(self) -> str:
        return self.vnc_client_path or ""
--- NEW ---
    def _default_client(self, field: str | None, exe: str) -> str:
        if field and field.strip():
            return field
        from cashcontrol.infrastructure.path_resolver import get_soft_di
```

### _recovered_src\src\cashcontrol\infrastructure\update_client.py @ 08-21 09:26:27
```
--- OLD ---
    def _exe_available(self) -> bool:
        if not self._exe.exists():
            logger.warning("cc-updater.exe not found, skipping updates")
            return False
        return True
--- NEW ---
    def _exe_available(self) -> bool:
        if not self._exe.exists():
            logger.warning("cc-updater.exe not found, skipping updates")
            return False
        return True

    def 
```

### _recovered_src\src\cashcontrol\infrastructure\update_client.py @ 08-21 09:26:56
```
--- OLD ---
    async def _do_check(self) -> None:
        if not self._exe_available():
            return
--- NEW ---
    async def _do_check(self) -> None:
        if not self._exe_available() or not self._configured():
            return
```

| file | last | writes | edits ok | edits fail | reads | last time |
|---|---|---|---|---|---|---|
| .gitignore | edit | 0 | 1 | 0 | 2 | 2026-07-02 08:04 |
| .venv\test_dc.py | write | 1 | 0 | 0 | 0 | 2026-06-19 14:33 |
| .venv\test_rules.py | write | 1 | 0 | 0 | 0 | 2026-06-19 14:06 |
| AGENTS.md | write | 1 | 0 | 0 | 0 | 2026-06-24 16:02 |
| ANALYSIS.md | write | 1 | 0 | 0 | 0 | 2026-06-23 07:15 |
| BUILD.md | write | 1 | 0 | 0 | 2 | 2026-07-02 08:41 |
| CashControl.iss | read | 0 | 9 | 0 | 9 | 2026-07-02 07:36 |
| Old_backup\pyproject.toml | edit | 0 | 3 | 0 | 2 | 2026-07-03 07:35 |
| Old_backup\src\cashcontrol\core\info\collectors\cash_software.py | edit | 0 | 1 | 0 | 1 | 2026-07-03 07:32 |
| Old_backup\src\cashcontrol\core\info\collectors\cash_type.py | edit | 0 | 1 | 0 | 1 | 2026-07-03 07:32 |
| Old_backup\src\cashcontrol\core\info\collectors\keyboard.py | edit | 0 | 1 | 0 | 1 | 2026-07-03 07:32 |
| Old_backup\src\cashcontrol\core\info\collectors\qrid.py | edit | 0 | 1 | 0 | 1 | 2026-07-03 07:32 |
| Old_backup\src\cashcontrol\core\info\info_manager.py | read | 0 | 0 | 1 | 3 | 2026-07-03 08:53 |
| Old_backup\src\cashcontrol\core\mover\executor.py | read_partial | 0 | 0 | 1 | 3 | 2026-07-03 07:31 |
| Old_backup\src\cashcontrol\gui\cash_session_widget.py | read | 0 | 2 | 6 | 8 | 2026-07-03 08:53 |
| Old_backup\src\cashcontrol\gui\db_viewer_widget.py | edit | 0 | 1 | 7 | 6 | 2026-07-03 07:33 |
| Old_backup\src\cashcontrol\gui\dialogs\command_editor.py | edit | 0 | 1 | 4 | 13 | 2026-07-03 07:48 |
| Old_backup\src\cashcontrol\gui\dialogs\reinstall_dialog.py | edit | 0 | 1 | 0 | 1 | 2026-07-03 07:30 |
| Old_backup\src\cashcontrol\gui\dialogs\settings\settings_dialog.py | read | 0 | 0 | 0 | 1 | 2026-07-03 08:41 |
| Old_backup\src\cashcontrol\gui\dialogs\setup_wizard\page_welcome.py | read | 0 | 0 | 0 | 1 | 2026-07-03 08:41 |
| Old_backup\src\cashcontrol\gui\main_window.py | read | 0 | 1 | 0 | 4 | 2026-07-03 08:41 |
| Old_backup\src\cashcontrol\gui\session_manager.py | edit | 0 | 3 | 0 | 3 | 2026-07-03 07:49 |
| Old_backup\src\cashcontrol\gui\tab_bar.py | edit | 0 | 1 | 0 | 4 | 2026-07-03 08:45 |
| Old_backup\src\cashcontrol\gui\tab_manager.py | edit | 1 | 1 | 0 | 2 | 2026-07-03 07:35 |
| Old_backup\src\cashcontrol\gui\toolbar.py | edit | 0 | 11 | 1 | 11 | 2026-07-03 08:34 |
| Old_backup\src\cashcontrol\gui\vnc_preview.py | edit | 0 | 1 | 5 | 7 | 2026-07-03 08:35 |
| Old_backup\src\cashcontrol\gui\widgets\info_section_widget.py | read | 0 | 3 | 0 | 2 | 2026-07-03 08:53 |
| Old_backup\src\cashcontrol\infrastructure\__init__.py | read | 0 | 0 | 0 | 1 | 2026-07-03 08:41 |
| Old_backup\src\cashcontrol\infrastructure\config_manager.py | read | 0 | 0 | 0 | 1 | 2026-07-03 08:41 |
| Old_backup\src\cashcontrol\main.py | read | 0 | 0 | 0 | 1 | 2026-07-03 08:41 |
| Ready\data\settings.json | read | 0 | 0 | 0 | 1 | 2026-08-21 08:50 |
| Ready\docs\code_analysis.md | read_partial | 0 | 0 | 0 | 2 | 2026-08-21 08:37 |
| Ready\docs\patch.md | read | 0 | 0 | 0 | 1 | 2026-08-21 08:37 |
| _recovered_src\pyproject.toml | edit | 0 | 1 | 1 | 1 | 2026-08-21 09:04 |
| _recovered_src\src\cashcontrol\__init__.py | write | 1 | 0 | 0 | 0 | 2026-08-21 09:03 |
| _recovered_src\src\cashcontrol\core\info\__init__.py | write | 1 | 0 | 0 | 0 | 2026-08-21 09:03 |
| _recovered_src\src\cashcontrol\core\info\collectors\os_info.py | read_partial | 0 | 0 | 0 | 1 | 2026-08-21 10:31 |
| _recovered_src\src\cashcontrol\core\info\info_manager.py | edit | 1 | 1 | 0 | 1 | 2026-08-21 10:42 |
| _recovered_src\src\cashcontrol\core\info\registry.py | read | 0 | 0 | 0 | 1 | 2026-08-21 10:29 |
| _recovered_src\src\cashcontrol\core\session.py | edit | 1 | 3 | 0 | 1 | 2026-08-21 10:41 |
| _recovered_src\src\cashcontrol\gui\cash_session_widget.py | read_partial | 0 | 0 | 0 | 2 | 2026-08-21 10:29 |
| _recovered_src\src\cashcontrol\gui\dialogs\settings\tab_updates.py | read_partial | 0 | 0 | 0 | 1 | 2026-08-21 09:22 |
| _recovered_src\src\cashcontrol\gui\main_window.py | edit | 0 | 2 | 0 | 2 | 2026-08-21 09:18 |
| _recovered_src\src\cashcontrol\gui\session_manager.py | edit | 0 | 2 | 0 | 1 | 2026-08-21 09:21 |
| _recovered_src\src\cashcontrol\gui\tab_manager.py | edit | 0 | 1 | 1 | 2 | 2026-08-21 09:21 |
| _recovered_src\src\cashcontrol\infrastructure\audit_logger.py | edit | 0 | 1 | 0 | 1 | 2026-08-21 09:05 |
| _recovered_src\src\cashcontrol\infrastructure\config_manager.py | edit | 0 | 2 | 4 | 1 | 2026-08-21 09:25 |
| _recovered_src\src\cashcontrol\infrastructure\config_manager_full.py | write | 1 | 0 | 0 | 0 | 2026-08-21 08:53 |
| _recovered_src\src\cashcontrol\infrastructure\path_resolver.py | edit | 1 | 3 | 0 | 1 | 2026-08-21 10:39 |
| _recovered_src\src\cashcontrol\infrastructure\update_client.py | edit | 0 | 3 | 2 | 3 | 2026-08-21 09:26 |
| _recovered_src\src\cashcontrol\main.py | read_partial | 0 | 0 | 0 | 1 | 2026-08-21 09:06 |
| analysis.md | read | 0 | 0 | 0 | 2 | 2026-06-19 16:23 |
| build.bat | edit | 2 | 17 | 0 | 23 | 2026-07-02 16:04 |
| cc-updater\applier.go | write | 1 | 0 | 0 | 2 | 2026-07-02 08:06 |
| cc-updater\checker.go | edit | 1 | 3 | 0 | 6 | 2026-07-02 08:40 |
| cc-updater\hash.go | read | 0 | 0 | 0 | 2 | 2026-07-02 08:00 |
| cc-updater\main.go | read | 0 | 0 | 0 | 2 | 2026-07-02 08:00 |
| collectors\_builtin_cpu.toml | read | 0 | 0 | 0 | 4 | 2026-07-02 07:36 |
| collectors\_builtin_dns.toml | read | 0 | 0 | 0 | 3 | 2026-06-21 12:53 |
| collectors\_builtin_fiscal_printer.toml | read | 0 | 0 | 0 | 2 | 2026-06-21 12:53 |
| collectors\_builtin_loymax.toml | read | 0 | 0 | 0 | 2 | 2026-06-21 12:53 |
| collectors\_builtin_os.toml | read | 0 | 0 | 0 | 2 | 2026-06-21 12:53 |
| commands\README.md | read | 0 | 0 | 0 | 2 | 2026-06-19 16:23 |
| commands\_builtin_reboot.toml | read | 0 | 0 | 0 | 4 | 2026-06-22 07:37 |
| commands\_builtin_restart.toml | read | 0 | 0 | 0 | 3 | 2026-06-22 07:37 |
| commands\Найти_кассира.py | read | 0 | 0 | 0 | 3 | 2026-06-22 08:01 |
| commands\Поправить_FITO.py | read | 0 | 0 | 0 | 3 | 2026-06-22 08:01 |
| commands\Удалить_зависший_чек.py | read | 0 | 0 | 0 | 3 | 2026-06-22 08:01 |
| data\port_mapping.json | read | 0 | 0 | 0 | 4 | 2026-07-02 07:36 |
| data\sessions.json | read | 0 | 0 | 0 | 2 | 2026-06-22 07:37 |
| data\usb_id_mapping.json | read | 0 | 0 | 0 | 2 | 2026-07-02 07:36 |
| dev\UPDATE_STAGE_1_PATCHER.md | edit | 0 | 10 | 0 | 4 | 2026-06-20 12:07 |
| dev\UPDATE_STAGE_2_CLIENT.md | edit | 0 | 4 | 0 | 2 | 2026-06-20 12:07 |
| dev\UPDATE_STAGE_3_MIGRATION.md | read | 0 | 0 | 0 | 1 | 2026-06-20 11:49 |
| dev\UPDATE_SYSTEM_README.md | edit | 0 | 7 | 0 | 2 | 2026-06-20 12:07 |
| dist\CashControl\cashcontrol\infrastructure\hot_prefixes.json | read | 0 | 0 | 0 | 1 | 2026-07-02 22:25 |
| docs\code_analysis.md | write | 1 | 0 | 0 | 0 | 2026-06-21 12:54 |
| docs\patch.md | edit | 0 | 1 | 0 | 2 | 2026-07-02 08:07 |
| make_master.bat | read | 0 | 0 | 0 | 5 | 2026-07-02 08:41 |
| modules\gui\toolbar.py | read | 0 | 0 | 0 | 1 | 2026-07-02 08:18 |
| patch.bat | write | 1 | 0 | 0 | 0 | 2026-06-20 12:14 |
| pyproject.toml | read | 0 | 2 | 0 | 8 | 2026-07-02 07:34 |
| regression_check.py | write | 1 | 0 | 0 | 0 | 2026-06-22 09:50 |
| release.bat | write | 1 | 0 | 0 | 0 | 2026-06-20 12:14 |
| scripts\backup_project.py | read | 0 | 0 | 0 | 2 | 2026-06-21 12:53 |
| scripts\cc_patcher\__init__.py | write | 1 | 0 | 0 | 0 | 2026-06-20 12:14 |
| scripts\cc_patcher\__main__.py | write | 1 | 0 | 0 | 0 | 2026-06-20 12:14 |
| scripts\cc_patcher\baseline.py | write | 1 | 0 | 0 | 0 | 2026-06-20 12:14 |
| scripts\cc_patcher\differ.py | write | 1 | 0 | 0 | 0 | 2026-06-20 12:14 |
| scripts\cc_patcher\packer.py | write | 1 | 0 | 1 | 2 | 2026-06-20 12:15 |
| scripts\cc_patcher\publisher.py | write | 1 | 0 | 0 | 0 | 2026-06-20 12:14 |
| scripts\cc_patcher\scanner.py | edit | 1 | 1 | 0 | 1 | 2026-06-20 12:15 |
| scripts\clean_project.py | read | 0 | 0 | 0 | 1 | 2026-06-21 12:53 |
| scripts\make_master.py | edit | 2 | 6 | 0 | 4 | 2026-07-02 08:40 |
| scripts\sync_version.py | read | 0 | 0 | 0 | 3 | 2026-06-22 12:07 |
| src\cashcontrol\__init__.py | write | 1 | 1 | 0 | 9 | 2026-07-03 07:23 |
| src\cashcontrol\actions\__init__.py | read | 0 | 0 | 0 | 3 | 2026-06-22 07:35 |
| src\cashcontrol\actions_registry.py | edit | 0 | 2 | 0 | 9 | 2026-06-22 08:08 |
| src\cashcontrol\anchored_summary.txt | read | 0 | 0 | 0 | 1 | 2026-06-22 07:51 |
| src\cashcontrol\core\__init__.py | write | 1 | 0 | 0 | 5 | 2026-07-03 07:23 |
| src\cashcontrol\core\aliases\__init__.py | read | 0 | 0 | 0 | 4 | 2026-06-22 07:35 |
| src\cashcontrol\core\aliases\alias_manager.py | read | 0 | 0 | 0 | 4 | 2026-06-21 12:50 |
| src\cashcontrol\core\commands.py | edit | 0 | 3 | 0 | 9 | 2026-06-23 07:40 |
| src\cashcontrol\core\db.py | edit | 0 | 6 | 0 | 16 | 2026-06-23 07:41 |
| src\cashcontrol\core\executor.py | write | 1 | 0 | 0 | 0 | 2026-07-03 07:24 |
| src\cashcontrol\core\info\__init__.py | write | 1 | 1 | 0 | 8 | 2026-07-03 07:23 |
| src\cashcontrol\core\info\collectors\__init__.py | write | 2 | 0 | 0 | 7 | 2026-07-03 07:24 |
| src\cashcontrol\core\info\collectors\_port_mapper.py | read | 0 | 0 | 0 | 3 | 2026-06-21 12:50 |
| src\cashcontrol\core\info\collectors\_toml_collector.py | read | 0 | 0 | 0 | 4 | 2026-06-21 12:50 |
| src\cashcontrol\core\info\collectors\_usb_mapper.py | read | 0 | 0 | 0 | 3 | 2026-06-21 12:50 |
| src\cashcontrol\core\info\collectors\bank_terminal.py | edit | 0 | 7 | 0 | 8 | 2026-06-22 09:34 |
| src\cashcontrol\core\info\collectors\barcode_scanner.py | read | 0 | 0 | 0 | 5 | 2026-06-21 12:50 |
| src\cashcontrol\core\info\collectors\cash_software.py | write | 1 | 2 | 0 | 6 | 2026-07-03 07:24 |
| src\cashcontrol\core\info\collectors\cash_type.py | write | 1 | 3 | 0 | 11 | 2026-07-03 07:24 |
| src\cashcontrol\core\info\collectors\cpu_info.py | read | 0 | 0 | 0 | 3 | 2026-06-21 12:50 |
| src\cashcontrol\core\info\collectors\customer_display.py | read | 0 | 0 | 0 | 3 | 2026-06-21 12:50 |
| src\cashcontrol\core\info\collectors\dns_info.py | read | 0 | 0 | 0 | 3 | 2026-06-21 12:50 |
| src\cashcontrol\core\info\collectors\drawer_close.py | read | 2 | 2 | 0 | 4 | 2026-06-21 12:50 |
| src\cashcontrol\core\info\collectors\fiscal_printer.py | read | 0 | 0 | 0 | 3 | 2026-06-21 12:50 |
| src\cashcontrol\core\info\collectors\fiscal_register.py | read | 0 | 0 | 0 | 3 | 2026-06-19 16:28 |
| src\cashcontrol\core\info\collectors\keyboard.py | write | 1 | 3 | 0 | 7 | 2026-07-03 07:24 |
| src\cashcontrol\core\info\collectors\loymax.py | read | 0 | 0 | 0 | 3 | 2026-06-21 12:50 |
| src\cashcontrol\core\info\collectors\os_info.py | edit | 0 | 1 | 0 | 4 | 2026-06-22 09:34 |
| src\cashcontrol\core\info\collectors\payment_ranks.py | read | 2 | 3 | 0 | 3 | 2026-06-21 12:50 |
| src\cashcontrol\core\info\collectors\qrid.py | write | 1 | 1 | 0 | 6 | 2026-07-03 07:24 |
| src\cashcontrol\core\info\collectors\scales.py | read | 0 | 0 | 0 | 4 | 2026-06-21 12:50 |
| src\cashcontrol\core\info\info_manager.py | write | 1 | 12 | 0 | 17 | 2026-07-03 07:24 |
| src\cashcontrol\core\info\registry.py | read | 1 | 0 | 0 | 1 | 2026-06-22 08:14 |
| src\cashcontrol\core\info\rules.py | edit | 1 | 8 | 0 | 9 | 2026-06-23 07:41 |
| src\cashcontrol\core\mover\__init__.py | read | 0 | 0 | 0 | 4 | 2026-06-22 07:35 |
| src\cashcontrol\core\mover\executor.py | edit | 0 | 3 | 0 | 6 | 2026-06-23 07:51 |
| src\cashcontrol\core\mover\scenario.py | read | 0 | 0 | 0 | 3 | 2026-06-21 12:50 |
| src\cashcontrol\core\mover\steps\__init__.py | read | 0 | 0 | 0 | 5 | 2026-06-23 07:35 |
| src\cashcontrol\core\mover\steps\base.py | read | 0 | 0 | 0 | 2 | 2026-06-21 12:50 |
| src\cashcontrol\core\mover\steps\loymax.py | read | 0 | 0 | 0 | 3 | 2026-06-23 07:35 |
| src\cashcontrol\core\mover\steps\qrid.py | read | 0 | 0 | 0 | 3 | 2026-06-23 07:35 |
| src\cashcontrol\core\mover\steps\run_commands.py | read | 0 | 0 | 0 | 3 | 2026-06-23 07:35 |
| src\cashcontrol\core\mover\steps\set_com_port.py | read | 0 | 0 | 0 | 3 | 2026-06-23 07:35 |
| src\cashcontrol\core\mover\steps\upload_files.py | read | 0 | 0 | 0 | 3 | 2026-06-23 07:35 |
| src\cashcontrol\core\reinstall\__init__.py | read | 0 | 0 | 0 | 4 | 2026-06-22 07:35 |
| src\cashcontrol\core\reinstall\archive_scanner.py | read | 0 | 0 | 0 | 3 | 2026-06-21 12:50 |
| src\cashcontrol\core\reinstall\installer.py | read | 0 | 0 | 0 | 4 | 2026-06-21 12:50 |
| src\cashcontrol\core\reinstall\iso_extractor.py | edit | 0 | 2 | 0 | 6 | 2026-06-23 07:40 |
| src\cashcontrol\core\security\__init__.py | read | 0 | 0 | 0 | 4 | 2026-06-22 07:35 |
| src\cashcontrol\core\security\encryption.py | read | 0 | 0 | 0 | 5 | 2026-06-21 12:50 |
| src\cashcontrol\core\security\password_manager.py | read | 0 | 0 | 0 | 5 | 2026-06-21 12:50 |
| src\cashcontrol\core\session.py | write | 1 | 2 | 0 | 15 | 2026-07-03 07:23 |
| src\cashcontrol\core\ssh.py | edit | 0 | 4 | 0 | 17 | 2026-06-24 15:55 |
| src\cashcontrol\gui\__init__.py | write | 1 | 0 | 0 | 8 | 2026-07-03 07:23 |
| src\cashcontrol\gui\cash_session_widget.py | edit | 1 | 34 | 3 | 54 | 2026-07-02 08:04 |
| src\cashcontrol\gui\db_viewer_components.py | edit | 1 | 1 | 0 | 0 | 2026-06-22 09:44 |
| src\cashcontrol\gui\db_viewer_widget.py | edit | 1 | 9 | 0 | 18 | 2026-06-23 07:42 |
| src\cashcontrol\gui\dialogs\__init__.py | write | 1 | 0 | 0 | 3 | 2026-07-03 07:23 |
| src\cashcontrol\gui\dialogs\add_cash_dialog.py | read | 0 | 0 | 0 | 2 | 2026-06-21 12:50 |
| src\cashcontrol\gui\dialogs\alias_editor.py | read | 0 | 0 | 0 | 2 | 2026-06-21 12:50 |
| src\cashcontrol\gui\dialogs\command_editor.py | edit | 0 | 2 | 0 | 5 | 2026-06-23 07:40 |
| src\cashcontrol\gui\dialogs\command_result_dialog.py | read | 0 | 0 | 0 | 2 | 2026-06-21 12:50 |
| src\cashcontrol\gui\dialogs\help_content.py | write | 1 | 0 | 0 | 1 | 2026-06-24 15:55 |
| src\cashcontrol\gui\dialogs\help_css.py | write | 1 | 0 | 0 | 0 | 2026-06-22 09:36 |
| src\cashcontrol\gui\dialogs\help_dialog.py | write | 1 | 1 | 0 | 12 | 2026-06-22 09:37 |
| src\cashcontrol\gui\dialogs\logs_viewer.py | read | 0 | 0 | 0 | 2 | 2026-06-21 12:50 |
| src\cashcontrol\gui\dialogs\mover_dialog.py | read | 0 | 0 | 0 | 2 | 2026-06-21 12:50 |
| src\cashcontrol\gui\dialogs\mover_editor_dialog.py | read | 0 | 0 | 0 | 2 | 2026-06-21 12:50 |
| src\cashcontrol\gui\dialogs\mover_progress_dialog.py | edit | 0 | 3 | 0 | 4 | 2026-06-23 07:38 |
| src\cashcontrol\gui\dialogs\reinstall_dialog.py | edit | 0 | 1 | 0 | 2 | 2026-06-23 07:41 |
| src\cashcontrol\gui\dialogs\reinstall_progress_dialog.py | read | 0 | 0 | 0 | 3 | 2026-06-23 07:23 |
| src\cashcontrol\gui\dialogs\settings\__init__.py | read | 0 | 0 | 0 | 2 | 2026-07-02 08:02 |
| src\cashcontrol\gui\dialogs\settings\settings_dialog.py | read | 0 | 3 | 0 | 5 | 2026-07-02 08:02 |
| src\cashcontrol\gui\dialogs\settings\tab_connection.py | read | 0 | 0 | 0 | 4 | 2026-07-02 08:02 |
| src\cashcontrol\gui\dialogs\settings\tab_general.py | read | 0 | 0 | 0 | 2 | 2026-06-21 12:51 |
| src\cashcontrol\gui\dialogs\settings\tab_logs.py | read | 0 | 0 | 0 | 2 | 2026-06-21 12:51 |
| src\cashcontrol\gui\dialogs\settings\tab_programs.py | edit | 0 | 1 | 0 | 2 | 2026-06-23 07:41 |
| src\cashcontrol\gui\dialogs\settings\tab_updates.py | read | 0 | 0 | 0 | 2 | 2026-06-21 09:53 |
| src\cashcontrol\gui\dialogs\setup_wizard\__init__.py | read | 0 | 0 | 0 | 2 | 2026-06-22 07:35 |
| src\cashcontrol\gui\dialogs\setup_wizard\page_connection.py | read | 0 | 0 | 0 | 2 | 2026-06-21 12:51 |
| src\cashcontrol\gui\dialogs\setup_wizard\page_connection_test.py | edit | 0 | 4 | 0 | 8 | 2026-06-23 07:40 |
| src\cashcontrol\gui\dialogs\setup_wizard\page_finish.py | read | 0 | 0 | 0 | 2 | 2026-06-21 12:51 |
| src\cashcontrol\gui\dialogs\setup_wizard\page_programs.py | read | 0 | 0 | 0 | 3 | 2026-06-21 12:51 |
| src\cashcontrol\gui\dialogs\setup_wizard\page_welcome.py | read | 0 | 1 | 0 | 4 | 2026-06-21 12:51 |
| src\cashcontrol\gui\dialogs\setup_wizard\wizard.py | read | 0 | 0 | 0 | 3 | 2026-06-22 07:35 |
| src\cashcontrol\gui\history_manager.py | read | 0 | 0 | 0 | 3 | 2026-06-23 07:23 |
| src\cashcontrol\gui\main_window.py | edit | 0 | 25 | 0 | 29 | 2026-07-02 08:26 |
| src\cashcontrol\gui\notification_manager.py | read | 0 | 0 | 0 | 3 | 2026-06-21 12:50 |
| src\cashcontrol\gui\session_manager.py | write | 1 | 2 | 0 | 16 | 2026-07-03 07:24 |
| src\cashcontrol\gui\sidebar.py | read | 0 | 0 | 0 | 7 | 2026-07-02 08:03 |
| src\cashcontrol\gui\status_bar.py | read | 0 | 0 | 0 | 5 | 2026-06-24 15:55 |
| src\cashcontrol\gui\styles\fluent_tabs.qss | read | 0 | 0 | 0 | 1 | 2026-06-24 15:55 |
| src\cashcontrol\gui\styles\fluent_tabs_dark.qss | read | 0 | 0 | 0 | 1 | 2026-06-24 15:55 |
| src\cashcontrol\gui\styles\fluent_tabs_light.qss | read | 0 | 0 | 0 | 1 | 2026-06-24 15:55 |
| src\cashcontrol\gui\tab_bar.py | write | 4 | 5 | 0 | 8 | 2026-07-03 07:24 |
| src\cashcontrol\gui\tab_manager.py | edit | 0 | 31 | 0 | 32 | 2026-07-02 08:26 |
| src\cashcontrol\gui\theme_engine.py | read | 0 | 0 | 0 | 10 | 2026-06-24 15:55 |
| src\cashcontrol\gui\theme_helper.py | read | 0 | 0 | 0 | 5 | 2026-06-24 15:55 |
| src\cashcontrol\gui\toolbar.py | read | 0 | 21 | 0 | 36 | 2026-07-02 08:21 |
| src\cashcontrol\gui\vnc_preview.py | edit | 0 | 15 | 0 | 29 | 2026-06-23 07:41 |
| src\cashcontrol\gui\widgets\__init__.py | write | 1 | 0 | 0 | 4 | 2026-07-03 07:23 |
| src\cashcontrol\gui\widgets\info_section_widget.py | read | 1 | 0 | 0 | 5 | 2026-06-21 12:51 |
| src\cashcontrol\gui\widgets\virtual_keyboard.py | edit | 0 | 9 | 0 | 8 | 2026-06-23 07:41 |
| src\cashcontrol\infrastructure\__init__.py | write | 1 | 3 | 0 | 8 | 2026-07-03 07:23 |
| src\cashcontrol\infrastructure\audit_logger.py | write | 1 | 2 | 0 | 11 | 2026-07-03 07:23 |
| src\cashcontrol\infrastructure\command_loader.py | read | 0 | 0 | 0 | 8 | 2026-06-22 07:37 |
| src\cashcontrol\infrastructure\config_manager.py | write | 1 | 4 | 0 | 23 | 2026-07-03 07:23 |
| src\cashcontrol\infrastructure\hot_prefixes.json | write | 1 | 0 | 0 | 0 | 2026-07-02 08:28 |
| src\cashcontrol\infrastructure\hot_reload_manager.py | read | 0 | 2 | 0 | 11 | 2026-07-02 08:19 |
| src\cashcontrol\infrastructure\module_loader.py | write | 2 | 10 | 0 | 8 | 2026-07-02 22:49 |
| src\cashcontrol\infrastructure\path_resolver.py | write | 1 | 4 | 0 | 21 | 2026-07-03 07:23 |
| src\cashcontrol\infrastructure\update_client.py | read | 0 | 3 | 0 | 10 | 2026-07-02 08:19 |
| src\cashcontrol\main.py | edit | 0 | 7 | 0 | 13 | 2026-07-02 08:07 |
| test_db.py | edit | 2 | 10 | 0 | 3 | 2026-06-19 14:59 |
| test_sco3_db.py | write | 1 | 0 | 0 | 0 | 2026-06-22 09:27 |
| test_setup_db_unit.py | write | 1 | 0 | 0 | 0 | 2026-06-22 09:29 |
| tests\test_xml_parse_reference.py | edit | 2 | 4 | 0 | 0 | 2026-06-23 07:47 |
| update_manifest.bat | read | 0 | 0 | 0 | 5 | 2026-07-02 08:41 |
| update_modules.bat | write | 1 | 0 | 0 | 0 | 2026-07-02 08:41 |
| uv.lock | read_partial | 0 | 0 | 0 | 1 | 2026-06-22 07:37 |
| version.txt | write | 1 | 0 | 0 | 6 | 2026-07-03 07:23 |

## No content recovered

- _recovered_src\src\cashcontrol\core\db.py
- _recovered_src\src\cashcontrol\core\ssh.py
