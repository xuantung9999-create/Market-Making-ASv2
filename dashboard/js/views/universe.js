/* universe.js: Market book > Universe (Dashboard Guide D10). Reads the run's `screen` section (results/screen.csv):
   the coin universe with tick size, spread, volume and trade rate. */

const UNI_COLS = [["symbol", "Coin", r => esc(r.symbol)],
  ["constrained", "Tick-constrained", r => r.constrained ? "yes" : "no"],
  ["tick_bp", "Tick (bp)", r => isNum(r.tick_bp) ? fmtP(r.tick_bp) : "–"],
  ["spread_ticks", "Spread (ticks)", r => isNum(r.spread_ticks) ? fmtP(r.spread_ticks) : "–"],
  ["usd_volume_day", "Volume (USD / day)", r => isNum(r.usd_volume_day) ? fmtP(r.usd_volume_day) : "–"],
  ["trades_per_s", "Trades / s", r => isNum(r.trades_per_s) ? fmtP(r.trades_per_s) : "–"],
  ["days", "Days", r => isNum(r.days) ? fmt(r.days, 0) : "–"]];
const UNI_SORT = { k: "usd_volume_day", dir: -1 };

function drawUniverseTable(rows) {
  const s = UNI_SORT;
  const sorted = rows.slice().sort((a, c) => { const x = a[s.k], y = c[s.k]; return (x === y ? 0 : x === null || x === undefined ? 1 : y === null || y === undefined ? -1 : x < y ? -1 : 1) * s.dir; });
  fillHtml("un-table", `<table><thead><tr>${UNI_COLS.map(c => `<th class="sortable" data-k="${c[0]}">${c[1]}${s.k === c[0] ? (s.dir > 0 ? " ▲" : " ▼") : ""}</th>`).join("")}</tr></thead>
    <tbody>${sorted.map(r => `<tr>${UNI_COLS.map(c => `<td>${c[2](r)}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
  $("un-table").querySelectorAll("th.sortable").forEach(th => th.addEventListener("click", () => {
    s.dir = s.k === th.dataset.k ? -s.dir : 1; s.k = th.dataset.k; drawUniverseTable(rows);
  }));
}

function drawUniverseBars(rows) {
  const r = rows.filter(x => isNum(x.usd_volume_day)).sort((a, c) => c.usd_volume_day - a.usd_volume_day);
  if (!r.length) return emptyPanel("un-vol", "No volume figures in this run");
  deskPlot("un-vol", [{ type: "bar", x: r.map(x => x.symbol), y: r.map(x => x.usd_volume_day),
    marker: { color: r.map(x => x.constrained ? SERIES[1] : SERIES[0]) }, hovertemplate: "%{x}: $%{y:,.0f} per day<extra></extra>" }],
    { showlegend: false, xaxis: axis("", { type: "category" }), yaxis: axis("USD volume per day", { type: "log" }) });
}

function drawUniverse() {
  const b = deskBundle("market");
  if (!b) return;
  const rows = section(b, "screen");
  if (!rows) { emptyPanel("un-table", "Not in this run (only the queue-baseline run carries the screener)"); emptyPanel("un-vol"); return; }
  drawUniverseTable(rows); drawUniverseBars(rows);
}
register("market", drawUniverse);
