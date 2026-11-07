@echo off
chcp 65001 >nul
set PYTHONUTF8=1

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Не найдено окружение .venv.
    pause
    exit /b 1
)

.venv\Scripts\python.exe check_setup.py %*
pause
