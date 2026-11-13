/* model.js: Desk > Model (Dashboard Guide Task D8). Reads only: edge, calib, agent. */
const IMB_LABELS = ["Book against us", "Neutral", "Book with us"], VOL_LABELS = ["Calm", "Normal", "Fast"];

function drawModelEdge(b) {
  const f = Source.filter, e = section(b, "edge"), host = $("md-edge");
  if (!e) return emptyPanel("md-edge", "Not in this run (only walk-forward and paper runs carry the agent's edge table)");
  const syms = (f.symbol === "ALL" ? [...new Set(e.map(r => r.symbol))] : [f.symbol]).filter(s => e.some(r => r.symbol === s));
  if (!syms.length) return emptyPanel("md-edge");
  host.classList.remove("is-empty");
  host.innerHTML = syms.flatMap(s => ["JOIN", "BACK"].map(a => `<div class="chart small" id="md-edge-${s}-${a}"></div>`)).join("");
  const lim = 20;   // fixed at ±20 bp so every panel and every run compares
  syms.forEach(s => ["JOIN", "BACK"].forEach(a => {
    const id = `md-edge-${s}-${a}`, rows = e.filter(r => r.symbol === s && r.action === a);
    if (!rows.length) return emptyPanel(id, `${s} ${a}: not enough fills to estimate`);
    const z = [0, 1, 2].map(i => [0, 1, 2].map(j => { const r = rows.find(x => x.imb === i && x.vol === j); return r ? r.mean : null; }));
    const txt = [0, 1, 2].map(i => [0, 1, 2].map(j => { const r = rows.find(x => x.imb === i && x.vol === j); return r ? `${fmt(r.mean, 1)}${r.n < 30 ? "*" : ""}` : ""; }));
    const hov = [0, 1, 2].map(i => [0, 1, 2].map(j => { const r = rows.find(x => x.imb === i && x.vol === j); return r ? `mean ${fmt(r.mean, 2)} bp · se ${fmt(r.se, 2)} · n ${fmt(r.n, 0)}` : "no data"; }));
    plot(id, [{ type: "heatmap", z, x: VOL_LABELS, y: IMB_LABELS, text: txt, texttemplate: "%{text}", customdata: hov, zmin: -lim, zmax: lim,
                colorscale: [[0, LOSS], [0.5, C.panel], [1, PROFIT]], showscale: false, hovertemplate: "%{y}, %{x}: %{customdata}<extra></extra>" }],
         { title: { text: `${s} · ${a}`, font: { size: 13 } }, margin: { l: 110, r: 10, t: 30, b: 40 } });
  }));
}

function drawModelCalib(b) {
  const f = Source.filter, c = section(b, "calib");
  const rows = c ? c.filter(r => f.symbol === "ALL" || r.symbol === f.symbol) : [];
  if (!rows.length) return emptyPanel("md-calib", "Not in this run (needs live-track fills with a prediction)");
  const syms = [...new Set(rows.map(r => r.symbol))];
  const all = rows.flatMap(r => [r.pred_mean, r.real_mean]), lo = Math.min(...all), hi = Math.max(...all);
  const tr = syms.map((s, i) => { const r = rows.filter(x => x.symbol === s);
    return { x: r.map(x => x.pred_mean), y: r.map(x => x.real_mean), error_y: { type: "data", array: r.map(x => x.se || 0), visible: true },
             mode: "markers", name: s, marker: { color: SERIES[i % SERIES.length], size: 9 }, hovertemplate: `${s}: predicted %{x:.2f}, realised %{y:.2f} bp<extra></extra>` }; });
  tr.push({ x: [lo, hi], y: [lo, hi], mode: "lines", name: "perfect calibration", line: { color: C.muted, dash: "dot" } });
  deskPlot("md-calib", tr, { xaxis: axis("Predicted net edge (bp)"), yaxis: axis("Realised net edge (bp)") });
}

function drawModelArms(b) {
  const f = Source.filter, ag = section(b, "agent");
  const rows = ag ? ag.filter(r => f.symbol === "ALL" || r.symbol === f.symbol) : [];
  if (!rows.length) { emptyPanel("md-arms"); emptyPanel("md-scores"); return; }
  const syms = [...new Set(rows.map(r => r.symbol))];
  const tr = syms.map((s, i) => { const r = rows.filter(x => x.symbol === s);
    return { x: r.map(x => x.ts), y: r.map(() => s.replace("USDT", "")), name: s, mode: "markers", showlegend: false,
             marker: { symbol: "square", size: 16, cmin: 0, cmax: 11, colorscale: "Viridis", color: r.map(x => x.live_arm),
                       colorbar: i ? undefined : { title: { text: "arm" }, thickness: 10 }, line: { width: 0 } },
             text: r.map(x => `arm ${x.live_arm}${x.switched ? " (switch)" : ""}`), hovertemplate: `${s} %{x}: %{text}<extra></extra>` }; });
  const sw = syms.map(s => `${s.replace("USDT", "")}: ${rows.filter(r => r.symbol === s && r.switched).length}`).join(", ");
  $("md-arms-sub").textContent = `One square per recorded interval, coloured by the live setting (0–11); switches of setting: ${sw}`;
  deskPlot("md-arms", tr, { xaxis: axis("UTC", { type: "date" }), yaxis: axis(""), hovermode: "closest" });
  const last = syms.map(s => rows.filter(r => r.symbol === s).slice(-1)[0]);
  fillHtml("md-scores", `<table><thead><tr><th>Arm</th>${last.map(r => `<th>${esc(r.symbol)}</th>`).join("")}</tr></thead><tbody>${
    [...Array(12).keys()].map(a => `<tr><td>${a}${last.some(r => r.live_arm === a) ? " (live)" : ""}</td>${last.map(r => `<td class="${pnlCls(r.scores[a])}">${sign(r.scores[a], 3)}</td>`).join("")}</tr>`).join("")
  }</tbody></table><p class="note">Decayed mean score per 30-min interval, bp of the full position (10 lots × $100). Menu: e_min ∈ {0, 2, 5} bp × z ∈ {0, 1} × γ ∈ {0.5, 2}; arm 11 is the most cautious and the starting point.</p>`);
}

function drawModelHealth() {
  const b = deskBundle("model-health");
  if (!b) return;
  drawModelEdge(b); drawModelCalib(b); drawModelArms(b);
}
register("model-health", drawModelHealth);
