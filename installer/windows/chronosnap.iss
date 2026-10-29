; Instalador Windows do ChronoSnap (Inno Setup 6)
#ifndef AppVersion
  #define AppVersion "1.0.5"
#endif
#ifndef StageDir
  #define StageDir "..\..\build\work\stage"
#endif
#ifndef OutDir
  #define OutDir "..\..\build\out"
#endif

[Setup]
AppId={{6B1F6E54-5C3A-4B5E-9A52-3C0F1E7C0A11}
AppName=ChronoSnap
AppVersion={#AppVersion}
AppPublisher=Tetsuo Rodolfo Okubo
DefaultDirName={autopf}\ChronoSnap
DefaultGroupName=ChronoSnap
DisableProgramGroupPage=yes
; O usuário pode escolher o local de instalação
DisableDirPage=no
LicenseFile={#StageDir}\LICENSE.txt
OutputDir={#OutDir}
OutputBaseFilename=ChronoSnap-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\chronosnap.ico
CloseApplications=yes
UsePreviousTasks=no

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho do Manager na área de trabalho"; GroupDescription: "Atalhos:"

[Dirs]
; Dados locais; gravável por usuários comuns e preservado em atualizações e na desinstalação.
Name: "{app}\data"; Permissions: users-modify

[Files]
Source: "{#StageDir}\server\*"; DestDir: "{app}\server"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#StageDir}\manager\*"; DestDir: "{app}\manager"; Flags: recursesubdirs createallsubdirs ignoreversion
Source: "{#StageDir}\LICENSE.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourcePath}\..\..\assets\chronosnap.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourcePath}\install_postgresql.ps1"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourcePath}\install_mariadb_mysql.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\ChronoSnap Manager"; Filename: "{app}\manager\ChronoSnapManager.exe"; WorkingDir: "{app}\manager"; IconFilename: "{app}\manager\ChronoSnapManager.exe"
Name: "{autodesktop}\ChronoSnap Manager"; Filename: "{app}\manager\ChronoSnapManager.exe"; WorkingDir: "{app}\manager"; IconFilename: "{app}\manager\ChronoSnapManager.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\manager\ChronoSnapManager.exe"; Description: "Abrir o ChronoSnap Manager"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/F /IM ChronoSnapServer.exe"; Flags: runhidden; RunOnceId: "StopServer"

[Code]
procedure InstalarPostgreSQL();
var
  ResultCode: Integer;
  Parametros: String;
begin
  WizardForm.StatusLabel.Caption := 'Instalando o PostgreSQL. Acompanhe a janela do instalador (pode levar alguns minutos)...';
  Parametros := '-NoProfile -ExecutionPolicy Bypass -File "' + ExpandConstant('{app}\install_postgresql.ps1') + '"';
  if WizardSilent then
    Parametros := Parametros + ' -SemPausa';
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'), Parametros, '', SW_SHOWNORMAL, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
    SuppressibleMsgBox(
      'O ChronoSnap foi instalado, mas o PostgreSQL não pôde ser instalado.' + #13#10 +
      'O sistema usará o SQLite até que o PostgreSQL seja instalado ou configurado.' + #13#10#13#10 +
      'Detalhes da falha: ' + ExpandConstant('{app}\data\logs\install_postgresql.log'),
      mbError, MB_OK, IDOK);
end;

procedure InstalarMySQLCompativel(Produto, Nome: String);
var
  ResultCode: Integer;
  Parametros, LogFile: String;
begin
  WizardForm.StatusLabel.Caption := 'Instalando o ' + Nome + '. Isso pode levar alguns minutos...';
  Parametros := '-NoProfile -ExecutionPolicy Bypass -File "' +
    ExpandConstant('{app}\install_mariadb_mysql.ps1') + '" -Produto ' + Produto;
  if WizardSilent then
    Parametros := Parametros + ' -SemPausa';
  if not Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
    Parametros, '', SW_SHOWNORMAL, ewWaitUntilTerminated, ResultCode) or (ResultCode <> 0) then
  begin
    LogFile := ExpandConstant('{app}\data\logs\install_' + Produto + '.log');
    SuppressibleMsgBox(
      'O ChronoSnap foi instalado, mas o ' + Nome + ' nao pode ser instalado.' + #13#10 +
      'O SQLite continua disponivel como banco padrao.' + #13#10#13#10 +
      'Consulte o registro: ' + LogFile,
      mbError, MB_OK, IDOK);
  end;
end;

var
  PaginaBancoLocal: TWizardPage;
  TipoServidorLocal: TNewComboBox;
  PaginaBanco: TWizardPage;
  UsarOutroBanco: TNewCheckBox;
  TipoBanco: TNewComboBox;
  EditServidor, EditPorta, EditBanco, EditUsuario, EditSenha: TNewEdit;
  RotuloBanco: TNewStaticText;

function ChaveProvedor(): String;
begin
  case TipoBanco.ItemIndex of
    0: Result := 'mysql';
    1: Result := 'mariadb';
    2: Result := 'mssql';
    3: Result := 'oracle';
  else
    Result := 'postgresql';
  end;
end;

function PortaPadrao(): String;
begin
  case TipoBanco.ItemIndex of
    0, 1: Result := '3306';
    2: Result := '1433';
    3: Result := '1521';
  else
    Result := '5432';
  end;
end;

procedure AtualizarCamposBanco();
var
  Ativo: Boolean;
begin
  Ativo := UsarOutroBanco.Checked;
  TipoBanco.Enabled := Ativo;
  EditServidor.Enabled := Ativo;
  EditPorta.Enabled := Ativo;
  EditBanco.Enabled := Ativo;
  EditUsuario.Enabled := Ativo;
  EditSenha.Enabled := Ativo;
end;

procedure UsarOutroBancoClick(Sender: TObject);
begin
  AtualizarCamposBanco();
end;

procedure TipoBancoChange(Sender: TObject);
begin
  EditPorta.Text := PortaPadrao();
  if TipoBanco.ItemIndex = 3 then
    RotuloBanco.Caption := 'Service name:'
  else
    RotuloBanco.Caption := 'Nome do banco de dados:';
end;

function NovoRotulo(Pagina: TWizardPage; Texto: String; Topo: Integer): TNewStaticText;
begin
  Result := TNewStaticText.Create(Pagina);
  Result.Parent := Pagina.Surface;
  Result.Caption := Texto;
  Result.Left := 0;
  Result.Top := ScaleY(Topo);
end;

function NovoCampo(Pagina: TWizardPage; Topo, Largura: Integer): TNewEdit;
begin
  Result := TNewEdit.Create(Pagina);
  Result.Parent := Pagina.Surface;
  Result.Left := 0;
  Result.Top := ScaleY(Topo);
  Result.Width := Largura;
end;

procedure InitializeWizard();
var
  Larg: Integer;
  Nota: TNewStaticText;
begin
  PaginaBancoLocal := CreateCustomPage(wpSelectTasks, 'Banco de dados',
    'SQLite e recomendado e permanece como padrao. Opcionalmente, baixe e configure um servidor local.');
  Larg := PaginaBancoLocal.SurfaceWidth;
  NovoRotulo(PaginaBancoLocal, 'Opcao de banco de dados:', 0);
  TipoServidorLocal := TNewComboBox.Create(PaginaBancoLocal);
  TipoServidorLocal.Parent := PaginaBancoLocal.Surface;
  TipoServidorLocal.Style := csDropDownList;
  TipoServidorLocal.Left := 0;
  TipoServidorLocal.Top := ScaleY(20);
  TipoServidorLocal.Width := Larg;
  TipoServidorLocal.Items.Add('SQLite (padrao; nao instala servidor)');
  TipoServidorLocal.Items.Add('Instalar PostgreSQL local (download de cerca de 380 MB)');
  TipoServidorLocal.Items.Add('Instalar MariaDB local (download de cerca de 90 MB)');
  TipoServidorLocal.Items.Add('Instalar MySQL local (download de cerca de 270 MB)');
  TipoServidorLocal.ItemIndex := 0;
  Nota := NovoRotulo(PaginaBancoLocal,
    'A instalacao de um servidor requer internet e privilegios de administrador. SQLite nao baixa nem instala outro servidor.',
    58);
  Nota.AutoSize := False;
  Nota.WordWrap := True;
  Nota.Width := Larg;
  Nota.Height := ScaleY(44);

  PaginaBanco := CreateCustomPage(PaginaBancoLocal.ID, 'Conectar a outro banco existente',
    'Conecte o ChronoSnap a um servidor de banco de dados existente (opcional).');
  Larg := PaginaBanco.SurfaceWidth;

  UsarOutroBanco := TNewCheckBox.Create(PaginaBanco);
  UsarOutroBanco.Parent := PaginaBanco.Surface;
  UsarOutroBanco.Caption := 'Usar um banco de dados alternativo em vez do SQLite';
  UsarOutroBanco.Left := 0;
  UsarOutroBanco.Top := ScaleY(0);
  UsarOutroBanco.Width := Larg;
  UsarOutroBanco.OnClick := @UsarOutroBancoClick;

  NovoRotulo(PaginaBanco, 'Tipo de banco:', 28);
  TipoBanco := TNewComboBox.Create(PaginaBanco);
  TipoBanco.Parent := PaginaBanco.Surface;
  TipoBanco.Style := csDropDownList;
  TipoBanco.Left := 0;
  TipoBanco.Top := ScaleY(42);
  TipoBanco.Width := Larg;
  TipoBanco.Items.Add('MySQL');
  TipoBanco.Items.Add('MariaDB');
  TipoBanco.Items.Add('SQL Server');
  TipoBanco.Items.Add('Oracle');
  TipoBanco.Items.Add('PostgreSQL (servidor existente)');
  TipoBanco.ItemIndex := 0;
  TipoBanco.OnChange := @TipoBancoChange;

  NovoRotulo(PaginaBanco, 'Servidor:', 72);
  EditServidor := NovoCampo(PaginaBanco, 88, Larg - ScaleX(90));
  EditServidor.Text := 'localhost';
  Nota := NovoRotulo(PaginaBanco, 'Porta:', 72);
  Nota.Left := Larg - ScaleX(80);
  EditPorta := NovoCampo(PaginaBanco, 88, ScaleX(80));
  EditPorta.Left := Larg - ScaleX(80);
  EditPorta.Text := '3306';

  RotuloBanco := NovoRotulo(PaginaBanco, 'Nome do banco de dados:', 116);
  EditBanco := NovoCampo(PaginaBanco, 132, Larg);
  EditBanco.Text := 'chronosnap';

  NovoRotulo(PaginaBanco, 'Usuario:', 160);
  EditUsuario := NovoCampo(PaginaBanco, 176, (Larg - ScaleX(12)) div 2);
  EditUsuario.Text := 'chronosnap_app';

  Nota := NovoRotulo(PaginaBanco, 'Senha:', 160);
  Nota.Left := (Larg + ScaleX(12)) div 2;
  EditSenha := NovoCampo(PaginaBanco, 176, (Larg - ScaleX(12)) div 2);
  EditSenha.Left := (Larg + ScaleX(12)) div 2;
  EditSenha.PasswordChar := '*';

  Nota := NovoRotulo(PaginaBanco, 'O banco e o usuario precisam existir. As tabelas sao criadas automaticamente na primeira inicializacao do servidor.', 212);
  Nota.AutoSize := False;
  Nota.WordWrap := True;
  Nota.Width := Larg;
  Nota.Height := ScaleY(36);

  AtualizarCamposBanco();
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := False;
  if (PaginaBanco <> nil) and (PageID = PaginaBanco.ID) then
    Result := (TipoServidorLocal <> nil) and (TipoServidorLocal.ItemIndex <> 0);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Porta: Integer;
begin
  Result := True;
  if (CurPageID = PaginaBanco.ID) and UsarOutroBanco.Checked then
  begin
    Porta := StrToIntDef(Trim(EditPorta.Text), 0);
    if (Trim(EditServidor.Text) = '') or (Trim(EditBanco.Text) = '') or (Trim(EditUsuario.Text) = '') then
    begin
      MsgBox('Informe servidor, banco de dados e usuario.', mbError, MB_OK);
      Result := False;
    end
    else if (Porta < 1) or (Porta > 65535) then
    begin
      MsgBox('A porta deve estar entre 1 e 65535.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function EscaparJson(const Valor: String): String;
var
  I: Integer;
  C: Char;
  Codigo: Integer;
  Hex: String;
begin
  Result := '';
  for I := 1 to Length(Valor) do
  begin
    C := Valor[I];
    Codigo := Ord(C);
    if C = '\' then
      Result := Result + '\\'
    else if C = '"' then
      Result := Result + '\"'
    else if (Codigo < 32) or (Codigo > 126) then
    begin
      Hex := Format('%.4x', [Codigo]);
      Result := Result + '\u' + Hex;
    end
    else
      Result := Result + C;
  end;
end;

procedure GravarBancoAlternativo();
var
  Caminho, Json, Usuario: String;
  ResultCode: Integer;
begin
  Caminho := ExpandConstant('{app}\data\database.json');
  Json := '{' + #13#10 +
    '  "backend": "' + ChaveProvedor() + '",' + #13#10 +
    '  "host": "' + EscaparJson(Trim(EditServidor.Text)) + '",' + #13#10 +
    '  "port": ' + IntToStr(StrToIntDef(Trim(EditPorta.Text), 0)) + ',' + #13#10 +
    '  "database": "' + EscaparJson(Trim(EditBanco.Text)) + '",' + #13#10 +
    '  "username": "' + EscaparJson(Trim(EditUsuario.Text)) + '",' + #13#10 +
    '  "password": "' + EscaparJson(EditSenha.Text) + '"' + #13#10 +
    '}' + #13#10;
  if not SaveStringToFile(Caminho, Json, False) then
  begin
    SuppressibleMsgBox('Nao foi possivel gravar a configuracao do banco de dados. Configure-o depois em Configuracoes > Banco de dados.',
      mbError, MB_OK, IDOK);
    Exit;
  end;
  Usuario := GetUserNameString();
  Exec(ExpandConstant('{sys}\icacls.exe'),
    '"' + Caminho + '" /inheritance:r /grant:r "*S-1-5-18:(F)" "*S-1-5-32-544:(F)" "' + Usuario + ':(F)"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep <> ssPostInstall then
    Exit;
  case TipoServidorLocal.ItemIndex of
    1:
      InstalarPostgreSQL();
    2:
      InstalarMySQLCompativel('mariadb', 'MariaDB');
    3:
      InstalarMySQLCompativel('mysql', 'MySQL');
  else
    if UsarOutroBanco.Checked then
      GravarBancoAlternativo();
  end;
end;
