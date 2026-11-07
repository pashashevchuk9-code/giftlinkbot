@echo off
chcp 65001 >nul
echo Отключаю сон и гибернацию при питании от сети...
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change disk-timeout-ac 0
echo.
echo Готово. Экран может гаснуть, но компьютер не будет засыпать.
echo Для ноутбука при работе от батареи настройки не менялись.
pause
