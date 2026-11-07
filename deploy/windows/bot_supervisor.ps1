$ErrorActionPreference = "Stop"

$ProjectDir = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $ProjectDir

$Pythonw = Join-Path $ProjectDir ".venv\Scripts\pythonw.exe"
$LogDir = Join-Path $ProjectDir "logs"
$SupervisorLog = Join-Path $LogDir "supervisor.log"
$PidFile = Join-Path $LogDir "bot.pid"
$StopFlag = Join-Path $LogDir "stop.flag"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

function Write-SupervisorLog([string]$Message) {
    $line = "{0} | {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Add-Content -Path $SupervisorLog -Value $line -Encoding UTF8
}

if (-not (Test-Path -LiteralPath $Pythonw)) {
    Write-SupervisorLog "ОШИБКА: не найден $Pythonw"
    exit 1
}

$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

Write-SupervisorLog "супервизор запущен"

while ($true) {
    if (Test-Path -LiteralPath $StopFlag) {
        Remove-Item -LiteralPath $StopFlag -Force -ErrorAction SilentlyContinue
        Write-SupervisorLog "получен стоп-флаг, выход"
        break
    }

    Write-SupervisorLog "запуск main.py"
    try {
        $process = Start-Process `
            -FilePath $Pythonw `
            -ArgumentList "main.py" `
            -WorkingDirectory $ProjectDir `
            -WindowStyle Hidden `
            -PassThru
        Set-Content -LiteralPath $PidFile -Value $process.Id -Encoding ASCII
        while (-not $process.HasExited) {
            if (Test-Path -LiteralPath $StopFlag) {
                Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
                Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
                Remove-Item -LiteralPath $StopFlag -Force -ErrorAction SilentlyContinue
                Write-SupervisorLog "получен стоп-флаг, бот остановлен"
                exit 0
            }
            Start-Sleep -Seconds 2
        }
        $exitCode = $process.ExitCode
    }
    catch {
        $exitCode = -1
        Write-SupervisorLog ("не удалось запустить процесс: {0}" -f $_.Exception.Message)
    }
    finally {
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
    }

    if (Test-Path -LiteralPath $StopFlag) {
        Remove-Item -LiteralPath $StopFlag -Force -ErrorAction SilentlyContinue
        Write-SupervisorLog "получен стоп-флаг после остановки бота, выход"
        break
    }

    Write-SupervisorLog ("бот завершился с кодом {0}; перезапуск через 10 секунд" -f $exitCode)
    Start-Sleep -Seconds 10
}
