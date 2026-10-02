; Inno Setup script for the existing ZYRA application.
#define MyAppName "ZYRA"
#define MyAppVersion "1.0.0"
#define MyAppExeName "ZYRA.exe"

[Setup]
AppId={{D6F263D5-7B7D-4E5F-9F37-ZYRA2026}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\ZYRA
DefaultGroupName=ZYRA
OutputBaseFilename=ZYRA-Setup
OutputDir=installer-output
Compression=lzma
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}

[Files]
Source: "dist\ZYRA\ZYRA.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\ZYRA\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\ZYRA"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\ZYRA"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon
[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch ZYRA"; Flags: nowait postinstall skipifsilent
