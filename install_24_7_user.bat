@echo off
chcp 65001 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0deploy\windows\install_autostart.ps1" -CurrentUser
echo.
pause
