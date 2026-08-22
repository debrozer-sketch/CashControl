@echo off
chcp 65001 > nul
setlocal EnableDelayedExpansion

set APP_NAME=CashControl
set ICON_PATH=src\cashcontrol\gui\resources\icon.ico
set ENTRY_POINT=src\cashcontrol\main.py
set NUITKA_OUT=dist\main.dist
set FINAL_OUT=dist\%APP_NAME%

cd /d "%~dp0"

echo [1/6] Syncing version and checking environment...
uv run python scripts/sync_version.py
if errorlevel 1 (
    echo ERROR: Version sync failed.
    pause & exit /b 1
)

REM Read version from version.txt (updated by sync_version.py)
set /p APP_VERSION=<version.txt
echo.
echo ============================================================
echo   CashControl v%APP_VERSION% - Build via Nuitka
echo ============================================================
echo.

where uv >nul 2>&1
if errorlevel 1 (
    echo ERROR: uv not found. Install from: https://docs.astral.sh/uv/
    pause & exit /b 1
)
uv run python -c "import nuitka" >nul 2>&1
if errorlevel 1 (
    echo ERROR: Nuitka not installed. Run: uv sync --group dev
    pause & exit /b 1
)
echo OK

echo.
echo [2/6] Cleaning previous build...
if exist "%NUITKA_OUT%" rmdir /s /q "%NUITKA_OUT%"
if exist "%FINAL_OUT%"  rmdir /s /q "%FINAL_OUT%"
echo OK

echo.
echo [3/6] Compiling with Nuitka (this may take several minutes)...
echo.

set ICON_FLAG=
if exist "%ICON_PATH%" set ICON_FLAG=--windows-icon-from-ico="%ICON_PATH%"

REM --no-debug-immortal-assumptions: PySide6 часто нарушает immortal refcount
REM --debug: если segfault повторится, даст детальный стек
set NUITKA_EXTRA=

uv run nuitka ^
    --standalone ^
    --windows-console-mode=attach ^
    %ICON_FLAG% ^
    --output-dir=dist ^
    --company-name="CashControl" ^
    --product-name=%APP_NAME% ^
    --file-version=%APP_VERSION%.0 ^
    --product-version=%APP_VERSION%.0 ^
    --file-description="Remote POS Terminal Management" ^
    --copyright="CashControl Team" ^
    --enable-plugin=pyside6 ^
    --nofollow-import-to=PySide6.QtWebEngine ^
    --nofollow-import-to=PySide6.QtWebEngineCore ^
    --nofollow-import-to=PySide6.QtWebEngineWidgets ^
    --nofollow-import-to=PySide6.QtWebEngineQuick ^
    --nofollow-import-to=PySide6.QtQuick ^
    --nofollow-import-to=PySide6.QtQml ^
    --nofollow-import-to=PySide6.Qt3D ^
    --nofollow-import-to=PySide6.QtCharts ^
    --nofollow-import-to=PySide6.QtDataVisualization ^
    --nofollow-import-to=PySide6.QtMultimedia ^
    --nofollow-import-to=PySide6.QtBluetooth ^
    --nofollow-import-to=PySide6.QtNfc ^
    --nofollow-import-to=PySide6.QtPositioning ^
    --nofollow-import-to=PySide6.QtLocation ^
    --nofollow-import-to=PySide6.QtSensors ^
    --nofollow-import-to=PySide6.QtSerialPort ^
    --nofollow-import-to=cashcontrol.gui.toolbar ^
    --nofollow-import-to=cashcontrol.gui.vnc_preview ^
    --nofollow-import-to=cashcontrol.gui.db_viewer_widget ^
    --nofollow-import-to=cashcontrol.gui.dialogs.command_editor ^
    --nofollow-import-to=cashcontrol.gui.dialogs.command_result_dialog ^
    --nofollow-import-to=cashcontrol.gui.dialogs.logs_viewer ^
    --nofollow-import-to=cashcontrol.gui.dialogs.help_dialog ^
    --nofollow-import-to=cashcontrol.gui.dialogs.alias_editor ^
    --nofollow-import-to=cashcontrol.gui.dialogs.add_cash_dialog ^
    --nofollow-import-to=cashcontrol.gui.dialogs.settings ^
    --nofollow-import-to=cashcontrol.gui.widgets ^
    --no-deployment-flag=excluded-module-usage ^
    --include-package=cashcontrol --include-package-data=cashcontrol.infrastructure:hot_prefixes.json ^
    --include-package=PySide6 ^
    --include-package=qfluentwidgets ^
    --include-package=qasync ^
    --include-package=asyncssh ^
    --include-package=asyncpg ^
    --include-package=pydantic ^
    --include-package=cryptography ^
    --include-package=loguru ^
    --include-package=win32api ^
    --include-package=win32crypt ^
    --include-package=numpy ^
    "%ENTRY_POINT%"

if errorlevel 1 (
    echo.
    echo ERROR: Compilation failed. See output above.
    pause & exit /b 1
)

echo.
echo [4/6] Copying external files to distribution...

if exist "%NUITKA_OUT%" (
    rename "%NUITKA_OUT%" "%APP_NAME%"
) else (
    echo WARNING: Folder %NUITKA_OUT% not found!
    pause & exit /b 1
)

REM Пользовательские данные НИКОГДА не попадают в сборку:
REM они создаются приложением на месте установки при первом запуске,
REM а апгрейд поверх старой версии их не трогает.
echo   [purge user data from dist]
if exist "%FINAL_OUT%\data" rmdir /s /q "%FINAL_OUT%\data"
if exist "%FINAL_OUT%\logs" rmdir /s /q "%FINAL_OUT%\logs"
if exist "%FINAL_OUT%\.pending_update" del /q "%FINAL_OUT%\.pending_update" 2>nul

echo   commands\...
if exist "commands" xcopy /s /q /y "commands" "%FINAL_OUT%\commands\" >nul

echo   collectors\...
if exist "collectors" xcopy /s /q /y "collectors" "%FINAL_OUT%\collectors\" >nul

echo   styles\...
if exist "styles" xcopy /s /q /y "styles" "%FINAL_OUT%\styles\" >nul

echo   soft\...
if exist "soft" (
    xcopy /s /q /y "soft" "%FINAL_OUT%\soft\" >nul
)

echo   docs\...
if exist "docs" xcopy /s /q /y "docs" "%FINAL_OUT%\docs\" >nul

echo   modules\...
if exist "modules" (
    xcopy /s /q /y "modules" "%FINAL_OUT%\modules\" >nul
) else (
    REM Build modules/ from source (Variant A — src is source of truth)
    if not exist "%FINAL_OUT%\modules" mkdir "%FINAL_OUT%\modules"
    if exist "src\cashcontrol\gui\dialogs" (
        mkdir "%FINAL_OUT%\modules\gui\dialogs\settings" 2>nul
        mkdir "%FINAL_OUT%\modules\gui\widgets\keyboard_layouts" 2>nul
        xcopy /y "src\cashcontrol\gui\toolbar.py" "%FINAL_OUT%\modules\gui\" >nul
        xcopy /y "src\cashcontrol\gui\vnc_preview.py" "%FINAL_OUT%\modules\gui\" >nul
        xcopy /y "src\cashcontrol\gui\db_viewer_widget.py" "%FINAL_OUT%\modules\gui\" >nul
        xcopy /y "src\cashcontrol\gui\dialogs\__init__.py" "%FINAL_OUT%\modules\gui\dialogs\" >nul
        for %%f in (command_editor command_result_dialog logs_viewer help_dialog alias_editor add_cash_dialog) do (
            if exist "src\cashcontrol\gui\dialogs\%%f.py" xcopy /y "src\cashcontrol\gui\dialogs\%%f.py" "%FINAL_OUT%\modules\gui\dialogs\" >nul
        )
        xcopy /y "src\cashcontrol\gui\dialogs\settings\__init__.py" "%FINAL_OUT%\modules\gui\dialogs\settings\" >nul
        for %%f in (settings_dialog tab_connection tab_general tab_logs tab_programs) do (
            if exist "src\cashcontrol\gui\dialogs\settings\%%f.py" xcopy /y "src\cashcontrol\gui\dialogs\settings\%%f.py" "%FINAL_OUT%\modules\gui\dialogs\settings\" >nul
        )
        xcopy /y "src\cashcontrol\gui\widgets\__init__.py" "%FINAL_OUT%\modules\gui\widgets\" >nul
        for %%f in (info_section_widget virtual_keyboard) do (
            if exist "src\cashcontrol\gui\widgets\%%f.py" xcopy /y "src\cashcontrol\gui\widgets\%%f.py" "%FINAL_OUT%\modules\gui\widgets\" >nul
        )
        if exist "src\cashcontrol\gui\widgets\keyboard_layouts" (
            xcopy /s /q /y "src\cashcontrol\gui\widgets\keyboard_layouts\*.json" "%FINAL_OUT%\modules\gui\widgets\keyboard_layouts\" >nul
        )
    )
)

if exist "%FINAL_OUT%\main.exe" rename "%FINAL_OUT%\main.exe" "%APP_NAME%.exe"

echo   icon.ico...
if exist "%ICON_PATH%" copy /y "%ICON_PATH%" "%FINAL_OUT%\icon.ico" >nul

echo   version.txt...
if exist "version.txt" copy /y "version.txt" "%FINAL_OUT%\version.txt" >nul


echo.
echo [5/6] Removing unused Qt components...

if exist "%FINAL_OUT%\QtWebEngineProcess.exe"             del /q "%FINAL_OUT%\QtWebEngineProcess.exe"
if exist "%FINAL_OUT%\icudtl.dat"                         del /q "%FINAL_OUT%\icudtl.dat"
if exist "%FINAL_OUT%\v8_context_snapshot.bin"            del /q "%FINAL_OUT%\v8_context_snapshot.bin"
if exist "%FINAL_OUT%\qtwebengine_resources.pak"          del /q "%FINAL_OUT%\qtwebengine_resources.pak"
if exist "%FINAL_OUT%\qtwebengine_resources_100p.pak"     del /q "%FINAL_OUT%\qtwebengine_resources_100p.pak"
if exist "%FINAL_OUT%\qtwebengine_resources_200p.pak"     del /q "%FINAL_OUT%\qtwebengine_resources_200p.pak"
if exist "%FINAL_OUT%\qtwebengine_devtools_resources.pak" del /q "%FINAL_OUT%\qtwebengine_devtools_resources.pak"
if exist "%FINAL_OUT%\qt6.conf"                           del /q "%FINAL_OUT%\qt6.conf"
if exist "%FINAL_OUT%\Qt6WebEngine.dll"                   del /q "%FINAL_OUT%\Qt6WebEngine.dll"
if exist "%FINAL_OUT%\Qt6WebEngineCore.dll"               del /q "%FINAL_OUT%\Qt6WebEngineCore.dll"
if exist "%FINAL_OUT%\Qt6WebEngineWidgets.dll"            del /q "%FINAL_OUT%\Qt6WebEngineWidgets.dll"
if exist "%FINAL_OUT%\Qt6WebChannel.dll"                  del /q "%FINAL_OUT%\Qt6WebChannel.dll"
if exist "%FINAL_OUT%\Qt6Positioning.dll"                 del /q "%FINAL_OUT%\Qt6Positioning.dll"
if exist "%FINAL_OUT%\Qt6Quick.dll"                       del /q "%FINAL_OUT%\Qt6Quick.dll"
if exist "%FINAL_OUT%\Qt6QuickWidgets.dll"                del /q "%FINAL_OUT%\Qt6QuickWidgets.dll"
if exist "%FINAL_OUT%\Qt6Qml.dll"                         del /q "%FINAL_OUT%\Qt6Qml.dll"
if exist "%FINAL_OUT%\Qt6QmlModels.dll"                   del /q "%FINAL_OUT%\Qt6QmlModels.dll"
if exist "%FINAL_OUT%\Qt6QmlWorkerScript.dll"             del /q "%FINAL_OUT%\Qt6QmlWorkerScript.dll"
if exist "%FINAL_OUT%\Qt6Charts.dll"                      del /q "%FINAL_OUT%\Qt6Charts.dll"
if exist "%FINAL_OUT%\Qt6DataVisualization.dll"           del /q "%FINAL_OUT%\Qt6DataVisualization.dll"
if exist "%FINAL_OUT%\Qt6Multimedia.dll"                  del /q "%FINAL_OUT%\Qt6Multimedia.dll"
if exist "%FINAL_OUT%\Qt6MultimediaWidgets.dll"           del /q "%FINAL_OUT%\Qt6MultimediaWidgets.dll"
if exist "%FINAL_OUT%\Qt6Bluetooth.dll"                   del /q "%FINAL_OUT%\Qt6Bluetooth.dll"
if exist "%FINAL_OUT%\Qt6Location.dll"                    del /q "%FINAL_OUT%\Qt6Location.dll"
if exist "%FINAL_OUT%\Qt6Sensors.dll"                     del /q "%FINAL_OUT%\Qt6Sensors.dll"
if exist "%FINAL_OUT%\Qt6SerialPort.dll"                  del /q "%FINAL_OUT%\Qt6SerialPort.dll"
if exist "%FINAL_OUT%\Qt6Nfc.dll"                         del /q "%FINAL_OUT%\Qt6Nfc.dll"
if exist "%FINAL_OUT%\Qt63DCore.dll"                      del /q "%FINAL_OUT%\Qt63DCore.dll"
if exist "%FINAL_OUT%\Qt63DRender.dll"                    del /q "%FINAL_OUT%\Qt63DRender.dll"
if exist "%FINAL_OUT%\Qt63DAnimation.dll"                 del /q "%FINAL_OUT%\Qt63DAnimation.dll"
if exist "%FINAL_OUT%\Qt63DInput.dll"                     del /q "%FINAL_OUT%\Qt63DInput.dll"
if exist "%FINAL_OUT%\Qt63DLogic.dll"                     del /q "%FINAL_OUT%\Qt63DLogic.dll"
if exist "%FINAL_OUT%\Qt63DExtras.dll"                    del /q "%FINAL_OUT%\Qt63DExtras.dll"

if exist "%FINAL_OUT%\PySide6\qt-plugins\position"    rmdir /s /q "%FINAL_OUT%\PySide6\qt-plugins\position"
if exist "%FINAL_OUT%\PySide6\qt-plugins\geoservices" rmdir /s /q "%FINAL_OUT%\PySide6\qt-plugins\geoservices"
if exist "%FINAL_OUT%\PySide6\qt-plugins\sensors"     rmdir /s /q "%FINAL_OUT%\PySide6\qt-plugins\sensors"
if exist "%FINAL_OUT%\PySide6\qt-plugins\audio"       rmdir /s /q "%FINAL_OUT%\PySide6\qt-plugins\audio"

echo   Trimming Qt translations to ru only...
for %%f in ("%FINAL_OUT%\PySide6\translations\*.qm") do (
    echo %%~nf | findstr /i "_ru" >nul || del /q "%%f"
)

echo   Done.

echo.
echo ============================================================
echo   BUILD SUCCESSFUL!
echo ============================================================
echo.
echo   Result: %FINAL_OUT%\
echo   EXE:    %FINAL_OUT%\%APP_NAME%.exe
echo.
REM Remove Nuitka build cache (intermediate C files, not needed after build)
if exist "dist\main.build" rmdir /s /q "dist\main.build"

pause
