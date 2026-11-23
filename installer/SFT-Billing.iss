; SFT Billing v2 installer.  Build:  ISCC installer\SFT-Billing.iss   (needs _stage\ built first, see README)
#define AppName "SFT Billing"
#define AppVersion "2.0.0"

[Setup]
AppId={{B3A5C0D2-7E41-4C8A-9F63-2D1E8A6B4C70}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Surfine Technology
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
OutputDir=output
OutputBaseFilename=SFT-Billing-Setup-v{#AppVersion}
SetupIconFile=app.ico
UninstallDisplayIcon={app}\sft_billing.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\_stage\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\sft_billing.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\sft_billing.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\sft_billing.exe"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

[Code]
var
  ModePage: TInputOptionWizardPage;
  FilePage: TInputFileWizardPage;

function DataDir: String;
begin
  Result := ExpandConstant('{localappdata}\SFT Billing');
end;

function HasExistingData: Boolean;
begin
  Result := FileExists(DataDir + '\sft_billing.db');
end;

procedure InitializeWizard;
begin
  ModePage := CreateInputOptionPage(wpSelectDir,
    'How do you want to set up this PC?', 'Choose how SFT Billing should start on this computer.',
    '', True, False);
  ModePage.Add('Clean installation — start fresh with a new user and an empty workspace');
  ModePage.Add('Copy from another PC — load a data file made with "Copy data" on your other PC');
  ModePage.SelectedValueIndex := 0;

  FilePage := CreateInputFilePage(ModePage.ID,
    'Choose the data file', 'Select the .sftpack file you copied from your other PC.',
    'The new PC will still create its own user and password.');
  FilePage.Add('Data file:', 'SFT Billing data file (*.sftpack)|*.sftpack', '.sftpack');

  { Scripted installs: SFT-Billing-Setup.exe /RESTORE="C:\path\data.sftpack" }
  if ExpandConstant('{param:RESTORE|}') <> '' then
  begin
    ModePage.SelectedValueIndex := 1;
    FilePage.Values[0] := ExpandConstant('{param:RESTORE|}');
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = FilePage.ID) and (ModePage.SelectedValueIndex <> 1);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if CurPageID = FilePage.ID then
    if (FilePage.Values[0] = '') or (not FileExists(FilePage.Values[0])) then
    begin
      MsgBox('Please choose the data file to copy from.', mbError, MB_OK);
      Result := False;
    end;
  if (CurPageID = ModePage.ID) and (ModePage.SelectedValueIndex = 0) and HasExistingData then
    Result := MsgBox('This PC already has SFT Billing data.' + #13#10 + #13#10 +
      'A clean installation moves the existing data aside (it is kept in a folder named "SFT Billing.old") and starts empty.' + #13#10 + #13#10 +
      'Continue?', mbConfirmation, MB_YESNO) = IDYES;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  OldDir: String;
begin
  if CurStep <> ssPostInstall then Exit;

  if ModePage.SelectedValueIndex = 0 then
  begin
    { Clean installation: keep any old data aside, never delete it }
    if HasExistingData then
    begin
      OldDir := DataDir + '.old';
      if DirExists(OldDir) then DelTree(OldDir, True, True, True);
      RenameFile(DataDir, OldDir);
    end;
    ForceDirectories(DataDir);
  end
  else
  begin
    { Copy from another PC: the app loads this file on first launch, before the account step }
    if HasExistingData then
    begin
      OldDir := DataDir + '.old';
      if DirExists(OldDir) then DelTree(OldDir, True, True, True);
      RenameFile(DataDir, OldDir);
    end;
    ForceDirectories(DataDir + '\import');
    CopyFile(FilePage.Values[0], DataDir + '\import\restore.sftpack', False);
  end;
end;
