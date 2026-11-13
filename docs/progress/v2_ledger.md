# SDD ledger — plan: docs/BUILD_GUIDE.md

Executor: Claude (inline), working on a copy in its own workspace; files written back to the user's folder.
Baseline: 92 tests passing.
Task 0: Ruling: the user's folder is not a git repo and Claude cannot run git on the user's PC — history kept in Claude's workspace copy; `setup_git.bat` added so the user can create the repo locally with one double-click — cost if wrong: user runs one .bat.
Task 0: complete (commit 35cfa51, tests: pytest -q → 92 passed)
Task 1: Ruling: added --symbols-file flag so the .bat reads config/candidates.txt directly instead of parsing it in batch — additive, --symbol/--symbols unchanged — cost if wrong: none.
Task 1: complete (commit 71604dd, tests: pytest -q → 97 passed)
Task 2: Ruling: screen run on the 7 days already downloaded (4-10 Nov); the 60-day download needs the user's network (this workspace cannot reach data.binance.vision) — user runs run_download_history.bat — cost if wrong: screen re-run after download may change the universe.
Task 2: result: v2 universe = COTIUSDT, SKLUSDT, ANKRUSDT (ARBUSDT tick 6.0 bp < 10, excluded).
Task 2: complete (commit 1bf1648, tests: pytest -q → 102 passed)
Task 3: Ruling: QueueSim takes an extra keyword feed_features=True; the agent (Task 6) sets False so one shared FeatureEngine is fed once, not once per simulator — guide says "one FeatureEngine; every simulator receives the same events" and forbids forking QueueSim later — cost if wrong: none, default keeps the guide's signature.
Task 3: Ruling: timers right after warm-up or a stale period are never skipped (else skipping would delay the first quote until the next market event and change results) — needed for the "skipping does not change results" test — cost if wrong: none.
Task 3: Ruling: an event at exactly an order's activation time sees the order already active; activation uses the book as of just before that event — section 5 leaves equal-time activation open — cost if wrong: at most one fill shifted by one event.
Task 3: Ruling: fills carry net_edge_bp (60 s markout minus fee; NaN if the day ends first) so Tasks 7-8 never recompute it — additive column.
Task 3: complete (commit 58cd961, tests: pytest -q → 131 passed)
Task 4: complete (commit 445a023, tests: pytest -q → 136 passed)
Task 5: Ruling: cell variance = decayed sum of squared deviations / (n - 1) (0 if n <= 1); added read-only helpers cell() and pooled() for the shrinkage test and the dashboard — guide does not define the variance estimator — cost if wrong: slightly different se, affects only z > 0 arms.
Task 5: complete (commit d06b242, tests: pytest -q → 145 passed)
Task 6: Ruling: a matured shadow fill is learned at the first event at or after fill time + 60 s, using the mid known just before that event (never a later one) — guide's test fixes "mid at 160 s"; this is the strictly past-only reading — cost if wrong: none.
Task 6: Ruling: run_agent does not call end_day; the caller does (scripts, paper trader) — keeps one place that owns day boundaries — cost if wrong: none.
Task 6: complete (commit 82df8e7, tests: pytest -q → 155 passed)
Task 7: run on the 7 downloaded days (4-10 Nov) for COTI, SKL, ANKR. Sanity check vs v1 passes: ANKR 2026-11-10 bridge 404 fills / -43.36 USD vs v1 touch 408 / -42.98, same sign.
Task 7: result: Join touch net 10 bp is negative on every coin and every queue assumption: -20.6 to -29.0 bp per USD traded at q0.5-q2.0, 0-14% positive days, t between -4.3 and -10.9. Not tuned (guide).
Task 7: Ruling: per-symbol table adds net_7.5bp per day and net_edge_bp_mean (section 2 asks to also report 7.5 bp) — additive.
Task 7: complete (commit 01a7d39, tests: pytest -q → 155 passed)
Task 8: Ruling: added QueueSim.result(day=d) for per-day rows of a simulator that lives across days (test_per_day_results_add_up) — guide needs per-day agent rows but gives no way to get them — cost if wrong: none, result() unchanged.
Task 8: Ruling: Gate A json gets a "status": "not evaluated" when no day is past warm-up, "fail: declined to trade" when counted days exist but the agent never reaches 20 fills — the guide's 5 checks would otherwise call missing data a fail — cost if wrong: none, the 5 booleans are unchanged.
Task 8: Ruling: added tests/test_gate_a.py (guide lists none for Task 8); it caught an empty-filter crash on zero counted days, fixed.
Task 8: NOT RUN for a verdict: only 7 days per coin are downloaded = all warm-up. Smoke run (3-day warm-up, not a gate result) and table inspection: the agent learns JOIN net edge -13 (ANKR), -15 (COTI), -6.5 (SKL) bp, BACK -4, -12, +2 bp, and the live track stays OUT (0 fills). book_imb is always 0 on inferred tapes (equal sizes), so only the volatility bucket varies until real book data exists.
Task 8: code complete (commit 7871092, tests: pytest -q → 159 passed); verdict pending user's 60-day download.
Final review: self-review (no separate reviewer agent; not requested). Checked guide section 6 review focus: one-sided days skipped with a note (v2_common.load_day); stale only in paper mode; tick change -> warning + table reset (Task 8) / warning (Task 7); prices compared as integer ticks; end-of-day fills excluded from markouts and learning. No Critical/Important findings.

## Session 2 (12 Nov): dashboard findings + Tasks 9-11
Dashboard guide section 6 applied: QueueSim minute rows carry ts_us; totals["uptime"] per side; fills carry mk_1/10/60/300; agent live fills carry pred_edge_bp; gate_a.json has scoreboard "conditions".
Ruling: QueueSim writes no minute row before the day's first book update (mid unknown) — bundles reject NaN — cost if wrong: none (no position can exist before a book).
Dashboard D12 (first part): run_queue_baseline writes qb-<date>; run_agent_walkforward writes wf-<date>-q<queue> (counted days only, none yet); daily_supervisor writes paper-<first date>. New mm/report helpers: edge_rows, agent_rows, calib_rows, wait_hist_of, screen_rows (tests/test_report_v2.py). data.js split and --public copies (rest of D12) not done.
Dashboard: qb-2026-11-12 bundle written (7 days, 3 coins, 4 queue variants; Overview shows -1,910.73 USD, -23.2 bp/USD, t -11.9). About tab and roadmap updated with v2 findings.
Task 9: Ruling: recorded trades are timed by receive time (recv_us) in both runs so book and trades share one clock — cost if wrong: none.
Task 9: complete (code + tests; smoke-run on a synthetic feed; real verdict needs 3+ recorded days).
Task 10: Ruling: paper records its raw feed under data/paper/feed (not data/live) so it never duplicates a separately running recorder — cost if wrong: none.
Task 10: Ruling: per-day files day_<date>.json (fills, pnl, first/last timer) and state/<SYM>_start_<date>.json make the day replayable exactly; replay uses the paper's own timer schedule — the guide asks for an exact replay match.
Task 10: Ruling: coin_state enabled=false keeps the agent learning but stops the live track (reuses the loss-stop switch); size_mult rebuilds the simulators at midnight with the same learned state — guide does not say how "enabled" acts.
Task 10: note: a book and a trade message arriving in the same microsecond could be ordered differently on replay (book first); Task 11 would report it as a mismatch.
Task 10: complete (tests: scripted session == run_agent live fills; state round-trip; unknown streams ignored; restart keeps live_arm; midnight replay matches to 1e-9).
Task 11: Ruling: Gate B has no pre-registered pass rule in the guide, so its scoreboard conditions carry values with pass = null (shown as n/a) — cost if wrong: none.
Task 11: Ruling: a day with no fills (z undefined) leaves coin_state unchanged — cost if wrong: one day slower to restore size.
Task 11: complete (tests: coin-state rules, z, Gate B, end-to-end replay of a scripted 2-day paper session).
Suite: 180 passed in 8.79s
