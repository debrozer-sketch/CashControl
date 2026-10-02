@echo off
setlocal
cd /d "%~dp0"

where uv >nul 2>&1
if errorlevel 1 (
    echo ERROR: uv not found. Install: https://docs.astral.sh/uv/
    pause & exit /b 1
)

rem Без аргумента собираются оба варианта. Аргумент — только один из них,
rem когда нужен быстрый пересбор после правки.
if "%~1"=="" (
    call :build department
    if errorlevel 1 goto :fail
    call :build public
    if errorlevel 1 goto :fail
    goto :done
)
if /i "%~1"=="department" (
    call :build department
    if errorlevel 1 goto :fail
    goto :done
)
if /i "%~1"=="public" (
    call :build public
    if errorlevel 1 goto :fail
    goto :done
)
echo.
echo ERROR: unknown variant "%~1". Expected: department, public, or nothing for both.
pause & exit /b 1

:build
echo.
echo ============================================================
echo   CashControl - portable build + installer (%1)
echo ============================================================
echo.
uv run python scripts\build_dist.py --variant %1 --installer
if errorlevel 1 exit /b 1
exit /b 0

:fail
echo.
echo ERROR: build failed, see output above.
pause & exit /b 1

:done
set "VER=?"
if exist version.txt set /p VER=<version.txt
echo.
echo ============================================================
echo   Done. Two builds, each with its own folder and installer.
echo ============================================================
echo.
echo   Department  dist\CashControl\CashControl.cmd
echo               dist\installer\CashControl-setup-%VER%.exe
echo.
echo   Public      dist\CashControl-public\CashControl.cmd
echo               dist\installer\CashControl-public-setup-%VER%.exe
echo.
echo Sanity check: move/rename a folder, then run it from there.
echo.
pause
exit /b 0