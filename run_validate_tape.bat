@echo off
rem v2 Task 9: compare the inferred book with the real recorded book (needs 3+ days of run_recorder_multi.bat).
rem Log: results\validate_tape_log.txt   Output: results\tape_validation.csv
cd /d "%~dp0"
if not exist results mkdir results
set LOG=results\validate_tape_log.txt
echo === validate tape %date% %time% === > "%LOG%"
set VPY=.venv\Scripts\python.exe
if not exist "%VPY%" (echo .venv missing - run run_day5.bat once first >> "%LOG%" & goto :end)
"%VPY%" -m scripts.validate_tape >> "%LOG%" 2>&1
:end
echo === DONE %time% === >> "%LOG%"
echo Finished. See %LOG%
pause
