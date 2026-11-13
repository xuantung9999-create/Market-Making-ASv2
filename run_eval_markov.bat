@echo off
cd /d "%~dp0"
python -m scripts.eval_markov > results\eval_markov.txt 2>&1
type results\eval_markov.txt
pause
