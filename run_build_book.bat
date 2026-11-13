@echo off
cd /d "%~dp0"
python -m scripts.build_book_bundle
pause
