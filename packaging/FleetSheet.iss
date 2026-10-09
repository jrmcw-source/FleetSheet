; =====================================================================
; FleetSheet.iss — Inno Setup script for FleetSheet (Windows, per-user)
;
; WHAT THIS BUILDS
;   A per-user installer (no admin / no UAC prompt) that installs
;   FleetSheet into %LOCALAPPDATA%\FleetSheet, with Start Menu shortcut,
;   optional desktop shortcut, and a standard uninstaller.
;
; BUILD MACHINE LAYOUT (relative to this .iss file)
;   packaging\
;     FleetSheet.iss
;     VERSION                  <-- copy from new-version/app/VERSION before compiling
;     stage\                   <-- assemble before compiling:
;       pythonw.exe            <-- bundled Python (embeddable package), alongside app\
;       app\app.py             <-- application entry point
;       app\...                <-- all application code (packages\, EULA.txt, etc.)
;       FleetSheet-Launcher.py <-- browser-window launcher (this workstream)
;       FleetSheet-Start.bat   <-- server start + browser open wrapper (this workstream)
;       EULA.txt               <-- maximal AS-IS / NO SUPPORT / NO LIABILITY EULA
;       README.txt
;
;   NEVER put fleetsheet.db / fleetsheet.db-wal / fleetsheet.db-shm or
;   fleetsheet-launch.log into stage\ — a shipped stub DB blocks first-run
;   seeding and breaks clean installs.
;
; COMPILE (on Windows, Inno Setup 6.x with ISPP):
;   iscc FleetSheet.iss
;   Output: packaging\output\FleetSheet-Setup-<VERSION>.exe
;
; SIGNING (see SIGNING.md — do this BEFORE distributing):
;   iscc /S"certsign=signtool sign /fd SHA256 /sha1 <THUMBPRINT> /tr http://timestamp.digicert.com /td SHA256 $p" FleetSheet.iss
;   (SignedUninstaller=yes below then also signs the uninstaller.)
; =====================================================================

#define MyAppName "FleetSheet"
#define MyAppPublisher "FleetSheet"
#define MyAppURL "https://github.com/jrmcw-source/FleetSheet"
#define MyAppExeName "pythonw.exe"

; --- Version: read from the VERSION file next to this script (one line,
; --- e.g. "2026-10-08u"). Falls back to "dev" if the file is missing.
#if FileExists(SourcePath + "\\VERSION")
  #define _VerHandle FileOpen(SourcePath + "\\VERSION")
  #define MyAppVersion Trim(FileRead(_VerHandle))
  #expr FileClose(_VerHandle)
#else
  #define MyAppVersion "dev"
#endif

[Setup]
AppId={{4402641A-35DB-474B-8A02-335602646ADA}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppVerName={#MyAppName} {#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppURL}
AppSupportURL={#MyAppURL}
AppUpdatesURL={#MyAppURL}

; --- Per-user install: NO admin / NO UAC prompt. This is the #1 install
; --- friction reducer for non-technical users on locked-down shop PCs.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog

; --- Install location: per-user, writable without elevation.
DefaultDirName={localappdata}\{#MyAppName}
DisableProgramGroupPage=yes
DefaultGroupName={#MyAppName}

; --- 64-bit bundled Python.
ArchitecturesInstallIn64BitMode=x64os
MinVersion=10.0

; --- Installer branding / UX.
WizardStyle=modern
SetupLogging=yes
Compression=lzma2/ultra64
SolidCompression=yes
OutputDir=.\output
OutputBaseFilename=FleetSheet-Setup-{#MyAppVersion}
UninstallDisplayName={#MyAppName} {#MyAppVersion}
; Uncomment and point at a real .ico when the project has one:
; SetupIconFile=stage\fleetsheet.ico
; UninstallDisplayIcon={app}\fleetsheet.ico

; --- Code signing (see SIGNING.md). Define the SignTool on the iscc
; --- command line; the uninstaller is signed too.
;SignTool=certsign $p
SignedUninstaller=yes

; --- EULA shown in the wizard (maximal AS-IS / NO SUPPORT / NO LIABILITY).
LicenseFile=stage\EULA.txt

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; Everything staged (code, bundled python, launchers, docs). The database
; is created at first run and is never part of the installer payload.
Source: "stage\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
; Start Menu + optional desktop shortcut. The .bat starts the server
; (with auto-open suppressed) and then opens the dedicated browser window.
Name: "{group}\{#MyAppName}"; Filename: "{app}\FleetSheet-Start.bat"; WorkingDir: "{app}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\FleetSheet-Start.bat"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\FleetSheet-Start.bat"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent shellexec

[Code]
// --- Pre-install: stop any running FleetSheet server so an upgrade never
// --- hits locked files. Targets only the process listening on FleetSheet's
// --- port (8765) — never blindly kills pythonw.exe, which may belong to
// --- other software.
const
  FleetSheetPort = '8765';

function KillPortOwner(const Port: string): Boolean;
var
  ResultCode: Integer;
  TmpFile, Line, Pid: string;
  Lines: TArrayOfString;
  I, P: Integer;
begin
  Result := False;
  TmpFile := ExpandConstant('{tmp}\fs_netstat.txt');
  // netstat -ano lists PID per connection; filter LISTENING on our port.
  // Exec cannot capture stdout, so redirect through cmd.
  if Exec('cmd.exe', '/c netstat -ano | findstr ":' + Port + '" | findstr "LISTENING" > "' + TmpFile + '"',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode) then
  begin
    if LoadStringsFromFile(TmpFile, Lines) then
    begin
      for I := 0 to GetArrayLength(Lines) - 1 do
      begin
        Line := Trim(Lines[I]);
        // Last whitespace-separated token on the line is the PID.
        P := Length(Line);
        while (P > 0) and (Line[P] <> ' ') and (Line[P] <> #9) do Dec(P);
        Pid := Trim(Copy(Line, P + 1, Length(Line)));
        if (Pid <> '') and (Pid <> '0') then
        begin
          Exec('taskkill.exe', '/F /PID ' + Pid, '', SW_HIDE,
               ewWaitUntilTerminated, ResultCode);
          Result := True;
        end;
      end;
    end;
    DeleteFile(TmpFile);
  end;
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
  // Best effort: a stale server from a previous install must not block
  // file replacement. Failures here are non-fatal.
  try
    KillPortOwner(FleetSheetPort);
  except
  end;
end;
