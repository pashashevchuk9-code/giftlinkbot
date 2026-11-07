param(
    [switch]$DryRun,
    [switch]$CurrentUser
)

$ErrorActionPreference = "Stop"

$TaskName = "GiftIinkBot"
$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$Supervisor = Join-Path $PSScriptRoot "bot_supervisor.ps1"
$Pythonw = Join-Path $ProjectDir ".venv\Scripts\pythonw.exe"
$EnvFile = Join-Path $ProjectDir ".env"
$LogDir = Join-Path $ProjectDir "logs"
$PowerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"

if ($DryRun) {
    Write-Host "DRY RUN"
    Write-Host "ProjectDir: $ProjectDir"
    Write-Host "Supervisor: $Supervisor"
    Write-Host "Pythonw:    $Pythonw"
    Write-Host "Env:        $EnvFile"
    Write-Host "Task:       $TaskName"
    Write-Host "Mode:       $(if ($CurrentUser) { 'текущий пользователь, при входе' } else { 'SYSTEM, при загрузке и входе' })"
    exit 0
}

$isAdmin = ([Security.Principal.WindowsPrincipal](
    [Security.Principal.WindowsIdentity]::GetCurrent()
)).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

if (-not $CurrentUser -and -not $isAdmin) {
    Write-Host "Нужны права администратора." -ForegroundColor Red
    Write-Host "Запустите install_24_7.bat и подтвердите UAC."
    Write-Host "Либо установите автозапуск под текущим пользователем:"
    Write-Host "  install_24_7_user.bat"
    exit 1
}

if (-not (Test-Path -LiteralPath $Pythonw)) {
    Write-Host "Не найдено окружение .venv: $Pythonw" -ForegroundColor Red
    Write-Host "Сначала выполните установку из README."
    exit 1
}

if (-not (Test-Path -LiteralPath $EnvFile)) {
    Write-Host "Не найден .env: $EnvFile" -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
Remove-Item -LiteralPath (Join-Path $LogDir "stop.flag") -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath (Join-Path $LogDir "bot.pid") -Force -ErrorAction SilentlyContinue

$running = Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" |
    Where-Object {
        $_.CommandLine -and
        $_.CommandLine -like "*$ProjectDir*main.py*"
    }

if ($running) {
    Write-Host "Внимание: main.py уже запущен вручную (PID: $($running.ProcessId -join ', '))." -ForegroundColor Yellow
    Write-Host "Остановите его, иначе второй экземпляр не сможет подключиться к Telegram."
}

$action = New-ScheduledTaskAction `
    -Execute $PowerShellExe `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$Supervisor`"" `
    -WorkingDirectory $ProjectDir

if ($CurrentUser) {
    $currentIdentity = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $triggers = @(New-ScheduledTaskTrigger -AtLogOn)
    $principal = New-ScheduledTaskPrincipal `
        -UserId $currentIdentity `
        -LogonType Interactive `
        -RunLevel Limited
}
else {
    $triggers = @(
        (New-ScheduledTaskTrigger -AtStartup),
        (New-ScheduledTaskTrigger -AtLogOn)
    )
    $principal = New-ScheduledTaskPrincipal `
        -UserId "SYSTEM" `
        -LogonType ServiceAccount `
        -RunLevel Highest
}

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggers `
    -Principal $principal `
    -Settings $settings `
    -Description "NFT за Stars: постоянная работа бота @GiftIinkBot" `
    -Force | Out-Null

Start-ScheduledTask -TaskName $TaskName
Start-Sleep -Seconds 3

$info = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Host ""
Write-Host "Задача установлена: $TaskName" -ForegroundColor Green
Write-Host "Режим: $(if ($CurrentUser) { 'текущий пользователь, запуск при входе' } else { 'SYSTEM, запуск при загрузке и входе' })"
Write-Host "Состояние: $((Get-ScheduledTask -TaskName $TaskName).State)"
Write-Host "Последний запуск: $($info.LastRunTime)"
Write-Host "Следующий запуск: $($info.NextRunTime)"
Write-Host ""
Write-Host "Логи бота:    $LogDir\bot.log"
Write-Host "Логи надзора: $LogDir\supervisor.log"
Write-Host ""
Write-Host "Проверить статус: status_24_7.bat"
Write-Host "Остановить:        stop_24_7.bat"
Write-Host "Удалить автозапуск: uninstall_24_7.bat"
Write-Host ""
Write-Host "Для работы 24/7 отключите сон ПК (от имени пользователя):"
Write-Host "  powercfg /change standby-timeout-ac 0"
Write-Host "  powercfg /change hibernate-timeout-ac 0"
