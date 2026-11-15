# Session chart spec: one animated, layered chart for the simulator and the live sessions

> **For the model doing the work (Sonnet):** one task per session, in the order of section 10. Read
> sections 1-9 first, then only your task. `docs/BUILD_GUIDE.md` section 3 (how to work, when to
> stop and ask) still applies. Where this spec disagrees with `docs/DASHBOARD_SHOWCASE_SPEC.md`,
> `docs/DASHBOARD_LIVE_SPEC.md`, `docs/DASHBOARD_REDESIGN.md` or `docs/DASHBOARD_GUIDE.md`, this
> spec wins, and only for the session chart. Written 15 Nov 2026; the suite was at 481 passing.
>
> Source of the request: `../dashboard_chart_design_spec.md` (one folder above the project). That
> file was written for Python Plotly notebooks and does not match this project in several places.
> Section 3 lists every difference and what was decided. **Do not implement from that file.**

## 1. Goal

Replace the basic line plots that show "one trading session" with one layered, annotated chart that
can replay the session: price with our quotes and fills on top, inventory against its limit and
cumulative P&L below, a row of tiles that follow the replay, and a slider with Play.

The same component draws two things:

1. **The simulator path** (Appendix > Simulator > Playground): the Avellaneda-Stoikov strategy on
   one synthetic path, computed in the browser.
2. **A live session** (Execution test page for the testnet sessions; Agent > "Live on real data"
   for the paper sessions): what the trader did on the real feed.

The reader is the interviewer of the Showcase spec, who knows what a market maker is. The chart
must let them see, without reading a table: where the quotes sat against the mid, when fills
happened, how inventory moved against its cap, and what that did to P&L.

## 2. Decisions already made by the owner (do not reopen)

| Topic | Decision |
| --- | --- |
| Where | Both the simulator and the live sessions, through one shared component |
| Colours | Take the structure of the reference style (layers, band, annotations, slider, titles that state the finding). Keep this site's colours and fonts. No neon palette, no `plotly_dark` template |
| Animation | A slider with Play/Pause. The chart opens showing the whole session with the slider at the end. No autoplay |
| Simulator layout | One figure replaces the price card and the inventory card. Inventory and P&L panels show A-S plus the symmetric benchmark as a thin muted line. The two KPI cards above stay |
| Live placement | Execution test page: directly after "What the test caught". Agent page: first card of "Live on real data" |
| Testnet P&L | **No P&L panel for a testnet session.** Its cumulative P&L stays where it is, inside the "P&L, for reconciliation only" fold. Paper sessions get the P&L panel |
| Live quotes | On live data our quotes are drawn in **bp from the mid in their own strip**, not as a band on the price axis (the band would be thinner than the line: BTC moved about 10% while quotes sit 1-2 bp from the mid) |
| Allowed changes | Dashboard JavaScript, markup and CSS; `mm/livestats.py`, `scripts/build_session.py`, `scripts/publish_dashboard.py` and their tests. **No change to `simulateBoth`, to any trading logic, to the recorder, and no restart of a trader or the supervisor** |

## 3. What the design file asks for that does not fit, and what to do instead

| # | Design file says | Fact in this project | Do this |
| --- | --- | --- | --- |
| D1 | `make_subplots`, `plotly_dark`, Python figures | The dashboard is vanilla JavaScript with Plotly 2.35.2 from a CDN; it must open as a file | Build the figure in JavaScript with the helpers in `js/core.js` (`axis`, `layout`, `CONFIG`) |
| D2 | Style references "in the repo" (Quant Guild notebooks) | Those notebooks are not on this PC | Do not look for them. Section 5 is the full visual definition |
| D3 | Neon palette, Arial, Consolas | Owner chose site colours | Section 5.2 |
| D4 | Reservation price r on every chart | Only the simulator has r. The testnet BTC session is a `join` policy; the agent sessions have no r either | r is drawn on the simulator only. Never compute an r for a live session |
| D5 | Units $ and BTC | The simulator is unitless (s0 = 100, one unit per fill). Live inventory is in lots of `lot_usd`, P&L in USDT | Simulator axes: "price", "inventory (units)", "profit". Live axes: "USDT" price, "bp from mid", "lots", "USDT" |
| D6 | Plotly `frames` with a `sliders` layout entry, margins b = 140 | A Plotly slider is not keyboard-friendly, is hard to use at 390 px, and cannot drive HTML tiles | An HTML `<input type="range">` and a Play button above the figure drive the reveal (section 6) |
| D7 | Stats header: Mid, Inventory, PnL, Fills, Max \|q\|, Spread | Fine for the simulator. A testnet session has no P&L tile (decision above) | Section 5.5 |
| D8 | Annotate "the largest fill" | Every simulator fill is one unit | Simulator: the fill furthest from the mid. Live: the costliest fill (section 7.3) |
| D9 | "Bid < reservation < ask on every frame" | True by construction in the simulator. Not a rule for live quotes, which go stale between replacements | Checked by the component's self-check on the simulator only (section 6.4) |
| D10 | Legend below the plot | The site puts a horizontal legend above the plot (`baseLayout` in `core.js`) | Keep the site's position |
| D11 | Title text example "Inventory stays inside ±5 BTC limit" | Good rule, wrong unit | Titles state the finding with the real unit; who writes them is in section 7.4 |

## 4. What is there today

| # | Seen | Where | Effect |
| --- | --- | --- | --- |
| E1 | "One trading session, A-S strategy": mid, r, band, fills. A "Replay session" button redraws it in about 5 s; it cannot be paused or scrubbed | `drawPath`, `pathTraces`, `btn-replay` in `js/views/research.js`; `ch-path` in `index.html` | The replay is a one-way film |
| E2 | Inventory of the same path is a separate card; it does not move with the replay | `drawInv`, `ch-inv` | The reader cannot connect a fill to the inventory step it caused |
| E3 | No P&L for the single path, although the data exists: `SIM.inv.fan[0]` and `SIM.sym.fan[0]` are path 0 | `simulateBoth` | The effect of the skew on profit is shown only as a distribution |
| E4 | A live session has no price chart at all outside the tape drill-down. `curve` holds P&L and lots; there is no mid series and no quote series in the bundle | `scripts/build_session.py::build_bundle` | "Where were we quoting" cannot be seen for a session |
| E5 | The live cumulative P&L card also draws inventory, inside the collapsed fold | `drawCum` in `js/views/lv_overview.js` | Inventory against the cap, an execution fact, is hidden with the P&L |
| E6 | Titles are variable names ("Inventory on the same path") | `index.html` | The card does not say what happened |

`ov2-cum` and `drawCum` are **not** changed by this spec.

## 5. The chart

### 5.1 Structure

One card. Top to bottom:

1. Card title (h2) and one sentence (`.sub`).
2. Control row: Play/Pause button, the slider, a readout of the current x ("t = 0.42" or
   "14 Nov 02:57 UTC").
3. Tile row (section 5.5).
4. One Plotly figure with shared x across its panels:

| Source | Panels at 900 px and wider | Height |
| --- | --- | --- |
| Simulator | Row 1 (58%): price. Row 2 (42%): inventory left, P&L right | 660 px |
| Testnet session | Row 1 (52%): price. Row 2 (18%): quotes in bp. Row 3 (30%): inventory, full width | 640 px |
| Paper session | Row 1 (46%): price. Row 2 (16%): quotes in bp. Row 3 (38%): inventory left, P&L right | 700 px |

Below 900 px every panel is its own full-width row in the same order, and the height grows by
160 px per extra row. Recompute on resize. No horizontal page scroll at 1,440, 1,024 and 390 px.

Which panels exist is decided by the data, not by the view: the model object (section 6.1) carries
`panels`. For live sessions Python sets it (section 7).

### 5.2 Colours and marks (site tokens only; no new hex values outside this table)

| Mark | Simulator | Live session |
| --- | --- | --- |
| Mid | `C.text`, solid, 1.8 px | same |
| Reservation r | `C.accent`, dashed, 1.4 px | not drawn |
| Quoted band | fill between bid and ask on the price axis, `rgba(C.accent, 0.13)`, no outline | in the bp strip: fill between our bid and ask distance, `rgba(C.accent, 0.13)`; bid edge `BID_C` 1.2 px, ask edge `ASK_C` 1.2 px |
| Buy fill | triangle-up, size 9, `C.bid`, 1 px outline in `--bg` | triangle-up, size 8, `BID_C` |
| Sell fill | triangle-down, size 9, `C.ask` | triangle-down, size 8, `ASK_C` |
| Artifact fill | none | `ART_C`, same shapes; purple is used for nothing else |
| Inventory | `C.accent`, step line (`hv`), 1.6 px | `#cbd5e1`, step line, 1.5 px |
| Inventory limit | `±q_max` when the cap is on: `#818cf8`, dotted, 1 px | same, always drawn |
| Benchmark (inventory and P&L panels) | `C.muted`, 1 px, labelled "benchmark" at its right end | none |
| P&L | `C.text`, 1.8 px | `#e2e8f0`, 2 px; "net excluding artifacts" dashed 1.5 px |
| Drawdown | fill between the running peak and the P&L line, `rgba(C.ask, 0.12)` | same |
| Zero line | every inventory, P&L and bp panel: `#64748b`, 1 px | same |
| Quote-state background | none | `stateBands(b, …)` on the price panel, as on the existing charts |
| Restart, loss stop, UTC day | none | `markerLines(b, ["restart", "loss_stop", "day"])` on the price panel |
| Annotation | text `C.text` 11 px mono, arrow `C.muted`; at most three per figure | same |

The simulator keeps green and red for fills because the research views already use `--bid` and
`--ask` that way; the live side keeps the live spec's rule (bid blue, ask amber, green and red for
profit and loss only). Do not unify them in this spec.

### 5.3 Axes, hover, legend

- Fonts, grid, tick style: `axis()` and `layout()` from `core.js`, unchanged.
- **Axis ranges are fixed from the whole series before the first frame**, so nothing rescales
  during a replay. Simulator price: min bid to max ask, padded 5% (as `pathLayout` does now).
- Live price axis and bp axis follow live spec rule 5.3: the range comes from Python
  (`axes.price`, `axes.bp`: 1st to 99th percentile, padded 10%). A fill outside the range is drawn
  on the edge as a hollow triangle with its true value in the hover, and one line under the figure
  says how many ("2 fills off scale").
- Hover: `x unified`. Every hover line has a name and a unit: `mid 100.412`, `r 100.180`,
  `inventory +3 units`, `P&L −1.42`, `bid −1.6 bp`, `+4 lots`, `−12.31 USDT`. Live prices through
  `fmtP`. No `trace 0`, no bare number.
- Legend: one, horizontal, above the figure, for the price panel's series only. Lower panels use
  direct labels at the right end of each line (`showlegend: false`).
- Mode bar hidden; no scroll zoom. Drag-zoom on x stays, and zooming one panel zooms all (shared x).

### 5.4 Panel titles and annotations

- Each panel has one sentence at its top-left that states the finding (section 7.4), 13 px,
  `C.text`. Wrap it with `<br>` to the panel's pixel width (about 7 px per character); allow two
  lines; reserve the space so the sentence never covers data.
- Annotations mark events (section 7.3). An annotation appears only when the replay has reached its
  x. At rest (slider at the end) all are visible. Under 600 px width, annotations are dropped and
  the same texts are listed under the figure.

### 5.5 Tiles

Existing `.tiles` / `.tile` classes. Label above, value in mono, one line of context below. The
values are those **at the slider position**; the context line says so ("at t = 0.42", "at 14 Nov
02:57 UTC"). At rest they are the end-of-session values.

| Tile | Simulator | Testnet | Paper |
| --- | --- | --- | --- |
| Mid | yes | yes | yes |
| Inventory | `q` units | lots, "of ±`q_max`" | same |
| P&L | yes, red or green | **no** | USDT, red or green |
| Fills | count so far, "b buys, s sells" | count so far in the range | same |
| Max \|inventory\| | so far | so far in the range | same |
| Spread | ask − bid now | quote width now in bp, or "not quoting" | same |

Only the P&L tile is coloured.

## 6. The component: `dashboard/js/session_chart.js`

Loaded after `js/core.js` and before every `js/views/*.js`. Vanilla JavaScript, no dependency.

### 6.1 One model, two adapters

`SessionChart.mount(rootId, model)` draws; calling it again with a new model replaces the chart.
The component knows nothing about `SIM` or session bundles. Each adapter builds this object:

```
{
  kind: "sim" | "live",
  xType: "linear" | "date",          // x values: numbers, or ms since epoch
  x: [...],                           // n points
  panels: ["price", "quotes"?, "inventory", "pnl"?],
  units: { price, inventory, pnl },   // strings for axis titles and hover
  mid: [...], res: [...] | null,
  band: { bid: [...], ask: [...] } | null,        // price units (sim)
  quotes: { bid: [...], ask: [...] } | null,      // bp from mid, null where no order rested (live)
  fills: [{ x, y, side, bp, artifact, text }],    // y = price; bp = distance from mid (live)
  inventory: [...], inventoryBench: [...] | null, qMax: number | null,
  pnl: [...] | null, pnlPeak: [...] | null, pnlAlt: [...] | null, pnlBench: [...] | null,
  tiles: { mid: [...], inventory: [...], pnl: [...] | null, fills: [...], buys: [...], sells: [...],
           maxAbs: [...], spread: [...] },        // one value per point; the tile shows tiles.k[i]
  titles: { card, sub, price, quotes, inventory, pnl },
  events: [{ panel, x, y, text }],               // at most three
  axes: { price: [lo, hi] | null, bp: [lo, hi] | null },
  offScale: string | null,                        // sentence under the figure
  bands: [...], lines: [...],                     // ready-made Plotly shapes for the price panel (live)
  palette: {...}                                  // the column of section 5.2
}
```

- `sim` adapter: in `js/views/research.js`, from `SIM` (section 7.1). It computes its own tiles and
  sentences.
- `live` adapter: in a new `js/views/lv_chart.js`, from the chart file of section 7.2. It copies
  arrays and strings. **It does no arithmetic on a value that is displayed**: no sums, no maxima,
  no rebasing. Indexing an array at the slider position and filtering fills to the window is all.

### 6.2 Reveal

- Frames: `F = min(200, n)` indices spread evenly over the points, the last one being `n − 1`. The
  first frame shows at least two points. Frame k draws every series cut at `index[k]`, the fills
  with `x` up to that point, and the annotations reached.
- Slider: `<input type="range" min="0" max="F−1">` with a visible label ("Replay position").
  Arrow keys move one frame. Dragging draws that frame.
- Play: starts from frame 0 when the slider is at the end, otherwise from where it is; about 40 ms
  per frame (8 s for a full replay); the button reads "Pause" while playing and "Play" otherwise.
  Reaching the end stops. Changing a simulator parameter, the session or the range stops the replay
  and shows the whole series.
- `prefers-reduced-motion`: the Play button is not shown; the slider still works.
- Drawing a frame uses `Plotly.react` with the same layout object, as the current replay does. A
  full 200-frame replay of a 500-point live chart must stay smooth; if it does not, update only the
  changed traces with `Plotly.restyle` rather than reducing the frame count.
- A live bundle refresh (every 5 minutes) while a replay runs: stop the replay and draw the new
  data at rest.

### 6.3 Empty and partial states

- No fills and no orders in the range (today: all three paper sessions): draw the price panel only
  (mid, state background, markers) and one sentence from Python saying why ("No orders in the last
  24 h: the agent stayed out, no setting has the 50 shadow fills it needs"). No empty inventory or
  P&L panel, no tiles of zeros except Mid.
- No mid data either: one sentence through `lvEmpty`, no figure, no controls.
- The chart file is missing or failed to load: one sentence, "The session chart is written with the
  next 5-minute build."

### 6.4 Self-check and pure functions

- `SessionChart.check(model)` returns a list of problems as strings; `mount` logs each with
  `console.error` and still draws. Checks: all series have length `n`; `x` is increasing; `panels`
  is consistent with the series present; at most three events; for `kind: "sim"`,
  `bid < res < ask` at every point.
- `SessionChart.frameIndex(n)` (the frame indices) and `SessionChart.check` take plain data and
  touch no DOM. The file ends with
  `if (typeof module !== "undefined") module.exports = { frameIndex, check };` so pytest can run
  them through `node` when node is installed (section 10, task C1).

## 7. Data

### 7.1 Simulator (JavaScript; `simulateBoth` is not edited)

| Model field | From |
| --- | --- |
| `x` | `SIM.t` |
| `mid`, `res`, `band.bid`, `band.ask` | `SIM.path.s`, `.r`, `.bid`, `.ask` |
| `fills` | `SIM.path.bidFill` (buy) and `.askFill` (sell): `[t, price]` |
| `inventory`, `inventoryBench` | `SIM.path.qInv`, `SIM.path.qSym` |
| `pnl`, `pnlBench` | `SIM.inv.fan[0]`, `SIM.sym.fan[0]` (path 0; both have N + 1 points) |
| `pnlPeak` | running maximum of `pnl` |
| `qMax` | `P.qmax`, or null when it is 0 (cap off) |

### 7.2 Live sessions (Python)

New function `mm/livestats.py::chart_series(...)` and a new file per session,
`dashboard/live/chart-<id>.js` (`window.SESSION_CHART = window.SESSION_CHART || {};
window.SESSION_CHART["<id>"] = {...}`), written by `scripts/build_session.py` in the same pass as
the session bundle and loaded by script tag (no `fetch`). A separate file keeps the session bundle
under its 1.5 MB guard; the chart file has the same limit.

```
{ "id": "...", "built_ms": ...,
  "by_range": { "6h" | "24h" | "3d" | "all": {
      "panels": ["price", "quotes", "inventory"],          # + "pnl" for a paper session
      "t": [...],                    # ms, at most 500 buckets of equal width over the range
      "mid": [...],                  # last mid in the bucket; null inside a feed gap
      "bid_bp": [...], "ask_bp": [...],   # time-weighted mean distance of our resting order from the mid, in bp
                                          # (bid below the mid is negative); null if no order rested on that side
      "lots": [...],                 # inventory at the bucket end
      "max_abs_lots": [...],         # running maximum of |lots| since the range start
      "fills_cum": [...], "buys_cum": [...], "sells_cum": [...],   # since the range start
      "width_bp": [...],             # ask_bp − bid_bp, null unless both sides rested
      "pnl": [...], "pnl_ex_artifact": [...], "pnl_peak": [...],  # paper only; cumulative since the session began
      "fill_ids": null | [...],      # null = draw every fill of the window; else the `i` of the fills to draw
      "axes": { "price": [lo, hi], "bp": [lo, hi] },
      "off_scale": "2 fills off scale" | null,
      "titles": { "card": "...", "sub": "...", "price": "...", "quotes": "...", "inventory": "...", "pnl": "..." },
      "events": [ { "panel": "inventory", "t": ..., "y": ..., "text": "..." } ],
      "empty": null | "sentence"     # set when section 6.3 applies
  } } }
```

- Our resting orders come from the `orders_*.jsonl` rows: a `place` opens an order at its `price`
  and `side`; the matching `cancel`, `cancel-miss` or full fill closes it (the logic already in
  `build_session.py::_order_segments`). The mid comes from the book feed (`ls.book_arrays`).
- Each fill row in the session bundle gains `dist_bp`: (fill price − mid) / mid × 10,000, signed in
  price terms. The bp strip plots fills at `dist_bp`.
- `fill_ids`: when a window has more than 1,500 fills, Python keeps every artifact fill and then
  the largest by absolute edge in USDT, up to 1,500, and `titles.price` says "showing the 1,500
  largest of N".
- P&L (paper only) is the existing mark-to-market curve, **cumulative since the session began, not
  rebased to the range**, as the existing `cum_pnl` sentence already says. Do not derive a "P&L in
  this range" from the curve: on 15 Nov the 6 h change of the BTC curve was +1.79 USDT while the
  6 h tile said −9.39, because the tile sums per-fill terms and the curve carries inventory held
  from before the window (section 12, question 1). Any number in a P&L sentence comes from
  `by_range[r].tiles`, never from the series.

### 7.3 Events (at most three per chart; chosen in the adapter for the simulator, in Python for live)

| Event | Simulator | Live |
| --- | --- | --- |
| Inventory | The point of maximum \|q\| of A-S: "max \|q\| = 7". With the cap on and reached: "cap reached, ±5" at the first time | First time \|lots\| exceeds `q_max`: "past the cap: −11 of ±10 lots". If never: the point of maximum \|lots\| |
| Fill | The fill furthest from the mid at its time: "sell 1.42 above mid" | The costliest fill of the range by edge in USDT; an artifact fill reads "book glitch: sold 1,430 bp under the mid" |
| P&L | The trough of the largest drawdown: "drawdown −8.3" | Paper only: the same, in USDT |

An event is left out when it has nothing to say (no fills, flat inventory, no drawdown).

### 7.4 Sentences

- **Live:** Python writes every title, sub-line, annotation text and empty-state sentence into the
  chart file, with the range named in it ("in the last 24 h"). JavaScript prints them.
- **Simulator:** the numbers are computed in the browser, so its sentences are built in the
  simulator adapter from a small set of templates. This is the one exception to "Python writes
  every sentence", and it is limited to `research.js`.

| Panel | Simulator template (values filled in) | Live sentence written by Python (example) |
| --- | --- | --- |
| Card title | "One trading session, replayed" | "BTCUSDT join: the session, replayed" |
| Price | "34 fills, 18 buys and 16 sells; quotes sat below the mid 61% of the session" (below = r < s, i.e. while long) | "Mid fell from 67,540 to 64,450 in the last 24 h; 802 fills, 11 of them book glitches" |
| Quotes | – | "Both sides quoted 21% of the last 24 h; median quote width 3.1 bp" or the reason for no orders |
| Inventory | Cap on: "Inventory stayed inside ±5" or "Inventory reached the ±5 cap 3 times". Cap off: "A-S inventory peaked at 4; the benchmark reached 11" | "Inventory went past the ±10-lot cap once, to −11 lots" or "Inventory stayed inside the ±10-lot cap" |
| P&L | "A-S ended at +38.2 with a worst drawdown of −8.3; the benchmark ended at +41.0" | Paper: the existing `cum_pnl` sentence for the range |

The example numbers above are illustrations. Nothing in this table is typed into a file.

## 8. Public copy

- `python -m scripts.publish_dashboard --live-snapshot` also copies each `chart-<id>.js` into
  `dashboard_public/snapshot/`, through a new allow-list `CHART_ALLOW` holding exactly the keys of
  section 7.2. Add `dist_bp` to the fills entry of `SESSION_ALLOW`.
- Without the flag no chart file is published. The leak scan already covers every written file.
- On the public copy the chart shows the snapshot and the page's existing "Snapshot frozen" banner
  applies. The replay works; nothing refreshes.

## 9. Rules for every task

1. No change to what orders are sent, when, or at what price. No restart of the traders or the
   supervisor. `simulateBoth`, `mm/simulator.py` and the recorder are not edited. A trading or data
   bug: describe it in the task report and stop.
2. Live: Python computes every number and writes every sentence, with pytest coverage. JavaScript
   formats and draws. Simulator: section 7.4.
3. Vanilla JavaScript, Plotly from the existing CDN reference, no build step, no new dependency, no
   new CDN, no web font. The page still works opened as a file; `fetch(` stays only in `js/live.js`.
4. No colour value that is not in section 5.2 or already a token in `index.html` / `core.js`.
5. No number from one run typed into a file: no price, no count, no date in HTML or in a view.
6. Every existing `id="view-…"` and every existing hash keeps working. Existing tests are edited
   only where a task says so, and the commit message lists them.
7. Each task ends with the suite green (481 plus the new tests) and one commit. The task report
   states the new count, what was not done, and anything that looked wrong.
8. Check the result in a browser at 1,440, 1,024 and 390 px and attach screenshots at 1,440 and 390.
   Report console errors; there must be none from `SessionChart.check`.

## 10. Tasks

**C1. Component and simulator.** JavaScript and markup only.
- Write `js/session_chart.js` (sections 5 and 6) and add its script tag after `js/core.js`.
- In `index.html`, replace the "One trading session, A-S strategy" card and the "Inventory on the
  same path" card of `view-simulator` with one card holding the control row, the tile row and one
  chart element `ch-session`. The "Terminal profit distribution" card becomes full width. Remove
  `btn-replay`, `ch-path` and `ch-inv`.
- In `js/views/research.js`: remove `pathTraces`, `pathLayout`, `drawPath`, the replay handler and
  `drawInv`; add the simulator adapter (sections 7.1, 7.3, 7.4) and call `SessionChart.mount`. A
  slider change in the parameter panel still recomputes and redraws everything.
- Tests, in `tests/test_dashboard_static.py`: `session_chart.js` is loaded after `core.js` and
  before the first view file; it contains no `fetch(` and no reference to `SIM`, `Sess` or
  `SESSION_DATA`; `index.html` has `ch-session` and no `btn-replay`, `ch-path`, `ch-inv`;
  `research.js` still defines `simulateBoth` with its body unchanged (the test holds the SHA-256
  of the function's text, taken before your edit). Update any existing test that names the removed
  ids, in the same commit.
- Test, new `tests/test_session_chart_js.py`, skipped when `node` is not on the PATH: through
  `node -e`, `frameIndex(n)` for n = 1, 2, 150, 201, 1500 returns at most 200 increasing indices
  ending at n − 1 and its first index is at least 1 when n ≥ 2; `check` returns no problem for a
  valid model and names the problem for a model with unequal lengths and for a `sim` model with
  one `bid ≥ res` point.
- Browser check: Playground at the paper settings, and with `q_max = 5`, γ at both ends of its
  slider, and 50 paths. The first frame is not empty; the tiles change while dragging; Play then
  Pause then Play continues; at rest the chart equals the last frame.

**C2. Live series (Python only; no JavaScript).**
- `mm/livestats.py::chart_series` and the writer in `scripts/build_session.py` (section 7.2), the
  events (7.3) and the sentences (7.4). `dist_bp` on the fills rows.
- Tests in a new `tests/test_chart_series.py`, on a synthetic session of three days with fills,
  orders on both sides, one gap with no orders, one artifact fill and one cap breach:
  every array of a range has the same length, at most 500; `t` is increasing;
  `fills_cum[-1]`, and `buys_cum[-1] + sells_cum[-1]`, equal `by_range[r].counts.fills` of the
  session bundle; `lots[-1]` equals the last `lots_after` in the window; `max_abs_lots` never
  decreases and its last value equals the largest \|lots\| in the window; `bid_bp` is null exactly
  in the buckets where no bid rested; `width_bp` equals `ask_bp − bid_bp` to 1e-9 where both exist;
  a testnet session has no `pnl` key and no "pnl" in `panels`, a paper session has both;
  every number that appears in a `titles` sentence equals the series or tile value it describes;
  the inventory event names the cap breach; the fill event of a range containing the artifact
  fill contains "book glitch"; a session with no fills and no orders has `empty` set and
  `panels == ["price"]`; with 1,600 fills in a window `fill_ids` has 1,500 entries including the
  artifact fill; the file contains no `NaN` and is under 1.5 MB.
- Run the real build once (`python -m scripts.build_session`, which only reads `data/`) and report
  the size of each `chart-<id>.js` and the four `titles.price` sentences of the BTC session.

**C3. Live views.**
- `js/live_sessions.js`: load `chart-<id>.js` next to the session bundle (same `loadScript`, same
  refresh). `js/views/lv_chart.js`: the live adapter (section 6.1) and `drawLvChart(rootId)`.
- `index.html`: a card with `lvc-exec` in `view-lv-overview` directly after the "What the test
  caught" card; a card with `lvc-agent` as the first card of `lvm-body` in `view-lv-model`. Both
  follow the session selector and the range buttons of their page.
- Empty states of section 6.3.
- Tests in `tests/test_dashboard_static.py`: both ids present and in the stated positions;
  `lv_chart.js` is loaded after `session_chart.js` and `live_sessions.js`; `lv_chart.js` contains
  no `Math.max`, `Math.min`, `.reduce(` or `+=` (the adapter does no arithmetic) and no
  digit-bearing sentence, in the manner of the existing Story test.
- Browser check on `http://localhost:8765/index.html`: BTC testnet at each of the four ranges; ETH
  testnet; one paper session (today: the empty state). The off-scale line matches the hollow
  markers. No P&L panel and no P&L tile on a testnet session.

**C4. Public copy and documents.**
- Section 8, with tests in `tests/test_live_not_published.py`: default publish writes no
  `chart-*.js`; `--live-snapshot` writes them under `snapshot/` only; a planted absolute path or
  `secret` in a chart file fails the publish; a key outside `CHART_ALLOW` is dropped.
- Run `python -m scripts.publish_dashboard --live-snapshot`, open `dashboard_public/index.html`
  **as a file**, and confirm the simulator chart, the Execution test chart and the Agent chart work
  with no server.
- Update the dashboard paragraph of `README.md`, the "Progress" block of
  `docs/DASHBOARD_GUIDE.md`, and the screenshots in `docs/img/` for the simulator, Execution test
  and Agent pages at 1,440 and 390 px.

## 11. Acceptance

A reader opening Simulator > Playground can, without touching a parameter:

1. See mid, reservation price, the quoted band and every fill, and state from the titles alone how
   many fills there were, whether inventory stayed inside its limit, and where A-S ended against
   the benchmark.
2. Press Play, pause on a fill, and read mid, inventory, P&L, fills, max \|q\| and spread at that
   moment from the tiles.
3. Drag the slider to the start and see a non-empty first frame.

On the Execution test page, for the BTC testnet session at 24 h:

4. Say from the bp strip when the trader was quoting both sides, one side, or nothing, and how wide.
5. Find the costliest fill and the first cap breach by their annotations.
6. See no P&L panel and no P&L tile on this chart.

Everywhere:

7. Every number in a title or tile equals the number in the series under it, and names its range.
8. Legend, titles and axis labels are not clipped at 1,440, 1,024 or 390 px; no horizontal scroll.
9. The public copy, opened as a file, shows the same three charts from the snapshot.
10. The console shows no error.

## 12. Open questions for the owner

1. The live cumulative curve and the range tiles measure different things (15 Nov, BTC, last 6 h:
   curve change +1.79 USDT, tile net −9.39). The existing sentence explains that the curve is
   cumulative since the session began, and this spec keeps both as they are. If one number per
   range is wanted on the curve as well, that is a change to `mm/livestats.py` attribution and
   needs its own decision.
2. The simulator keeps green and red fill markers while the live chart uses blue and amber
   (section 5.2). Say so if one rule should cover both.
3. The paper sessions have no orders and no fills today, so their chart is the price panel and one
   sentence. C3 cannot be judged on a paper P&L panel until the agent trades; the synthetic test in
   C2 is the only cover until then.
