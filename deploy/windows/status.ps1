$ErrorActionPreference = "Continue"

$TaskName = "GiftIinkBot"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$LogDir = Join-Path $ProjectDir "logs"
$PidFile = Join-Path $LogDir "bot.pid"

Write-Host "Проект: $ProjectDir"
Write-Host ""

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($task) {
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Host "Задача:        $TaskName"
    Write-Host "Состояние:     $($task.State)"
    Write-Host "Последний код: $($info.LastTaskResult)"
    Write-Host "Последний старт: $($info.LastRunTime)"
    Write-Host "Следующий старт: $($info.NextRunTime)"
}
else {
    Write-Host "Задача $TaskName не установлена." -ForegroundColor Yellow
    Write-Host "Установить: install_24_7.bat"
}

Write-Host ""
if (Test-Path -LiteralPath $PidFile) {
    $botPid = Get-Content -LiteralPath $PidFile -ErrorAction SilentlyContinue
    $process = Get-Process -Id ([int]$botPid) -ErrorAction SilentlyContinue
    if ($process) {
        Write-Host "Процесс бота:  PID $botPid, запущен $($process.StartTime)"
    }
    else {
        Write-Host "PID-файл есть, но процесс $botPid не найден." -ForegroundColor Yellow
    }
}
else {
    $running = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
        Where-Object { $_.CommandLine -and $_.CommandLine -like "*$ProjectDir*main.py*" }
    if ($running) {
        Write-Host "Процесс бота:  PID $($running.ProcessId -join ', ')"
    }
    else {
        Write-Host "Процесс бота не найден." -ForegroundColor Yellow
    }
}

Write-Host ""
$logFile = Join-Path $LogDir "bot.log"
if (Test-Path -LiteralPath $logFile) {
    Write-Host "Последние строки bot.log:"
    Get-Content -LiteralPath $logFile -Tail 20 -Encoding UTF8
}
else {
    Write-Host "Лог bot.log ещё не создан."
}

Write-Host ""
$supervisorLog = Join-Path $LogDir "supervisor.log"
if (Test-Path -LiteralPath $supervisorLog) {
    Write-Host "Последние строки supervisor.log:"
    Get-Content -LiteralPath $supervisorLog -Tail 10 -Encoding UTF8
}
