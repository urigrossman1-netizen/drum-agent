; Inno Setup script for the Drum Agent installer (DrumAgent-Setup.exe).
;   iscc /DAppVersion=1.0.0 packaging\windows\DrumAgent.iss
; It packs dist\DrumAgent (the PyInstaller folder, with tools\ inside). It installs for the
; current user (no administrator rights): %LOCALAPPDATA%\Programs\Drum Agent. The user's charts
; (%LOCALAPPDATA%\Drum Agent) are kept when the app is uninstalled.

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{8C1F4D7E-2B6A-4E59-9A3D-6F0B7C2E5A41}
AppName=Drum Agent
AppVersion={#AppVersion}
AppVerName=Drum Agent {#AppVersion}
AppPublisher=Drum Agent
AppPublisherURL=https://github.com/urigrossman1-netizen/drum-agent
AppSupportURL=https://github.com/urigrossman1-netizen/drum-agent/issues
DefaultDirName={localappdata}\Programs\Drum Agent
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=DrumAgent-Setup
SetupIconFile=..\..\build\drum-agent.ico
UninstallDisplayIcon={app}\DrumAgent.exe
UninstallDisplayName=Drum Agent
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes

[Tasks]
Name: "desktopicon"; Description: "Put Drum Agent on the desktop"; Flags: checkedonce

[Files]
Source: "..\..\dist\DrumAgent\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\Drum Agent"; Filename: "{app}\DrumAgent.exe"
Name: "{autodesktop}\Drum Agent"; Filename: "{app}\DrumAgent.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\DrumAgent.exe"; Description: "Open Drum Agent now"; Flags: nowait postinstall skipifsilent
