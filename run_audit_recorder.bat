@echo off
rem v2.1 Task 12: audit what the recorder saved (coverage, gaps, crossed books, out-of-book trades).
rem Log: results\audit_recorder_log.txt   Table: results\audit_recorder.csv
cd /d "%~dp0"
if not exist results mkdir results
set LOG=results\audit_recorder_log.txt
set VPY=.venv\Scripts\python.exe
if not exist "%VPY%" (echo .venv missing - run run_day5.bat once first & pause & exit /b 1)
"%VPY%" -m scripts.audit_recorder > "%LOG%" 2>&1
type "%LOG%"
pause
