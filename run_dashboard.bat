@echo off
rem Serves the project root so the dashboard (and its Live tab) can read data/live/*.json
cd /d "%~dp0"
set PY=.venv\Scripts\python.exe
if not exist %PY% set PY=python
start "" "http://localhost:8000/dashboard/index.html#live"
%PY% -m http.server 8000 --bind 127.0.0.1
