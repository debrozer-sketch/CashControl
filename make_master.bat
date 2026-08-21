@echo off
chcp 65001 > nul
echo.
echo ============================================================
echo   CashControl - Create master image
echo ============================================================
echo.

set MASTER_PATH=\\192.168.0.253\tmp\TEMP\SETRETAIL\CashControl

cd /d "%~dp0"

echo Master image path: %MASTER_PATH%
echo.
echo Copying files and generating manifest...
echo.

uv run python scripts/make_master.py --output "%MASTER_PATH%"

echo.
if %ERRORLEVEL% == 0 (
    echo SUCCESS: Master image created at %MASTER_PATH%
) else (
    echo ERROR: See output above.
)
echo.
pause