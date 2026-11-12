; Inno Setup script for Ghost Macro Recorder.
; Build with:  ISCC.exe installer\GhostMacroRecorder.iss   (build.ps1 does this for you)
; Installs into C:\Program Files\Ghost Macro Recorder, adds Start Menu (and optional
; desktop) shortcuts, and registers an uninstaller in Settings > Apps.

#define AppName "Ghost Macro Recorder"
#define AppVersion "1.0.3"
#define AppPublisher "Ghost Macro Recorder"
#define AppExe "GhostMacroRecorder.exe"

[Setup]
AppId={{6E3B8C1A-4F2D-4C77-9B1E-2A5D9F0C7E41}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
; Fixed name so .../releases/latest/download/GhostMacroRecorder-Setup.exe always works
OutputBaseFilename=GhostMacroRecorder-Setup
SetupIconFile=..\assets\app.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
LicenseFile=..\LICENSE
CloseApplications=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\GhostMacroRecorder\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
; In-app updates run this installer with /SILENT: open the app again afterwards, as the user.
Filename: "{app}\{#AppExe}"; Flags: nowait runasoriginaluser; Check: WizardSilent

[UninstallDelete]
; Everything in the install folder goes, including files the app created after installing.
; (Your macros and settings live in %APPDATA%\GhostMacroRecorder and are kept.)
Type: filesandordirs; Name: "{app}"
Type: files; Name: "{userstartup}\{#AppName}.lnk"

[Code]
// The app hides in the tray instead of closing, so Windows' "close the app" request
// can't shut it down. End it ourselves before files are replaced or removed.
procedure CloseRunningApp();
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM {#AppExe}', '', SW_HIDE,
    ewWaitUntilTerminated, ResultCode);
  Sleep(700);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  CloseRunningApp();
  Result := '';
end;

function InitializeUninstall(): Boolean;
begin
  CloseRunningApp();
  Result := True;
end;

// Remove the "Start with Windows" entry the app may have added for this user.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'GhostMacroRecorder');
end;
