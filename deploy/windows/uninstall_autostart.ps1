param(
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

$TaskName = "GiftIinkBot"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$LogDir = Join-Path $ProjectDir "logs"
$PidFile = Join-Path $LogDir "bot.pid"
$StopFlag = Join-Path $LogDir "stop.flag"

if ($DryRun) {
    Write-Host "DRY RUN: будет удалена задача $TaskName"
    exit 0
}

$isAdmin = ([Security.Principal.WindowsPrincipal](
    [Security.Principal.WindowsIdentity]::GetCurrent()
)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $isAdmin) {
    Write-Host "Нужны права администратора." -ForegroundColor Red
    Write-Host "Запустите uninstall_24_7.bat и подтвердите UAC."
    exit 1
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType File -Force -Path $StopFlag | Out-Null

Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1

if (Test-Path -LiteralPath $PidFile) {
    $botPid = Get-Content -LiteralPath $PidFile -ErrorAction SilentlyContinue
    if ($botPid) {
        Stop-Process -Id ([int]$botPid) -Force -ErrorAction SilentlyContinue
    }
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $StopFlag -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue

Write-Host "Автозапуск удалён, бот остановлен." -ForegroundColor Green
Write-Host "Данные и логи сохранены в: $ProjectDir"
