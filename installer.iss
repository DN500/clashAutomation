; Inno Setup script - compile with Inno Setup after running build.bat
[Setup]
AppName=Herta Capture
AppVersion=5.3
DefaultDirName={localappdata}\Programs\Herta Capture
DefaultGroupName=Herta Capture
PrivilegesRequired=lowest
OutputDir=installer
OutputBaseFilename=HertaCapture-Setup
Compression=lzma2
SolidCompression=yes
SetupIconFile=icon.ico

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"

[Files]
Source: "dist\HertaCapture\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\Herta Capture"; Filename: "{app}\HertaCapture.exe"
Name: "{autodesktop}\Herta Capture"; Filename: "{app}\HertaCapture.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\HertaCapture.exe"; Description: "Launch Herta Capture"; Flags: nowait postinstall skipifsilent
