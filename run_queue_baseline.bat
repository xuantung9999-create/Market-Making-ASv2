@echo off
rem v2 Task 7: Join touch through the queue engine on every downloaded day of the v2 universe.
rem Log: results\queue_baseline_log.txt   Output: results\queue_baseline.csv
cd /d "%~dp0"
if not exist results mkdir results
set LOG=results\queue_baseline_log.txt
echo === queue baseline %date% %time% === > "%LOG%"
set VPY=.venv\Scripts\python.exe
if not exist "%VPY%" (echo .venv missing - run run_day5.bat once first >> "%LOG%" & goto :end)
"%VPY%" -m scripts.run_queue_baseline >> "%LOG%" 2>&1
:end
echo === DONE %time% === >> "%LOG%"
echo Finished. See %LOG%
pause
