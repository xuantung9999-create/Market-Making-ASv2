@echo off
REM v2.1 Task 16: agent walk-forward with the 18-cell book state; writes Gate A' to results\gate_a_prime.json
python -m scripts.run_agent_walkforward --book-state %*
