/* risk.js: Desk > Risk (Dashboard Guide Task D7). Reads only: curves, days, stress, summary, config. */

function riskSyms(b) { const f = Source.filter; return f.symbol === "ALL" ? Source.symbolsOf(b) : [f.symbol]; }

function drawRiskInventory(b) {
  const f = Source.filter, cv = section(b, "curves"), qmax = (b.config || {}).q_max;
  if (!cv) { emptyPanel("rk-inv"); emptyPanel("rk-invdist"); return; }
  const tr = [], all = [];
  riskSyms(b).forEach((s, i) => {
    const c = cv[`${s}|${f.variant}`];
    if (!c || !c.q) return;
    tr.push({ x: c.t, y: c.q, name: s, mode: "lines", line: { width: 1.2, color: SERIES[i % SERIES.length] }, hovertemplate: `${s} %{y} lots<extra></extra>` });
    all.push(...c.q);
  });
  if (!tr.length) { emptyPanel("rk-inv"); emptyPanel("rk-invdist"); return; }
  const shapes = isNum(qmax) ? [qmax, -qmax].map(y => ({ type: "line", xref: "paper", x0: 0, x1: 1, y0: y, y1: y, line: { color: STATE_COLOR.INV_CAP, dash: "dash" } })) : [];
  // the inventory record covers only the last days of the run: frame the axis on it, not on the 60-day P&L span
  // (the curve is padded with zeros before that, so frame the last 3 days, as the caption says)
  const ts = tr.flatMap(t => t.x.filter((_, j) => isNum(t.y[j]))).sort();
  const end = ts.length ? Date.parse(String(ts[ts.length - 1]).replace(" ", "T") + (/[zZ+]/.test(String(ts[ts.length - 1]).slice(10)) ? "" : "Z")) : NaN;
  const span = isFinite(end) ? [new Date(end - 3 * 864e5).toISOString(), new Date(end).toISOString()] : undefined;
  const qlim = isNum(qmax) ? qmax * 1.15 : undefined;
  deskPlot("rk-inv", tr, { xaxis: axis("UTC", { type: "date", range: rangeX(span && span[1]) || span }),
    yaxis: axis("Inventory (lots)", { zeroline: true, zerolinecolor: C.muted, range: qlim && Math.max(...all.map(Math.abs)) <= qlim ? [-qlim, qlim] : undefined }), shapes });
  const qh = section(b, "q_hist"), hist = qh ? riskSyms(b).map(x => qh[`${x}|${f.variant}`]).filter(Boolean) : [];
  const lv = [...new Set(hist.flatMap(h => h.levels))].sort((p, q) => p - q);
  const share = lv.map(l => hist.reduce((a, h) => { const i = h.levels.indexOf(l); return a + (i >= 0 ? h.share[i] : 0); }, 0) / Math.max(1, hist.length) * 100);
  const x = hist.length ? lv : null;
  deskPlot("rk-invdist", [hist.length ? { type: "bar", x: lv, y: share, marker: { color: lv.map(l => isNum(qmax) && Math.abs(l) >= qmax ? STATE_COLOR.INV_CAP : rgba(C.accent, 0.55)) },
      hovertemplate: "%{x} lots: %{y:.1f}% of the run<extra></extra>" }
    : { type: "histogram", x: all, histnorm: "percent", xbins: { size: 1 }, marker: { color: rgba(C.accent, 0.55) }, hovertemplate: "%{x} lots: %{y:.1f}% of time<extra></extra>" }],
    { xaxis: axis("Inventory (lots)"), yaxis: axis("Share of the whole run (%)"), showlegend: false });
}

function drawRiskDrawdown(b) {
  const f = Source.filter, cv = section(b, "curves");
  const c = cv && (cv[`${f.symbol === "ALL" ? "ALL" : f.symbol}|${f.variant}`] || (f.symbol === "ALL" && Source.symbolsOf(b).length === 1 ? cv[`${Source.symbolsOf(b)[0]}|${f.variant}`] : null));
  if (!c) return emptyPanel("rk-dd");
  let peak = 0;
  const dd = c.pnl.map(v => { peak = Math.max(peak, v); return v - peak; });
  deskPlot("rk-dd", [
    { x: c.t, y: c.pnl, name: "Cumulative P&L", mode: "lines", line: { color: C.accent, width: 1.5 }, hovertemplate: "%{y:,.2f} USD<extra></extra>" },
    { x: c.t, y: dd, name: "Drawdown", mode: "lines", fill: "tozeroy", line: { color: LOSS, width: 1 }, fillcolor: rgba(LOSS, 0.2), hovertemplate: "%{y:,.2f} USD<extra></extra>" },
  ], { xaxis: axis("UTC", { type: "date", range: rangeX(c.t.slice(-1)[0]) || undefined }), yaxis: axis("USD", { zeroline: true, zerolinecolor: C.muted }) });
}

function drawRiskTiles(b) {
  const ds = filteredDays(b), qmax = (b.config || {}).q_max, stop = 20;
  if (!ds.length) return emptyPanel("rk-tiles");
  const qmaxSeen = Math.max(...ds.map(d => isNum(d.q_abs_max) ? d.q_abs_max : 0));
  const worst = Math.min(...ds.map(d => isNum(d.pnl) ? d.pnl : 0));
  const stops = ds.filter(d => d.loss_stop).length, hasStop = ds.some(d => d.loss_stop !== undefined);
  const qh = section(b, "q_hist"), f0 = Source.filter;
  const atCap = (() => { if (!qh || !isNum(qmax)) return null; const hs = (f0.symbol === "ALL" ? Source.symbolsOf(b) : [f0.symbol]).map(x => qh[`${x}|${f0.variant}`]).filter(Boolean);
    if (!hs.length) return null; return hs.reduce((a, h) => a + h.levels.reduce((s2, l, i) => s2 + (Math.abs(l) >= qmax ? h.share[i] : 0), 0), 0) / hs.length; })();
  const tiles = [
    ["Time at the cap", atCap === null ? "–" : pct(atCap, 1), atCap > 0.1 ? "neg" : "", `share of the run at ±${qmax} lots`],
    ["Largest inventory", isNum(qmax) ? pct(qmaxSeen / qmax) : fmt(qmaxSeen, 0), "", `of the ±${qmax} lot cap`],
    ["Worst coin-day (USD)", sign(worst), pnlCls(worst), `daily loss stop: −${stop} USD (agent only)`],
    ["Loss-stop days", hasStop ? fmt(stops, 0) : "–", "", hasStop ? "days the stop fired" : "not recorded in this run"],
  ];
  fillHtml("rk-tiles", tiles.map(t => `<div class="tile"><div class="k">${t[0]}</div><div class="v ${t[2]}">${t[1]}</div><div class="s">${t[3]}</div></div>`).join(""));
}

function drawRiskStress(b) {
  const f = Source.filter, st = section(b, "stress");
  if (!st) return emptyPanel("rk-stress");
  const syms = riskSyms(b), rows = st.filter(r => syms.includes(r.symbol));
  if (!rows.length) return emptyPanel("rk-stress");
  const shocks = [...new Set(rows.map(r => r.shock_pct))].sort((a, c) => a - c);
  const sum = (b.summary || []).filter(r => r.variant === f.variant);
  const body = syms.map(s => {
    const r = sum.find(x => x.symbol === s) || {};
    return `<tr><td>${esc(s)}</td>${shocks.map(k => { const x = rows.find(y => y.symbol === s && y.shock_pct === k); return `<td>${x ? fmt(x.loss_at_cap_usd, 0) + " / " + fmt(x.loss_at_max_seen_usd, 0) : "–"}</td>`; }).join("")}
      <td>${isNum(r.var95_day) ? sign(r.var95_day) : "needs 20 days"}</td><td>${isNum(r.es95_day) ? sign(r.es95_day) : "–"}</td></tr>`;
  }).join("");
  fillHtml("rk-stress", `<table><thead><tr><th>Coin</th>${shocks.map(k => `<th>${k}% gap: loss at cap / at max seen (USD)</th>`).join("")}<th>VaR 95%/day</th><th>ES 95%/day</th></tr></thead><tbody>${body}</tbody></table>`);
}

function drawRisk() {
  const b = deskBundle("risk");
  if (!b) return;
  drawRiskTiles(b); drawRiskInventory(b); drawRiskDrawdown(b); drawRiskStress(b);
}
register("risk", drawRisk);
