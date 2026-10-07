[Setup]
AppName=Melora
AppVersion=1.0.0
AppPublisher=Melora

DefaultDirName={autopf}\Melora
DefaultGroupName=Melora

OutputDir=installer
OutputBaseFilename=Melora-Setup

SetupIconFile=melora.ico

Compression=lzma
SolidCompression=yes

WizardStyle=modern

UninstallDisplayIcon={app}\Melora.exe


[Files]
Source: "dist\Melora\*"; DestDir: "{app}"; \
    Flags: ignoreversion recursesubdirs createallsubdirs


[Tasks]
Name: "desktopicon"; \
    Description: "Create a desktop shortcut"; \
    GroupDescription: "Additional shortcuts:"; \
    Flags: unchecked


[Icons]
Name: "{autoprograms}\Melora"; \
    Filename: "{app}\Melora.exe"

Name: "{autodesktop}\Melora"; \
    Filename: "{app}\Melora.exe"; \
    Tasks: desktopicon