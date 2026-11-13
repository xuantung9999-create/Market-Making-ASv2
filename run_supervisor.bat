@echo off
rem v2 Task 11: daily supervisor. Replays each closed paper day, checks the model against reality,
rem updates data\paper\coin_state.json and writes results\paper_report_<date>.md. Run once a day.
rem Log: results\supervisor_log.txt
cd /d "%~dp0"
if not exist results mkdir results
set LOG=results\supervisor_log.txt
echo === supervisor %date% %time% === >> "%LOG%"
set VPY=.venv\Scripts\python.exe
if not exist "%VPY%" (echo .venv missing - run run_day5.bat once first >> "%LOG%" & goto :end)
"%VPY%" -m scripts.daily_supervisor >> "%LOG%" 2>&1
:end
echo === DONE %time% === >> "%LOG%"
echo Finished. See %LOG%
pause
