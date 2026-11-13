@echo off
rem Day 5: set up venv, run tests, download 2 days of BTCUSDT trades, chart them,
rem then start the live recorder in its own window. Log: results\day5_run_log.txt
cd /d "%~dp0"
if not exist results mkdir results
set LOG=results\day5_run_log.txt
echo === Day 5 run %date% %time% === > "%LOG%"

set PY=python
where py >nul 2>nul && set PY=py -3
echo [python] >> "%LOG%"
%PY% --version >> "%LOG%" 2>&1 || (echo PYTHON NOT FOUND >> "%LOG%" & goto :end)

if not exist .venv\Scripts\python.exe (
  echo [creating .venv] >> "%LOG%"
  %PY% -m venv .venv >> "%LOG%" 2>&1
)
set VPY=.venv\Scripts\python.exe

echo [pip install] >> "%LOG%"
"%VPY%" -m pip install -q -r requirements.txt >> "%LOG%" 2>&1

echo [pytest] >> "%LOG%"
"%VPY%" -m pytest -q >> "%LOG%" 2>&1

echo [download] >> "%LOG%"
"%VPY%" -m mm.data download --symbol BTCUSDT --date 2026-11-09 --days 2 >> "%LOG%" 2>&1

echo [explore 2026-11-09] >> "%LOG%"
"%VPY%" -m scripts.explore_day data\BTCUSDT_2026-11-09_trades.parquet >> "%LOG%" 2>&1
echo [explore 2026-11-10] >> "%LOG%"
"%VPY%" -m scripts.explore_day data\BTCUSDT_2026-11-10_trades.parquet >> "%LOG%" 2>&1

echo [starting recorder in a new window] >> "%LOG%"
start "A-S recorder - close this window to stop" "%VPY%" -m mm.recorder --symbol BTCUSDT

:end
echo === DONE %time% === >> "%LOG%"
