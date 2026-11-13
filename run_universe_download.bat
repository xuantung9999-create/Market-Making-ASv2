@echo off
rem Download the coin universe (9-10 Nov 2026). Log: results\universe_download_log.txt
cd /d "%~dp0"
set VPY=.venv\Scripts\python.exe
if not exist "%VPY%" (echo Run run_day5.bat first to create the venv > results\universe_download_log.txt & exit /b 1)
"%VPY%" -m scripts.download_universe > results\universe_download_log.txt 2>&1
echo === DONE === >> results\universe_download_log.txt
