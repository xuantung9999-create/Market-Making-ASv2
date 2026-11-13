@echo off
REM v2.1 Task 17: hedge pre-check per coin (needs data\futures from run_futures_download.bat)
python -m scripts.hedge_precheck %*
