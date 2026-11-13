@echo off
rem v2 Task 10: paper trader for the v2 universe (no orders are ever sent).
rem Reads public Binance data, runs the self-calibrating agent, logs to data\paper.
rem Close the window it opens to stop. Set Windows to never sleep while plugged in.
rem Before the first run, run_agent_walkforward.bat exports the learned tables to data\paper\state.
rem Log: results\paper_log.txt
cd /d "%~dp0"
if not exist results mkdir results
set LOG=results\paper_log.txt
echo === paper trader start %date% %time% === >> "%LOG%"
set VPY=.venv\Scripts\python.exe
if not exist "%VPY%" (echo .venv missing - run run_day5.bat once first & pause & exit /b 1)
set SYMS=ANKRUSDT,SKLUSDT,COTIUSDT
start "v2 paper trader - close this window to stop" cmd /c ""%VPY%" -m mm.paper --symbols %SYMS% >> "%LOG%" 2>&1"
echo Paper trader started for %SYMS%. Output goes to %LOG%
