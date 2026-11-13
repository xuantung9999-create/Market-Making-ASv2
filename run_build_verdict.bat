@echo off
cd /d "%~dp0"
python scripts\slim_runs.py && python scripts\build_verdict.py
pause
