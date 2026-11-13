# Dashboard redesign: build guide

> **For the model doing the work (Sonnet):** one task per session, in order. Read sections 1-5, then
> only your task. `docs/BUILD_GUIDE.md` section 3 (how to work, when to stop and ask) and
> `docs/DASHBOARD_GUIDE.md` sections 3-5 (run bundle, snapshot, constraints) still apply. Where this
> guide and `DASHBOARD_GUIDE.md` section 2 (layout) disagree, this guide wins.

**Goal:** make the page answer, in this order, the three questions a trader opens it for each morning:
*what is the result, what is the market doing right now, and can I trust both?* Everything that is a
simulation of a made-up market moves into one tab.

**Stack (unchanged):** vanilla JavaScript, Plotly from the CDN already referenced, the existing dark
theme, no build step. Python computes every statistic; JavaScript formats and draws.

## 1. What is wrong today (audit, 13 Nov 2026)

| # | Problem | Effect on the reader |
| --- | --- | --- |
| 1 | The default run is the agent walk-forward and the default variant is `agent`, which has 0 fills | The landing page is a wall of zeros. The actual finding (always quoting loses 18 bp per dollar; the agent refused) is invisible |
| 2 | 18 tabs in one row; simulated-market content is spread over three of them (Simulator, How the model quotes, Paper replication) | No hierarchy; synthetic and real results sit side by side |
| 3 | A marketing header (eyebrow, title, lede, chips, headline) fills the first screen | The first real number is below the fold |
| 4 | Recorded order-book data is never shown | "Is the recorder working?" and "what does the book look like?" cannot be answered from the page |
| 5 | Paper and testnet status files exist on disk but have no view | No live state |
| 6 | Run bundles are 10-16 MB each (`curves` is 9 MB of 5-minute points, `agent` 1.4 MB) | Slow first load; breaks the 3 MB rule in `DASHBOARD_GUIDE.md` |
| 7 | P&L is shown in USD of a 100 USD lot | Not comparable across coins or with fees; bp per dollar traded is the unit a desk uses |
| 8 | Results are shown without uncertainty | A -18 bp with t = -8 looks the same as a -18 bp with t = -1 |
| 9 | Four Desk views are placeholders (Signals, Market, Sim vs live, Data health); the Progress list in `DASHBOARD_GUIDE.md` is stale (D5-D8 are built) | Dead tabs |

## 2. New layout

One row, eight tabs, then three quieter ones on the right.

| Tab | Question | Contains (old view ids nested inside) |
| --- | --- | --- |
| **Verdict** | Does it make money, and how sure are we? | `view-overview`, rebuilt |
| **Live** | What is happening right now? | new `view-live` (hidden when opened as a file) |
| **Market book** | What does the book look like, and does it predict? | new `view-book`; `view-market` (screener) as sub-tab "Universe" |
| **P&L** | Where does the P&L come from? | `view-pnl` |
| **Execution** | Are my fills good fills? | `view-execution` |
| **Risk** | How much can I lose? | `view-risk` |
| **Model** | Is the model right about itself? | `view-model-health`; `view-signals` as sub-tab "Signals" |
| **Data** | Can I trust what I am looking at? | `view-health`; `view-simlive` as sub-tab "Sim vs live" |
| *Simulator* | How does the textbook model behave? | `view-simulator`, `view-model`, `view-replication` as sub-tabs "Playground", "How it quotes", "Paper replication" |
| *Research archive* | What did v1 find? | `view-real-data`, `view-backtest`, `view-universe`, `view-informed`, `view-tuning` as sub-tabs |
| *About* | What is this project? | `view-about`, plus the old header's lede and chips |

Rules:

- **Every existing `id="view-..."` stays in `index.html`.** `tests/test_dashboard_static.py` checks
  them and must not be edited. Nesting changes which tab shows a section, not its id.
- Old links keep working: `#model`, `#replication`, `#signals` and so on open the right tab and sub-tab.
- The synthetic `demo` run is not offered in the run selector unless the URL has `?demo=1`. Simulated
  markets live in the Simulator tab and nowhere else.
- Header becomes one 48 px bar: project name, run selector with source badge, symbol filter, and a
  one-line verdict taken from the bundle (`takeaways.headline`). Lede, chips and headline tiles move
  to About.

## 3. Design rules (apply to every view)

1. **Unit.** The primary metric is bp per dollar traded. USD appears as a secondary column, labelled
   "per 100 USD lot". Every axis and column header carries its unit; all times are UTC.
2. **Uncertainty.** Any mean shown as a mark gets a 95% interval (mean +/- 1.96 se) or a t-statistic
   beside it. Cells and points with n < 30 are hatched or hollow, never hidden.
3. **Colour.** Green and red mean profit and loss only. Bid is blue `#38bdf8`, ask is amber `#f5a524`
   (first two entries of `SERIES`). Source badges keep their existing colours.
4. **One sentence per chart.** Under each title, a subtitle states what the chart shows *in this run*,
   read from `takeaways.<chart id>` in the bundle. If the key is missing, show the static "how to read
   this" text. JavaScript never composes a finding.
5. **Compare, do not filter.** Where variants exist (`agent`, `join_touch`, `frozen_start`, queue
   0.5x / 1x / 2x), show them side by side. A filter that can hide the result is a bug.
6. **Zero is drawn.** Every P&L, edge and markout axis includes zero with a visible line. The fee
   level (10 bp) is drawn wherever a fill's edge is plotted before fees.
7. **Empty states.** Missing section: one grey line, "Not in this run". Section present but no fills:
   "No fills: the agent stayed out", with the count of days. Never an empty chart or a row of zeros.
8. **Density.** At most two charts per row, 280 px tall; one column below 900 px. Tables: numbers
   right-aligned, `font-variant-numeric: tabular-nums`, sticky header, sortable by click.
9. **Time range.** Charts over time default to the last 14 days with buttons 3d / 14d / all; the
   choice is shared across tabs.
10. **Weight.** No file under `dashboard/` above 3 MB. The page is usable before any run file larger
    than 300 kB has loaded.

## 4. Chart-by-chart decisions

| Where | Today | Decision |
| --- | --- | --- |
| Verdict | 6 tiles for one variant | Keep 6 tiles, but for the baseline (`join_touch`, queue 1x): net bp/USD, t, share of days positive, counted coin-days, agent fills, Gate A |
| Verdict | Cumulative P&L, one line per coin | Keep; add the before-fees line (dashed) and one line per variant for the pooled total |
| Verdict | (none) | **New, top of page: forest plot.** Rows = coin x queue assumption (plus pooled). Mark = net bp per dollar, whisker = 95% interval, second hollow mark = before fees. Vertical line at 0 |
| Verdict | Blotter | Keep; columns in bp; one row per coin x variant; sparkline stays |
| Verdict | Gate scoreboard | Keep; move directly under the forest plot |
| P&L | Waterfall in USD | Change to bp per dollar: spread capture, inventory P&L, fees, net; grouped by coin so the three coins sit side by side |
| P&L | Daily bars stacked by coin | Replace with small multiples: one row per coin, daily bars with the 7-day mean. Stacked signed bars cannot be read |
| P&L | Hour-of-day heatmaps | Keep the net-edge one; drop the USD one. Hover shows fills; cells with under 30 fills hatched |
| P&L | Daily P&L histogram | Keep; annotate mean, t and days |
| P&L | Statistics table | Keep; pooled row first; Sharpe as value +/- se |
| Execution | Markout curves by side and by action | Keep both; add a third panel **by queue wait** (terciles of `wait_s`): fills after a long wait are the test of the queue model |
| Execution | Queue wait histogram | Keep; log-spaced bins |
| Execution | (none) | **New: fill rate.** Fills per hour and share of time with a resting order (`uptime`), per coin and side |
| Risk | Inventory path over the whole run | Default to the last 3 days; add "share of time at +/- q_max" tile |
| Risk | Inventory histogram, drawdown, stress table | Keep |
| Model | Edge heatmap | Keep; diverging scale centred on 0, fixed at +/- 20 bp across coins so panels compare |
| Model | Calibration chart | Keep |
| Model | Arm timeline as a 0-11 step line | Replace with a one-row colour strip per coin (which arm was live) plus a count of switches; a table of arm definitions beside it |
| Model > Signals | placeholder | Net edge by imbalance bucket and by volatility bucket with intervals (old D9) |
| Data | placeholder | Recorder coverage grid, tape validation, sim vs live (old D10, D11) |

## 5. New data

All produced in Python, validated by `validate_bundle`, tested with pytest.

**`verdict` bundle** (`dashboard/runs/pub-verdict.js`, under 300 kB, loaded first, default run):

```text
kind "walkforward", built from qb-* and the three wf-* runs
forest     [{symbol, variant, queue_mult, n_days, net_bp, net_se, gross_bp, gross_se, t, hit_rate}]
compare    [{symbol, variant, queue_mult, fills, pnl_total, net_bp, mk_60, max_dd}]
curves     pooled "ALL|<variant>" only, daily points
gates      as today
takeaways  {headline, "<chart id>": sentence, ...}
```

`net_bp = sum(pnl) / sum(notional) * 1e4`. `net_se` is the standard error of the day-level ratio by
the delta method: with daily `p_i`, `n_i`, `r = sum p / sum n` over `D` days, `se = sqrt(D / (D - 1) * sum((p_i - r*n_i)^2)) / sum n`
times 1e4 (with equal daily notional this equals the sample standard deviation of daily bp over `sqrt(D)`). `gross_bp` uses `pnl + fees`.

**Bundle diet** (in `mm/report.py`, used by the three producer scripts):

- `curves`: 5-minute points for the last 3 days of the run, daily points before that.
- `agent`: keep only rows where `switched` is true, plus one row per symbol per day.
- New optional sections: `markout_by_wait [{symbol, variant, wait_bucket, h_s, bp, se, n}]`,
  `fill_rate [{symbol, variant, side, fills_per_hour, uptime}]`, `takeaways {..}`.

**Book bundle** (`dashboard/runs/book-<date>.js`, from `data/live` via `mm.recorder.load_live`):

```text
kind "book", label, built_utc, symbols
touch      {SYM: {t: [], bid: [], ask: [], bid_qty: [], ask_qty: []}}      1-second samples thinned to changes (price moves, size moves over 10%), at most 2,500 points, last 6 hours
trades     {SYM: {t: [], price: [], qty: [], side: []}}                    last 6 hours, capped at 1,500 per coin (largest kept)
profile    [{symbol, tick_bp, spread_ticks_med, share_one_tick, touch_qty_med, touch_in_trades,
             updates_per_min, trades_per_min, deplete_s_med}]
imb_curve  [{symbol, h_s, bucket, imb_mid, move_bp, se, n}]                 10 imbalance deciles x horizons 1, 5, 30 s
spread_hist {SYM: {ticks: [], share: []}}
hourly     {SYM: {spread_bp: [24], touch_usd: [24], trades: [24]}}
coverage   [{symbol, date, hours, gap_minutes}]
```

`touch_in_trades` = median size at the best price / median trade size. `deplete_s_med` = median time
for a newly formed best level to trade through or be cancelled away.

**Live file** (`data/live/heartbeat.json`, rewritten every 2 s by `mm/recorder.py`; the same file
`docs/SPEC_V2_1.md` Task 12 asks for):

```text
schema 1, ts_utc,
symbols {SYM: {bid, ask, bid_qty, ask_qty, last_book_utc, last_trade_utc,
               book_per_min, trades_per_min, last_trades: [{t, price, qty, side}] (latest 30)}}
```

Written atomically (temp file, then replace). The page reads it, and `data/paper/snapshot.json` and
`data/testnet/<SYM>/status.json`, only in `js/live.js` and only when `location.protocol` is http(s).
The Docker `dashboard` service already serves the repo root, so these paths are reachable as
`/data/...` with no new server.

## 6. Wireframes

```text
VERDICT
+------------------------------------------------------------------------------------------+
| MM-AS   [Run: 60-day verdict  WALK-FORWARD]  [Symbol: all]    Net -18.2 bp/USD, t -8.4   |
+------------------------------------------------------------------------------------------+
| Verdict | Live | Market book | P&L | Execution | Risk | Model | Data     Simulator ...   |
+------------------------------------------------------------------------------------------+
| net bp/USD | t-stat | days + | coin-days | agent fills | Gate A                          |
+--------------------------------------------+---------------------------------------------+
| Net edge by coin and queue (forest plot)   | Gate A scoreboard                           |
|  COTI q0.5  --o--    .                     |  A1 mean daily net > 0, t > 3      FAIL     |
|  COTI q1.0  --o--    .        | 0          |  ...                                        |
+--------------------------------------------+---------------------------------------------+
| Cumulative P&L (net solid, before fees dashed, one line per variant)                     |
+------------------------------------------------------------------------------------------+
| Blotter: coin x variant | fills/day | net bp | 60 s markout | max DD | sparkline         |
+------------------------------------------------------------------------------------------+

MARKET BOOK                                                     [coin: ANKRUSDT v]  [6h|1h|15m]
+---------------------------+--------------------------------------------------------------+
| BID            ASK        | Best bid / ask (step lines) with trades as dots              |
| 0.00389      0.00390      |   dot colour = aggressor side, dot area = size               |
| 1.2M units   0.4M units   +--------------------------------------------------------------+
| [#########|###]  imb +0.50| Size at the best price: bid up, ask down (mirrored areas)     |
| spread 1 tick = 25.7 bp   |   imbalance as a line on the right axis                      |
| microprice - mid +6.4 bp  +------------------------------+-------------------------------+
| queue = 31 median trades  | Next move by imbalance decile| Spread in ticks (share of time)|
| updates 212/min, age 1 s  |  1 s, 5 s, 30 s, with bands  |                               |
+---------------------------+------------------------------+-------------------------------+
| Profile table: one row per coin (tick bp, spread, touch size, queue in trades, depletion) |
+------------------------------------------------------------------------------------------+
```

The left card of Market book is live when served over http (from `heartbeat.json`, with an age
counter that turns amber above 10 s and red above 60 s) and otherwise shows the last sample in the
book bundle with its timestamp and a "recorded" badge.

**Live tab:** one status row per source (Recorder, Paper, Testnet), each with last-update age and a
state dot; then one card per coin: bid, ask, inventory, P&L today, fills today, resting orders with
queue ahead, live arm, flags. Testnet cards carry a permanent label: "TESTNET: execution test, not a
result".

## 7. Tasks

Each task ends with the suite green and a commit. Open the page and click every tab; report console
errors. If you cannot open a browser, say so and list what the user must check.

**R0. Baseline.** Run the suite. In `docs/DASHBOARD_GUIDE.md` tick the D5-D8 boxes that are already
built (P&L, Execution, Risk, Model views exist) and add one line pointing to this guide.

**R1. Shell.** New header bar and tab row per section 2. Add `subtabs(hostId, [{id, label}])` to
`js/core.js`: a segmented control that shows one nested `view-*` section at a time and remembers the
choice in the hash (`#simulator/replication`). Map every old hash to its new place. Hide the demo run
unless `?demo=1`.
- Tests (extend `test_dashboard_static.py`, do not edit existing tests): the tab row has exactly 11
  links; `view-live` and `view-book` exist; `view-model` and `view-replication` are descendants of the
  element with `data-tab="simulator"`; the tab row has no link whose `data-view` is `model`,
  `replication`, `signals`, `market`, `simlive` or `health`.

**R2. Verdict data.** `mm/report.py`: `forest_rows(days)`, `compare_rows(days)`,
`thin_curves(curves, keep_days=3)`, `thin_agent(rows)`, `takeaways(bundle)`, and
`verdict_bundle(runs: list[dict]) -> dict`. `scripts/build_verdict.py` + `run_build_verdict.bat` read
the `qb-*` and `wf-*` runs and write `pub-verdict.js`. Apply the diet in the three producer scripts.
- Tests: for daily pnl `[10, -5, 20, 5, -10]` and notional 1,000 each, `net_bp == 40.0` and
  `net_se == pytest.approx(53.385, abs=1e-2)`; a variant with zero fills yields a row with `fills == 0`
  and no `net_bp` key; `thin_curves` keeps the last point of every day; `verdict_bundle` output passes
  `validate_bundle` and serialises under 300 kB for the committed runs; every committed run file is
  under 3 MB after the diet.
- Check: the pooled queue-1x `join_touch` row reads about -18.2 bp net, -8.2 bp before fees.

**R3. Verdict view.** Rebuild `js/views/overview.js` per the wireframe: tiles, forest plot (Plotly
scatter with `error_x`, categorical y, newest first), gate scoreboard, cumulative P&L, blotter.

**R4. Chart revisions.** Apply every "change", "replace" and "new" row of section 4 for P&L,
Execution, Risk and Model, including the shared 3d / 14d / all range buttons. Build Model > Signals.

**R5. Book statistics.** `mm/bookstats.py` (pure functions on the `load_live` frames) and
`scripts/build_book_bundle.py` + `.bat`. Past-only: a move at horizon h for a sample at t uses the
book at or before t + h and is dropped if the day ends first.
- Tests on a synthetic tape: a book that alternates imbalance 0.9 / 0.1 with the mid moving up after
  0.9 gives a strictly increasing `imb_curve`; `share_one_tick == 1.0` when the spread never widens;
  hours containing a gap over 120 s are excluded from every statistic and counted in `coverage`.

**R6. Market book view.** `js/views/book.js` per the wireframe, from the book bundle. Nest
`view-market` (screener table, sortable) as sub-tab "Universe".

**R7. Live.** `mm/recorder.py` writes `heartbeat.json` (additive; existing recorder tests unchanged).
`js/live.js` polls it every 2 s and the paper and testnet files every 10 s; tolerates one bad read
without clearing the screen; shows "no live feed" after three. Build `view-live` and wire the Market
book touch card.
- Tests: `heartbeat.json` from a scripted recorder session has every key in section 5 and no `NaN`;
  `fetch(` appears only in `js/live.js`.

**R8. Data view.** Coverage grid (coin x date, colour = hours recorded), tape validation, tests
passed, bundle ages; sub-tab "Sim vs live" (old D11).

**R9. Depth (built; opt-in with `--depth` / `run_recorder_multi_depth.bat`; stream `<symbol>@depth10@1000ms`, checked against the Binance spot WebSocket docs).** The recorder stores only the best bid and ask. A ladder
or depth heatmap needs Binance's partial-depth stream (10 levels, 1 s snapshots; confirm the stream
name and limits in the Binance spot WebSocket docs before coding). Adds `--depth` to the recorder, a
`depth` section to the book bundle, and two panels: a 10-level ladder with cumulative size, and a
price x time heatmap of resting size.

**R10. Publish.** `scripts/publish_dashboard.py` includes `pub-verdict.js` and the newest `book-*`
run. Check the public copy on a 390 px wide screen. Save three screenshots (Verdict, Market book,
Execution) to `docs/img/` and reference them from `README.md`.

## 8. Review focus

1. **Zero-fill variants.** The agent has no fills on the headline run. Every view must say so in
   words and still show the baseline.
2. **Thin coins.** ANKR and SKL can go minutes without a trade. Charts must not interpolate across
   gaps; the touch card must distinguish "quiet market" (book fresh, no trades) from "feed down".
3. **Price scale.** 0.0039 and 100,000 in one table: significant digits, never fixed decimals. Sizes
   in base units can be millions: show USD beside them.
4. **Testnet numbers leaking into results.** Nothing from `data/testnet` may enter a run bundle.
5. **Stale takeaways.** A sentence in `takeaways` is rebuilt with the bundle; the page never caches it.
