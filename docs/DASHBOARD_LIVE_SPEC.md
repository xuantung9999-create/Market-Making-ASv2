# Live dashboard spec: what the traders did, and why they lost

> **For the model doing the work (Sonnet):** one task per session, in the order of section 9. Read
> sections 1-8 first, then only your task. `docs/BUILD_GUIDE.md` section 3 (how to work, when to stop
> and ask) still applies. Where this spec disagrees with `docs/DASHBOARD_REDESIGN.md` or
> `docs/DASHBOARD_GUIDE.md`, this spec wins. Written 14 Nov 2026; the suite was at 334 passing.

## 1. Goal

The owner opens the page to answer, in two minutes and in this order:

1. **Is each bot healthy right now, and if not, what went wrong?** (incidents first)
2. **Where did the P&L come from?** (spread captured, adverse selection, inventory, fees, and a
   separate bucket for testnet artifacts)
3. **How did it execute?** (was it quoting, how long orders waited, what happened after each fill)
4. **What was the model thinking?** (which arm was live, what edge it predicted, why it stayed out)

The subject is the **live sessions**: the two testnet traders and the paper trader. Testnet answers
"does it execute correctly"; paper (real mainnet book, simulated fills) answers "does the model make
money". Every view takes a session and works for both. The 60-day backtest material stays, but moves
out of the way.

## 2. Decisions already made by the owner (do not reopen)

| Topic | Decision |
| --- | --- |
| Main subject | Live sessions (testnet and paper), not the backtest |
| Reading order | Incidents and health first, economic breakdown below |
| Testnet artifacts | Shown in their own attribution bucket with the fills listed. Never hidden, never mixed into the strategy numbers |
| Paper trader | In scope: add it to the 24/7 supervisor; same views as testnet |
| Time unit | One continuous timeline rebuilt from the fill files across restarts; restarts, loss-stops and UTC day boundaries drawn as markers |
| Drill-down | Clicking any fill or incident opens the tape around it |
| Old tabs | Live tabs first; all backtest and simulator material under one "Research" tab |
| Paper trader coins | ANKRUSDT, COTIUSDT, SKLUSDT |
| Trader restarts | Restart the testnet traders as soon as L1 (and L1b, if ready) is merged and the suite is green. No further go-ahead needed for that one restart |
| Position across restarts | The executor carries its position, cash, fees and daily loss-stop state across restarts (task L1b). This is the only trading change allowed |
| Allowed changes | Trader logging (`mm/testnet.py`, `mm/paper.py`), a new Python analysis step, removing and merging tabs and updating their tests |

## 3. What is wrong today (audit of the running page, 14 Nov 2026)

| # | Seen on the page | Cause | Effect |
| --- | --- | --- | --- |
| 1 | Live > Market feed says "No testnet trader running" and "No paper trader running" while two testnet traders have been up 17.6 h | Not diagnosed. The supervisor's server whitelists `/data/testnet/<SYM>/status.json`, so find out why `js/live.js` shows nothing | Two blank panels on the landing tab |
| 2 | BTC row says "quoting", with Bid and Ask both "–", position -11 lots against a cap of 10, and no order since 02:57 UTC | "quoting" only means "loss stop not fired". The trader records no reason for having no order; `Executor._place` returns silently when the balance check fails | The page cannot say why the bot is idle. This is the largest gap |
| 3 | "Fills total 250" beside "Fills 24 h 297"; ETH shows 0 total and 7 in 24 h | `status.json` counters restart from 0 with the process | Numbers contradict each other |
| 4 | Testnet P&L chart is a sawtooth that snaps back to 0 | `pos`, `cash` and `fees` restart from 0 with the process; the chart plots the per-process number | The loss cannot be read off the chart |
| 5 | Position chart: ETH swings +/-0.5, BTC is a flat line | Base units of two coins share one axis | BTC inventory is invisible |
| 6 | Order activity: one 400-high bar, the other 23 hours near zero | Linear count axis, one burst | Uninformative |
| 7 | One BTC sell at 57,882.59 with mid 67,542.74 (edge -1,430 bp, about -17.1 USDT on 0.00177 BTC) is an ordinary table row | No outlier or artifact detection | The biggest single loss is not explained. For scale: the session then showed about -25 USDT net with about -23 USDT of estimated fees |
| 8 | "Edge vs mid" uses the mid at detection | Fills are found by polling once a second, so the mid is up to a second late | Edge and markouts are biased |
| 9 | No markouts, no queue wait, no time-in-market, no attribution for live sessions | Never built; they exist only for backtest bundles | "How did it execute" is unanswered |
| 10 | ETH agent: 0 fills and zeros everywhere | Nothing shows the arm scores or why the live arm stays out | A deliberate "stay out" looks like a broken bot |
| 11 | Header sentence is always the backtest verdict | Static `takeaways.headline` from `pub-verdict.js` | Says nothing about the live state on the live tabs |
| 12 | Paper panels are empty | The paper trader is not in `config/live.json` | Permanent blank |

A known trading fault, fixed in task L1b: the executor starts with `pos = 0`, `cash = 0` and
`stopped = False` after a restart while the account still holds inventory. The inventory cap and the
daily loss stop therefore both start from a false zero, which fits BTC reaching -11 lots with a cap
of 10 and a day's loss passing the 20 USDT limit. Confirm this in L0 before L1b. Any other trading
bug: describe it and stop.

## 4. Layout

Six tabs. The first five take the session selector; Research does not.

| Tab | Question | Contents |
| --- | --- | --- |
| **Overview** | Healthy? What went wrong? | State strip per session, incident timeline, incident list, headline tiles, cumulative P&L with markers |
| **P&L** | Where did the money go? | Attribution waterfall, attribution over time, per-day table, worst fills |
| **Execution** | How did it execute? | Quote-state strip, markout curves, edge-at-fill histogram, queue wait, order funnel, fills table with tape drill-down |
| **Model** | What was it thinking? | Live-arm strip, arm scores, predicted against realised edge, reasons for staying out |
| **Market & health** | Can I trust the inputs? | Existing Market feed cards, recorder table, supervisor processes, feed gaps |
| *Research* | What did the backtest find? | Sub-tabs: Verdict, P&L, Execution, Risk, Model, Market book, Data, Simulator, Archive, About. Contents unchanged |

- Header bar: project name, **session selector** (for example `testnet · BTCUSDT · join`,
  `testnet · ETHUSDT · agent`, `paper · ANKRUSDT`, plus "All sessions" on Overview only), range
  buttons `6h / 24h / 3d / all` shared across tabs, and one live sentence from the session bundle
  (`headline`). The backtest sentence appears only inside Research.
- Every existing `id="view-..."` stays in `index.html`; old hashes resolve to their new place.
- Tests that encode the old layout change with it, in the same commit, and the commit message lists
  them: `test_tab_row_has_exactly_eleven_links` (now six), the tab-wrapper tests, and the hash-map
  test in `tests/test_dashboard_static.py`. No other existing test is edited.
- A testnet session carries the permanent label "TESTNET: execution test, not a result". A paper
  session carries "PAPER: real market data, simulated fills".
- Desktop first (two columns at 1,200 px and wider), one column below 900 px, readable at 390 px.

## 5. Chart rules

Each rule exists because of a row in section 3.

1. **Every panel answers its question or says why it cannot.** An empty state is one sentence with
   the reason and the time it started: "Not quoting since 02:57 UTC: sell side at inventory cap
   (-11 of 10 lots), buy side blocked by balance". Never an empty chart, a row of dashes or zeros.
2. **One unit per axis.** Inventory is in lots of `lot_usd` (cap drawn at +/- `q_max`) or in USDT.
   Base units appear only in tables. Sessions are small multiples with a shared x axis.
3. **Outliers do not set the scale.** A value axis spans the 1st to 99th percentile of the visible
   data, padded 10%; points outside are drawn at the edge as hollow triangles with the true value on
   hover, and a count ("3 points off scale") sits under the chart. Count axes with a max-to-median
   ratio above 20 use a log scale.
4. **Time charts show state, not blank time.** Behind every time series, a background band coloured
   by quote state (section 6), so a flat stretch reads as "loss stop" or "feed down".
5. **Unit of P&L.** USDT for totals (these are 100 USDT lots; say so). bp of notional traded for
   everything per fill. Both in tables. All times UTC.
6. **Uncertainty.** A mean gets a 95% interval or its n. Any statistic on fewer than 30 fills is
   drawn hollow and labelled "n = 12".
7. **Colour.** Green and red mean profit and loss only. Bid blue `#38bdf8`, ask amber `#f5a524`.
   Artifact is purple `#a78bfa`, used for nothing else. Quote states use a fixed palette defined once
   in `js/core.js`.
8. **Zero and the fee are drawn** on every edge, markout and P&L axis.
9. **One sentence per chart**, under the title, taken from the bundle's `takeaways`. Python writes
   every finding; JavaScript only formats and draws.
10. **Proportions.** Time series are full width and 240 px tall. Distributions and curves sit two
    per row at 280 px. A chart with fewer than 3 marks becomes a table or a tile.
11. **Numbers.** Prices in significant digits, tabular numerals, right-aligned, sticky sortable
    headers.

## 6. Data

### 6.1 New trader logging (additive; no change to any order decision)

Applies to `mm/testnet.py`; the paper trader writes the same files where the concept exists.

- **`state_<date>.jsonl`**, one line when the quote state of a side changes, plus one line per side
  every 60 s: `{ts_us, side, state, detail}`. Exactly one state per side at a time:

  | State | Meaning |
  | --- | --- |
  | `QUOTING` | an order is resting |
  | `WARMUP` | inside `warmup_s` |
  | `POLICY_OUT` | the policy chose OUT (include the live arm and its predicted edge in `detail`) |
  | `LOSS_STOP` | the daily loss stop fired |
  | `INV_CAP` | real inventory at the cap on this side |
  | `NO_BALANCE` | the spot balance check failed (today a silent `return`) |
  | `BELOW_MIN` | below the exchange minimum |
  | `REJECTED` | the last place was rejected and nothing is resting (include the error) |
  | `STALE_FEED` | no book update for `stale_s` |
  | `EXCHANGE_ERROR` | REST or websocket failure |

- **`orders_*.jsonl` place records** gain: `bid`, `ask`, `bid_qty`, `ask_qty`, `mid` at the
  decision, `action` (JOIN or BACK), `live_arm`, and `pred_bp` (the table's predicted net edge, when
  the policy has one).
- **`fills_*.jsonl`** gain: `fill_ts_us` (the exchange's own time from the order response, not the
  detection time), `place_ts_us`, `bid` and `ask` at detection, `fee_est`.
- **`session.jsonl`**, appended at every start and clean stop: `{ts_us, op: "start" | "stop", pid,
  args, base_free, quote_free, pos_at_start}`.
- **`status.json`** gains `state: {bid: {state, detail, since_us}, ask: {...}}` and
  `session_start_us`. Existing keys are unchanged.
- Old files lack these fields. Every reader treats them as optional. Old fills are placed in time by
  `ts_us` and flagged `timing: "detected"`.
- Restarting the running traders to pick up the new logging needs the owner's go-ahead.

### 6.2 Analysis step

`mm/livestats.py` holds pure functions on data frames. `scripts/build_session.py` reads
`data/testnet/**`, `data/paper/**` and the recorded feed, and writes the files below. The supervisor
calls it on its existing schedule; the heavy parts run every 5 minutes at most.

```text
dashboard/live/sessions.js            window.SESSIONS = [{id, source, symbol, policy, first_ms, last_ms, n_fills}]
dashboard/live/session-<id>.js        one bundle per session, under 1.5 MB
dashboard/live/tape-<id>-<date>.js    loaded on the first drill-down for that day, under 1.5 MB
```

Session bundle (`id` = `<source>-<symbol>-<policy>`, for example `testnet-BTCUSDT-join`):

```text
meta         {id, source, symbol, policy, lot_usd, q_max, max_loss, fee_bps, built_ms, thresholds}
headline     one sentence
now          {state: {bid, ask}, lots, pos_usd, open: {bid, ask}, last_fill_ms, process: {running, uptime_s, restarts}}
curve        {t, pnl, pnl_ex_artifact, lots}                     cumulative across restarts
markers      [{t, kind: "restart" | "loss_stop" | "day" | "incident", ref}]
states       {bid: [{t0, t1, state, detail}], ask: [...]}
uptime       [{side, state, seconds, share}]
attribution  {total: {edge, adverse, carry, fees, artifact, net}, by_day: [...], by_hour: [...]}    USDT, and bp of notional
fills        [{i, t, side, price, qty, mid, edge_bp, mk_1, mk_5, mk_30, mk_60, mk_300, wait_s, pnl_after, lots_after, artifact, reason}]
markout      [{group: "all" | "buy" | "sell" | "JOIN" | "BACK", h_s, bp, se, n}]      artifacts excluded, count stated
funnel       {placed, cancelled, rejected, filled, partial, by_hour: [...], reject_reasons: [{error, n}]}
incidents    [{id, kind, severity, t0, t1, sentence, fills: [i], cost_usd}]
model        {arm_strip: [{t0, t1, arm}], arms: [{arm, e_min_bp, z, gamma_bp, score_bp, fills}],
              history: [{t, scores, fills, live_arm, switched}], calibration: [{pred_bucket, pred_bp, real_bp, se, n}]}
takeaways    {"<chart id>": sentence}
```

### 6.3 Definitions

- **Mid.** The mid of the session's own recorded feed (`data/testnet/feed`, or the paper feed) at or
  just before a timestamp. A mid from a book older than 5 s is "stale" and the statistic is dropped,
  with the drop counted.
- **Continuous P&L.** Rebuilt from all fill files in time order: `cash + pos * mid - fees`, with
  `pos` and `cash` accumulated from fills, ignoring the per-process counters. `fees` is the estimate
  at `fee_bps`, labelled "estimated".
- **Attribution.** These five terms sum to `net` exactly. Test the identity to 1e-6.
  - `edge` = sum over fills of `side * (mid_fill - price) * qty`
  - `adverse` = change in mid over the 60 s after each fill, times the signed quantity of that fill
  - `carry` = all remaining inventory P&L (position times mid change, minus `adverse`)
  - `fees` = minus the estimated fees
  - `artifact` = the `edge` of every artifact fill, plus the inventory P&L across every artifact
    jump. These amounts are removed from `edge`, `adverse` and `carry`.
- **Artifact fill.** `|price - mid_fill|` above `max(50 bp, 5 x the median spread of the previous
  5 minutes)`. **Artifact jump.** The mid moves more than 100 bp between two consecutive book
  updates less than 2 s apart. Thresholds live in `meta.thresholds` and are printed under the
  attribution chart. The 02:57:01 UTC BTC sell on 14 Nov must be flagged.
- **Markout** at horizon h, in bp: `side * (mid(t + h) - price) / price * 1e4`, before fees.
  Past-only: dropped if the feed has a gap inside the window.
- **Queue wait.** `fill_ts - place_ts` of the filled order.
- **Incidents** (the sentence is written in Python and includes numbers):

  | Kind | Rule | Severity |
  | --- | --- | --- |
  | `loss_stop` | a `loss-stop` record | high |
  | `artifact_fill` | defined above | high |
  | `inventory_breach` | `abs(lots) > q_max` | high |
  | `idle` | process running, no side `QUOTING` for over 5 min, state not `POLICY_OUT` | high |
  | `restart` | a session start with no clean stop before it | medium |
  | `reject_burst` | 5 or more rejects within 60 s | medium |
  | `feed_gap` | no book update for over 120 s | medium |
  | `exchange_error` | any | low |
  | `policy_out` | `POLICY_OUT` for over 1 h (information, not a fault) | info |

### 6.4 Tape for drill-down

Per session and UTC day: the touch (bid, ask, sizes) sampled once a second and thinned to changes,
the trades, and our own orders as segments `{side, price, t_place, t_end, end: "fill" | "cancel" |
"reject"}`. Kept only inside windows from 60 s before to 300 s after each fill or incident, with
overlapping windows merged. If a day exceeds 1.5 MB, keep the windows of incidents and of the 200
fills with the largest absolute edge, and say so in the panel.

## 7. Views

**Overview**
- State strip: one card per session showing the state of each side with its reason and how long it
  has lasted, lots against the cap as a bar, open orders, last fill age, process uptime. This
  replaces the "quoting" column.
- Tiles: net P&L, net excluding artifacts, fees, fills, share of time quoting, open incidents.
- Incident timeline: one row per session, x = time, marks coloured by severity, over the quote-state
  band. Click selects the incident.
- Incident list: newest first: time, session, sentence, cost in USDT, "open tape".
- Cumulative P&L: net solid, excluding artifacts dashed, markers as vertical lines; lots as a step
  line in a 100 px panel beneath, sharing the x axis.

**P&L**
- Waterfall: edge, adverse selection, carry, fees, artifact, net. USDT on the bars, bp of notional
  in the labels. One per session; side by side when "All sessions" is chosen.
- Attribution over time: stacked signed bars per hour (per day beyond 3 d), net as a line.
- Day table: fills, notional, the five terms, net, loss-stop yes or no.
- Worst and best 20 fills by `edge + mk_60`, artifact rows tinted purple, click opens the tape.

**Execution**
- Quote-state strip per side with the `uptime` shares as a small table.
- Markout curves by side and by action, with the fee line and standard-error bands.
- Edge at fill: histogram in bp, artifacts off scale and counted (rule 3).
- Queue wait: log-spaced histogram, plus markout by wait tercile.
- Order funnel: placed to resting to filled, cancelled or rejected; reject reasons as a table;
  activity per hour on a log axis.
- Fills table: paged, sortable, filter by side and by artifact; click a row to open the tape panel:
  best bid and ask as step lines, trades as dots, our orders as horizontal segments, the fill as a
  marker, the markout horizons as vertical ticks, and a caption sentence.

**Model**
- Live-arm strip over time with switches counted, and the menu table (arm, `e_min_bp`, `z`,
  `gamma_bp`, score, fills) with the live arm highlighted.
- Arm scores over time from `history_*.jsonl`; zero drawn.
- Predicted against realised edge (`pred_bp` against the 60 s markout net of fee), bucketed, with
  intervals.
- "Why it stayed out": share of time `POLICY_OUT`, the best arm's score against the entry
  threshold, and a sentence such as "Every arm scores below 0 bp, so the agent quotes nothing".
- For a `join` session this tab shows one line: "Fixed policy: always join the best price. No model
  decisions."

**Market & health**
- The current Market feed cards and the PC status process and recorder tables, merged into one tab.
  Fix audit row 1.

## 8. Rules for the work

1. No change to what orders are sent, when, or at what price, except task L1b. Everything else is
   logging only. If another trading bug shows up, report it and stop.
2. One restart of the traders and the supervisor is approved, after L1 (and L1b) is merged with the
   suite green. Before it, confirm no order is left resting; after it, check the new log files
   appear and report. Any later restart needs the owner's go-ahead.
3. Nothing from `data/testnet`, `data/paper` or `dashboard/live` may reach a published run bundle or
   the public copy (`scripts/publish_dashboard.py`). Keep the existing test for this green.
4. Python computes every number and sentence, with pytest coverage. JavaScript formats and draws.
5. Vanilla JavaScript, Plotly from the existing CDN reference, the existing dark theme, no build
   step. `fetch(` stays only in `js/live.js`; session bundles load by script tag like `status.js`.
6. No file under `dashboard/` above 3 MB. The Overview tab is usable before any tape file loads.
7. Each task ends with the suite green and one commit. Open the page served by the supervisor
   (`http://localhost:8765/index.html`), click every tab at 1,400 px and 390 px, and report console
   errors. Attach a screenshot of each tab you changed.

## 9. Tasks

**L0. Baseline and bug hunt.** Run the suite. Diagnose audit row 1 and fix it. Find out why BTCUSDT
has had no resting order since 02:57 UTC on 14 Nov, from the code and the logs, and write the answer
in the task report. This is a diagnosis; fix nothing in the order logic.

**L1. Logging.** Section 6.1 in `mm/testnet.py`, and the equivalent in `mm/paper.py`.
- Tests with the fake exchange already used in `tests/test_testnet.py`: each state in the table is
  produced by its scenario; `NO_BALANCE` is logged where the code returned silently; a place record
  carries `bid`, `ask` and `mid`; a fill carries `fill_ts_us`; existing tests are unchanged.

**L1b. Carry state across restarts** (the one trading change). Every checkpoint, the executor writes
`data/testnet/state/<SYM>_exec.json`: `{pos, cash, fees, day, day_start_pnl, stopped, ts_us}`,
atomically. At start it loads the file, so the inventory cap and the daily loss stop continue from
the real numbers. A loss stop that fired stays fired until the next UTC day, restart or not. At
start it also compares `pos` with what the fill files sum to; if they differ by more than one lot it
logs a `state-mismatch` record, uses the fill-file sum, and the dashboard raises a high incident.
No file: start from zero as today and log that. No other order logic changes.
- Tests with the fake exchange: stop at -9 lots and restart, then one more sell is allowed and the
  next is blocked by the cap; a session that restarts after a loss stop on the same UTC day places
  no orders; on a new UTC day it quotes again; a missing or corrupt file starts from zero with a log
  record; a mismatch is logged.
- Then do the approved restart (section 8, rule 2).

**L2. Paper trader in the supervisor.** Add a `paper` entry to `config/live.json` and to
`scripts/supervise_live.py` for ANKRUSDT, COTIUSDT and SKLUSDT, and start it with the approved
restart.

**L3. Statistics.** `mm/livestats.py`: continuous P&L, attribution, artifact detection, markouts,
queue wait, state intervals, incidents.
- Tests on synthetic fills and a synthetic feed: two process sessions that each restart at zero
  produce one continuous curve; the attribution identity holds to 1e-6; a fill 1,430 bp from mid is
  an artifact and its edge lands in `artifact`, not `edge`; a 3-minute feed gap drops the markouts
  inside it and creates a `feed_gap` incident; `abs(lots) = 11` with `q_max = 10` creates an
  `inventory_breach`; old-format files without the new fields still load.

**L4. Bundles.** `scripts/build_session.py`, the supervisor hook, the size limits and the tape
files. `takeaways` and `headline` are built here.
- Tests: the bundle has every key of section 6.2 and no `NaN`; sizes are under the limits for the
  data on disk; nothing is written outside `dashboard/live`.
- Check against the real data: the BTC join session lists the 02:57:01 fill as an artifact of about
  -17 USDT, shows four loss-stops, and its `net` equals the sum of the five terms.

**L5. Shell.** Six tabs, the session selector, the range buttons, the live headline, the Research
tab with its sub-tabs, and the test changes listed in section 4.

**L6. Overview.** **L7. P&L and Execution without the tape.** **L8. Tape drill-down.**
**L9. Model.** **L10. Market & health, then the final pass:** remove `js/views/pcstatus.js` panels
that are now duplicated, update `docs/DASHBOARD_GUIDE.md` and `README.md`, and replace the
screenshots in `docs/img/`.

## 10. Acceptance: the two-minute test

With the data on disk on 14 Nov 2026, a reader who has never seen the project must be able to answer
each of these from the page alone, without opening a file:

1. Is the BTC bot quoting right now? If not, since when and why?
2. How much has the BTC session lost in total across restarts, and how much of that is fees, the one
   bad fill, and everything else?
3. Which single event cost the most, and what did the book look like around it?
4. How many times did the loss stop fire, and when?
5. After a typical BTC fill, where is the mid 60 seconds later?
6. Why has the ETH agent made no fills in the current session?
7. What share of the last 24 hours did each bot have an order resting on each side?
8. Is the paper trader making or losing money per dollar traded, and on how many fills?

No live tab shows an empty chart, a row of dashes, or two numbers that contradict each other.

## 11. Open questions for the owner

None at the time of writing. The three earlier questions (paper coins, restart timing, carrying
position) are settled in section 2.
