# ClearLedger COM-Agent — установка Windows Service через NSSM.
# Запускать от Administrator.
#
# Что делает:
#   1. Скачивает NSSM (если ещё нет) в C:\Tools\nssm\
#   2. Создаёт venv для агента в C:\Services\ClearLedgerCOMAgent\venv
#   3. Устанавливает зависимости из requirements.txt
#   4. Регистрирует Windows Service "ClearLedgerCOMAgent"
#   5. Запускает сервис на порту 8080, slушает 0.0.0.0
#   6. Открывает firewall-порт только из 10.10.70.0/24 (Miran internal)
#
# Переменные окружения сервиса:
#   COM_AGENT_TOKEN — secret для Bearer auth (обязательно в проде)
#   COM_AGENT_AUTO_CONNECT — connect_string 1С для авто-подключения при старте

[CmdletBinding()]
param(
    [string]$InstallDir = "C:\Services\ClearLedgerCOMAgent",
    [string]$SourceDir  = "$PSScriptRoot",
    [int]$Port = 8080,
    [string]$Token = "",
    [string]$AutoConnect = ""
)

$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

function Write-Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-OK($msg)   { Write-Host "    $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "[!] $msg" -ForegroundColor Yellow }

# ── 1. NSSM ───────────────────────────────────────────────────────────
Write-Step "Проверка NSSM"
$nssmPath = $null
foreach ($candidate in @("C:\Tools\nssm\nssm.exe", "C:\ProgramData\chocolatey\bin\nssm.exe",
                          "C:\ProgramData\chocolatey\lib\NSSM\tools\nssm-2.24-101-g897c7ad\win64\nssm.exe")) {
    if (Test-Path $candidate) { $nssmPath = $candidate; break }
}
if (-not $nssmPath) {
    $cmd = Get-Command nssm -ErrorAction SilentlyContinue
    if ($cmd) { $nssmPath = $cmd.Path }
}
if (-not $nssmPath) {
    Write-Step "Установка NSSM через Chocolatey"
    & choco install nssm -y --no-progress | Out-Null
    $nssmPath = (Get-Command nssm).Path
}
Write-OK "NSSM: $nssmPath"

# ── 2. Копирование исходников ────────────────────────────────────────
Write-Step "Копирование агента в $InstallDir"
New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
Copy-Item "$SourceDir\app" $InstallDir -Recurse -Force
Copy-Item "$SourceDir\requirements.txt" $InstallDir -Force
Write-OK "Скопировано"

# ── 3. venv + зависимости ────────────────────────────────────────────
Write-Step "Создание venv (Python 3.13)"
$python = "py"  # py launcher
& $python -3.13 -m venv "$InstallDir\venv"
$venvPython = "$InstallDir\venv\Scripts\python.exe"
& $venvPython -m pip install --upgrade pip -q
& $venvPython -m pip install -r "$InstallDir\requirements.txt" -q
Write-OK "Зависимости установлены"

# ── 4. Service registration ──────────────────────────────────────────
Write-Step "Регистрация Windows Service 'ClearLedgerCOMAgent'"
$svcName = "ClearLedgerCOMAgent"

$existing = Get-Service -Name $svcName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Warn "Сервис уже существует — удаляю старый"
    Stop-Service $svcName -Force -ErrorAction SilentlyContinue
    & $nssmPath remove $svcName confirm
    Start-Sleep -Seconds 2
}

# install
& $nssmPath install $svcName $venvPython "-m" "uvicorn" "app.main:app" "--host" "0.0.0.0" "--port" "$Port"
& $nssmPath set $svcName AppDirectory $InstallDir
& $nssmPath set $svcName Description "ClearLedger COM-Agent — HTTP-обёртка над V83.COMConnector"
& $nssmPath set $svcName Start SERVICE_AUTO_START
& $nssmPath set $svcName AppStdout "$InstallDir\agent.log"
& $nssmPath set $svcName AppStderr "$InstallDir\agent-err.log"
& $nssmPath set $svcName AppRotateFiles 1
& $nssmPath set $svcName AppRotateBytes 10485760  # 10MB ротация

# Env vars
if ($Token) {
    & $nssmPath set $svcName AppEnvironmentExtra "COM_AGENT_TOKEN=$Token"
}
if ($AutoConnect) {
    $envBlock = "COM_AGENT_TOKEN=$Token`r`nCOM_AGENT_AUTO_CONNECT=$AutoConnect"
    & $nssmPath set $svcName AppEnvironmentExtra $envBlock
}

Write-OK "Сервис зарегистрирован"

# ── 5. Firewall ──────────────────────────────────────────────────────
Write-Step "Открытие firewall (порт $Port из 10.10.70.0/24)"
Remove-NetFirewallRule -DisplayName "ClearLedger COM-Agent" -ErrorAction SilentlyContinue
New-NetFirewallRule `
    -DisplayName "ClearLedger COM-Agent" `
    -Direction Inbound `
    -LocalPort $Port `
    -Protocol TCP `
    -Action Allow `
    -RemoteAddress 10.10.70.0/24,127.0.0.1 `
    -Profile Any | Out-Null
Write-OK "Firewall правило создано: TCP/$Port из 10.10.70.0/24"

# ── 6. Запуск ────────────────────────────────────────────────────────
Write-Step "Запуск сервиса"
Start-Service $svcName
Start-Sleep -Seconds 3
$status = (Get-Service $svcName).Status
if ($status -eq 'Running') {
    Write-OK "Сервис запущен"
} else {
    Write-Warn "Сервис не запустился (статус: $status). Логи: $InstallDir\agent-err.log"
}

# ── 7. Smoke ─────────────────────────────────────────────────────────
Write-Step "Smoke-тест: GET /health"
try {
    $resp = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 5
    Write-OK ($resp | ConvertTo-Json -Compress)
} catch {
    Write-Warn "Health не отвечает: $_"
}

Write-Host ""
Write-Host "ГОТОВО." -ForegroundColor Green
Write-Host "Сервис:    ClearLedgerCOMAgent (Get-Service)"
Write-Host "URL:       http://10.10.70.45:$Port"
Write-Host "Логи:      $InstallDir\agent.log"
Write-Host "Управление: Stop-Service / Start-Service / Restart-Service ClearLedgerCOMAgent"
