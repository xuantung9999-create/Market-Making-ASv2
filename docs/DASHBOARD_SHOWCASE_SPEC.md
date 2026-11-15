# Showcase spec: make the page tell the finding to an interviewer

> **For the model doing the work (Sonnet):** one task per session, in the order of section 11. Read
> sections 1-10 first, then only your task. `docs/BUILD_GUIDE.md` section 3 (how to work, when to
> stop and ask) still applies. Where this spec disagrees with `docs/DASHBOARD_LIVE_SPEC.md`,
> `docs/DASHBOARD_REDESIGN.md` or `docs/DASHBOARD_GUIDE.md`, this spec wins. Written 15 Nov 2026
> from a review of the page served at `http://localhost:8765/index.html`.

## 1. Goal

The reader is now a **quant or trading interviewer who opens a public link and gives it two
minutes**. They have never seen the project and nobody is narrating.

What they must leave with, in this order:

1. **This person built a complete trading stack**: data, calibration, a queue-aware simulator, a
   self-calibrating agent, a paper trader and a testnet executor, with tests.
2. **The stack told the truth.** A candidate edge (+16 bp on one day) was put through a
   pre-registered 60-day test and failed (-18.2 bp per dollar traded after fees, t = -9.1).
3. **They understand why**, and can say it in one sentence (section 3).

Today the page does the opposite. It opens on the BTC testnet session and a loss of 118 USDT that
the README itself says is not a result; the finding is two clicks away under Research > Verdict; and
several numbers on the live tabs contradict each other (section 4).

The owner's daily monitoring view still exists, but it is no longer the front door.

## 2. Decisions already made by the owner (do not reopen)

| Topic | Decision |
| --- | --- |
| Main reader | Interviewer or recruiter, on the public copy |
| Core message | "I built a full trading stack"; the negative result is the proof it works |
| Landing page | A single case-study scroll, read top to bottom like a short paper |
| Testnet | Demoted to "does it execute correctly". Its P&L is shown small and labelled as noise |
| Public copy and live data | The public copy now includes a **frozen, sanitised snapshot** of the live sessions. This replaces rule 3 of the live spec (section 8 below) |
| Unflattering testnet facts | Published in full, framed as "what the execution test caught and what was fixed" |
| Long tail of tabs | Three levels: Story, Evidence, Appendix (section 5) |
| One click from the landing page | The Verdict forest plot with the gates, and the tape drill-down around a fill |
| Look | Keep the dark desk theme and refine it. No light theme, no theme toggle |
| Allowed changes | Page structure, CSS, JavaScript views, and the Python that writes bundles and sentences. **No change to trading logic, and no restart of any trader or the supervisor** |

## 3. The owner's conclusions (the page states these, in these words or close to them)

These are the claims the owner will defend in an interview. Python writes them into the story
bundle with the numbers filled in from the run bundles; nothing here is typed into HTML.

1. **Adverse selection first, fees second.** "Even at zero fee, joining the best price loses
   8.2 bp per dollar traded at a realistic queue position; the 10 bp maker fee more than doubles it
   to -18.2 bp." Never write that fees alone decide the result: the before-fees column disproves it.
2. **Queue position is the difference between the two simulators.** At the front of the queue with
   100 ms latency the same strategy is near break-even before fees (-1.3 bp); behind the displayed
   size it is -8.2 bp.
3. **Simulator realism was the lesson.** A backtest with no queue model manufactured a +16 bp edge
   on ANKR from one day. The queue model, latency, fees and a gate fixed in advance removed it.
4. **The agent was right to refuse.** It learned that every market state it could see loses money
   and made no fills in 53 counted days. Gate A: fail, 0 of 5 conditions.
5. **Book imbalance is a real open bet.** v2 ran on a book inferred from trades, so it was blind to
   imbalance and true queue size. v2.1 tests that on recorded depth, with pass rules already fixed
   (`docs/SPEC_V2_1.md`). State it as not yet evaluated.

## 4. What is wrong today (audit of the running page, 15 Nov 2026, 02:15 UTC)

**Story problems**

| # | Seen on the page | Effect |
| --- | --- | --- |
| A1 | Landing tab is `testnet · BTCUSDT · join` with "net -118.25 USDT" in the header | The first number a visitor reads is one the project says to ignore |
| A2 | The 60-day verdict is under Research > Verdict, behind a second nav row of 10 items | The finding is hidden |
| A3 | The About page leads with tiles "Sharpe 9.6 vs 5.2" and "R² 0.992" from the synthetic market and the v1 fit | The top-line numbers are the least realistic ones; the v2 result is item 10 of a list |
| A4 | Nothing shows the stack as a whole | "I built a full trading stack" cannot be seen anywhere |
| A5 | On the public copy the five live tabs show one sentence saying they are not published | Half the navigation is dead for the main reader |
| A6 | Header says "MM-AS", the browser title says "Avellaneda–Stoikov Market Maker" | Two names |

**Numbers that contradict each other**

| # | Seen on the page | Cause |
| --- | --- | --- |
| B1 | Header: "net -118.25 USDT on 1703 fills". Tiles right below (range 24h): "-48.47" and "803" | `headline` and every `takeaways` sentence are built once for all time in `scripts/build_session.py::takeaways`; tiles and charts are cut to the range in JavaScript |
| B2 | Waterfall caption: "fees are -161.09, artifacts -81.73". Its own bars: "-76.82" and "-84.42" | Same cause |
| B3 | Cumulative P&L caption "-118.25 over 1703 fills" over a 24 h chart | Same cause |
| B4 | Tile "Open incidents 15", header "15 open incidents", list "14 incidents in this range" | Two counts with different rules |
| B5 | Market & health card: BTCUSDT "P&L -108.56", "Fills / rejects 0 / 0" | Read from the per-process `status.json`, not the continuous session numbers |
| B6 | Worst 20 fills caption: "The costliest single event: Daily loss stop fired…" | `tk["worst_fills"]` takes the costliest incident of any kind; a loss stop is not a fill |
| B7 | Paper, Model tab, "Why it stayed out: The best arm scores +8.06 bp against an entry threshold of 0 bp", while the live arm is 11 with score 0.00 | The sentence omits the real reason: `AgentConfig.min_arm_fills = 50`, and arm 0 has 8.6 decayed fills, so no arm is eligible and the agent stays on its most conservative start arm |
| B8 | Paper header: "no fills yet. no state recorded." while the state strip shows `policy out` for 12.1 h | `now["state"]` is empty although state intervals exist |
| B9 | Loss-stop state: "daily loss stop (day -7.70 of -20 USDT)". Incident: "Daily loss stop fired… P&L -118.49 USDT, limit 20 USDT a day" | The incident prints cumulative P&L against a daily limit; the state prints a day figure that is inside the limit while the stop is active. One of them is wrong or unexplained |
| B10 | Incidents: "a book glitch costing -0.90 USDT", severity high, Cost column "-0.90" | A favourable glitch is described as a negative cost |
| B11 | Footer on every tab: "Data built 2026-11-12 07:07 UTC" while the live data is minutes old | The footer shows the build time of `data.js` only |

**Reading and layout problems**

| # | Seen on the page | Effect |
| --- | --- | --- |
| C1 | Switching tabs keeps the scroll position | A new tab opens in the middle of its content |
| C2 | A session with no fills shows the same "no fills" sentence three times in each of five cards (P&L tab), and a Model tab for a `join` session that is one line on an empty page | Empty states look broken |
| C3 | No "All sessions" choice in the selector, which the live spec asked for on Overview | Five sessions can only be seen one at a time |
| C4 | Inventory bar on the state card: the two cap ticks are not symmetric around the bar, and +10 of ±10 fills only the right part | Position against the cap cannot be read |
| C5 | Queue wait: one bar holds almost every fill at about 15 s; terciles are 0-14.3, 14.3-14.9, 14.9-31.6 s | This looks like the requote or polling cycle, not queue time. Unverified; see task S1 |
| C6 | Markout chart for a `join` session draws a "JOIN" line identical in meaning to "all" | Redundant series |
| C7 | Verdict gate scoreboard: the value column is "–" for A1, A3, A4 | The reader cannot see how far each condition missed |
| C8 | Verdict: "the 3 coins together lost 36,438 USD on 100 USD lots" | Reads like real money. It is simulated, on about 20 million USD traded; say both |
| C9 | The About badge "331 tests passing" is typed in; the live spec says 334 | A stale proof point |
| C10 | Per-day table and the process table print raw values: `3221225786` as an exit code, full command lines | Noise for a visitor; identifying detail for a public copy |

## 5. Structure

Three levels. One nav row; no second row.

```
Story          the landing page, #story (also the empty hash)
Evidence       Verdict · Fill economics · Agent · Execution test
Appendix ▾     a menu: Backtest P&L · Risk · Market book · Universe · Data · Sim vs live ·
               Simulator · v1 archive · Method and limits · Operations (localhost only)
```

| New page | Hash | Built from (existing view ids, kept in `index.html`) | Change |
| --- | --- | --- | --- |
| Story | `#story` | new `view-story` | New; section 6 |
| Verdict | `#verdict` | `view-overview` | Fix C7, C8. Old `#overview` resolves here |
| Fill economics | `#fills` | `view-execution` (backtest markouts by side and action, queue wait, fill quality per coin) plus the attribution waterfall from `view-pnl` | One page that answers "what is a fill worth". Old `#execution` resolves here |
| Agent | `#agent` | `view-model-health`, `view-signals`, then a section "Live on real data" from `view-lv-model` for the three paper sessions | Backtest first, paper trader second. Old `#model-health`, `#l-model` resolve here |
| Execution test | `#exec-test` | `view-lv-overview`, `view-lv-exec`, `view-lv-pnl` for the testnet sessions | Section 7. Old `#l-overview`, `#l-exec`, `#l-pnl` resolve here |
| Appendix pages | unchanged hashes | `view-pnl`, `view-risk`, `view-book`, `view-market`, `view-health`, `view-simlive`, `view-simulator`, `view-model`, `view-replication`, the five archive views, `view-about` | Contents unchanged except A3 |
| Operations | `#l-health` | `view-live`, `view-pcstatus` | Not in the public copy at all (section 8) |

Rules:

- Every existing `id="view-…"` stays. Every old hash still resolves; extend the hash map and its test.
- The session selector and the range buttons appear **only** on pages that use them (Execution test,
  and the "Live on real data" section of Agent). They leave the global header.
- The header holds the project name and the nav, nothing else. The one-sentence headline moves into
  each page, under its title, and describes that page.
- One name everywhere: **"Crypto market making: from Avellaneda–Stoikov to a queue-aware agent"** as
  the page title and the Story heading; "MM-AS" may remain as the short mark in the header.
- Changing page scrolls to the top (C1). A deep link with a section (`#exec-test/tape`) scrolls to
  that section instead.

## 6. The Story page

A single column, text measure at most 72 characters, charts up to 960 px wide, sections separated
by generous space. Each section is: a short heading that states the finding, one or two sentences,
one figure, one link "See the evidence →". No tables longer than six rows. No session selector, no
filters, no controls except hover on charts.

Every number and sentence comes from a new **story bundle**, `dashboard/runs/pub-story.js`
(`window.STORY = {...}`), written by a new `scripts/build_story.py` from the existing run bundles,
`results/gate_a.json`, `results/queue_baseline.csv`, the v1 universe result and (when present) the
live snapshot. If a source is missing, the section that needs it shows one sentence saying what is
missing; it never shows a typed-in number.

| # | Section heading (written by Python, shown here with today's numbers) | Figure | Links to |
| --- | --- | --- | --- |
| 1 | **Hero.** Title; one sentence: "A market-making stack built from the 2008 paper up to live testnet orders. Its 60-day pre-registered test said no: -18.2 bp per dollar traded after fees." | Four tiles: net bp per dollar (-18.2), t-statistic (-9.1, "60 dates, 3 coins"), agent fills (0 in 53 days), Gate A (FAIL, "fixed before the test"). Under them one line of facts: test count, days and coins tested, simulated fills, real orders sent on testnet | – |
| 2 | **What was built.** | The pipeline as a row of six boxes joined by arrows, wrapping to two rows under 900 px: Data → Calibration → Queue-aware simulator → Edge table and agent → Paper trader → Testnet executor. Each box: name, one line of what it does, one number, the module name in mono (`mm/queue_sim.py`). HTML and CSS, not an image. Each box is a link | The page that shows that component |
| 3 | **Every assumption loses money.** Sentence from conclusion 1 | The forest plot (reuse the Verdict chart, "All coins" rows plus one row per coin at the headline queue; at most 8 rows) | `#verdict` |
| 4 | **Where a fill's money goes.** Sentence: spread captured, lost to price moving against the fill, fee, net | A four-bar waterfall in bp per dollar traded for the headline run: spread captured → inventory and adverse selection → fee → net. The 60 s markout (-6.0 bp) as an annotation | `#fills` |
| 5 | **The edge that was not there.** Sentence from conclusion 3 | A "realism ladder": four points left to right on one bp axis, before fees and after fees: v1 no-queue backtest (ANKR, one day, labelled as such) → front of queue, 100 ms → queue 1x, 300 ms → queue 2x. Zero line drawn | `#verdict` |
| 6 | **The agent declined to trade.** Sentence from conclusion 4, then one line on the paper trader as of the snapshot date (for example "On live data since 14 Nov it is still out: no setting has the 50 shadow fills it needs") | The Gate A scoreboard, compact, with the value of every condition (C7) | `#agent` |
| 7 | **It sends real orders.** One sentence on what testnet is for, with "TESTNET: execution test, not a result" as a label, then "What the test caught" as three or four one-line items (section 7) | Left: three numbers (orders placed, filled, rejected). Right: one tape figure around a real fill, with our order, the touch and the markout ticks | `#exec-test/tape` |
| 8 | **What is next, and what this cannot show.** Conclusion 5, then three limits from "Known limitations" in the About page, shortened | none | `docs/SPEC_V2_1.md` on GitHub, `#about` |

Footer of the Story page: author, GitHub link, "Backtest built <date> · live snapshot frozen
<date> UTC". This two-part provenance line replaces the single "Data built" footer on every page
(B11); a page shows only the part that applies to it.

## 7. The Execution test page

One page for the testnet sessions. Order of content:

1. **Purpose line and label.** "TESTNET: execution test, not a result. The testnet book is thin and
   moved by other people's test bots; this page checks that orders are placed, replaced, filled,
   counted and cancelled correctly."
2. **What the test caught.** A short table written by Python: finding, evidence, status (fixed, with
   the task that fixed it; open; by design). Seed it from what is on disk: position and loss stop
   not carried across restarts (fixed, live spec L1b); silent return when the balance check fails
   (fixed, L1 `NO_BALANCE`); post-only orders rejected with "would immediately match and take"
   (count, by design); restarts without a clean stop (count, open); book-glitch fills (count and net
   USDT, by design of the testnet). Do not invent findings: every row cites a count or an incident
   from the bundle.
3. **State now and quote-state strip** (existing), with the inventory bar fixed (C4): a symmetric
   axis from -q_max to +q_max, zero in the centre, the caps at the two ends.
4. **Order funnel, queue wait, markouts, edge at fill** (existing).
5. **Incidents** (existing). A favourable glitch reads "book glitch, +0.90 USDT in our favour" and
   is severity `info`, not `high` (B10). The Cost column is always a cost: positive means money lost.
6. **Fills table with the tape drill-down** (existing). The section has the anchor `#exec-test/tape`
   and opens with one curated example already drawn, chosen in Python (`story.tape_example`): the
   largest artifact fill, with its caption. The reader sees a tape without clicking.
7. **P&L, for reconciliation only**, collapsed by default (`<details>`): cumulative curve,
   waterfall, per-day table, worst and best fills. Its summary line says "Net <x> USDT, of which fees
   <y> and book glitches <z>. Not a strategy result."

Session selector: `testnet · BTCUSDT · join` and `testnet · ETHUSDT · agent`. Paper sessions are
chosen on the Agent page. The Model tab for a `join` session no longer exists as a page (C2).

## 8. The frozen live snapshot (replaces live spec rule 3)

- `python -m scripts.publish_dashboard --live-snapshot` copies into `dashboard_public/snapshot/`:
  `sessions.js`, every `session-<id>.js`, and only the tape files needed for the curated example and
  for the incidents listed on the page, each under 1.5 MB. Without the flag nothing live is
  published, as today.
- **Never published, flag or no flag:** `dashboard/live/status.js`, anything from `view-live` and
  `view-pcstatus` (host name, LAN address, process table, command lines, exit codes), `.env`,
  anything under `data/`. On the public copy the Operations entry is absent from the Appendix menu.
- The publish step scans every file it wrote and fails if it finds a Windows or Unix absolute path,
  a private IP address (`10.`, `172.16-31.`, `192.168.`), the host name, a process id field, or the
  strings `apiKey`, `secret`, `signature`. Session bundles are filtered through an allow-list of keys
  (section 6.2 of the live spec plus the additions here), not a deny-list.
- Every page that shows snapshot data carries a banner: "Snapshot frozen <date> <time> UTC. Not
  live." On localhost the same pages show live data and no banner.
- Tests: rewrite `tests/test_live_not_published.py` to assert the new rule: default publish has no
  live files; `--live-snapshot` publishes sessions and the chosen tapes under `snapshot/` only;
  `status.js` is never present; a planted absolute path, private IP or `secret` in a session bundle
  makes the publish fail. The commit message names this test as intentionally changed.

## 9. Correctness rules (these fix section 4, part B)

1. **Every number names its window.** A tile, sentence or caption that depends on the range says
   the range in its label ("last 24 h", "all time since 12 Nov"). Python builds the numbers and the
   sentences once per range: the session bundle gains `by_range: {"6h" | "24h" | "3d" | "all":
   {tiles, takeaways, headline, counts}}`. JavaScript picks the entry for the selected range and
   never slices data for a number that Python also reports. Fixes B1, B2, B3.
2. **One count per concept.** "Open incidents" is one number with one rule, used by the tile, the
   headline and the list heading. Fixes B4.
3. **One source per number.** Anything shown for a session comes from the session bundle. The
   Operations cards may show process facts from `status.json` (uptime, heartbeat) but not P&L, fills
   or inventory. Fixes B5.
4. **Sentences match their panel.** `worst_fills` is about fills only. Fixes B6.
5. **The agent's reason is the real reason.** The bundle's `model` gains `min_arm_fills`,
   `eligible_arms` and `start_arm`. `why_out` has three cases: every eligible arm scores below zero;
   no arm is eligible yet ("No setting has the 50 shadow fills needed to be chosen (best so far: arm
   0, +8.06 bp on 8.6 fills), so the agent stays on its most conservative setting, arm 11, which
   quotes nothing"); an eligible arm is positive and live. Fixes B7.
6. **State.** If state intervals exist, `now.state` is the last interval. Fixes B8.
7. **Loss stop.** The incident sentence prints the day's P&L at the moment the stop fired and the
   daily limit. The state detail prints the day's P&L and, when it is inside the limit, why the stop
   is still active (for example "fired at 00:29 UTC, holds until the next UTC day"). Fixes B9. If the
   logs show the stop firing while the day's P&L was inside the limit, that is a trading question:
   describe it in the task report and stop; do not change the trader.
8. **Empty states.** A card shows at most one sentence. When a whole page has nothing to show for
   the selected session, it shows one panel with one sentence and hides the empty cards. Fixes C2.
9. **Proof points are measured.** The test count comes from the bundle (`health.tests_passed`,
   written when the suite runs), never typed in. Fixes C9.

## 10. Visual guidelines

The existing dark theme and the chart rules in section 5 of the live spec stay. Additions:

- **Hierarchy.** One page title (28 px on the Story page, 20 px elsewhere), then the page's one
  sentence (16 px, full contrast), then cards. Card titles 15 px semibold; captions 13 px muted.
  Headings state the finding ("Every assumption loses money"), not the chart type.
- **Tiles.** At most four in a row on the Story page and six elsewhere. Label above, value, one line
  of context below that says what the number is measured over. A value is red or green only if it is
  a profit or loss.
- **Spacing.** 8 px grid. 24 px between cards, 64 px between Story sections, 16 px page gutter at
  390 px. No card inside a card.
- **Text.** Body copy at most 72 characters wide. Numbers in the existing mono face with tabular
  figures, right-aligned in tables. Units in the column header, not repeated in cells.
- **Charts.** One sentence under the title, from the bundle. Zero drawn on every P&L, edge and
  markout axis; the fee drawn where a fill must clear it. Direct labels instead of a legend when
  there are three series or fewer. On the Story page charts are static-looking: no mode bar, no
  zoom, hover only.
- **Labels.** `TESTNET`, `PAPER`, `SIM`, `WALK-FORWARD`, `SNAPSHOT` badges keep fixed colours and
  appear once per page, next to the page title, not on every card.
- **Words.** Plain statements with the number in them. No "N/A", no bare dash where a reason is
  known: write the reason ("no fills: the agent stayed out").
- **Widths.** Check 1,440, 1,024 and 390 px. No horizontal page scroll at any of them; a wide table
  scrolls inside its own wrapper.

## 11. Tasks

**S0. Baseline.** Run the suite and record the count. Open the page, click every tab, record
console errors. Change nothing.

**S1. Fix the contradictions (Python and views).** Section 9, rules 1-9, in
`scripts/build_session.py`, `mm/livestats.py` and the `lv_*` views.
- Tests in `tests/test_build_session.py`: for a synthetic session spanning three days, the 24 h
  tile values equal the numbers inside the 24 h sentences; the open-incident count is identical in
  `by_range[r].counts`, the headline and the list; `worst_fills` never names a loss stop; the three
  `why_out` cases each produce their sentence; a session with state intervals and no fills has a
  non-empty `now.state`; a favourable artifact fill has severity `info` and a sentence containing
  "in our favour".
- Investigate C5: read how `wait_s` is computed and how often orders are replaced. Report whether
  the 15 s spike is queue time or the replace cycle. If it is the replace cycle, relabel the panel
  "Order age at fill" and say so in its sentence; do not change the trader.

**S2. Shell.** Section 5: one nav row with the Appendix menu, the new hash map, scroll to top, the
selector and range buttons moved into the pages that use them, the provenance footer. Update
`tests/test_dashboard_static.py` in the same commit (tab count, hash map, tab wrappers) and list the
changed tests in the commit message. No other existing test is edited.

**S3. Story bundle.** `scripts/build_story.py` and `tests/test_build_story.py`: every sentence of
section 3 is produced with numbers read from the run bundles; the waterfall terms sum to the net to
1e-6; the ladder has its four points; a missing source yields a "missing" marker for that section
and no number; the bundle contains no `NaN`. Add the call to the script that builds the verdict
bundle.

**S4. Story page.** Section 6, against the story bundle. Sonnet may not type a result number or a
finding into `index.html` or a view file; add a static test that the Story view file contains no
digit-bearing sentence outside format helpers (the same spirit as the existing "Python writes every
sentence" rule).

**S5. Evidence pages.** Verdict (C7, C8), Fill economics and Agent as mapped in section 5.

**S6. Execution test page.** Section 7, including the "What the test caught" table (built in
`scripts/build_session.py`, with a test that every row cites a count or incident present in the
bundle) and the curated tape example.

**S7. Public snapshot.** Section 8. Then run `python -m scripts.publish_dashboard --live-snapshot`,
open `dashboard_public/index.html` **as a file**, and confirm every page works with no server.

**S8. Final pass.** About page: remove the simulated Sharpe and R² tiles from the top and put them
in the paper-replication section with their caveat (A3). Update `README.md` (the dashboard
paragraph and the screenshots in `docs/img/`) and the "Progress" block of
`docs/DASHBOARD_GUIDE.md`. Attach a screenshot of every page at 1,440 and 390 px.

Rules for every task:

1. No change to what orders are sent, when, or at what price. No restart of the traders or the
   supervisor. If a trading bug shows up, describe it and stop.
2. Python computes every number and writes every sentence, with pytest coverage. JavaScript formats
   and draws.
3. Vanilla JavaScript, Plotly from the existing CDN reference, no build step, no new dependency. The
   page still works opened as a file; `fetch(` stays only in `js/live.js`.
4. No file under `dashboard/` above 3 MB (`data.js` is the known exception until D12).
5. Each task ends with the suite green and one commit.

## 12. Acceptance: the two-minute test

On the public copy, opened as a file, a reader who has never seen the project can answer each of
these from the Story page alone, without clicking:

1. What did this person build, end to end?
2. What was the result of the 60-day test, in one number, and is it statistically meaningful?
3. Would it have made money with zero fees?
4. Why did an earlier backtest show a profit, and what removed it?
5. What did the agent do, and was that the right call?
6. Has this code ever sent a real order? What went wrong when it did?
7. What is the next experiment, and has it been run?

And with one click each: the forest plot with all five gate conditions and their values; a tape
around a real fill showing the book, the trades, our order and the markout ticks.

Across the whole site: no two numbers for the same thing disagree; every range-dependent number
names its range; no page shows a host name, a LAN address, a file path or a command line.

## 13. Open questions for the owner

1. B9: is the loss stop meant to stay active across the UTC day boundary when the new day's P&L is
   inside the limit? S1 reports what the logs show; the answer decides whether it is a wording fix
   or a trader fix (outside this spec).
2. The curated tape example defaults to the largest artifact fill (14 Nov 02:57 UTC BTC sell). If
   an ordinary fill tells the execution story better, name it and S6 uses that one.
