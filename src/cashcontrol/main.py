"""
CashControl — Entry point.

Initializes logging, config, async event loop, and launches the main window.
On first launch, shows setup wizard.
"""

from __future__ import annotations

import asyncio
import sys

from PySide6.QtWidgets import QApplication  # noqa: E402  # must be before qasync
import qasync  # noqa: E402

from cashcontrol import __app_name__, __version__  # noqa: E402
from cashcontrol.infrastructure.audit_logger import (  # noqa: E402
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


async def _startup_update_check(app_window) -> None:
    """Check for updates at startup using cc-updater.exe."""
    logger = get_logger()
    from cashcontrol.infrastructure.config_manager import ConfigManager

    cfg = ConfigManager().settings.update
    if not cfg.enabled:
        return

    from cashcontrol.infrastructure.update_client import UpdateClient

    client = UpdateClient(cfg.network_path)

    if UpdateClient.has_pending_cold():
        await client.apply_cold()
        UpdateClient.clear_pending()

    if not cfg.check_on_startup:
        return

    result = await client.check()
    if result.error:
        logger.warning(f"Update check error: {result.error}")
        return

    if not result.available:
        return

    if result.hot_files:
        applied = await client.apply_hot()
        if applied:
            from cashcontrol.gui.notification_manager import get_notification_manager
            app_window.set_status("Применяю hot-обновления…")
            from cashcontrol.infrastructure.hot_reload_manager import HotReloadManager
            from cashcontrol.infrastructure.path_resolver import get_app_root
            hr = HotReloadManager()
            app_root = get_app_root()
            for f in result.hot_files:
                hr.reload_module(app_root / f)
            get_notification_manager().notify(
                f"Обновлено файлов: {len(result.hot_files)}",
                level="success",
            )
            app_window.set_status("Готово")

    if result.cold_files:
        client.set_pending_cold()
        app_window.set_status(
            f"Доступно обновление v{result.new_version}. "
            f"Оно будет применено при следующем запуске."
        )
        from cashcontrol.gui.notification_manager import get_notification_manager
        get_notification_manager().notify(
            f"Доступно обновление v{result.new_version}. Перезапустите программу.",
            level="info",
        )


def main() -> None:
    """Application entry point."""
    setup_logger()
    logger = get_logger()
    audit_log(action_type="system", action_name="app_start", result="success")

    logger.info(f"Starting {__app_name__} v{__version__}")

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
        window = MainWindow()
        window.show()
        asyncio.ensure_future(_startup_update_check(window))

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