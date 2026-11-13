@echo off
rem v2 Task 1: record best bid/ask + trades for every coin in config\candidates.txt
rem over one websocket, in its own window. Close that window to stop.
rem IMPORTANT: set Windows to never sleep while plugged in, or the recording has gaps.
rem Log: results\recorder_multi_log.txt
cd /d "%~dp0"
if not exist results mkdir results
set LOG=results\recorder_multi_log.txt
echo === v2 recorder start %date% %time% === >> "%LOG%"
set VPY=.venv\Scripts\python.exe
if not exist "%VPY%" (echo .venv missing - run run_day5.bat once first >> "%LOG%" & echo .venv missing - run run_day5.bat once first & pause & exit /b 1)
start "v2 recorder - close this window to stop" cmd /c ""%VPY%" -m mm.recorder --symbols-file config\candidates.txt >> "%LOG%" 2>&1"
echo Recorder started in a new window. Output goes to %LOG%
