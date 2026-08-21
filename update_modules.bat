@echo off
chcp 65001 > nul
echo.
echo ============================================================
echo   CashControl - Publish hot module update (no rebuild)
echo ============================================================
echo.

set MASTER_PATH=\\192.168.0.253\tmp\TEMP\SETRETAIL\CashControl

cd /d "%~dp0"

echo Master image path: %MASTER_PATH%
echo.
echo Copying hot modules (toolbar, dialogs, vnc, widgets) and
echo recalculating manifest...
echo (core files and version.txt are NOT touched)
echo.

uv run python scripts/make_master.py --output "%MASTER_PATH%" --modules-only

echo.
if %ERRORLEVEL% == 0 (
    echo SUCCESS: Hot modules published. Running clients will pick up
    echo the update within their next check cycle (no restart needed).
) else (
    echo ERROR: See output above.
)
echo.
pause
