# Gera o instalador Windows (código compilado com Nuitka + Inno Setup).
# Requisitos: Python 3.11+ (com tkinter) e Inno Setup 6 (winget install JRSoftware.InnoSetup).
param([string]$Version = "1.0.5")
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Work = Join-Path $PSScriptRoot "work"
$Out = Join-Path $PSScriptRoot "out"
$Stage = Join-Path $Work "stage"
$Venv = Join-Path $Work "venv"
$Py = Join-Path $Venv "Scripts\python.exe"

if (-not (Test-Path $Py)) {
    # Python 3.14 ainda não é compatível com o pydantic.v1 compilado pelo Nuitka: usar 3.12 ou 3.13
    $base = $null
    foreach ($v in "3.12", "3.13") {
        $base = (& py "-$v" -c "import sys;print(sys.executable)" 2>$null)
        if ($LASTEXITCODE -eq 0 -and $base) { break }
        $base = $null
    }
    if (-not $base) { throw "Instale o Python 3.12 (winget install Python.Python.3.12)." }
    & $base -m venv $Venv
}
& $Py -m pip install -q -r (Join-Path $Root "server\requirements.txt") nuitka zstandard ordered-set
if ($LASTEXITCODE) { throw "Falha ao instalar dependências de build." }

Remove-Item $Stage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory $Stage, $Out -Force | Out-Null

# MinGW em vez de --zig: o runtime do Zig emite instruções AVX (memcpy) e trava com 0xC000001D
# em CPUs/VMs sem AVX (ex.: Windows Server em VM com CPU genérica).
$common = @("--standalone", "--mingw64", "--assume-yes-for-downloads", "--remove-output",
    "--company-name=Tetsuo Rodolfo Okubo", "--product-name=ChronoSnap",
    "--file-version=$Version.0", "--product-version=$Version.0")

Write-Host "== Compilando servidor =="
$env:PYTHONPATH = Join-Path $Root "server"
& $Py -m nuitka @common "--output-dir=$Work\nk_server" "--output-filename=ChronoSnapServer.exe" "--windows-icon-from-ico=$Root\assets\chronosnap-program.ico" `
    "--include-data-dir=$Root\server\templates=templates" "--include-data-dir=$Root\server\static=static" `
    "--include-package=uvicorn" "--include-package=routes" "--include-package=services" `
    "--include-package=sqlalchemy.dialects.sqlite" "--include-package=sqlalchemy.dialects.postgresql" `
    "--include-package=sqlalchemy.dialects.mysql" "--include-package=sqlalchemy.dialects.mssql" "--include-package=sqlalchemy.dialects.oracle" `
    "--include-package=psycopg" "--include-package=psycopg_binary" "--include-package=aiosqlite" `
    "--include-package=pymysql" "--include-package=pymssql" "--include-package=oracledb" `
    "--include-module=python_multipart" "--include-module=bcrypt" `
    "$Root\server\run_server.py"
if ($LASTEXITCODE) { throw "Falha ao compilar o servidor." }
Move-Item "$Work\nk_server\run_server.dist" "$Stage\server"

Write-Host "== Compilando Manager =="
& $Py -m nuitka @common "--output-dir=$Work\nk_manager" "--output-filename=ChronoSnapManager.exe" `
    "--enable-plugin=tk-inter" "--windows-console-mode=disable" "--windows-icon-from-ico=$Root\assets\chronosnap-program.ico" `
    "--include-package=pystray" "--include-package=PIL" `
    "--include-data-files=$Root\assets\chronosnap-program.ico=chronosnap-program.ico" `
    "$Root\installer\manager.py"
if ($LASTEXITCODE) { throw "Falha ao compilar o Manager." }
Move-Item "$Work\nk_manager\manager.dist" "$Stage\manager"

# Licença em UTF-8 com BOM para o Inno Setup exibir os acentos corretamente
$txt = [IO.File]::ReadAllText((Join-Path $Root "COPYING"), [Text.Encoding]::UTF8)
[IO.File]::WriteAllText("$Stage\LICENSE.txt", $txt, (New-Object Text.UTF8Encoding $true))

Write-Host "== Gerando instalador =="
$iscc = @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 não encontrado." }
& $iscc "/DAppVersion=$Version" "/DStageDir=$Stage" "/DOutDir=$Out" (Join-Path $Root "installer\windows\chronosnap.iss")
if ($LASTEXITCODE) { throw "Falha ao gerar o instalador." }
Write-Host "Instalador gerado em $Out"
