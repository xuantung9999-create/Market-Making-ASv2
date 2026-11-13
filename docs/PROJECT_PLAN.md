# Project plan

The original 2-week plan (Days 1-12), followed by the v2 build guide (`docs/BUILD_GUIDE.md`) and the
v2.1 research spec (`docs/SPEC_V2_1.md`).

Progress
- [x] D1 Wed 11 Nov — derivation notes (notes/derivation.md), repo setup
- [x] D2 Thu 12 Nov — strategy core (mm/strategy.py) + 22 tests (tests/test_strategy.py)
- [x] D3 Thu 12 Nov — paper replication simulator (mm/simulator.py) + 9 tests (tests/test_simulator.py), single-path plot
- [x] D4 (pulled forward) — 1,000-path Monte Carlo for γ ∈ {0.01, 0.1, 0.5}: results/day4_paper_table.csv
- [x] D5 code (Thu 12 Nov) — mm/data.py downloader (adapted from mm-backtester, now tick-level + checksum), mm/recorder.py live recorder, scripts/explore_day.py, 8 offline tests
- [x] D5 run — 9–10 Nov downloaded (1.85M trades), overview charts, recorder running
- [x] Dashboard (pulled forward from D10–11) — dashboard/index.html + scripts/build_dashboard.py
- [x] D6 Thu 12 Nov — mm/backtest.py: 100 ms bars, requote 500 ms, 50 ms latency, strict/touch fills, fees, cap, exact P&L attribution; 10 tests
- [x] D7 Thu 12 Nov — mm/metrics.py, scripts/run_backtest.py, notes/week1_review.md: every strategy loses ~1.5 bp/volume to adverse selection; A-S halves inventory risk
- [x] D8 Thu 12 Nov — mm/calibrate.py + scripts/download_universe.py + scripts/run_universe.py: 12 coins BTC → micro caps, calibrate day 1 / test day 2, random-entry check, markout t-stats; notes/day8_small_caps.md; dashboard tab
- [x] D9 Thu 12 Nov — 7 days × 12 coins; walk-forward (3-day calibration → next day); two-part fill curve; mm/flow.py alpha model; mm/protect.py lean + kill switch; notes/day9_informed_flow.md; dashboard tab
- [x] D9b Thu 12 Nov — GLFT quotes (mm/protect.py), gamma_for_glft_skew, scripts/run_sweep.py: 32 settings x 48 coin-days, causal tuning, requote/latency sensitivity
- [x] D10 Thu 12 Nov — leader features (mm/flow.py), scripts/run_leadlag.py (BTC spot + perp), scripts/book_study.py (50 min live book); notes/day10_tuning_signals.md; dashboard tab
- [ ] D11 — keep recorder running several days; book imbalance into flow model; event-driven requoting
- [ ] D12 — paper trading with the tuned setting

v2 build guide: docs/BUILD_GUIDE.md (progress log: docs/progress/v2_ledger.md)

- [x] v2 Task 0 — baseline, config/candidates.txt
- [x] v2 Task 1 — multi-symbol recorder
- [x] v2 Task 2 — history download + tick-constraint screener
- [x] v2 Task 3 — book tape + queue engine
- [x] v2 Task 4 — incremental features
- [x] v2 Task 5 — edge table + edge policy
- [x] v2 Task 6 — calibration agent
- [x] v2 Task 7 — queue baseline on history
- [x] v2 Task 8 — agent walk-forward + Gate A (code; verdict needs 60-day download)
- [x] v2 Task 9 — inferred tape vs real book (code + tests; needs live data to run)
- [x] v2 Task 10 — paper trader (code + tests; needs live data to run)
- [x] v2 Task 11 — daily supervisor + Gate B (code + tests; needs live data to run)

Dashboard: Task 7/8/11 scripts now write run bundles to dashboard/runs (guide D12, first part); About tab updated with the v2 findings.
