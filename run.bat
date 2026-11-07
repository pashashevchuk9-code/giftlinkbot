@echo off
chcp 65001 >nul
set PYTHONUTF8=1

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Не найдено окружение .venv.
    echo Создайте его:
    echo   py -3 -m venv .venv
    echo   .venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

.venv\Scripts\python.exe main.py
pause
