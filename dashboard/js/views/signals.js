/* signals.js: Model > Signals (Dashboard Redesign R4). Reads only: edge (the agent's learned net edge per state). */

function pooledEdge(rows, key) {
  const g = {};
  rows.forEach(r => { const n = r.n || 0; if (n <= 0) return; const o = g[r[key]] = g[r[key]] || { n: 0, s: 0, v: 0 };
    o.n += n; o.s += r.mean * n; o.v += ((isNum(r.se) ? r.se : 0) * n) ** 2; });
  return Object.entries(g).map(([k, o]) => ({ k: +k, n: o.n, mean: o.s / o.n, se: Math.sqrt(o.v) / o.n })).sort((a, c) => a.k - c.k);
}

function drawSignalChart(id, rows, key, labels) {
  const pts = pooledEdge(rows, key);
  if (!pts.length) return emptyPanel(id, "No fills: the agent stayed out, so there is no edge to estimate");
  const small = p => p.n < 30;
  deskPlot(id, [{ type: "scatter", mode: "markers", x: pts.map(p => labels[p.k]), y: pts.map(p => p.mean),
    error_y: { type: "data", array: pts.map(p => 1.96 * p.se), color: C.muted, thickness: 1.2, width: 4 },
    marker: { size: 11, color: pts.map(p => small(p) ? "rgba(0,0,0,0)" : pnlColor(p.mean)), line: { width: 2, color: pts.map(p => pnlColor(p.mean)) } },
    customdata: pts.map(p => p.n), hovertemplate: "%{x}: %{y:.2f} bp (n=%{customdata:,.0f})<extra></extra>" }],
    { showlegend: false, hovermode: "closest", xaxis: axis("", { type: "category" }), yaxis: axis("net edge per fill (bp)", { zeroline: true, zerolinecolor: C.muted, zerolinewidth: 1.5 }) });
}

function drawSignals() {
  const b = deskBundle("signals");
  if (!b) return;
  const f = Source.filter, e = section(b, "edge");
  if (!e) { emptyPanel("sg-imb", "Not in this run (only walk-forward and paper runs carry the agent's edge table)"); emptyPanel("sg-vol", "Not in this run"); return; }
  const rows = e.filter(r => f.symbol === "ALL" || r.symbol === f.symbol);
  drawSignalChart("sg-imb", rows, "imb", IMB_LABELS);
  drawSignalChart("sg-vol", rows, "vol", VOL_LABELS);
}
register("signals", drawSignals);
