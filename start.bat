@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" goto missing
".venv\Scripts\python.exe" check_config.py
if errorlevel 1 goto failed
".venv\Scripts\python.exe" discord_bot.py
pause
exit /b 0
:missing
echo Run setup.bat first.
:failed
pause
exit /b 1
