@echo off
rem Testnet trader: REAL post-only orders on the Binance SPOT TESTNET (fake money).
rem Needs .env with BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_API_SECRET (copy .env.example).
rem First run: POLICY=join (always quotes) to test the plumbing. Then POLICY=agent.
rem Press Ctrl+C to stop: every open order is cancelled on exit. (Closing the window skips that;
rem the next start cancels any leftovers.)
rem Log: results\testnet_log.txt   Orders/fills: data\testnet\<SYMBOL>\
cd /d "%~dp0"
if not exist results mkdir results
if not exist .env (echo .env missing - copy .env.example to .env and paste your testnet keys & pause & exit /b 1)
set VPY=.venv\Scripts\python.exe
if not exist "%VPY%" (echo .venv missing - run run_day5.bat once first & pause & exit /b 1)
set SYMS=BTCUSDT
set POLICY=join
set LOG=results\testnet_log.txt
set PYTHONUNBUFFERED=1
echo === testnet trader start %date% %time% (%POLICY%) === >> "%LOG%"
"%VPY%" -m mm.testnet --symbols %SYMS% --policy %POLICY% 2>&1 | powershell -NoProfile -Command "$input | Tee-Object -FilePath '%LOG%' -Append"
pause
