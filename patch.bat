@echo off
chcp 65001 > nul
cd /d "%~dp0"

if "%~1"=="" (
    echo Использование: patch.bat "Описание изменений"
    echo.
    echo Пример: patch.bat "Исправлена проверка ФР"
    pause
    exit /b 1
)

echo.
echo === CashControl - Publish Patch ===
echo.

python -m scripts.cc_patcher publish --description "%~1"

echo.
if %ERRORLEVEL% == 0 (
    echo SUCCESS: Patch published.
) else (
    echo ERROR: See output above.
)
echo.
pause
