/* overview.js: the Verdict tab (Dashboard Redesign R3).
   Reads only the verdict bundle (runs/pub-verdict.js): forest, compare, curves, gross_curves, gates, takeaways.
   Every sentence under a chart comes from takeaways in the bundle; this file never composes a finding. */

const HEADLINE_Q = 1.0;

function sparkline(vals, w = 120, h = 26) {
  if (!vals || vals.length < 2) return "–";
  const step = Math.max(1, Math.floor(vals.length / 120));
  const v = vals.filter((_, i) => i % step === 0 || i === vals.length - 1);
  let lo = Math.min(0, ...v), hi = Math.max(0, ...v);
  if (hi === lo) hi = lo + 1;
  const X = i => (i / (v.length - 1)) * (w - 2) + 1, Y = y => h - 2 - ((y - lo) / (hi - lo)) * (h - 4);
  const pts = v.map((y, i) => `${X(i).toFixed(1)},${Y(y).toFixed(1)}`).join(" ");
  const col = pnlColor(v[v.length - 1]);
  return `<svg class="spark" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true">
    <line x1="0" x2="${w}" y1="${Y(0).toFixed(1)}" y2="${Y(0).toFixed(1)}" stroke="${C.line}" stroke-width="1"/>
    <polyline points="${pts}" fill="none" stroke="${col}" stroke-width="1.5"/></svg>`;
}

/* The verdict bundle, or a message in the view and null. */
function verdictBundle() {
  const host = $("desk-msg-overview"), body = $("desk-body-overview");
  const b = Source.verdict;
  const msg = b ? "" : (Source.verdictError || "Loading verdict…");
  host.textContent = msg; host.hidden = !msg; body.hidden = !!msg;
  return msg ? null : b;
}
const tk = (b, key, fallback) => (b.takeaways && b.takeaways[key]) || fallback;
const jtRow = (b, sym, q) => (b.forest || []).find(r => r.symbol === sym && r.variant === "join_touch" && r.queue_mult === q);
const agentRow = (b, sym = "ALL") => (b.forest || []).find(r => r.symbol === sym && r.variant === "agent");

function drawVerdictLine(b) {
  const el = $("ov-headline");
  el.textContent = tk(b, "headline", "");
  el.hidden = !el.textContent;
}

function drawVerdictTiles(b) {
  const r = jtRow(b, "ALL", HEADLINE_Q);
  if (!r || !isNum(r.net_bp)) return emptyPanel("ov-tiles", "No baseline row in the verdict bundle");
  const coinDays = (b.forest || []).filter(x => x.symbol !== "ALL" && x.variant === "join_touch" && x.queue_mult === HEADLINE_Q)
                                   .reduce((a, x) => a + (x.n_days || 0), 0);
  const ag = agentRow(b), gate = b.gates && b.gates.A;
  const tiles = [
    ["Net bp per $ traded", sign(r.net_bp, 1), pnlCls(r.net_bp), `always join the best price, queue ${HEADLINE_Q}x`],
    ["t-statistic", isNum(r.t) ? fmt(r.t, 1) : "–", "", "|t| > 2: unlikely to be luck"],
    ["Days with profit", pct(r.hit_rate), "", `of ${fmt(r.n_days, 0)} days`],
    ["Counted coin-days", fmt(coinDays, 0), "", "days with 20+ fills"],
    ["Agent fills", ag ? fmt(ag.fills, 0) : "–", "", ag ? `in ${fmt(ag.days_total, 0)} days` : "agent not run"],
    ["Gate A", gate ? (gate.pass ? "PASS" : "FAIL") : "–", gate ? (gate.pass ? "pos" : "neg") : "", "pre-registered, before real money"],
  ];
  fillHtml("ov-tiles", tiles.map(t => `<div class="tile"><div class="k">${t[0]}</div><div class="v ${t[2]}">${t[1]}</div><div class="s">${t[3]}</div></div>`).join(""));
}

/* Forest plot: one row per coin x queue assumption (pooled first). Filled mark = net, hollow mark = before fees,
   whisker = 95% interval of the net mark. Rows with fewer than 30 days are drawn hollow, never hidden. */
function drawVerdictForest(b) {
  const rows = (b.forest || []).filter(r => r.variant === "join_touch" || (r.variant === "agent" && r.symbol === "ALL"));
  if (!rows.length) return emptyPanel("ov-forest");
  const order = r => [r.symbol === "ALL" ? 0 : 1, r.symbol, r.variant === "agent" ? 1 : 0, -(r.queue_mult === 0 ? 9 : -r.queue_mult)];
  rows.sort((a, c) => { const x = order(a), y = order(c); for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] < y[i] ? -1 : 1; return 0; });
  const label = r => `${r.symbol === "ALL" ? "All coins" : r.symbol.replace("USDT", "")} · ${r.scenario || r.variant}`;
  const withNum = rows.filter(r => isNum(r.net_bp));
  const small = r => (r.n_days || 0) < 30;
  const net = { type: "scatter", mode: "markers", name: "Net of fees",
    x: withNum.map(r => r.net_bp), y: withNum.map(label),
    error_x: { type: "data", array: withNum.map(r => isNum(r.net_se) ? 1.96 * r.net_se : 0), color: C.muted, thickness: 1.2, width: 4 },
    marker: { size: 9, symbol: "circle", color: withNum.map(r => small(r) ? "rgba(0,0,0,0)" : pnlColor(r.net_bp)),
              line: { width: 2, color: withNum.map(r => pnlColor(r.net_bp)) } },
    customdata: withNum.map(r => [r.n_days, isNum(r.t) ? r.t.toFixed(1) : "–", r.fills]),
    hovertemplate: "%{y}<br>net %{x:.1f} bp<br>%{customdata[0]} days, t = %{customdata[1]}, %{customdata[2]:,} fills<extra></extra>" };
  const gross = { type: "scatter", mode: "markers", name: "Before fees",
    x: withNum.map(r => r.gross_bp), y: withNum.map(label),
    marker: { size: 8, symbol: "diamond-open", color: C.text, line: { width: 1.5, color: C.text } },
    hovertemplate: "%{y}<br>before fees %{x:.1f} bp<extra></extra>" };
  const none = rows.filter(r => !isNum(r.net_bp));
  const notes = none.map(r => ({ x: 0, y: label(r), xref: "x", yref: "y", text: "no fills: the agent stayed out", showarrow: false,
                                 xanchor: "left", xshift: 8, font: { size: 11, color: C.muted } }));
  const cats = rows.map(label);
  deskPlot("ov-forest", [net, gross], {
    height: Math.max(300, 26 * cats.length + 90), margin: { l: 210, r: 16, t: 10, b: 44 }, hovermode: "closest",
    xaxis: axis("bp per dollar traded (UTC days, 95% interval)", { zeroline: true, zerolinecolor: C.muted, zerolinewidth: 1.5 }),
    yaxis: Object.assign(axis("", { automargin: true }), { autorange: "reversed", categoryorder: "array", categoryarray: cats, type: "category" }),
    annotations: notes,
  });
}

function drawVerdictGates(b) {
  const g = section(b, "gates");
  if (!g) return emptyPanel("ov-gates", "Not evaluated yet");
  const mark = p => p === true ? '<span class="mark pass">PASS</span>' : p === false ? '<span class="mark fail">FAIL</span>' : '<span class="mark na">n/a</span>';
  let html = "";
  for (const name of ["A", "B"]) {
    const gate = g[name];
    html += `<tr><th>Gate ${name}</th><th>${gate ? "" : "not evaluated yet"}</th><th></th><th>${gate ? mark(gate.pass) : ""}</th></tr>`;
    if (!gate) continue;
    for (const c of gate.conditions || [])
      html += `<tr><td>${esc(c.id)}</td><td>${esc(c.text)}</td><td>${isNum(c.value) ? fmtP(c.value) : "–"}</td><td>${mark(c.pass)}</td></tr>`;
  }
  fillHtml("ov-gates", `<table class="gates"><tbody>${html}</tbody></table>`);
}

/* Pooled cumulative net P&L, one line per variant; the before-fees line (dashed) for the headline queue and the agent. */
function drawVerdictCurve(b) {
  const curves = section(b, "curves"), gross = b.gross_curves || {};
  if (!curves) return emptyPanel("ov-cum");
  const keys = Object.keys(curves).filter(k => k.startsWith("ALL|")).sort();
  const tr = [];
  keys.forEach((k, i) => {
    const v = k.slice(4), c = curves[k], col = SERIES[i % SERIES.length];
    tr.push({ x: c.t, y: c.pnl, name: v, mode: "lines", line: { width: v === "q1.0" ? 3 : 1.6, color: col }, legendgroup: v,
              hovertemplate: `${v} %{y:,.0f} USD<extra></extra>` });
    if ((v === "q1.0" || v === "agent") && gross[k])
      tr.push({ x: gross[k].t, y: gross[k].pnl, name: v + " before fees", mode: "lines", line: { width: 1.4, color: col, dash: "dash" }, legendgroup: v,
                hovertemplate: `${v} before fees %{y:,.0f} USD<extra></extra>` });
  });
  if (!tr.length) return emptyPanel("ov-cum");
  deskPlot("ov-cum", tr, { xaxis: axis("UTC date", { type: "date" }), yaxis: axis("USD, 100 USD lots, all coins", { zeroline: true, zerolinecolor: C.muted, zerolinewidth: 1.5 }) });
}

/* Blotter: one row per coin x variant (pooled first), numbers in bp per dollar traded. */
function drawVerdictBlotter(b) {
  const cmp = section(b, "compare"), forest = b.forest || [];
  if (!cmp) return emptyPanel("ov-blotter");
  const f = (r) => forest.find(x => x.symbol === r.symbol && x.variant === r.variant && x.queue_mult === r.queue_mult) || {};
  const rows = cmp.slice().sort((a, c) => (a.symbol === "ALL" ? 0 : 1) - (c.symbol === "ALL" ? 0 : 1) || a.symbol.localeCompare(c.symbol)
                                          || a.variant.localeCompare(c.variant) || (a.queue_mult || 0) - (c.queue_mult || 0))
    .map(r => {
      const x = f(r), nf = isNum(x.net_bp);
      return `<tr><td>${esc(r.symbol === "ALL" ? "All coins" : r.symbol)}</td><td>${esc(r.scenario || r.variant)}</td>
        <td>${fmt(r.fills, 0)}</td>
        <td class="${pnlCls(x.net_bp)}">${nf ? sign(x.net_bp, 1) : "–"}</td>
        <td>${isNum(x.gross_bp) ? sign(x.gross_bp, 1) : "–"}</td>
        <td>${isNum(x.t) ? fmt(x.t, 1) : "–"}</td>
        <td>${isNum(r.mk_60) ? sign(r.mk_60, 2) : "–"}</td>
        <td class="${pnlCls(r.pnl_total)}">${sign(r.pnl_total, 0)}</td>
        <td>${isNum(r.max_dd) ? sign(r.max_dd, 0) : "–"}</td></tr>`;
    }).join("");
  fillHtml("ov-blotter", `<table><thead><tr><th>Coin</th><th>Scenario</th><th>Fills</th><th>Net (bp/$)</th><th>Before fees (bp/$)</th>
    <th>t</th><th>60 s markout (bp)</th><th>P&amp;L (USD per 100 USD lot)</th><th>Max drawdown (USD)</th></tr></thead><tbody>${rows}</tbody></table>`);
}

function drawOverview() {
  const b = verdictBundle();
  if (!b) return;
  drawVerdictLine(b);
  drawVerdictTiles(b);
  $("ov-forest-sub").textContent = tk(b, "ov-forest", "Filled mark: net of fees. Hollow diamond: before fees. Line: 95% interval. Hollow circle: fewer than 30 days.");
  $("ov-cum-sub").textContent = tk(b, "ov-cum", "Cumulative P&L, all coins, one line per queue assumption; dashed = before fees.");
  $("ov-gates-sub").textContent = tk(b, "ov-gates", "Pre-registered pass/fail conditions before real money.");
  drawVerdictForest(b);
  drawVerdictGates(b);
  drawVerdictCurve(b);
  drawVerdictBlotter(b);
}
register("overview", drawOverview);
