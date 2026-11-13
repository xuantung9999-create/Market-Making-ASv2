@echo off
rem v2 Task 2: download 60 days of trades for every coin in config\candidates.txt,
rem then screen them for tick constraint. Takes a while (several GB for BTC/SOL/DOGE).
rem Log: results\download_history_log.txt
cd /d "%~dp0"
if not exist results mkdir results
set LOG=results\download_history_log.txt
echo === download_history %date% %time% === > "%LOG%"
set VPY=.venv\Scripts\python.exe
if not exist "%VPY%" (echo .venv missing - run run_day5.bat once first >> "%LOG%" & goto :end)
echo [download] >> "%LOG%"
"%VPY%" -m scripts.download_history --days 60 >> "%LOG%" 2>&1
echo [screen] >> "%LOG%"
"%VPY%" -m scripts.screen_universe >> "%LOG%" 2>&1
:end
echo === DONE %time% === >> "%LOG%"
echo Finished. See %LOG%
pause
