# Session chart time-axis fix: draw the live session chart in UTC

> **For the model doing the work (Sonnet):** one task per session, in the order of section 6. Read
> sections 1-5 first, then only your task. `docs/BUILD_GUIDE.md` section 3 (how to work, when to
> stop and ask) still applies. This spec amends `docs/DASHBOARD_SESSION_CHART_SPEC.md` (sections 5,
> 6 and 9 of that spec still apply). Where the two disagree, this spec wins, but only for how x values
> reach Plotly. Written 15 Nov 2026. Take the suite count at the start of your task as the baseline.

## 1. Goal

The live session chart (`lvc-exec` on the Execution test page and `lvc-agent` on the Agent page) labels
its times as UTC, but its traces are drawn in the **viewer's local time**. Its quote-state bands and its
restart, loss-stop and UTC-day lines are drawn in UTC. In UTC+7 the two layers are 7 hours apart on the
same axis. A reader sees fills inside a loss-stop band and restarts that don't line up with anything. The
fix is to draw every layer in UTC, the same way on every viewer's machine.

## 2. Decisions (do not reopen)

| Topic | Decision |
| --- | --- |
| Time zone shown | **UTC everywhere** (confirmed by the owner, 15 Nov 2026). The trader's day, its loss stop and every log are in UTC, and the rest of the site already labels UTC. Never show the viewer's local time |
| Where the conversion happens | In `js/session_chart.js`, at the point where values go to Plotly. The model keeps x as epoch milliseconds, so `check`, `frameIndex`, `utcLabel` and the tiles stay as they are |
| Format given to Plotly | An ISO string ending in `Z`, made with `new Date(ms).toISOString()`, the same form `isoT` in `js/live_sessions.js` produces and every other date chart on the site uses |
| Simulator | Unchanged. Its x is `linear` and gets no conversion |
| Python | No change. `chart-<id>.js` already holds genuine UTC epoch ms (checked: `livestats.chart_series` and `build_session` use `tz=timezone.utc`) |
| Allowed changes | `dashboard/js/session_chart.js`, `tests/`, and the republished `dashboard_public/` copy. No trading logic, no Python under `mm/`, no trader or supervisor restart |

## 3. What is there today (audit)

| # | Seen | Where | Effect |
| --- | --- | --- | --- |
| A1 | Plotly 2.35.2 reads a **number** on a `date` axis as local wall-clock time, and an **ISO string** as UTC. Checked in the browser on 15 Nov in UTC+7: the same instant given both ways was placed exactly 7 h apart (`getTimezoneOffset() = -420`) | Plotly behaviour | Any chart that hands raw epoch ms to a date axis drifts by the viewer's offset |
| A2 | The live model passes epoch ms straight through: `x: entry.t`, fills `x: f.t`, events `x: e.t` | `js/views/lv_chart.js:10,19,30` | Mid, fills, quotes in bp, inventory and annotations are shifted to local time |
| A3 | The axis range is built from the same numbers: `r.x = [m.x[0], m.x[n-1]]`, used as `range: R.x` | `js/session_chart.js:138,296` | The axis window is shifted too. Its right end showed 14:46 while the readout said 07:46 UTC |
| A4 | End-of-line labels use `x: xEnd = m.x[idx]` (numeric) | `js/session_chart.js:252,257` | Labels shifted with the traces |
| A5 | `stateBands` and `markerLines` already convert with `isoT` | `js/live_sessions.js:180,184` | These are correct (UTC), so they disagree with A2-A4 |
| A6 | Readout, slider `aria-valuetext` and tiles use `utcLabel(ms)` with `getUTC*` | `js/session_chart.js:62-67` | Correct. Leave as is |
| A7 | Every other date chart on the site passes ISO strings (`isoT(...)`, or `"…Z"` strings from `data.js` and `runs/*.js`) | `lv_*.js`, `story.js`, `research.js`, `risk.js`, `overview.js`, `book.js` | Not affected. Task U1 confirms this with one grep |
| A8 | The bug depends on the viewer's time zone: zero shift for a UTC viewer, −5 h for New York, and so on | public copy | An interviewer in another zone sees a different wrong chart |

## 4. The change

In `js/session_chart.js`:

1. Add one pure function next to `frameIndex` and `check`, outside the IIFE, and export it:

   ```js
   /* The value Plotly gets for an x: an ISO UTC string on a date axis (Plotly reads a number there as
      local time), the number itself on a linear axis. Not finite -> null. */
   function plotX(xType, v) {
     if (typeof v !== "number" || !isFinite(v)) return null;
     return xType === "date" ? new Date(v).toISOString() : v;
   }
   ```

   `module.exports = { frameIndex, check, plotX }`, and add `plotX` to the object `SessionChart` returns.
2. Wherever an x goes into a Plotly trace, annotation or axis range, pass it through
   `plotX(m.xType, …)`:
   - `tracesFor`: the shared `x` array (map once per frame and reuse it for every trace in the frame).
   - `fillMarkers`: `x: g.map(v => …)`.
   - `decorate`: event annotations `x: e.x`, end labels `x: xEnd`.
   - `ranges`/`decorate`: the axis `range`. Keep `R.x` numeric for the arithmetic in `decorate`
     (`span`, `late`), and convert only where the range is put into the layout.
3. Do **not** convert `m.bands` or `m.lines`: the adapter already gives them as ISO strings (A5).
   Comparisons such as `e.x <= xEnd` and `f.x <= xEnd` stay numeric on the model values.
4. No change to `lv_chart.js`, `research.js` or Python.

## 5. Rules

1. No change to what orders are sent, when, or at what price. No restart of the traders or the supervisor.
2. Vanilla JavaScript, no new dependency, no build step. The page still opens as a file.
3. Existing tests are edited only where this spec says so. The commit message lists any test you edit.
4. The task ends with the suite green (baseline plus the new tests) and one commit. The report gives
   the new count, what was not done, and anything that looked wrong.

## 6. Tasks

**U1. Draw the session chart in UTC.**
- Make the change in section 4.
- Sweep: `rg -n "type: \"date\"" dashboard/js` and, for each date chart, confirm its x values are ISO strings
  (A7). List the result in the report. Fix nothing outside `session_chart.js`. If you find another chart
  that passes numbers to a date axis, report it and stop.
- Tests in `tests/test_session_chart_js.py` (through `node -e`, skipped without node):
  - `plotX("date", Date.UTC(2026,10,15,0,0))` returns `"2026-11-15T00:00:00.000Z"`.
  - `plotX("linear", 0.42)` returns `0.42`; `plotX("date", null)` and `plotX("date", NaN)` return `null`.
  - Run node with `TZ=Asia/Bangkok` and again with `TZ=America/New_York` (set in the subprocess
    environment): `plotX("date", …)` gives the same string under both.
- Tests in `tests/test_dashboard_static.py`:
  - `session_chart.js` defines and exports `plotX`.
  - `session_chart.js` contains no `range: R.x` and no `x: e.x`/`x: xEnd` that is not wrapped in `plotX(`.
- Browser check on `http://localhost:8765/index.html`, Execution test page, BTC testnet, ranges 6 h and 24 h.
  Run this in the console and paste its output into the report:
  ```js
  const gd = document.querySelector("#lvc-exec .sc-fig");
  ({ allStrings: gd.data.every(t => (t.x || []).every(v => v === null || typeof v === "string")),
     lastX: gd.data[0].x.filter(Boolean).slice(-1)[0], readout: document.querySelector("#lvc-exec .sc-readout").textContent,
     range: gd.layout.xaxis.range })
  ```
  `allStrings` is `true`, `lastX` and `range[1]` give the same day and hour:minute as `readout`.
  Also check by eye: each loss-stop band starts right after the last fill before it, and the restart lines
  sit at the start of warmups. Screenshots at 1,440 and 390 px.
- The Simulator > Playground chart still draws, and its axis still reads `t`.

**U2. Public copy and documents.**
- Run `python -m scripts.publish_dashboard --live-snapshot`. Open `dashboard_public/index.html` **as a
  file** and repeat the console check of U1 on the Execution test chart.
- Replace the Execution test and Agent screenshots in `docs/img/` that show the shifted axis. Add one
  line to the "Progress" block of `docs/DASHBOARD_GUIDE.md`.

## 7. Acceptance

1. On the BTC testnet chart at 24 h, the last fill before each loss stop sits at the left edge of its
   orange band, not 7 hours to its right.
2. The axis's right end, the readout and the "Mid" tile name the same UTC time.
3. The chart looks the same whether the viewer's machine is in UTC+7 or in UTC−5 (covered by the node
   test, because Plotly now only ever receives UTC strings).
4. The simulator chart is unchanged.
5. The console shows no error.

## 8. Open questions for the owner

None. On 15 Nov 2026 the owner confirmed: the whole site stays in UTC, and no view shows the viewer's
local time.
