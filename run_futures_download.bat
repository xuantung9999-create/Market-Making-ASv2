@echo off
rem Day 10: BTCUSDT perpetual-futures trades (4-10 Nov 2026), then restart the live recorder.
rem Log: results\futures_download_log.txt
cd /d "%~dp0"
set VPY=.venv\Scripts\python.exe
"%VPY%" -m mm.data download --symbol BTCUSDT --date 2026-11-04 --days 7 --market futures --out data\futures > results\futures_download_log.txt 2>&1
echo === DONE === >> results\futures_download_log.txt
start "A-S recorder - close this window to stop" "%VPY%" -m mm.recorder --symbol BTCUSDT
