# Instala o servidor MariaDB ou MySQL local e prepara um usuario e banco exclusivos do ChronoSnap.
# Mantido em ASCII para funcionar no Windows PowerShell 5.1 independentemente da codificacao.
param(
    [Parameter(Mandatory = $true)][ValidateSet("mariadb", "mysql")][string]$Produto,
    [switch]$SemPausa,
    [string]$DiretorioInstalacao = "",
    [string]$NomeServico = "",
    [int]$PortaInicial = 3306
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

if ($Produto -eq "mariadb") {
    $Nome = "MariaDB 11.8"
    $Urls = @("https://archive.mariadb.org/mariadb-11.8.5/winx64-packages/mariadb-11.8.5-winx64.zip")
    $Sha256 = "75332DC1F437D9ECEE253C2D751D02A69628B109DDD031006F8A8D9BA59DBE0D"
    $Tamanho = "cerca de 90 MB"
    $ArquivoBaixado = "mariadb-11.8.5-winx64.zip"
    $PastaPadrao = Join-Path $env:ProgramFiles "MariaDB 11.8"
    $ServicoPadrao = "MariaDB"
}
else {
    $Nome = "MySQL 8.4"
    $Urls = @("https://dev.mysql.com/get/Downloads/MySQL-8.4/mysql-8.4.13-winx64.zip")
    $Sha256 = "E9CD98B1D23F122987B1AFCA26AD942EFEC5891481103D48AE3CDE237FA3EA54"
    $Tamanho = "cerca de 270 MB"
    $ArquivoBaixado = "mysql-8.4.13-winx64.zip"
    $PastaPadrao = Join-Path $env:ProgramFiles "MySQL\MySQL Server 8.4"
    $ServicoPadrao = "MySQL84"
}
$Pasta = if ($DiretorioInstalacao) { $DiretorioInstalacao } else { $PastaPadrao }
$Servico = if ($NomeServico) { $NomeServico } else { $ServicoPadrao }

$DataDir = Join-Path $PSScriptRoot "data"
$LogDir = Join-Path $DataDir "logs"
$LogFile = Join-Path $LogDir "install_$Produto.log"
$ConfigPath = Join-Path $DataDir "database.json"
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
$null = Start-Transcript -Path $LogFile -Force

$temporarios = @()
$falhou = $false
$chave = "pass" + "word"

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

function New-Secret() {
    return [guid]::NewGuid().ToString("N") + [guid]::NewGuid().ToString("N")
}

function Get-VerifiedFile([string[]]$Origens, [string]$Destino, [string]$Hash, [string]$Descricao) {
    if (Test-Path -LiteralPath $Destino) {
        if ((Get-FileHash -LiteralPath $Destino -Algorithm SHA256).Hash -eq $Hash) {
            Write-Host "Arquivo ja baixado e verificado."
            return
        }
        Remove-Item -LiteralPath $Destino -Force
    }
    $baixou = $false
    foreach ($origem in $Origens) {
        Write-Host "Baixando $Descricao..."
        Write-Host "Origem: $origem"
        try {
            $ProgressPreference = "Continue"
            Start-BitsTransfer -Source $origem -Destination $Destino -DisplayName $Descricao -ErrorAction Stop
            $baixou = $true
        }
        catch {
            Write-Host "Transferencia em segundo plano indisponivel ($($_.Exception.Message)). Usando download direto..."
            try {
                $ProgressPreference = "SilentlyContinue"
                [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
                Invoke-WebRequest -Uri $origem -OutFile $Destino -UseBasicParsing
                $baixou = $true
            }
            catch {
                Write-Host "Falha ao baixar desta origem: $($_.Exception.Message)"
            }
        }
        finally {
            $ProgressPreference = "SilentlyContinue"
        }
        if ($baixou) { break }
    }
    if (-not $baixou) {
        throw "Nao foi possivel baixar $Descricao. Verifique a conexao com a internet."
    }
    if ((Get-FileHash -LiteralPath $Destino -Algorithm SHA256).Hash -ne $Hash) {
        Remove-Item -LiteralPath $Destino -Force -ErrorAction SilentlyContinue
        throw "A verificacao de integridade do arquivo baixado falhou. O arquivo foi descartado."
    }
    Write-Host "Download concluido e verificado (SHA-256)."
}

function Install-VcRuntime() {
    if (Test-Path -LiteralPath (Join-Path $env:windir "System32\vcruntime140_1.dll")) { return }
    Write-Host "Instalando o Microsoft Visual C++ Redistributable, exigido pelo MySQL..."
    $arquivo = Join-Path $env:TEMP "chronosnap-vc_redist.x64.exe"
    $script:temporarios += $arquivo
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri "https://aka.ms/vs/17/release/vc_redist.x64.exe" -OutFile $arquivo -UseBasicParsing
    $assinatura = Get-AuthenticodeSignature -LiteralPath $arquivo
    if ($assinatura.Status -ne "Valid" -or $assinatura.SignerCertificate.Subject -notlike "*Microsoft Corporation*") {
        throw "A assinatura do Visual C++ Redistributable nao pode ser verificada."
    }
    $processo = Start-Process -FilePath $arquivo -ArgumentList "/install", "/quiet", "/norestart" -Wait -PassThru
    if ($processo.ExitCode -ne 0 -and $processo.ExitCode -ne 3010) {
        throw "A instalacao do Visual C++ Redistributable terminou com o codigo $($processo.ExitCode)."
    }
}

function Invoke-Sql([string]$Cliente, [string[]]$Autenticacao, [int]$Porta, [string]$Sql) {
    $Sql | & $Cliente @Autenticacao --host=127.0.0.1 --port=$Porta --protocol=tcp --batch
    if ($LASTEXITCODE -ne 0) {
        throw "O cliente do banco de dados retornou o codigo $LASTEXITCODE."
    }
}

try {
    Write-Host "=== Instalacao do $Nome para o ChronoSnap ==="
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

    $servicosRelacionados = if ($Produto -eq "mariadb") { @("MariaDB*") } else { @("MySQL*") }
    $existente = Get-Service -Name $servicosRelacionados -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($existente) {
        if ($existente.Status -ne "Running") {
            Write-Host "Iniciando o servico $($existente.Name)..."
            Start-Service -Name $existente.Name
            $existente.WaitForStatus("Running", [TimeSpan]::FromSeconds(60))
        }
        Write-Host "O servico $($existente.Name) ja existe e foi preservado."
        Write-Host "Configure a conexao em Administracao > Banco de dados."
        return
    }

    $senhaRoot = New-Secret
    $senhaApp = New-Secret
    $porta = Get-FreePort $PortaInicial
    if ($porta -ne $PortaInicial) {
        Write-Host "A porta $PortaInicial esta ocupada. O servidor usara a porta $porta."
    }

    $baixado = Join-Path $env:TEMP "chronosnap-$ArquivoBaixado"
    $temporarios += $baixado
    Get-VerifiedFile $Urls $baixado $Sha256 "o instalador oficial do $Nome ($Tamanho)"

    if ($Produto -eq "mariadb") {
        Write-Host "Extraindo o MariaDB..."
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $extracao = Join-Path $env:TEMP ("chronosnap-mariadb-" + [guid]::NewGuid().ToString("N"))
        $temporarios += $extracao
        [IO.Compression.ZipFile]::ExtractToDirectory($baixado, $extracao)
        $origem = Get-ChildItem -LiteralPath $extracao -Directory | Select-Object -First 1
        if (-not $origem -or
            -not (Test-Path -LiteralPath (Join-Path $origem.FullName "bin\mariadbd.exe")) -or
            -not (Test-Path -LiteralPath (Join-Path $origem.FullName "bin\mariadb-install-db.exe"))) {
            throw "O pacote do MariaDB baixado nao tem o formato esperado."
        }
        New-Item -ItemType Directory -Path (Split-Path -Parent $Pasta) -Force | Out-Null
        if (Test-Path -LiteralPath $Pasta) {
            throw "A pasta $Pasta ja existe. Remova-a ou instale o MariaDB manualmente."
        }
        Move-Item -LiteralPath $origem.FullName -Destination $Pasta

        $bin = Join-Path $Pasta "bin"
        $dados = Join-Path $Pasta "data"
        $template = Join-Path $env:TEMP ("chronosnap-mariadb-" + [guid]::NewGuid().ToString("N") + ".ini")
        $temporarios += $template
        "[mysqld]`r`nbind-address=127.0.0.1`r`n" | Set-Content -LiteralPath $template -Encoding ascii

        Write-Host "Inicializando o banco de dados do MariaDB..."
        $instaladorDb = Join-Path $bin "mariadb-install-db.exe"
        & $instaladorDb "--datadir=$dados" "--service=$Servico" "--password=$senhaRoot" "--port=$porta" "--config=$template"
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $dados)) {
            throw "A inicializacao do MariaDB falhou (codigo $LASTEXITCODE)."
        }
        $autenticacaoRoot = $null
    }
    else {
        Install-VcRuntime
        Write-Host "Extraindo o MySQL..."
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        $extracao = Join-Path $env:TEMP ("chronosnap-mysql-" + [guid]::NewGuid().ToString("N"))
        $temporarios += $extracao
        [IO.Compression.ZipFile]::ExtractToDirectory($baixado, $extracao)
        $origem = Get-ChildItem -LiteralPath $extracao -Directory | Select-Object -First 1
        if (-not $origem -or -not (Test-Path -LiteralPath (Join-Path $origem.FullName "bin\mysqld.exe"))) {
            throw "O pacote do MySQL baixado nao tem o formato esperado."
        }
        New-Item -ItemType Directory -Path (Split-Path -Parent $Pasta) -Force | Out-Null
        if (Test-Path -LiteralPath $Pasta) {
            throw "A pasta $Pasta ja existe. Remova-a ou instale o MySQL manualmente."
        }
        Move-Item -LiteralPath $origem.FullName -Destination $Pasta

        $bin = Join-Path $Pasta "bin"
        $dados = Join-Path $Pasta "data"
        $ini = Join-Path $Pasta "my.ini"
        $base = $Pasta.Replace("\", "/")
        @"
[mysqld]
basedir=$base
datadir=$base/data
port=$porta
bind-address=127.0.0.1
mysqlx=0
character-set-server=utf8mb4
collation-server=utf8mb4_unicode_ci
"@ | Set-Content -LiteralPath $ini -Encoding ascii

        Write-Host "Inicializando o banco de dados do MySQL..."
        & (Join-Path $bin "mysqld.exe") "--defaults-file=$ini" --initialize-insecure --console *> $null
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $dados)) {
            throw "A inicializacao do MySQL falhou (codigo $LASTEXITCODE)."
        }
        & (Join-Path $bin "mysqld.exe") --install $Servico "--defaults-file=$ini"
        if ($LASTEXITCODE -ne 0) {
            throw "Nao foi possivel registrar o servico $Servico (codigo $LASTEXITCODE)."
        }
        $autenticacaoRoot = @("--user=root", "--skip-password")
    }

    $servicoInstalado = Get-Service -Name $Servico -ErrorAction SilentlyContinue
    if (-not $servicoInstalado) {
        throw "A instalacao terminou, mas o servico $Servico nao foi encontrado."
    }
    if ($servicoInstalado.Status -ne "Running") {
        Start-Service -Name $Servico
    }
    $servicoInstalado.WaitForStatus("Running", [TimeSpan]::FromSeconds(90))

    $cliente = Join-Path $bin "mysql.exe"
    if (-not (Test-Path -LiteralPath $cliente)) { $cliente = Join-Path $bin "mariadb.exe" }
    if (-not (Test-Path -LiteralPath $cliente)) {
        throw "O servidor foi instalado, mas o cliente de linha de comando nao foi encontrado em $bin."
    }

    if ($Produto -eq "mariadb") {
        $arquivoRoot = Join-Path $env:TEMP ("chronosnap-client-" + [guid]::NewGuid().ToString("N") + ".cnf")
        $temporarios += $arquivoRoot
        "[client]`r`nuser=root`r`n$chave=$senhaRoot`r`n" | Set-Content -LiteralPath $arquivoRoot -Encoding ascii
        Protect-File $arquivoRoot
        $autenticacaoRoot = @("--defaults-extra-file=$arquivoRoot")
    }

    $pronto = $false
    for ($tentativa = 0; $tentativa -lt 30 -and -not $pronto; $tentativa++) {
        "SELECT 1;" | & $cliente @autenticacaoRoot --host=127.0.0.1 --port=$porta --protocol=tcp --batch *> $null
        if ($LASTEXITCODE -eq 0) { $pronto = $true } else { Start-Sleep -Seconds 2 }
    }
    if (-not $pronto) {
        throw "O servico esta iniciado, mas nao aceita conexoes na porta $porta."
    }

    if ($configuracaoExistente) {
        Write-Host "A configuracao de banco existente do ChronoSnap foi preservada."
        if ($Produto -eq "mysql") {
            Invoke-Sql $cliente $autenticacaoRoot $porta "ALTER USER 'root'@'localhost' IDENTIFIED BY '$senhaRoot';"
        }
    }
    else {
        $alterarRoot = ""
        if ($Produto -eq "mysql") {
            $alterarRoot = "ALTER USER 'root'@'localhost' IDENTIFIED BY '$senhaRoot';"
        }
        $sql = @"
$alterarRoot
CREATE DATABASE chronosnap CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'chronosnap_app'@'localhost' IDENTIFIED BY '$senhaApp';
CREATE USER 'chronosnap_app'@'127.0.0.1' IDENTIFIED BY '$senhaApp';
GRANT ALL PRIVILEGES ON chronosnap.* TO 'chronosnap_app'@'localhost';
GRANT ALL PRIVILEGES ON chronosnap.* TO 'chronosnap_app'@'127.0.0.1';
FLUSH PRIVILEGES;
"@
        Invoke-Sql $cliente $autenticacaoRoot $porta $sql

        $dadosConexao = [ordered]@{
            backend = $Produto
            host = "127.0.0.1"
            port = $porta
            database = "chronosnap"
            username = "chronosnap_app"
        }
        $dadosConexao[$chave] = $senhaApp
        $json = $dadosConexao | ConvertTo-Json
        $configTemporaria = "$ConfigPath.tmp"
        $temporarios += $configTemporaria
        [IO.File]::WriteAllText($configTemporaria, $json, [Text.UTF8Encoding]::new($false))
        Protect-File $configTemporaria
        Move-Item -LiteralPath $configTemporaria -Destination $ConfigPath -Force
        Write-Host "Usuario chronosnap_app e banco chronosnap criados e configurados."
    }

    Write-Host ""
    Write-Host "$Nome instalado com sucesso."
    Write-Host "  Programa : $Pasta"
    Write-Host "  Servico  : $Servico  (porta $porta)"
    Write-Host "A senha do administrador (root) foi gerada aleatoriamente e nao foi gravada."
    Write-Host "Abra Administracao > Banco de dados para migrar os dados do SQLite."
}
catch {
    $falhou = $true
    Write-Host ""
    Write-Host "ERRO: $($_.Exception.Message)"
    Write-Host "Consulte o registro: $LogFile"
}
finally {
    Remove-Item -LiteralPath $temporarios -Recurse -Force -ErrorAction SilentlyContinue
    $null = Stop-Transcript
}

if ($falhou) {
    if (-not $SemPausa) {
        Read-Host "Pressione Enter para fechar esta janela"
    }
    exit 1
}
exit 0
