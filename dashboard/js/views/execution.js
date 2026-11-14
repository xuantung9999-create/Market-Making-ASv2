/* execution.js: Desk > Execution (Dashboard Guide Task D6). Reads only: markouts, wait_hist, days, config. */

function poolMarkouts(rows, key) {
  const g = {};
  rows.forEach(r => {
    const k = `${r[key]}|${r.h_s}`;
    (g[k] = g[k] || { grp: r[key], h: r.h_s, n: 0, s: 0, v: 0 });
    g[k].n += r.n; g[k].s += r.bp * r.n; g[k].v += (isNum(r.se) ? r.se * r.n : 0) ** 2;
  });
  const out = {};
  Object.values(g).forEach(o => { (out[o.grp] = out[o.grp] || []).push({ h: o.h, bp: o.s / o.n, se: Math.sqrt(o.v) / o.n }); });
  Object.values(out).forEach(a => a.sort((p, q) => p.h - q.h));
  return out;
}

function drawMarkoutChart(b, el, key, label) {
  const f = Source.filter, rows = (section(b, "markouts") || []).filter(r => r.variant === f.variant && (f.symbol === "ALL" || r.symbol === f.symbol));
  if (!rows.length) return emptyPanel(el);
  const groups = poolMarkouts(rows, key), fee = (b.config || {}).maker_fee_bps;
  const tr = [];
  Object.entries(groups).forEach(([g, pts], i) => {
    const side = /^(buy|bid)/i.test(g) ? BID_C : /^(sell|ask)/i.test(g) ? ASK_C : null;      // sides keep their colours
    const col = side || SERIES[i % SERIES.length], x = pts.map(p => p.h);
    tr.push({ x: x.concat([...x].reverse()), y: pts.map(p => p.bp + p.se).concat(pts.map(p => p.bp - p.se).reverse()), fill: "toself",
              fillcolor: rgba(col, 0.15), line: { width: 0 }, hoverinfo: "skip", showlegend: false });
    tr.push({ x, y: pts.map(p => p.bp), mode: "lines+markers", name: `${label} ${g}`, line: { color: col, width: 2 },
              hovertemplate: `${g} %{x} s: %{y:.2f} bp<extra></extra>` });
  });
  const shapes = isNum(fee) ? [{ type: "line", xref: "paper", x0: 0, x1: 1, y0: fee, y1: fee, line: { color: C.muted, dash: "dash" } }] : [];
  const ann = isNum(fee) ? [{ xref: "paper", x: 1, y: fee, text: `fee ${fmt(fee, 1)} bp: a fill must clear this`, showarrow: false, xanchor: "right", yanchor: "bottom", font: { color: C.muted, size: 11 } }] : [];
  deskPlot(el, tr, { xaxis: axis("Seconds after the fill (log)", { type: "log" }), yaxis: axis("Markout before fees (bp)", { zeroline: true, zerolinecolor: C.muted }), shapes, annotations: ann });
}

function drawExecWait(b) {
  const f = Source.filter, w = section(b, "wait_hist");
  if (!w) return emptyPanel("ex-wait");
  const syms = (f.symbol === "ALL" ? Object.keys(w) : [f.symbol]).filter(s => w[s]);
  if (!syms.length) return emptyPanel("ex-wait");
  // share of each coin's own fills, so a coin with 10x the fills does not flatten the others' shapes
  const tr = syms.map((s, i) => {
    const e = w[s].edges, tot = w[s].count.reduce((a, x) => a + x, 0) || 1;
    return { type: "scatter", mode: "lines+markers", name: s.replace("USDT", ""), x: w[s].count.map((_, j) => `${e[j]}–${e[j + 1]}`), y: w[s].count.map(c => 100 * c / tot),
             line: { color: SERIES[i % SERIES.length], width: 2, shape: "spline", smoothing: 0.6 }, marker: { size: 6 }, customdata: w[s].count,
             hovertemplate: `${s} %{x} s: %{y:.1f}% (%{customdata} fills)<extra></extra>` };
  });
  deskPlot("ex-wait", tr, { hovermode: "closest", xaxis: axis("Queue wait, order live to fill (s)"), yaxis: axis("Share of the coin's fills (%)", { rangemode: "tozero" }) });
}

/* Fills per hour with an order resting, and the share of the day one was resting (uptime). */
function drawExecRate(b) {
  const f = Source.filter, ds = filteredDays(b);
  if (!ds.length) return emptyPanel("ex-rate");
  const syms = f.symbol === "ALL" ? Source.symbolsOf(b) : [f.symbol];
  const rows = syms.map(s => { const d = ds.filter(x => x.symbol === s && isNum(x.uptime) && x.uptime > 0);
    if (!d.length) return null;
    const fills = d.reduce((a, x) => a + (x.fills || 0), 0), hrs = d.reduce((a, x) => a + 24 * x.uptime, 0);
    return { s, perHour: fills / hrs, up: d.reduce((a, x) => a + x.uptime, 0) / d.length }; }).filter(Boolean);
  if (!rows.length) return emptyPanel("ex-rate", "No fills: the agent stayed out, or uptime was not recorded");
  // a few coins: thin horizontal bars sized to the number of rows, not a wall of colour
  $("ex-rate").style.height = `${Math.max(140, 70 + 44 * rows.length)}px`;
  deskPlot("ex-rate", [{ type: "bar", orientation: "h", name: "Fills per hour with an order resting", y: rows.map(r => r.s.replace("USDT", "")), x: rows.map(r => r.perHour),
      marker: { color: rgba(C.accent, 0.8) }, width: 0.55, text: rows.map(r => `${fmt(r.perHour, 1)}/h · resting ${pct(r.up)} of the day`), textposition: "outside", cliponaxis: false,
      hovertemplate: "%{y}: %{x:.1f} fills/h<extra></extra>" }],
    { showlegend: false, hovermode: "closest", xaxis: axis("fills per hour while an order was resting", { rangemode: "tozero" }), yaxis: axis("", { autorange: "reversed" }), margin: { l: 56, r: 150, t: 10, b: 40 } });
}

function drawExecTable(b) {
  const f = Source.filter, ds = filteredDays(b);
  if (!ds.length) return emptyPanel("ex-table");
  const syms = f.symbol === "ALL" ? Source.symbolsOf(b) : [f.symbol];
  const rows = syms.map(s => {
    const d = ds.filter(x => x.symbol === s), n = d.reduce((a, x) => a + (x.fills || 0), 0);
    if (!d.length) return "";
    const w = k => { const v = d.filter(x => isNum(x[k]) && x.fills); const ww = v.reduce((a, x) => a + x.fills, 0); return ww ? v.reduce((a, x) => a + x[k] * x.fills, 0) / ww : null; };
    const buys = d.reduce((a, x) => a + (x.buy_fills || 0), 0), m1 = w("mk_1"), m60 = w("mk_60");
    return `<tr><td>${esc(s)}</td><td>${fmt(n / d.length, 0)}</td><td>${n ? pct(buys / n) : "–"}</td>
      <td class="${pnlCls(w("net_edge_bp"))}">${sign(w("net_edge_bp"))}</td>
      ${["mk_1", "mk_10", "mk_60", "mk_300"].map(k => `<td>${sign(w(k))}</td>`).join("")}
      <td>${isNum(m1) && isNum(m60) ? sign(m1 - m60) : "–"}</td><td>${isNum(w("wait_s_med")) ? fmt(w("wait_s_med"), 1) : "–"}</td></tr>`;
  }).join("");
  fillHtml("ex-table", `<table><thead><tr><th>Coin</th><th>Fills/day</th><th>Buy share</th><th>Net edge (bp)</th>
    <th>Markout 1 s</th><th>10 s</th><th>60 s</th><th>300 s (bp)</th><th>Adverse selection 1→60 s (bp)</th><th>Median wait (s)</th></tr></thead><tbody>${rows}</tbody></table>`);
}

function drawExecution() {
  const b = deskBundle("execution");
  if (!b) return;
  drawMarkoutChart(b, "ex-side", "side", "side");
  drawMarkoutChart(b, "ex-action", "action", "");
  drawExecWait(b); drawExecRate(b); drawExecTable(b);
}
register("execution", drawExecution);
