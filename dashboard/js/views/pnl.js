/* pnl.js: Desk > P&L (Dashboard Guide Task D5). Reads only: days, summary, hourly. */

/* Attribution in bp per dollar traded, grouped by coin: spread captured, what inventory did, fees, net. */
function drawPnlWaterfall(b) {
  const f = Source.filter, all = filteredDays(b);
  if (!all.length) return emptyPanel("pnl-wf");
  const syms = f.symbol === "ALL" ? Source.symbolsOf(b) : [f.symbol];
  const parts = [["spread_capture", "Spread capture", 1], ["inventory_pnl", "Inventory P&L", 1], ["fees", "Fees", -1], ["pnl", "Net", 1]];
  const bp = (ds, k, sg) => { const n = ds.reduce((a, d) => a + (d.notional || 0), 0); return n > 0 ? sg * ds.reduce((a, d) => a + (isNum(d[k]) ? d[k] : 0), 0) / n * 1e4 : null; };
  const groups = syms.map(s => [s, all.filter(d => d.symbol === s)]);
  if (syms.length > 1) groups.push(["All coins", all]);
  const tr = groups.map(([name, ds], i) => ({ type: "bar", name: name.replace("USDT", ""), x: parts.map(p => p[1]), y: parts.map(p => bp(ds, p[0], p[2])),
    marker: { color: name === "All coins" ? C.text : SERIES[i % SERIES.length] }, text: parts.map(p => { const v = bp(ds, p[0], p[2]); return isNum(v) ? fmt(v, 1) : ""; }),
    textposition: "outside", hovertemplate: `${name} %{x}: %{y:.1f} bp per $ traded<extra></extra>` }));
  deskPlot("pnl-wf", tr, { barmode: "group", yaxis: axis("bp per dollar traded", { zeroline: true, zerolinecolor: C.muted, zerolinewidth: 1.5 }), xaxis: axis("") });
}

/* Daily net P&L as small multiples: one row per coin, bars with the 7-day mean. Stacked signed bars cannot be read. */
function drawPnlDaily(b) {
  const f = Source.filter, ds = filteredDays(b);
  if (!ds.length) return emptyPanel("pnl-daily");
  const syms = f.symbol === "ALL" ? Source.symbolsOf(b) : [f.symbol];
  const tr = [], lay = { xaxis: axis("UTC date", { type: "date" }), showlegend: false, height: Math.max(260, 150 * syms.length + 40), hovermode: "x" };
  const gap = 0.06, h = (1 - gap * (syms.length - 1)) / syms.length;
  syms.forEach((s, i) => {
    const rows = ds.filter(d => d.symbol === s).sort((a, c) => a.date < c.date ? -1 : 1), y = rows.map(d => d.pnl);
    const ax = i ? "y" + (i + 1) : "y", top = 1 - i * (h + gap);
    lay["yaxis" + (i ? i + 1 : "")] = Object.assign(axis(s.replace("USDT", "") + " (USD)", { zeroline: true, zerolinecolor: C.muted }), { domain: [top - h, top], anchor: "x" });
    tr.push({ type: "bar", x: rows.map(d => d.date), y, yaxis: ax, marker: { color: y.map(pnlColor) }, hovertemplate: `${s} %{x}: %{y:,.0f} USD<extra></extra>` });
    const ma = y.map((_, k) => { const w = y.slice(Math.max(0, k - 6), k + 1); return w.reduce((a, v) => a + v, 0) / w.length; });
    tr.push({ type: "scatter", mode: "lines", x: rows.map(d => d.date), y: ma, yaxis: ax, line: { color: C.text, width: 1.6 }, hovertemplate: "7-day mean %{y:,.0f}<extra></extra>" });
  });
  lay.xaxis.anchor = syms.length > 1 ? "y" + syms.length : "y";
  const rg = rangeX(ds.reduce((m, d) => d.date > m ? d.date : m, ""));
  if (rg) lay.xaxis.range = rg;
  lay.margin = { l: 72, r: 16, t: 10, b: 44 };
  deskPlot("pnl-daily", tr, lay);
}

function drawPnlHeat(b) {
  const f = Source.filter, h = section(b, "hourly");
  if (!h) return emptyPanel("pnl-heat-edge");
  const syms = (f.symbol === "ALL" ? Source.symbolsOf(b) : [f.symbol]).filter(s => h[`${s}|${f.variant}`]);
  const ze = syms.map(s => h[`${s}|${f.variant}`].net_edge_bp || null);
  if (!syms.length || ze.some(r => !r)) return emptyPanel("pnl-heat-edge");
  const hrs = [...Array(24).keys()], le = Math.max(1e-9, ...ze.flat().filter(isNum).map(Math.abs));
  deskPlot("pnl-heat-edge", [{ type: "heatmap", x: hrs, y: syms, z: ze, zmin: -le, zmax: le, colorscale: [[0, LOSS], [0.5, C.panel], [1, PROFIT]],
    colorbar: { title: { text: "bp" } }, hovertemplate: "%{y} %{x}:00 UTC: %{z:,.2f} bp<extra></extra>" }],
    { xaxis: axis("UTC hour", { dtick: 2 }), yaxis: axis("") });
}

function drawPnlStats(b) {
  const f = Source.filter, rows = (section(b, "summary") || []).filter(r => r.variant === f.variant);
  if (!rows.length) return emptyPanel("pnl-stats");
  rows.sort((a, c) => (a.symbol === "ALL" ? -1 : c.symbol === "ALL" ? 1 : a.symbol < c.symbol ? -1 : 1));
  const tf = x => isNum(x) ? fmt(x, 2) : "too few days";
  const body = rows.map(r => `<tr><td>${esc(r.symbol === "ALL" ? "All coins" : r.symbol)}</td><td>${fmt(r.days, 0)}</td>
    <td class="${pnlCls(r.pnl_total)}">${sign(r.pnl_total)}</td><td class="${pnlCls(r.pnl_mean_day)}">${sign(r.pnl_mean_day)}</td>
    <td>${isNum(r.pnl_std_day) ? fmt(r.pnl_std_day) : "–"}</td><td>${tf(r.t_stat)}</td>
    <td>${isNum(r.sharpe_ann) ? fmt(r.sharpe_ann) + " ± " + fmt(r.sharpe_se) : "too few days"}</td>
    <td>${pct(r.hit_rate)}</td><td>${isNum(r.profit_factor) ? fmt(r.profit_factor) : "–"}</td>
    <td class="${pnlCls(r.max_dd)}">${isNum(r.max_dd) ? sign(r.max_dd) : "–"}</td>
    <td class="${pnlCls(r.net_bp_per_usd)}">${isNum(r.net_bp_per_usd) ? sign(r.net_bp_per_usd) : "–"}</td>
    <td>${isNum(r.turnover_day) ? fmt(r.turnover_day, 1) : "–"}</td>
    <td>${isNum(r.var95_day) ? sign(r.var95_day) : "needs 20 days"}</td><td>${isNum(r.es95_day) ? sign(r.es95_day) : "–"}</td></tr>`).join("");
  fillHtml("pnl-stats", `<table><thead><tr><th>Coin</th><th>Counted days</th><th>Total (USD)</th><th>Mean/day (USD)</th><th>Std/day (USD)</th>
    <th>t-stat</th><th>Sharpe (ann.)</th><th>Hit rate</th><th>Profit factor</th><th>Max DD (USD)</th><th>Net bp per $</th>
    <th>Turnover/day (× cap)</th><th>VaR 95%/day</th><th>ES 95%/day</th></tr></thead><tbody>${body}</tbody></table>`);
}

function drawPnlHist(b) {
  const ds = filteredDays(b).filter(d => (d.fills || 0) >= 20);
  if (!ds.length) return emptyPanel("pnl-hist", "No day with 20 or more fills in this selection");
  const x = ds.map(d => d.pnl), mean = x.reduce((a, v) => a + v, 0) / x.length;
  const sd = x.length > 1 ? Math.sqrt(x.reduce((a, v) => a + (v - mean) ** 2, 0) / (x.length - 1)) : null;
  const tstat = sd ? mean / (sd / Math.sqrt(x.length)) : null;
  deskPlot("pnl-hist", [{ type: "histogram", x, nbinsx: 30, marker: { color: rgba(SERIES[0], 0.7) }, hovertemplate: "%{x} USD: %{y} days<extra></extra>" }],
    { xaxis: axis("Daily net P&L (USD)"), yaxis: axis("Days"), showlegend: false,
      shapes: [{ type: "line", x0: 0, x1: 0, yref: "paper", y0: 0, y1: 1, line: { color: C.muted, dash: "dot" } },
               { type: "line", x0: mean, x1: mean, yref: "paper", y0: 0, y1: 1, line: { color: pnlColor(mean), width: 2 } }],
      annotations: [{ x: mean, yref: "paper", y: 0.97, text: `mean ${sign(mean)} USD · ${x.length} ${Source.filter.symbol === "ALL" ? "coin-days" : "days"}${isNum(tstat) && x.length >= 5 ? " · t = " + fmt(tstat, 1) : ""}`, showarrow: false, xanchor: "right", yanchor: "top", font: { color: pnlColor(mean) } }] });
}

function drawPnl() {
  const b = deskBundle("pnl");
  if (!b) return;
  drawPnlWaterfall(b); drawPnlDaily(b); drawPnlHeat(b); drawPnlStats(b); drawPnlHist(b);
}
register("pnl", drawPnl);
