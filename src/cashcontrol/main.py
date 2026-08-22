"""
CashControl — Entry point.

Initializes logging, config, async event loop, and launches the main window.
On first launch, shows setup wizard.
"""

from __future__ import annotations

import asyncio
import sys

import qasync
from PySide6.QtWidgets import QApplication  # must be before qasync

from cashcontrol import __app_name__, __version__
from cashcontrol.infrastructure.audit_logger import (
    audit_log,
    get_logger,
    setup_logger,
)


def _install_async_exception_handler(loop: asyncio.AbstractEventLoop) -> None:
    """Install a global exception handler for unhandled async exceptions."""
    logger = get_logger()

    def handler(loop: asyncio.AbstractEventLoop, context: dict) -> None:
        exception = context.get("exception")
        message = context.get("message", "")

        if exception:
            # Ignore ConnectionResetError and similar network noise
            if isinstance(exception, (ConnectionResetError, BrokenPipeError)):
                logger.debug(f"Network error (ignored): {exception}")
                return
            logger.error(f"Unhandled async exception: {exception} | {message}")
            audit_log(
                action_type="system",
                action_name="async_error",
                result="failure",
                error_message=str(exception),
            )
        else:
            logger.warning(f"Async warning: {message}")

    loop.set_exception_handler(handler)


def main() -> None:
    """Application entry point."""
    setup_logger()
    logger = get_logger()
    audit_log(action_type="system", action_name="app_start", result="success")

    logger.info(f"Starting {__app_name__} v{__version__}")

    from cashcontrol.infrastructure.module_loader import install

    install()  # до любых импортов GUI — иначе excluded-модули не найдутся

    from cashcontrol.infrastructure.config_manager import ConfigManager

    config = ConfigManager()

    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)

    # Setup asyncio event loop — before any dialogs with async
    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)
    _install_async_exception_handler(loop)

    # Apply theme before any windows
    from cashcontrol.gui.theme_engine import ThemeEngine
    ThemeEngine.instance().apply(config.settings.general.theme)

    # Show main window (after wizard if first launch)
    def _show_main_window():
        from cashcontrol.gui.main_window import MainWindow
        global _main_window          # держим ссылку — иначе GC удалит окно
        _main_window = MainWindow()
        _main_window.show()

    # First launch — run setup wizard (after event loop starts)
    if config.is_first_launch:
        logger.info("First launch detected, showing setup wizard")
        from cashcontrol.gui.dialogs.setup_wizard import CashControlSetupWizard

        wizard = CashControlSetupWizard(config)
        from PySide6.QtCore import QTimer

        def _run_wizard():
            result = wizard.exec()
            if not result:
                logger.info("Setup wizard cancelled, exiting")
                sys.exit(0)
            _show_main_window()

        QTimer.singleShot(0, _run_wizard)
    else:
        _show_main_window()

    logger.info("Entering event loop")

    with loop:
        try:
            loop.run_forever()
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        finally:
            logger.info("Event loop exited")
            audit_log(action_type="system", action_name="app_exit", result="success")


if __name__ == "__main__":
    main()
