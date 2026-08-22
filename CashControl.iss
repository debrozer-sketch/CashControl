; CashControl v3.0.0 - Inno Setup Script
; Compile with: Inno Setup Compiler (https://jrsoftware.org/isdl.php)
;
; Place this file in D:\Project\cashcontrol2\
; The compiled installer will appear in D:\Project\cashcontrol2\installer\

#define FileHandle FileOpen("version.txt")
#define MyAppVersion FileRead(FileHandle)
#expr FileClose(FileHandle)

#define AppName "CashControl"
#define AppVersion MyAppVersion
#define AppPublisher "CashControl Team"
#define AppExeName "CashControl.exe"
#define SourceDir "dist\CashControl"

[Setup]
AppId={{A1B2C3D4-E5F6-7890-ABCD-EF1234567890}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppVerName={#AppName} {#AppVersion}

; Installation directory — Program Files by default
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Always show the directory selection page (don't reuse last installed path)
DisableDirPage=no

; Output
OutputDir=installer
OutputBaseFilename=CashControl_Setup_{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
LZMAUseSeparateProcess=yes

; Appearance
WizardStyle=modern
SetupIconFile={#SourceDir}\icon.ico
UninstallDisplayIcon={app}\{#AppExeName}

; Require admin for Program Files install
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog

; Windows version check
MinVersion=10.0

; Don't allow running setup if app is already running
CloseApplications=yes
CloseApplicationsFilter=*.exe
RestartApplications=no

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; GroupDescription: "Дополнительно:"
Name: "startmenuicon"; Description: "Создать ярлык в меню Пуск"; GroupDescription: "Дополнительно:"

[Files]
; All files from dist\CashControl\ EXCEPT user data:
; data/logs создаются приложением на месте и не должны ни поставляться,
; ни перезаписываться при апгрейде поверх старой версии.
Source: "{#SourceDir}\*"; Excludes: "data,data\*,logs,logs\*,*.pyc"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start menu shortcut
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\icon.ico"; Tasks: startmenuicon
; Desktop shortcut
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; IconFilename: "{app}\icon.ico"; Tasks: desktopicon
; Uninstall in Start menu
Name: "{group}\Удалить {#AppName}"; Filename: "{uninstallexe}"; Tasks: startmenuicon

[Run]
; Offer to launch after install
Filename: "{app}\{#AppExeName}"; Description: "Запустить {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove user data on uninstall (logs, cache) — settings kept
Type: filesandordirs; Name: "{app}\logs"
; Uncomment below to also wipe settings/sessions on uninstall:
; Type: filesandordirs; Name: "{app}\data"

[Code]
// Check if app is running before uninstall
function InitializeUninstall(): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  if CheckForMutexes('{#AppName}') then begin
    MsgBox('{#AppName} сейчас запущен. Закройте программу и повторите.', mbError, MB_OK);
    Result := False;
  end;
end;