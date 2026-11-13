@echo off
rem Day 9: 5 more days (4-8 Nov 2026) for the 12 coins. Log: results\more_days_log.txt
cd /d "%~dp0"
set VPY=.venv\Scripts\python.exe
"%VPY%" -m scripts.download_universe --date 2026-11-04 --days 5 --symbols BTCUSDT SOLUSDT NEARUSDT DOGEUSDT ARBUSDT INJUSDT ONEUSDT COTIUSDT ANKRUSDT SKLUSDT CELRUSDT IOTXUSDT > results\more_days_log.txt 2>&1
echo === DONE === >> results\more_days_log.txt
