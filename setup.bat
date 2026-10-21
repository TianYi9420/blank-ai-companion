@echo off
setlocal
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" goto deps
py -3 -m venv .venv
if errorlevel 1 goto failed
:deps
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
if not exist config.json copy /y config.example.json config.json >nul
if not exist persona.json copy /y persona.example.json persona.json >nul
".venv\Scripts\python.exe" discord_bot.py --dry-run
pause
exit /b 0
:failed
echo Setup failed. Python 3.10+ and internet access are required.
pause
exit /b 1
