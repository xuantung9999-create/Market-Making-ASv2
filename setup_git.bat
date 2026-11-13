@echo off
rem One-time: turn this folder into a git repo and commit everything (data/ is ignored).
cd /d "%~dp0"
if exist .git (echo Already a git repo. & pause & exit /b)
git init
git add -A
git commit -m "baseline + v2 tasks (built by Claude)"
pause
