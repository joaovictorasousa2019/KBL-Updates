#define MyAppName "KBL Hub"
#ifndef MyAppVersion
  #define MyAppVersion "2.2.0"
#endif
#ifndef HubExe
  #define HubExe "dist\\KBL Hub.exe"
#endif
#ifndef PythonInstaller
  #define PythonInstaller "python-installer.exe"
#endif
#ifndef GhExe
  #define GhExe "gh.exe"
#endif

[Setup]
AppId={{B64B3D6E-2D78-4B8D-A4A6-4A59424C4855}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=KBL
DefaultDirName={localappdata}\KBL\Hub
DefaultGroupName=KBL
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
SetupIconFile=kbl_hub.ico
UninstallDisplayIcon={app}\KBL Hub.exe
OutputDir=output
OutputBaseFilename=KBL_Hub_Setup_v{#MyAppVersion}
CloseApplications=yes
RestartApplications=no
DisableProgramGroupPage=yes
DisableReadyPage=no
AllowNoIcons=yes
VersionInfoVersion={#MyAppVersion}.0
VersionInfoCompany=KBL
VersionInfoDescription=Instalador do KBL Hub
VersionInfoProductName=KBL Hub
VersionInfoProductVersion={#MyAppVersion}

[Files]
Source: "{#HubExe}"; DestDir: "{app}"; DestName: "KBL Hub.exe"; Flags: ignoreversion
Source: "bundled_catalog.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#GhExe}"; DestDir: "{app}\tools"; DestName: "gh.exe"; Flags: ignoreversion
Source: "{#PythonInstaller}"; DestDir: "{tmp}"; DestName: "python-installer.exe"; Flags: deleteafterinstall

[Icons]
Name: "{autoprograms}\KBL Hub"; Filename: "{app}\KBL Hub.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\KBL Hub"; Filename: "{app}\KBL Hub.exe"; WorkingDir: "{app}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; GroupDescription: "Atalhos:"; Flags: checkedonce

[Run]
Filename: "{tmp}\python-installer.exe"; Parameters: "/quiet InstallAllUsers=0 TargetDir=""{localappdata}\KBL\Runtime\Python312"" Include_pip=1 Include_tcltk=1 Include_test=0 Include_doc=0 Include_dev=0 Include_launcher=0 AssociateFiles=0 PrependPath=0 Shortcuts=0"; StatusMsg: "Instalando o runtime dos módulos KBL..."; Check: not PythonRuntimeExists; Flags: waituntilterminated
Filename: "{app}\KBL Hub.exe"; Description: "Abrir KBL Hub"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: files; Name: "{app}\KBL Hub.exe"
Type: files; Name: "{app}\bundled_catalog.json"
Type: filesandordirs; Name: "{app}\tools"

[Code]
function PythonRuntimeExists(): Boolean;
begin
  Result := FileExists(ExpandConstant('{localappdata}\KBL\Runtime\Python312\python.exe'));
end;

function InitializeSetup(): Boolean;
begin
  Result := True;
end;