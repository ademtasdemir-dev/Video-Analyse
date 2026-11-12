; Setup für YVdctuAio (Inno Setup 6). Wird von installer\bauen.py aufgerufen:
;   ISCC /DVersion=1.1.0 /DStufe=...\build\stufe /DWerkzeuge=...\build\werkzeuge /DAusgabe=...\build installer\YVdctuAio.iss
; Installiert ohne Administratorrechte in den Benutzerordner. Analysen und Einstellungen liegen getrennt davon
; in %LOCALAPPDATA%\YVdctuAio\daten und bleiben bei einem Update erhalten.

#ifndef Version
  #define Version "1.1.0"
#endif

[Setup]
AppId={{6E1B6C0E-52C7-4B5E-9D43-7A6F0C1E2A11}
AppName=YVdctuAio
AppVersion={#Version}
AppVerName=YVdctuAio {#Version}
AppPublisher=LAG|ZERØ
AppPublisherURL=https://github.com/ademtasdemir-dev/YVdctuAio
AppSupportURL=https://github.com/ademtasdemir-dev/YVdctuAio
VersionInfoVersion={#Version}.0
VersionInfoDescription=YVdctuAio Setup
DefaultDirName={autopf}\YVdctuAio
DefaultGroupName=YVdctuAio
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#Ausgabe}
OutputBaseFilename=YVdctuAio_Setup_{#Version}
SetupIconFile={#Stufe}\app\ui\icon.ico
UninstallDisplayIcon={app}\YVdctuAio.exe
UninstallDisplayName=YVdctuAio
LicenseFile={#Stufe}\LIZENZEN.txt
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
LZMANumBlockThreads=6
AppMutex=YVdctuAio_laeuft
CloseApplications=no

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktop"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#Stufe}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#Werkzeuge}\vc_redist.x64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: LaufzeitFehlt

[Icons]
Name: "{group}\YVdctuAio"; Filename: "{app}\YVdctuAio.exe"; WorkingDir: "{app}"
Name: "{group}\{cm:UninstallProgram,YVdctuAio}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\YVdctuAio"; Filename: "{app}\YVdctuAio.exe"; WorkingDir: "{app}"; Tasks: desktop

[Run]
; Die Microsoft-Laufzeit wird nur installiert, wenn sie fehlt. Windows fragt dafür einmal nach Administratorrechten.
Filename: "{tmp}\vc_redist.x64.exe"; Parameters: "/install /quiet /norestart"; StatusMsg: "{cm:Laufzeit}"; Check: LaufzeitFehlt; Flags: waituntilterminated
Filename: "{app}\YVdctuAio.exe"; Description: "{cm:LaunchProgram,YVdctuAio}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Was das Programm selbst im Programmordner anlegt (übersetzte Python-Dateien), räumt die Deinstallation mit weg.
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\app"
Type: filesandordirs; Name: "{app}\modelle"

[CustomMessages]
de.Laufzeit=Microsoft Visual C++ Laufzeit wird eingerichtet …
en.Laufzeit=Installing the Microsoft Visual C++ runtime …
de.DatenLoeschen=Sollen auch alle Analysen, Einstellungen und nachgeladenen Modelle von YVdctuAio gelöscht werden?%n%n%1%n%nNein lässt sie auf dem PC, zum Beispiel für eine spätere Neuinstallation.
en.DatenLoeschen=Also delete all analyses, settings and downloaded models of YVdctuAio?%n%n%1%n%nNo keeps them on this PC, for example for a later reinstall.

[Code]
function LaufzeitFehlt: Boolean;
begin
  Result := not FileExists(ExpandConstant('{sys}\msvcp140.dll')) or not FileExists(ExpandConstant('{sys}\vcruntime140_1.dll'));
end;

procedure CurUninstallStepChanged(Schritt: TUninstallStep);
var
  Daten: String;
begin
  if Schritt = usPostUninstall then
  begin
    Daten := ExpandConstant('{localappdata}\YVdctuAio');
    if DirExists(Daten) then
      if UninstallSilent or (MsgBox(FmtMessage(CustomMessage('DatenLoeschen'), [Daten]), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES) then
        if not UninstallSilent or (ExpandConstant('{param:DATENLOESCHEN|0}') = '1') then
          DelTree(Daten, True, True, True);
  end;
end;
