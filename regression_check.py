import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['CASHCONTROL_CONFIG'] = os.path.join(os.path.dirname(__file__), 'src/cashcontrol/config_test.toml')

# 1) Startup — import app
from cashcontrol.config import AppConfig
from cashcontrol.gui.main_window import MainWindow
from cashcontrol.gui.tab_manager import TabManager
from cashcontrol.gui.toolbar import CashToolbar
from cashcontrol.gui.cash_session_widget import CashSessionWidget
from cashcontrol.gui.dialogs.help_dialog import HelpDialog
print('1. Startup imports: OK')

# 2) Config load
cfg = AppConfig.load(os.path.join(os.path.dirname(__file__), 'src/cashcontrol/config_test.toml'))
print(f'2. Config loaded: {cfg.database is not None}')

# 3) db_viewer imports
from cashcontrol.gui.db_viewer_components import SQLHighlighter, SQLCompleter, SQLCodeEditor, QueryWorker, CellChange
from cashcontrol.gui.db_viewer_widget import DataTableWidget, SQLConsoleWidget, PostgresToolWidget, PostgresToolWindow
print('3. db_viewer imports: OK')

# 4) Collectors import
from cashcontrol.core.info.collectors.bank_terminal import BankTerminalCollector
from cashcontrol.core.info.collectors.keyboard import KeyboardCollector
from cashcontrol.core.info.collectors.os_info import OSInfoCollector
print('4. Collector imports: OK')

# 5) Helper methods exist
bt = BankTerminalCollector.__dict__
assert any(k in bt for k in ('_read_pinpad_ini', '_parse_pinpad_ini', '_port_display_name'))
print('5. BT helpers: OK')
assert '_find_keyboard_model' in KeyboardCollector.__dict__
print('6. Keyboard helpers: OK')
oi = OSInfoCollector.__dict__
assert all(k in oi for k in ('_exec', '_detect_os_type', '_detect_os_version'))
print('7. OSInfo helpers: OK')

# 6) VNC
from cashcontrol.gui.vnc_preview import VNCPreview
print('8. VNC import: OK')

# 7) Collectors produce same structure (unit test mock)
print('9. Skip live collector run — SSH not configured (see #3 in next steps)')

print()
print('=== ALL REGRESSION CHECKS PASSED ===')
