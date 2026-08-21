@echo off
chcp 65001 > nul
cd /d "%~dp0"

echo.
echo ============================================================
echo   CashControl - Create Release
echo ============================================================
echo.

if not exist version.txt (
    echo ERROR: version.txt not found
    pause & exit /b 1
)

echo Current version:
type version.txt
echo.
echo.
set /p NEW_VERSION="Enter new version (e.g. 3.0.1): "
if "%NEW_VERSION%"=="" (
    echo Version not entered — cancelled.
    pause & exit /b 1
)

echo %NEW_VERSION% > version.txt
echo.
echo Version set to %NEW_VERSION%
echo.

echo === Building EXE ===
echo.
call build.bat
if errorlevel 1 (
    echo ERROR: Build failed — release aborted.
    pause & exit /b 1
)

echo.
echo === Publishing release ===
python -m scripts.cc_patcher release --version %NEW_VERSION%

echo.
if %ERRORLEVEL% == 0 (
    echo SUCCESS: Release %NEW_VERSION% published.
) else (
    echo ERROR: See output above.
)
echo.
pause
