# Instala o servidor PostgreSQL local e prepara um usuario e banco exclusivos do ChronoSnap.
# Mantido em ASCII para funcionar no Windows PowerShell 5.1 independentemente da codificacao.
param([switch]$SemPausa)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$InstallerUrl = "https://get.enterprisedb.com/postgresql/postgresql-18.6-5-windows-x64.exe"
$InstallerSha256 = "227E2BC08091B4C2B8338C7D61B11D057F895711480B006F90BFCFCD2410A58A"
$PgMajor = "18"
$PgHome = Join-Path $env:ProgramFiles "PostgreSQL\$PgMajor"

$DataDir = Join-Path $PSScriptRoot "data"
$LogDir = Join-Path $DataDir "logs"
$LogFile = Join-Path $LogDir "install_postgresql.log"
$ConfigPath = Join-Path $DataDir "database.json"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$null = Start-Transcript -Path $LogFile -Force

$temporarios = @()
$falhou = $false

function Protect-File([string]$Path) {
    $usuario = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    & icacls $Path /inheritance:r /grant:r "${usuario}:(F)" *> $null
    if ($LASTEXITCODE -ne 0) {
        throw "Nao foi possivel proteger o arquivo $Path."
    }
}

function Get-FreePort([int]$Start) {
    for ($porta = $Start; $porta -lt ($Start + 50); $porta++) {
        $listener = $null
        try {
            $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Any, $porta)
            $listener.Start()
            return $porta
        }
        catch { }
        finally {
            if ($listener) { $listener.Stop() }
        }
    }
    throw "Nenhuma porta livre encontrada a partir de $Start."
}

function Get-OfficialInstaller([string]$Destino) {
    if (Test-Path -LiteralPath $Destino) {
        if ((Get-FileHash -LiteralPath $Destino -Algorithm SHA256).Hash -eq $InstallerSha256) {
            Write-Host "Instalador ja baixado e verificado."
            return
        }
        Remove-Item -LiteralPath $Destino -Force
    }
    Write-Host "Baixando o instalador oficial do PostgreSQL $PgMajor (cerca de 380 MB)..."
    Write-Host "Origem: $InstallerUrl"
    try {
        $ProgressPreference = "Continue"
        Start-BitsTransfer -Source $InstallerUrl -Destination $Destino -DisplayName "PostgreSQL" -ErrorAction Stop
    }
    catch {
        Write-Host "Transferencia em segundo plano indisponivel ($($_.Exception.Message)). Usando download direto..."
        $ProgressPreference = "SilentlyContinue"
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $InstallerUrl -OutFile $Destino -UseBasicParsing
    }
    finally {
        $ProgressPreference = "SilentlyContinue"
    }
    if ((Get-FileHash -LiteralPath $Destino -Algorithm SHA256).Hash -ne $InstallerSha256) {
        Remove-Item -LiteralPath $Destino -Force -ErrorAction SilentlyContinue
        throw "A verificacao de integridade do instalador PostgreSQL falhou. O arquivo baixado foi descartado."
    }
    Write-Host "Download concluido e verificado (SHA-256)."
}

try {
    Write-Host "=== Instalacao do PostgreSQL para o ChronoSnap ==="
    Write-Host "Registro desta instalacao: $LogFile"

    $principal = [Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        throw "E necessario executar o instalador como administrador."
    }

    $configuracaoExistente = $false
    if (Test-Path -LiteralPath $ConfigPath) {
        try {
            $atual = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
            $configuracaoExistente = $atual.backend -ne "sqlite"
        }
        catch {
            $configuracaoExistente = $true
        }
    }

    $servico = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($servico) {
        if ($servico.Status -ne "Running") {
            Write-Host "Iniciando o servico $($servico.Name)..."
            Start-Service -Name $servico.Name
            $servico.WaitForStatus("Running", [TimeSpan]::FromSeconds(60))
        }
        Write-Host "O servico $($servico.Name) ja existe e foi preservado."
        Write-Host "Configure a conexao em Administracao > Banco de dados."
        return
    }

    $senhaAdmin = [guid]::NewGuid().ToString("N").ToUpper() + [guid]::NewGuid().ToString("N") + "Aa1!"
    $senhaApp = [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
    $porta = Get-FreePort 5432
    if ($porta -ne 5432) {
        Write-Host "A porta 5432 esta ocupada. O PostgreSQL usara a porta $porta."
    }

    $instalador = Join-Path $env:TEMP "chronosnap-postgresql-$PgMajor.exe"
    $temporarios += $instalador
    Get-OfficialInstaller $instalador

    $opcoes = Join-Path $env:TEMP ("chronosnap-postgresql-" + [guid]::NewGuid().ToString("N") + ".ini")
    $temporarios += $opcoes
    @"
mode=unattended
unattendedmodeui=minimal
superpassword=$senhaAdmin
serverport=$porta
enable-components=server,commandlinetools
disable-components=pgAdmin,stackbuilder
"@ | Set-Content -LiteralPath $opcoes -Encoding ascii
    Protect-File $opcoes

    Write-Host "Instalando o servidor PostgreSQL. Isso pode levar alguns minutos..."
    $processo = Start-Process -FilePath $instalador -ArgumentList "--optionfile", "`"$opcoes`"" -Wait -PassThru
    if ($processo.ExitCode -ne 0) {
        $logEdb = Join-Path $env:TEMP "install-postgresql.log"
        if (Test-Path -LiteralPath $logEdb) {
            Write-Host "--- ultimas linhas do registro do instalador PostgreSQL ---"
            Get-Content -LiteralPath $logEdb -Tail 25 | ForEach-Object { Write-Host $_ }
        }
        throw "O instalador do PostgreSQL terminou com o codigo $($processo.ExitCode)."
    }

    $servico = Get-Service -Name "postgresql*" -ErrorAction SilentlyContinue | Select-Object -First 1
    if (-not $servico) {
        throw "A instalacao terminou, mas o servico do PostgreSQL nao foi encontrado."
    }
    if ($servico.Status -ne "Running") {
        Start-Service -Name $servico.Name
    }
    $servico.WaitForStatus("Running", [TimeSpan]::FromSeconds(60))

    $psql = Join-Path $PgHome "bin\psql.exe"
    $pgIsReady = Join-Path $PgHome "bin\pg_isready.exe"
    if (-not (Test-Path -LiteralPath $psql)) {
        throw "O PostgreSQL foi instalado, mas o cliente psql nao foi encontrado em $PgHome."
    }
    $pronto = $false
    for ($tentativa = 0; $tentativa -lt 30 -and -not $pronto; $tentativa++) {
        & $pgIsReady -h localhost -p $porta *> $null
        if ($LASTEXITCODE -eq 0) { $pronto = $true } else { Start-Sleep -Seconds 2 }
    }
    if (-not $pronto) {
        throw "O servico do PostgreSQL esta iniciado, mas nao aceita conexoes na porta $porta."
    }

    if ($configuracaoExistente) {
        Write-Host "A configuracao de banco existente do ChronoSnap foi preservada."
    }
    else {
        $arquivoSql = Join-Path $env:TEMP ("chronosnap-postgresql-" + [guid]::NewGuid().ToString("N") + ".sql")
        $temporarios += $arquivoSql
        @"
CREATE ROLE chronosnap_app LOGIN PASSWORD '$senhaApp';
CREATE DATABASE chronosnap OWNER chronosnap_app;
"@ | Set-Content -LiteralPath $arquivoSql -Encoding ascii
        Protect-File $arquivoSql

        $env:PGPASSWORD = $senhaAdmin
        & $psql -h localhost -p $porta -U postgres -d postgres -v ON_ERROR_STOP=1 -f $arquivoSql *> $null
        if ($LASTEXITCODE -ne 0) {
            throw "Nao foi possivel criar o usuario e o banco exclusivos do ChronoSnap."
        }

        $dados = [ordered]@{
            backend = "postgresql"
            host = "localhost"
            port = $porta
            database = "chronosnap"
            username = "chronosnap_app"
            password = $senhaApp
        } | ConvertTo-Json
        $configTemporaria = "$ConfigPath.tmp"
        $temporarios += $configTemporaria
        [IO.File]::WriteAllText($configTemporaria, $dados, [Text.UTF8Encoding]::new($false))
        Protect-File $configTemporaria
        Move-Item -LiteralPath $configTemporaria -Destination $ConfigPath -Force
        Write-Host "Usuario chronosnap_app e banco chronosnap criados e configurados."
    }

    Write-Host ""
    Write-Host "PostgreSQL $PgMajor instalado com sucesso."
    Write-Host "  Programa : $PgHome"
    Write-Host "  Dados    : $(Join-Path $PgHome 'data')"
    Write-Host "  Servico  : $($servico.Name)  (porta $porta)"
    Write-Host "Abra Administracao > Banco de dados para migrar os dados do SQLite."
}
catch {
    $falhou = $true
    Write-Host ""
    Write-Host "ERRO: $($_.Exception.Message)"
    Write-Host "Consulte o registro: $LogFile"
}
finally {
    Remove-Item -LiteralPath $temporarios -Force -ErrorAction SilentlyContinue
    Remove-Item Env:PGPASSWORD -ErrorAction SilentlyContinue
    $null = Stop-Transcript
}

if ($falhou) {
    if (-not $SemPausa) {
        Read-Host "Pressione Enter para fechar esta janela"
    }
    exit 1
}
exit 0
