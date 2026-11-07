$ErrorActionPreference = "Stop"

$TaskName = "GiftIinkBot"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$LogDir = Join-Path $ProjectDir "logs"
$PidFile = Join-Path $LogDir "bot.pid"
$StopFlag = Join-Path $LogDir "stop.flag"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
New-Item -ItemType File -Force -Path $StopFlag | Out-Null

try {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
}
catch {
    Write-Host "Не удалось остановить задачу: $($_.Exception.Message)" -ForegroundColor Yellow
}

Start-Sleep -Seconds 1

if (Test-Path -LiteralPath $PidFile) {
    $botPid = Get-Content -LiteralPath $PidFile -ErrorAction SilentlyContinue
    if ($botPid) {
        Stop-Process -Id ([int]$botPid) -Force -ErrorAction SilentlyContinue
    }
}

Start-Sleep -Seconds 1
Remove-Item -LiteralPath $StopFlag -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    Write-Host "Бот остановлен. Задача автозапуска осталась: $TaskName" -ForegroundColor Green
    Write-Host "Она снова запустит бота при следующей загрузке/входе."
}
else {
    Write-Host "Бот остановлен, задача автозапуска отсутствует." -ForegroundColor Green
}
