@echo off
chcp 65001 > nul
echo.
echo ============================================================
echo   CashControl - Recalculate manifest
echo ============================================================
echo.

set MASTER_PATH=\\192.168.0.253\tmp\TEMP\SETRETAIL\CashControl

cd /d "%~dp0"

echo Master image path: %MASTER_PATH%
echo.
echo Recalculating SHA-256 and updating manifest.json...
echo (files are not copied)
echo.

uv run python scripts/make_master.py --output "%MASTER_PATH%" --manifest-only

echo.
if %ERRORLEVEL% == 0 (
    echo SUCCESS: Manifest updated. Clients will receive update on next check.
) else (
    echo ERROR: See output above.
)
echo.
pause