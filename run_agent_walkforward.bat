@echo off
rem v2 Task 8: agent walk-forward (7 warm-up days, then counted days) at 3 queue assumptions,
rem baselines, Gate A. Needs at least 8 days per coin: run run_download_history.bat first.
rem Also exports the final edge tables to data\paper\state for the paper trader.
rem Log: results\agent_walkforward_log.txt   Output: results\agent_walkforward.csv, results\gate_a.json
cd /d "%~dp0"
if not exist results mkdir results
set LOG=results\agent_walkforward_log.txt
echo === agent walk-forward %date% %time% === > "%LOG%"
set VPY=.venv\Scripts\python.exe
if not exist "%VPY%" (echo .venv missing - run run_day5.bat once first >> "%LOG%" & goto :end)
"%VPY%" -m scripts.run_agent_walkforward --export-state >> "%LOG%" 2>&1
:end
echo === DONE %time% === >> "%LOG%"
echo Finished. See %LOG%
pause
