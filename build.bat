@echo off
setlocal
cd /d "%~dp0"

echo.
echo ============================================================
echo   CashControl - portable build (dist\CashControl)
echo ============================================================
echo.

where uv >nul 2>&1
if errorlevel 1 (
    echo ERROR: uv not found. Install: https://docs.astral.sh/uv/
    pause & exit /b 1
)

uv run python scripts/build_dist.py
if errorlevel 1 (
    echo.
    echo ERROR: build failed, see output above.
    pause & exit /b 1
)

echo.
echo Done: dist\CashControl\CashControl.cmd
echo Sanity check: move/rename the folder, then run it from there.
echo.
pause
