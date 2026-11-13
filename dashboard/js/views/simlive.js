/* simlive.js: Data > Sim vs live (Dashboard Guide D11). The page's run is the simulation, "Compare with" is the
   live (paper or testnet) run; the arithmetic is in js/compare.js. */

const SL_TEXT = {
  "no-overlap": ["amber", "No coin and date appear in both runs, so there is nothing to compare."],
  "no-fills": ["amber", "One of the runs has no fills on the shared days, so fills and edge cannot be compared."],
};

function slVariantFor(b, want) {
  const vs = [...new Set((section(b, "days") || []).map(d => d.variant))];
  return vs.includes(want) ? want : (vs.includes("agent") ? "agent" : vs[0]);
}

function slVerdict(v) {
  if (SL_TEXT[v.state]) return `<div class="verdict amber">${esc(SL_TEXT[v.state][1])}</div>`;
  const line = `fills ${fmt(v.fills_ratio, 2)}x the simulation, net edge ${sign(v.edge_diff_bp, 1)} bp apart`;
  return v.state === "consistent"
    ? `<div class="verdict ok"><b>Consistent</b>: ${line} (rule: fills within ±30% and edge within 2 bp).</div>`
    : `<div class="verdict amber"><b>Simulator and live disagree</b>: ${line} (rule: fills within ±30% and edge within 2 bp).</div>`;
}

function drawSimLive() {
  const a = deskBundle("simlive");
  if (!a) return;
  const b = Source.compare;
  if (!b) {
    ["sl-table", "sl-pnl", "sl-fills", "sl-mk"].forEach(id => emptyPanel(id, "Pick a run in “Compare with” (a paper or testnet run) to check the simulator against"));
    $("sl-verdict").innerHTML = "";
    return;
  }
  const va = Source.filter.variant, vb = slVariantFor(b, va);
  const out = Compare.compareRuns(a, b, va, vb);
  $("sl-verdict").innerHTML = slVerdict(out.verdict);
  $("sl-sub").textContent = `${a.label} (${va}) against ${b.label} (${vb}), on the ${out.common_days} coin-days both contain`;
  const f = (r, x) => !isNum(x) ? "–" : /USD/.test(r.label) || /Fills/.test(r.label) ? fmtP(x) : fmt(x, 2);
  fillHtml("sl-table", `<table><thead><tr><th>Measure</th><th>Simulation</th><th>Live</th><th>Difference</th></tr></thead><tbody>${out.rows.map(r =>
    `<tr><td>${esc(r.label)}</td><td>${f(r, r.a)}</td><td>${f(r, r.b)}</td><td class="${pnlCls(r.diff)}">${isNum(r.diff) ? (r.diff > 0 ? "+" : r.diff < 0 ? "−" : "") + f(r, Math.abs(r.diff)) : "–"}</td></tr>`).join("")}</tbody></table>`);
  if (!out.curves.dates.length) { ["sl-pnl", "sl-fills"].forEach(id => emptyPanel(id, "No shared days")); }
  else {
    deskPlot("sl-pnl", [{ type: "scatter", mode: "lines", name: "Simulation", x: out.curves.dates, y: out.curves.a, line: { color: SERIES[0], width: 2 } },
      { type: "scatter", mode: "lines", name: "Live", x: out.curves.dates, y: out.curves.b, line: { color: SERIES[1], width: 2 } }],
      { xaxis: axis("date"), yaxis: axis("cumulative net P&L (USD)", { zeroline: true, zerolinecolor: C.muted, zerolinewidth: 1.5 }) });
    deskPlot("sl-fills", [{ type: "bar", name: "Simulation", x: out.fills_by_date.dates, y: out.fills_by_date.a, marker: { color: SERIES[0] } },
      { type: "bar", name: "Live", x: out.fills_by_date.dates, y: out.fills_by_date.b, marker: { color: SERIES[1] } }],
      { barmode: "group", xaxis: axis("date"), yaxis: axis("fills per day") });
  }
  const mk = (run, v) => { const g = {}; (section(run, "markouts") || []).filter(r => r.variant === v && isNum(r.bp) && r.n > 0).forEach(r => { const o = g[r.h_s] = g[r.h_s] || { s: 0, n: 0 }; o.s += r.bp * r.n; o.n += r.n; });
    return Object.entries(g).map(([h, o]) => [+h, o.s / o.n]).sort((x, y) => x[0] - y[0]); };
  const ma = mk(a, va), mb = mk(b, vb);
  if (!ma.length && !mb.length) emptyPanel("sl-mk", "No markouts in either run");
  else deskPlot("sl-mk", [[ma, "Simulation", SERIES[0]], [mb, "Live", SERIES[1]]].filter(s => s[0].length).map(([pts, name, col]) =>
    ({ type: "scatter", mode: "lines+markers", name, x: pts.map(p => p[0]), y: pts.map(p => p[1]), line: { color: col, width: 2 } })),
    { xaxis: axis("seconds after the fill", { type: "log" }), yaxis: axis("mean markout (bp)", { zeroline: true, zerolinecolor: C.muted, zerolinewidth: 1.5 }) });
}
register("simlive", drawSimLive);
