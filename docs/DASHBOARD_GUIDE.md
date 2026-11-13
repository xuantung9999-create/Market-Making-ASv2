# Trading Dashboard v2: Plan and Build Guide

> **For the model doing the work (Opus / Sonnet):** one task per session, in order. Read sections 1-5,
> then only your task. Steps use `- [ ]` checkboxes. Every design decision is made here; section 3 of
> `docs/BUILD_GUIDE.md` (how to work, when to stop and ask) applies to this guide too.

**Goal:** turn the current research showcase (`dashboard/index.html`) into a desk-style trading dashboard:
the screens a professional market-making trader checks every day (P&L and its attribution, execution
quality, risk, model health, signals, market state, simulation versus live, data health), fed today by
backtest and paper-trading results and later by live data **without changing the page**.

**Architecture:** Python computes every number and writes it in one fixed format, the *run bundle*.
The page only renders bundles. A bundle can come from a backtest, a walk-forward run, the paper trader
or, later, a real account: the page does not care which, it shows a badge saying which. Intraday data
arrives through a second small format, the *snapshot*, polled from a local server.

**Tech stack:** Python 3.11 with the existing requirements (no new packages; the local server uses the
standard library). Front end: the existing single dark theme, vanilla JavaScript, Plotly from the CDN
already used. No build step, no framework, no npm.

**Honest scope note.** Nobody outside a firm knows its internal screens, so "what a Jane Street trader
needs" is implemented here as the standard toolkit of a market-making desk: P&L attribution, markouts,
inventory and limits, calibration of the model's predictions, signal decay, and reconciliation of
simulation against live. Those are also the things a trading interviewer will ask you to explain.

---

## Progress

- [x] D1-D4 done 12 Nov 2026: page split into `js/`, `mm/report.py` with 23 tests, demo bundle in
  `dashboard/runs/`, run selector and Desk navigation, Overview view. Notes for later tasks:
  - `summary_rows` also writes display columns `fills_day`, `net_edge_bp` and `mk_60` (fill-weighted), and
    `build_bundle` adds pooled `ALL|<variant>` curves, so views never compute statistics in JavaScript.
  - Pending Desk views are registered in `js/views/desk_pending.js`; each D5-D11 task removes its entry.
  - Desk helpers (`section`, `emptyPanel`, `deskPlot`, `deskBundle`, `summaryRow`, `badge`, `sign`) are in `js/core.js`.
  - The demo bundle uses 30-minute curve points (real producers use 5-minute points) to stay small.
- [x] D5-D8 (P&L, Execution, Risk, Model) are built; D9-D11 are still placeholders in `js/views/desk_pending.js`.
- Layout and chart changes from 13 Nov 2026 are in `docs/DASHBOARD_REDESIGN.md`; where it disagrees with section 2 below, it wins.

## 1. What exists today

- `dashboard/index.html` (94 kB): markup, CSS and all JavaScript in one file; 9 tabs that tell the
  research story (Simulator, How the model quotes, Paper replication, Real market data, Backtest,
  BTC to micro caps, Informed traders, Tuning and signals, About).
- `dashboard/data.js` (4.8 MB): `window.DASH = {...}`, written by `scripts/build_dashboard.py`.
- Loaded with `<script src>` tags so it works when opened as a file, with no server.
- Published copy: the artifact "Avellaneda-Stoikov Market Maker" (for the CV).

What is missing for a trader: no position or P&L-today view, no P&L attribution over many days, no
significance statistics, no risk view, nothing about model health or the agent, no simulation-versus-
live comparison, no data-health view, no way to show a second data source, and one 4.8 MB data file.

## 2. Target layout

Two navigation groups. **Desk** is new and comes first; **Research** is today's 9 tabs, kept as they are.

| Desk view | The question it answers | Main panels |
| --- | --- | --- |
| Overview | Am I making money, on what, and is anything wrong right now? | Status strip; per-coin blotter; cumulative P&L; gate scoreboard |
| P&L | Where does the P&L come from, and is it statistically real? | Attribution waterfall; daily bars; by coin; by hour of day; statistics table; daily P&L histogram |
| Execution | Are my fills good fills? | Markout curves by side and action; net edge by state; queue wait histogram; fill counts |
| Risk | How much can I lose? | Inventory path and distribution; drawdown curve; limit usage; stress table; loss-stop log |
| Model | Is the model still right about itself? | Edge table heatmap; predicted versus realised edge; arm timeline and scores |
| Signals | Do the inputs still predict? | Net edge by imbalance and volatility bucket; feature table |
| Market | What is the universe doing? | Screener table; volume, volatility and spread per coin |
| Sim vs live | Does the simulator match reality? | Two-run comparison table and overlaid curves; replay match; tape validation |
| Data health | Can I trust what I am looking at? | Recorder coverage and gaps; feed delay; bundle ages; tests passed |

Rules for every view:

- A **source badge** next to the run name: `SIM`, `WALK-FORWARD`, `PAPER`, `LIVE` or `DEMO`, each a different colour. Simulated and live numbers must never be visually confusable.
- Every number shows its unit in the label (USD, bp, lots, s). All times are UTC and say so.
- A panel whose data is not in the selected run shows one grey line, "Not in this run", and nothing else. No empty charts, no zeros standing in for missing data.
- Summary tiles first, charts second, tables last (the existing pattern).
- Profit is green, loss is red, and those two colours are used for nothing else.

## 3. The run bundle (the contract between Python and the page)

One JSON object per run. Sections other than the first seven keys are optional.

```text
schema        1
run_id        slug, e.g. "wf-2026-11-20-q1"
kind          "backtest" | "walkforward" | "paper" | "live" | "demo"
label         short human name
built_utc     "YYYY-MM-DD HH:MM"
config        {maker_fee_bps, latency_ms, queue_mult, lot_usd, q_max, decision_ms}
days          list of day rows (below)
summary       list of summary rows (below), one per symbol|variant plus one pooled row per variant
curves        {"<symbol>|<variant>": {t: [ISO UTC], pnl: [], q: [], mid: []}}   5-minute points, cumulative over the run
hourly        {"<symbol>|<variant>": {pnl: [24], fills: [24], net_edge_bp: [24]}}   by UTC hour
markouts      [{symbol, variant, action, side, h_s, bp, se, n}]
edge          [{symbol, action, imb, vol, n, mean, se}]           the EdgeTable at the end of the run
calib         [{symbol, pred_mean, real_mean, se, n}]             5 bins of predicted net edge
agent         [{symbol, ts, live_arm, switched, scores}]
wait_hist     {symbol: {edges: [], count: []}}
stress        [{symbol, shock_pct, loss_at_cap_usd, loss_at_max_seen_usd}]
screen        rows of results/screen.csv
gates         {"A": {...}, "B": {...}}                            contents of gate json files
health        {recorder: [{symbol, date, hours, gap_minutes, delay_ms_med}], tests_passed}
```

Day row keys: `symbol, date, variant, pnl, spread_capture, inventory_pnl, fees, fills, buy_fills,
notional, mk_1, mk_10, mk_60, mk_300, net_edge_bp, wait_s_med, q_abs_max, q_std, max_dd, uptime,
switches, loss_stop, live_arm`. `pnl` is net of fees. Markouts are in bp before fees. Any key the
producing script cannot fill is left out (not set to 0 or null).

Summary row keys and definitions (computed in Python, never in JavaScript):

| Key | Definition |
| --- | --- |
| `days` | number of day rows with `fills >= 20` (only these enter the statistics) |
| `pnl_total`, `pnl_mean_day`, `pnl_std_day` | sum, mean and sample standard deviation of daily `pnl` |
| `t_stat` | `pnl_mean_day / (pnl_std_day / sqrt(days))` |
| `sharpe_ann` | `pnl_mean_day / pnl_std_day * sqrt(365)` |
| `sharpe_se` | `sqrt((1 + 0.5 * s**2) / days) * sqrt(365)` with `s` the daily (un-annualised) Sharpe |
| `hit_rate` | share of counted days with `pnl > 0` |
| `profit_factor` | sum of positive daily pnl / abs(sum of negative daily pnl); omitted if there are no losing days |
| `max_dd` | largest peak-to-trough fall of cumulative daily pnl (<= 0) |
| `net_bp_per_usd` | `pnl_total / notional_total * 1e4` |
| `turnover_day` | mean daily `notional / (q_max * lot_usd)` |
| `var95_day`, `es95_day` | 5th percentile of daily pnl and the mean of days at or below it; omitted if `days < 20` |

With fewer than 5 counted days, `t_stat`, `sharpe_ann` and `sharpe_se` are omitted and the page shows
"too few days".

Files: `dashboard/runs/<run_id>.js` containing `window.RUNS = window.RUNS || {}; window.RUNS["<run_id>"] = {...};`
and `dashboard/runs/index.js` containing `window.RUN_INDEX = [{run_id, kind, label, built_utc, symbols, n_days}, ...];`
newest first. `dashboard/runs/` is git-ignored except `index.js` and runs whose id starts with `pub-`.

## 4. The snapshot (intraday, for paper trading now and live later)

One JSON file, `data/paper/snapshot.json`, rewritten every 60 s by the paper trader:

```text
schema 1, kind "paper" | "live", ts_utc,
symbols: {SYM: {bid, ask, mid, q, pnl_day, spread_capture, inventory_pnl, fees, fills_day,
                live_arm, loss_stop, stale, size_mult,
                orders: {bid: {price, queue_ahead} | null, ask: {...} | null},
                last_fills: [{ts, side, price, qty, wait_s}]   (latest 20),
                curve: {t: [], pnl: [], q: [], mid: []}}}       (1-minute points, today)
```

The page reads it only when served over http by `scripts/serve_dashboard.py`. Opened as a file, or on
the published copy, the page never requests it and shows no live strip. A real exchange account later
only has to write this same file with `kind: "live"`; no page change is needed.

## 5. Global constraints

- All of section 2 of `docs/BUILD_GUIDE.md` applies (no keys, no orders, no new dependencies, past-only, existing tests stay green).
- The page must keep working when opened as a file with no server (`<script src>` only; no `fetch` outside the live poller).
- No JavaScript framework, no bundler, no new CDN. Plotly stays at the version already referenced.
- Statistics are computed in Python (`mm/report.py`) and tested with pytest. JavaScript formats and draws; it never computes a statistic beyond a sum for display.
- Existing research views must look and behave exactly as before after Task D1.
- No file under `dashboard/` larger than 3 MB after Task D12.
- Nothing personal, no account identifiers and no absolute file paths in any bundle or snapshot.

---

## Task D1: Split the page into files (no behaviour change)

**Files:** modify `dashboard/index.html`; create `dashboard/js/core.js`, `dashboard/js/views/research.js`, `tests/test_dashboard_static.py`.

- [x] Move the inline script into `js/core.js` (theme constants, `plot`, `axis`, `layout`, number formatters, tab router `show`, `renderVisible`) and `js/views/research.js` (every existing `draw*` function and the simulator). `index.html` keeps markup and CSS and loads Plotly, `data.js`, `js/core.js`, `js/views/research.js` in that order.
- [x] Test (Python, reads the files as text): `index.html` contains every existing view id (`view-simulator`, `view-model`, `view-replication`, `view-real-data`, `view-backtest`, `view-universe`, `view-informed`, `view-tuning`, `view-about`); it contains no inline `<script>` longer than 20 lines; every `<script src>` path exists on disk; no file references `fetch(`.
- [x] Open the page and click through all 9 tabs; report any console error. If you cannot open a browser, say so and list the tabs for the user to check.

## Task D2: `mm/report.py`, the bundle builder

**Files:** create `mm/report.py`, `tests/test_report.py`. Modify `.gitignore` (ignore `dashboard/runs/*` except `index.js` and `pub-*`).

**Produces:**

```python
def day_row(res, symbol: str, date: str, variant: str, extra: dict | None = None) -> dict: ...
def summary_rows(days: list[dict], q_max: int, lot_usd: float) -> list[dict]: ...
def curve(results: list, every_min: int = 5) -> dict: ...                 # t, pnl, q, mid; cumulative across the list
def hourly(results: list) -> dict: ...                                     # pnl, fills, net_edge_bp by UTC hour
def markout_rows(res, symbol: str, variant: str) -> list[dict]: ...
def stress_rows(days: list[dict], q_max: int, lot_usd: float, shocks=(5, 10, 20)) -> list[dict]: ...
def build_bundle(run_id: str, kind: str, label: str, config: dict, days: list[dict], **sections) -> dict: ...
def validate_bundle(b: dict) -> list[str]: ...                             # empty list = valid
def write_bundle(b: dict, out_dir: str = "dashboard/runs") -> Path: ...    # writes <run_id>.js, rewrites index.js
def demo_bundle(seed: int = 0) -> dict: ...                                # kind "demo", 3 symbols x 30 days, every section filled
```

`res` is anything shaped like `mm.backtest.BTResult` or the v2 `QSResult` (attributes `minute`, `fills`,
`totals`, `markouts`, `cfg`). `day_row` leaves out any key it cannot compute from `res`.
`stress_rows`: `loss_at_cap_usd = q_max * lot_usd * shock_pct / 100`, `loss_at_max_seen_usd` uses the
largest `q_abs_max` in that symbol's days instead of `q_max`.

- [x] Tests for `summary_rows` with daily pnl `[10, -5, 20, 5, -10]` (all with 20+ fills, notional 1,000 each, `q_max=10`, `lot_usd=100`): `pnl_total == 20`, `pnl_mean_day == 4`, `pnl_std_day == pytest.approx(11.9373, abs=1e-3)`, `t_stat == pytest.approx(0.7493, abs=1e-3)`, `hit_rate == 0.6`, `profit_factor == pytest.approx(35 / 15)`, `max_dd == -10`, `net_bp_per_usd == pytest.approx(40.0)`, `turnover_day == 1.0`, no `var95_day` key (fewer than 20 days).
- [x] More tests: a day with 19 fills is excluded from `days` and the statistics but its pnl still counts in `pnl_total`; 4 counted days -> no `t_stat` / `sharpe_ann` keys; no losing days -> no `profit_factor` key; a pooled row exists per variant with `symbol == "ALL"`; `stress_rows` for `q_max=10, lot_usd=100, shock 10` gives `loss_at_cap_usd == 100`.
- [x] `validate_bundle` tests: `demo_bundle()` is valid; removing `kind`, using `kind="foo"`, a day row without `symbol`, a `curves` entry whose arrays differ in length, or any `NaN` / `Infinity` anywhere each produce exactly one message naming the problem.
- [x] `write_bundle` tests (tmp dir): the `.js` file starts with `window.RUNS = window.RUNS || {};`; stripping the JavaScript prefix and suffix leaves text that `json.loads` accepts; `index.js` lists runs newest first and replaces an entry with the same `run_id`; an invalid bundle raises `ValueError` and writes nothing.
- [x] Implement, run the suite, commit. Run `python -c "from mm.report import *; write_bundle(demo_bundle())"` so later tasks have data.

## Task D3: Page shell: run selector, badges, navigation groups

**Files:** modify `dashboard/index.html`, `js/core.js`; create `js/source.js`.

- [x] Load `runs/index.js` and, on demand, `runs/<run_id>.js` by inserting a `<script>` tag (works from a file). `source.js` exposes `Source.list()`, `Source.load(runId) -> Promise<bundle>`, `Source.current`, and fires a `runchange` event.
- [x] Header: run selector (label, kind badge, built time, age such as "built 3 h ago"), a second optional selector "compare with", and the nav in two groups, Desk then Research. The default run is the newest non-demo run, else the demo run.
- [x] Badge colours are fixed per kind; `DEMO` adds a striped banner "Demo data, not results".
- [x] `section(b, name)` helper returns the section or `null`; `emptyPanel(el)` renders "Not in this run". Every Desk view must use them.
- [x] Test (extend `test_dashboard_static.py`): the 9 Desk view ids exist (`view-overview`, `view-pnl`, `view-execution`, `view-risk`, `view-model-health`, `view-signals`, `view-market`, `view-simlive`, `view-health`); `js/source.js` contains no `fetch(`.

## Tasks D4-D11: one Desk view per task

Each task: create `dashboard/js/views/<name>.js` with one `draw<Name>(bundle, compareBundle)` function,
add the markup to `index.html`, register it in the router, and check it against the demo bundle and
against one real bundle once Build Guide Task 7 or 8 has produced one. Each view reads only the bundle
sections listed for it. Use the symbol and variant filters from the shell; default variant is `agent`
when present, else the first.

**D4 Overview** (`days`, `summary`, `curves`, `gates`)
- [x] Tiles: total net P&L (USD), net bp per dollar traded, t-statistic, hit rate, max drawdown, counted days.
- [x] Blotter table, one row per symbol: last day's inventory (`q` at the end of the curve), P&L last day, P&L total, fills per day, net edge bp, 60 s markout bp, live arm, loss-stop flag, and a small inline sparkline of cumulative P&L.
- [x] Chart: cumulative net P&L, one line per symbol plus the total.
- [x] Gate scoreboard: each numbered condition of gates A and B with its value and a pass or fail mark; "not evaluated yet" when the section is missing.

**D5 P&L** (`days`, `summary`, `hourly`)
- [x] Waterfall: spread capture -> inventory P&L -> fees -> net, for the filtered selection.
- [x] Daily net P&L bars with a 7-day mean line; stacked by symbol when "all symbols" is selected.
- [x] Heatmap symbol x UTC hour of mean P&L, and the same for net edge bp.
- [x] Statistics table: every key of the summary rows, one row per symbol and the pooled row first; Sharpe shown as "value +/- sharpe_se".
- [x] Histogram of daily P&L with the mean and zero marked.

**D6 Execution** (`markouts`, `wait_hist`, `days`)
- [x] Markout curves (bp against horizon 1, 10, 60, 300 s, log x) with standard-error bands, split by side, and a second chart split by action (JOIN, BACK). A horizontal line at the fee level shows what a fill must clear.
- [x] Queue wait histogram and median wait per symbol.
- [x] Table per symbol: fills per day, buy share, net edge bp, markouts at each horizon, adverse selection (`mk_1 - mk_60`).

**D7 Risk** (`curves`, `days`, `stress`, `summary`, `config`)
- [x] Inventory path (lots) with the +/- `q_max` limits drawn; share of time at each inventory level.
- [x] Drawdown curve under the cumulative P&L curve.
- [x] Limit usage tiles: largest inventory seen as a share of `q_max`; worst day against the daily loss stop; number of loss-stop days.
- [x] Stress table from `stress`: loss in USD for a 5, 10 and 20 percent gap against a full position. `var95_day` and `es95_day` when present, else "needs 20 days".

**D8 Model** (`edge`, `calib`, `agent`)
- [x] Edge table heatmap per symbol and action: rows = book-imbalance bucket (against us, neutral, with us), columns = volatility bucket; cell shows mean net edge bp, with `n` and `se` on hover; cells with `n < 30` hatched.
- [x] Calibration chart: predicted net edge (x) against realised (y) with error bars and the diagonal. Points below the diagonal mean the model is too optimistic.
- [x] Arm timeline: which menu entry was live over time, with switch markers; a table of the 12 arms' latest decayed scores.

**D9 Signals** (`edge`, `markouts`)
- [ ] Bars: mean net edge by imbalance bucket and by volatility bucket, pooled over actions, with standard errors. The research tabs keep the older lead-lag and flow charts; link to them.

**D10 Market and Data health** (`screen`, `health`, `days`)
- [ ] Market: screener table (sortable) with tick bp, spread in ticks, daily volume, trades per second, constrained flag; bars of volume and volatility per coin.
- [ ] Data health: recorder coverage grid symbol x date coloured by hours recorded; gap minutes; median feed delay; bundle age; tests passed. Anything older than 36 hours is flagged amber.

**D11 Sim vs live** (two bundles)
- [ ] Requires a "compare with" run. Table of the summary keys side by side with the difference, for the symbols and dates present in both.
- [ ] Overlaid cumulative P&L and overlaid markout curves; fills per day in each.
- [ ] Verdict line using the Build Guide's rule: fills within +/-30 percent and net edge within 2 bp reads "consistent", otherwise "simulator and live disagree" in amber.

## Task D12: Wire the real producers, slim the old data file

**Files:** modify `scripts/run_queue_baseline.py`, `scripts/run_agent_walkforward.py`, `scripts/daily_supervisor.py` (Build Guide Tasks 7, 8, 11), `scripts/build_dashboard.py`.

- [ ] Each of the three scripts ends by calling `mm.report.build_bundle` and `write_bundle`: run ids `qb-<date>`, `wf-<date>-q<queue_mult>`, `paper-<date>` (one growing paper bundle, rewritten daily). Fill every section the script has data for.
- [ ] Split `dashboard/data.js` into `data/research_core.js` (everything except per-day minute series) and one file per heavy section, loaded only when its research tab is first opened. No file above 3 MB.
- [ ] `scripts/build_dashboard.py --public` writes `pub-` copies of the chosen runs with `curves` thinned to 30-minute points, for publishing.

## Task D13: Live strip and local server

**Files:** create `scripts/serve_dashboard.py`, `run_dashboard.bat`, `dashboard/js/live.js`, `tests/test_snapshot.py`; modify `mm/paper.py`.

- [ ] `mm/paper.py` writes `data/paper/snapshot.json` (section 4) every 60 s, atomically (write a temp file, then replace). Test: the snapshot of a scripted session has every key in section 4, validates with a `validate_snapshot(s) -> list[str]` function added to `mm/report.py`, and contains no `NaN`.
- [ ] `scripts/serve_dashboard.py`: standard-library `http.server` on `127.0.0.1:8765` only, serving `dashboard/` and, at `/live/snapshot.json`, the snapshot file with `Cache-Control: no-store`. Nothing else on disk is reachable. `run_dashboard.bat` starts it and opens the browser.
- [ ] `js/live.js`: only if `location.protocol` starts with `http`, poll `/live/snapshot.json` every 10 s. Render a strip above the Overview: per symbol bid, ask, inventory, P&L today, fills today, resting orders with queue ahead, live arm, flags. If `ts_utc` is older than 180 s the strip turns amber and says "stale since hh:mm UTC"; on a failed request it says "no live feed" and keeps the last values greyed out.
- [ ] The strip never appears on the published copy or when the page is opened as a file.

---

## 6. Additions this guide needs from the Build Guide tasks

Apply these when doing the named Build Guide task (they are small and do not change its tests):

- Task 3 (`QueueSim`): the result also carries `uptime` per side in `totals` (share of time after warm-up with a resting order).
- Task 6 (agent): each live fill records `pred_edge_bp`, the table's estimate for its action and bucket at the decision that placed it. `calib` is built from it: 5 equal-count bins of `pred_edge_bp`, mean realised net edge per bin.
- Task 8 and Task 11 write `gate_a.json` / Gate B numbers in the shape `{"conditions": [{"id", "text", "value", "pass"}], "pass": bool}` so the scoreboard can print them.

## 7. Review focus

1. **A run with one symbol and one day.** Every view must render without errors and statistics must read "too few days", not NaN.
2. **Mixed kinds in "compare with".** Comparing a 60-day walk-forward with a 3-day paper run must restrict both to the shared symbols and dates and say how many days are shared.
3. **Huge and tiny prices.** A coin at 0.0038 and one at 100,000 in the same table: format prices with significant digits, never fixed decimals.
4. **Stale or half-written snapshot.** The poller must tolerate invalid JSON for one cycle without clearing the strip.
5. **Demo data leaking into the published page.** `--public` must refuse to include a bundle with `kind == "demo"`.

## 8. Order of work and what unlocks what

- D1-D3 and D2's demo bundle need nothing from the Build Guide and can start now.
- D4-D11 can be built against the demo bundle; each is confirmed on real data once Build Guide Task 7 or 8 has run and D12 is wired.
- D13 needs Build Guide Task 10 (paper trader).
- Sonnet is enough for D1, D3-D11 and D13's page side; use Opus for D2 (statistics) and D12.
