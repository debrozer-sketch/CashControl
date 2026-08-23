; CashControl — Inno Setup 6 script (portable layout installer)
;
; Собирается из корня проекта ПОСЛЕ build.bat:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" CashControl.iss
; Результат: dist\installer\CashControl-setup-<version>.exe
;
; Установка per-user ({localappdata}\Programs\CashControl): не требует
; прав администратора и оставляет папку приложения доступной для записи —
; приложение хранит настройки в data/ рядом с exe.

#define MyAppName "CashControl"
#define MyAppExe "CashControl.exe"

#define VHandle FileOpen("version.txt")
#define MyAppVersion Trim(FileRead(VHandle))
#undef VHandle

[Setup]
AppId={{FEC403A3-DC59-4AB3-B8A4-A1FC432BAF08}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher=CashControl Team
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
PrivilegesRequired=lowest
UninstallDisplayName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
RestartApplications=no
OutputDir=dist\installer
OutputBaseFilename=CashControl-setup-{#MyAppVersion}
SetupIconFile=src\cashcontrol\gui\resources\icon.ico

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; \
    GroupDescription: "{cm:AdditionalIcons}"

[Files]
; data/ и logs/ никогда не входят в инсталлятор: это пользовательские данные,
; они создаются приложением на месте установки. Excludes страхует от случая,
; когда программу запускали из dist после сборки (иначе настройки, включая
; зашифрованные пароли, попали бы в setup.exe и удалялись деинсталлятором).
Source: "dist\CashControl\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs; \
    Excludes: "data,data\*,logs,logs\*"

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; WorkingDir: "{app}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; \
    Flags: nowait postinstall skipifsilent

[Uninstall]
; data/ и logs/ намеренно НЕ удаляются: настройки пользователя переживают
; обновление/переустановку. При полной деинсталляции удалите папку вручную.
