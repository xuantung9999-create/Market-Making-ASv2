@echo off
rem 24/7 mode for the always-on PC: order-book recorder + testnet traders + live dashboard.
rem  - First run sets up Python (.venv) and installs the packages (a few minutes).
rem  - Testnet traders need .env with BINANCE_TESTNET_API_KEY / _SECRET; until then only the
rem    recorder runs, and the traders start by themselves within a minute of you saving .env.
rem  - What runs is set in config\live.json. Crashed processes are restarted automatically.
rem  - Dashboard: open dashboard\index.html, tab "PC status" (refreshes every 30 s).
rem  - Stop: press Ctrl+C in this window (testnet orders are cancelled first).
rem  - Windows: Settings > System > Power > Sleep = Never, or recording and trading stop.
title Market maker 24x7 - Ctrl+C to stop
cd /d "%~dp0"
if not exist results mkdir results
set PYTHONUNBUFFERED=1
set VPY=.venv\Scripts\python.exe
if not exist "%VPY%" (
  echo First run: creating .venv and installing packages, please wait...
  set PY=python
  where py >nul 2>nul && set PY=py -3
  call %%PY%% -m venv .venv || (echo Python not found. Install Python 3.11+ from python.org & pause & exit /b 1)
  "%VPY%" -m pip install -q --upgrade pip
  "%VPY%" -m pip install -q -r requirements.txt || (echo pip install failed, see the messages above & pause & exit /b 1)
)
echo Checking packages...
"%VPY%" -m pip install -q --disable-pip-version-check -r requirements.txt
if not exist .env if exist .env.example copy .env.example .env >nul
:again
"%VPY%" -m scripts.supervise_live
rem The supervisor only returns on Ctrl+C or a crash of the supervisor itself. Restart after a crash.
if errorlevel 1 (
  echo Supervisor stopped with an error. Restarting in 30 s, close this window to cancel.
  timeout /t 30 >nul
  goto again
)
