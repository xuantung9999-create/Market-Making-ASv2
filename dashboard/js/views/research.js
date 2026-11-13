/* research.js: the original research tabs (simulator, model, replication, real data, backtest,
   universe, informed traders, tuning, about). Behaviour unchanged from the single-file page. */
/* ======================= Simulation (JS port of mm/simulator.py) ======================= */
function mulberry32(a) { return function () { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a);
  t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }

function simulateBoth(P, nPaths, seed) {
  const N = Math.round(P.T / P.dt), sq = Math.sqrt(P.dt) * P.sigma, g = P.gamma, s2 = P.sigma * P.sigma;
  const liq = (2 / g) * Math.log1p(g / P.k);
  const half = new Float64Array(N + 1), t = new Float64Array(N + 1);
  for (let i = 0; i <= N; i++) { t[i] = i * P.dt; half[i] = (g * s2 * Math.max(P.T - t[i], 0) + liq) / 2; }
  const rng = mulberry32(seed * 7919 + 13);
  const K = Math.min(40, nPaths);
  const mk = () => ({ final: new Float64Array(nPaths), q: new Float64Array(nPaths), fills: 0, fan: [], mean: new Float64Array(N + 1) });
  const res = { inv: mk(), sym: mk(), t, N };
  const p0 = { s: [], r: [], bid: [], ask: [], qInv: [], qSym: [], bidFill: [], askFill: [] };
  for (let p = 0; p < nPaths; p++) {
    let s = 100; const st = [{ q: 0, x: 0 }, { q: 0, x: 0 }];
    const fanI = p < K ? [0] : null, fanS = p < K ? [0] : null;
    for (let i = 0; i <= N; i++) {
      const tau = Math.max(P.T - t[i], 0);
      if (p === 0) {
        const r0 = s - st[0].q * g * s2 * tau;
        p0.s.push(s); p0.r.push(r0); p0.bid.push(r0 - half[i]); p0.ask.push(r0 + half[i]);
        p0.qInv.push(st[0].q); p0.qSym.push(st[1].q);
      }
      if (i === N) break;
      const step = rng() < 0.5 ? -sq : sq, ub = rng(), ua = rng();
      for (let k = 0; k < 2; k++) {
        const S = st[k];
        const centre = k === 0 ? s - S.q * g * s2 * tau : s;
        const bid = centre - half[i], ask = centre + half[i];
        const pb = Math.min(P.A * Math.exp(-P.k * (s - bid)) * P.dt, 1);
        const pa = Math.min(P.A * Math.exp(-P.k * (ask - s)) * P.dt, 1);
        let hit = ub < pb, lift = ua < pa;
        if (P.qmax > 0) { hit = hit && S.q < P.qmax; lift = lift && S.q > -P.qmax; }
        if (hit) { S.q += 1; S.x -= bid; }
        if (lift) { S.q -= 1; S.x += ask; }
        (k === 0 ? res.inv : res.sym).fills += hit + lift;
        if (p === 0 && k === 0) { if (hit) p0.bidFill.push([t[i], bid]); if (lift) p0.askFill.push([t[i], ask]); }
      }
      s += step;
      const vi = st[0].x + st[0].q * s, vs = st[1].x + st[1].q * s;
      res.inv.mean[i + 1] += vi; res.sym.mean[i + 1] += vs;
      if (fanI) { fanI.push(vi); fanS.push(vs); }
    }
    res.inv.final[p] = st[0].x + st[0].q * s; res.sym.final[p] = st[1].x + st[1].q * s;
    res.inv.q[p] = st[0].q; res.sym.q[p] = st[1].q;
    if (fanI) { res.inv.fan.push(fanI); res.sym.fan.push(fanS); }
  }
  for (const key of ["inv", "sym"]) { const m = res[key].mean; for (let i = 0; i <= N; i++) m[i] /= nPaths; }
  res.path = p0; res.avgSpread = 2 * half.slice(0, N).reduce((a, b) => a + b, 0) / N;
  return res;
}
function stats(arr) {
  const n = arr.length; let m = 0; for (const v of arr) m += v; m /= n;
  let v2 = 0; for (const v of arr) v2 += (v - m) ** 2; const sd = Math.sqrt(v2 / Math.max(n - 1, 1));
  return { mean: m, std: sd };
}

/* ======================= State + controls ======================= */
const PAPER = { gamma: 0.1, sigma: 2, k: 1.5, A: 140, qmax: 0, paths: 500, seed: 11 };
const P = Object.assign({ T: 1, dt: 0.005 }, PAPER);
const ctl = {
  gamma: { el: "p-gamma", to: v => 10 ** v, from: v => Math.log10(v), show: v => v < 0.01 ? v.toFixed(4) : v < 0.1 ? v.toFixed(3) : v.toFixed(2) },
  sigma: { el: "p-sigma", show: v => v.toFixed(1) }, k: { el: "p-k", show: v => v.toFixed(2) }, A: { el: "p-A", show: v => v.toFixed(0) },
  qmax: { el: "p-qmax", show: v => v === 0 ? "off" : v.toFixed(0) }, paths: { el: "p-paths", show: v => v.toLocaleString("en-US") },
  seed: { el: "p-seed", show: v => v.toFixed(0) },
};
function syncControls() {
  for (const [key, c] of Object.entries(ctl)) {
    const el = document.getElementById(c.el); el.value = c.from ? c.from(P[key]) : P[key];
    document.getElementById("o" + c.el.slice(1)).textContent = c.show(P[key]);
  }
}
let simTimer = null, SIM = null;
for (const [key, c] of Object.entries(ctl)) {
  document.getElementById(c.el).addEventListener("input", e => {
    const raw = parseFloat(e.target.value); P[key] = c.to ? c.to(raw) : raw;
    document.getElementById("o" + c.el.slice(1)).textContent = c.show(P[key]);
    clearTimeout(simTimer); simTimer = setTimeout(runSim, 60);
  });
}
document.getElementById("btn-paper").addEventListener("click", () => { Object.assign(P, PAPER); syncControls(); runSim(); });
document.getElementById("btn-reroll").addEventListener("click", () => { P.seed = (P.seed + 1 + Math.floor(Math.random() * 97)) % 100; syncControls(); runSim(); });
document.getElementById("p-t").addEventListener("input", e => { document.getElementById("o-t").textContent = (+e.target.value).toFixed(2); drawModel(); });

function runSim() {
  stopReplay();
  SIM = simulateBoth(P, P.paths, P.seed);
  dirty.simulator = dirty.model = true;
  renderVisible();
}

/* ======================= Simulator views ======================= */
function drawKpis() {
  const box = document.getElementById("sim-kpis");
  const card = (key, name, color) => {
    const r = SIM[key], s = stats(r.final), q = stats(r.q);
    return { html: `<div class="kpi" style="--c:${color}"><div class="name">${name}<span class="pill">Sharpe ${fmt(s.mean / s.std, 2)}</span></div>
      <dl><div><dt>Mean profit</dt><dd>${fmt(s.mean, 1)}</dd></div><div><dt>Profit std</dt><dd>${fmt(s.std, 1)}</dd></div>
      <div><dt>Final q std</dt><dd>${fmt(q.std, 2)}</dd></div><div><dt>Fills / path</dt><dd>${fmt(r.fills / P.paths, 1)}</dd></div>
      <div><dt>Avg spread</dt><dd>${fmt(SIM.avgSpread, 2)}</dd></div></dl></div>`, sharpe: s.mean / s.std };
  };
  const a = card("inv", "A-S strategy", C.accent), b = card("sym", "Symmetric benchmark", C.bench);
  box.innerHTML = a.html + b.html;
}
let replayId = null;
function pathTraces(n) {
  const p = SIM.path, t = Array.from(SIM.t.slice(0, n));
  const cut = a => a.slice(0, n);
  const bf = p.bidFill.filter(f => f[0] < t[t.length - 1] + 1e-9), af = p.askFill.filter(f => f[0] < t[t.length - 1] + 1e-9);
  return [
    { x: t, y: cut(p.ask), mode: "lines", line: { width: 0 }, hoverinfo: "skip", showlegend: false },
    { x: t, y: cut(p.bid), mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: rgba(C.accent, 0.13), name: "quoted band", hoverinfo: "skip" },
    { x: t, y: cut(p.s), mode: "lines", name: "mid s", line: { color: C.text, width: 1.6 }, hovertemplate: "%{y:.3f}" },
    { x: t, y: cut(p.r), mode: "lines", name: "reservation r", line: { color: C.accent, width: 1.4, dash: "dash" }, hovertemplate: "%{y:.3f}" },
    { x: bf.map(f => f[0]), y: bf.map(f => f[1]), mode: "markers", name: "bid filled (buy)", marker: { symbol: "triangle-up", size: 8, color: C.bid }, hovertemplate: "buy @ %{y:.3f}" },
    { x: af.map(f => f[0]), y: af.map(f => f[1]), mode: "markers", name: "ask filled (sell)", marker: { symbol: "triangle-down", size: 8, color: C.ask }, hovertemplate: "sell @ %{y:.3f}" },
  ];
}
function pathLayout() {
  const p = SIM.path, lo = Math.min(...p.bid), hi = Math.max(...p.ask), pad = (hi - lo) * 0.05;
  return { xaxis: axis("time t", { range: [0, 1] }), yaxis: axis("price", { range: [lo - pad, hi + pad] }) };
}
function drawPath() { plot("ch-path", pathTraces(SIM.N + 1), pathLayout()); }
function stopReplay() { if (replayId) { cancelAnimationFrame(replayId); replayId = null; document.getElementById("btn-replay").textContent = "▶ Replay session"; } }
document.getElementById("btn-replay").addEventListener("click", () => {
  if (replayId) { stopReplay(); drawPath(); return; }
  if (reduceMotion) { drawPath(); return; }
  const btn = document.getElementById("btn-replay"); btn.textContent = "■ Stop";
  const lay = pathLayout(); let n = 2, last = 0;
  const frame = ts => {
    if (ts - last > 24) { last = ts; Plotly.react("ch-path", pathTraces(n), layout(lay), CONFIG); n += 1; }
    if (n <= SIM.N + 1) replayId = requestAnimationFrame(frame); else { replayId = null; btn.textContent = "▶ Replay session"; }
  };
  replayId = requestAnimationFrame(frame);
});
function drawInv() {
  const t = Array.from(SIM.t);
  plot("ch-inv", [
    { x: t, y: SIM.path.qInv, name: "A-S", line: { color: C.accent, shape: "hv", width: 1.6 } },
    { x: t, y: SIM.path.qSym, name: "benchmark", line: { color: C.bench, shape: "hv", width: 1.6 } },
  ], { xaxis: axis("time t"), yaxis: axis("inventory q", { zeroline: true }) });
}
function drawHist() {
  const all = [...SIM.inv.final, ...SIM.sym.final]; const lo = Math.min(...all), hi = Math.max(...all);
  const size = (hi - lo) / 45 || 1;
  const h = (arr, name, color) => ({ type: "histogram", x: Array.from(arr), name, opacity: 0.6, marker: { color },
                                     xbins: { start: lo, end: hi + size, size }, hovertemplate: "%{x}: %{y} paths<extra>" + name + "</extra>" });
  plot("ch-hist", [h(SIM.sym.final, "benchmark", C.bench), h(SIM.inv.final, "A-S", C.accent)],
       { barmode: "overlay", hovermode: "closest", xaxis: axis("terminal profit"), yaxis: axis("paths") });
}
function drawFan() {
  const t = Array.from(SIM.t), tr = [];
  const add = (key, color, name) => {
    SIM[key].fan.forEach((y, i) => tr.push({ x: t, y, mode: "lines", line: { color: rgba(color, 0.16), width: 1 }, hoverinfo: "skip", showlegend: false, legendgroup: key }));
    tr.push({ x: t, y: Array.from(SIM[key].mean), mode: "lines", name: name + " average", legendgroup: key, line: { color, width: 3 }, hovertemplate: "%{y:.1f}" });
  };
  add("sym", C.bench, "benchmark"); add("inv", C.accent, "A-S");
  plot("ch-fan", tr, { xaxis: axis("time t"), yaxis: axis("profit (cash + q × mid)") });
}

/* ======================= Model views ======================= */
function drawModel() {
  const t = +document.getElementById("p-t").value, tau = P.T - t, g = P.gamma, s2 = P.sigma ** 2;
  const liq = (2 / g) * Math.log1p(g / P.k), half = (g * s2 * tau + liq) / 2;
  const qs = []; for (let q = -10; q <= 10; q++) qs.push(q);
  const rr = qs.map(q => -q * g * s2 * tau);
  plot("ch-geom", [
    { x: qs, y: rr.map(v => v + half), name: "ask − mid", mode: "lines+markers", line: { color: C.ask }, marker: { size: 5 } },
    { x: qs, y: rr, name: "r − mid", mode: "lines", line: { color: C.accent, dash: "dash" } },
    { x: qs, y: rr.map(v => v - half), name: "bid − mid", mode: "lines+markers", line: { color: C.bid }, marker: { size: 5 } },
  ], { xaxis: axis("inventory q"), yaxis: axis("distance from mid", { zeroline: true, zerolinecolor: C.muted }) });

  const ts = []; for (let i = 0; i <= 100; i++) ts.push(i / 100);
  const inv = ts.map(x => g * s2 * (P.T - x));
  plot("ch-spread", [
    { x: ts, y: ts.map(() => liq), name: "order-flow term", stackgroup: "s", line: { color: C.bench, width: 1 }, fillcolor: rgba(C.bench, 0.35), hovertemplate: "%{y:.3f}" },
    { x: ts, y: inv, name: "inventory-risk term", stackgroup: "s", line: { color: C.accent, width: 1 }, fillcolor: rgba(C.accent, 0.35), hovertemplate: "%{y:.3f}" },
  ], { xaxis: axis("time t"), yaxis: axis("total spread") });

  const dMax = Math.max(4 / P.k, 2.5 * half), ds = []; for (let i = 0; i <= 200; i++) ds.push(i * dMax / 200);
  const prof = ds.map(d => d * P.A * Math.exp(-P.k * d)), best = 1 / P.k, bestV = best * P.A * Math.exp(-1);
  const asHalf = liq / 2, asV = asHalf * P.A * Math.exp(-P.k * asHalf);
  plot("ch-profit", [
    { x: ds, y: prof, name: "δ × A·e^(−kδ)", mode: "lines", line: { color: C.text, width: 2 }, hovertemplate: "δ=%{x:.3f}: %{y:.2f}" },
    { x: [best], y: [bestV], name: "risk-neutral optimum 1/k", mode: "markers", marker: { color: C.bench, size: 11, line: { color: C.text, width: 1 } }, hovertemplate: "δ=%{x:.3f}" },
    { x: [asHalf], y: [asV], name: "A-S order-flow half-spread", mode: "markers", marker: { color: C.accent, size: 11, symbol: "diamond", line: { color: C.text, width: 1 } }, hovertemplate: "δ=%{x:.3f}" },
  ], { hovermode: "closest", xaxis: axis("δ, distance from mid"), yaxis: axis("expected profit per unit time"),
       annotations: [{ x: best, y: bestV, text: `1/k = ${best.toFixed(3)}`, showarrow: true, arrowcolor: C.muted, ax: 40, ay: -30,
                       font: { family: MONO, color: C.text, size: 11 }, bgcolor: "rgba(0,0,0,.45)", bordercolor: C.bench }] });

  const fp = ds.map(d => Math.min(P.A * Math.exp(-P.k * d) * P.dt, 1));
  const h0 = (g * s2 * P.T + liq) / 2, p0 = Math.min(P.A * Math.exp(-P.k * h0) * P.dt, 1);
  plot("ch-fill", [
    { x: ds, y: fp, name: "P(fill in dt)", mode: "lines", line: { color: C.text, width: 2 }, hovertemplate: "δ=%{x:.3f}: %{y:.3f}" },
    { x: [h0], y: [p0], name: "t = 0 quotes, q = 0", mode: "markers", marker: { color: C.accent, size: 11 }, hovertemplate: "δ=%{x:.3f}, p=%{y:.3f}" },
  ], { hovermode: "closest", xaxis: axis("δ, distance from mid"), yaxis: axis("probability per step", { rangemode: "tozero" }) });
}

/* ======================= Replication views ======================= */
function drawReplication() {
  const R = D.replication, rows = R.paper_table;
  const gammas = [...new Set(rows.map(r => r.gamma))];
  const pick = (st, f) => gammas.map(g => rows.find(r => r.gamma === g && r.strategy === st)[f]);
  const bars = f => [
    { type: "bar", x: gammas.map(g => "γ = " + g), y: pick("inventory", f), name: "A-S", marker: { color: C.accent }, hovertemplate: "%{y:.2f}" },
    { type: "bar", x: gammas.map(g => "γ = " + g), y: pick("symmetric", f), name: "benchmark", marker: { color: C.bench }, hovertemplate: "%{y:.2f}" },
  ];
  plot("ch-rep-std", bars("std_pnl"), { barmode: "group", xaxis: axis(""), yaxis: axis("std of profit") });
  plot("ch-rep-mean", bars("mean_pnl"), { barmode: "group", xaxis: axis(""), yaxis: axis("mean profit") });

  const g01 = f => rows.find(r => r.gamma === 0.1 && r.strategy === f);
  const a = g01("inventory"), b = g01("symmetric");
  document.getElementById("rep-callout").innerHTML = `At the paper's settings (γ = 0.1), A-S earns <b>${fmt(a.mean_pnl, 1)}</b> on average vs ${fmt(b.mean_pnl, 1)} for the benchmark, with profit volatility of <b>${fmt(a.std_pnl, 1)}</b> vs ${fmt(b.std_pnl, 1)}. That is ${fmt(100 * (1 - a.mean_pnl / b.mean_pnl), 0)}% less profit for ${fmt(100 * (1 - a.std_pnl / b.std_pnl), 0)}% less risk: a Sharpe ratio of <b>${fmt(a.mean_pnl / a.std_pnl, 1)}</b> vs ${fmt(b.mean_pnl / b.std_pnl, 1)}.`;

  const cols = [["gamma", "γ", 2], ["strategy", "Strategy"], ["avg_spread", "Avg spread", 2], ["mean_pnl", "Mean profit", 2], ["std_pnl", "Profit std", 2],
                ["mean_final_q", "Mean final q", 2], ["std_final_q", "Final q std", 2], ["fills_per_path", "Fills / path", 1]];
  const label = s => s === "inventory" ? "A-S (inventory)" : "Symmetric benchmark";
  document.getElementById("rep-table").innerHTML = "<thead><tr>" + cols.map(c => `<th scope="col">${c[1]}</th>`).join("") + "</tr></thead><tbody>" +
    rows.map(r => `<tr class="${r.strategy === "inventory" ? "inv" : "sym"}">` + cols.map(c => `<td>${c[0] === "strategy" ? label(r.strategy) : fmt(r[c[0]], c[2])}</td>`).join("") + "</tr>").join("") + "</tbody>";

  if (R.experiments.length) {
    const ex = R.experiments, names = [...new Set(ex.map(e => e.experiment))];
    const clean = n => n.replace(/^\d+\s*/, "");
    const sh = st => names.map(n => ex.find(e => e.experiment === n && e.strategy === st).sharpe);
    plot("ch-exp", [
      { type: "bar", orientation: "h", y: names.map(clean), x: sh("inventory"), name: "A-S", marker: { color: C.accent }, hovertemplate: "Sharpe %{x:.2f}" },
      { type: "bar", orientation: "h", y: names.map(clean), x: sh("symmetric"), name: "benchmark", marker: { color: C.bench }, hovertemplate: "Sharpe %{x:.2f}" },
    ], { barmode: "group", hovermode: "y unified", margin: { l: 150, r: 16, t: 10, b: 44 }, xaxis: axis("Sharpe ratio"), yaxis: axis("", { autorange: "reversed" }) });
  }
  const cs = R.cap_sweep, ref = R.as_reference;
  plot("ch-cap", [
    { x: cs.map(c => c.q_max), y: cs.map(c => c.sharpe), name: "benchmark + cap", mode: "lines+markers", line: { color: C.bench, width: 2 }, hovertemplate: "q_max %{x}: Sharpe %{y:.2f}" },
    { x: [cs[0].q_max, cs[cs.length - 1].q_max], y: [ref.sharpe, ref.sharpe], name: "A-S, no cap", mode: "lines", line: { color: C.accent, width: 2, dash: "dash" }, hovertemplate: "Sharpe %{y:.2f}" },
  ], { hovermode: "closest", xaxis: axis("inventory cap q_max"), yaxis: axis("Sharpe ratio", { rangemode: "tozero" }) });
  plot("ch-crn", [
    { x: R.crn.map(c => c.seed), y: R.crn.map(c => c.same), name: "same random numbers", mode: "lines+markers", line: { color: C.accent } },
    { x: R.crn.map(c => c.seed), y: R.crn.map(c => c.indep), name: "independent random numbers", mode: "lines+markers", line: { color: C.muted, dash: "dot" } },
  ], { xaxis: axis("run"), yaxis: axis("profit gap") });
}

/* ======================= Real data views ======================= */
let DAY = 0;
function drawRealData() {
  const days = D.real_days;
  const bar = document.getElementById("daybar");
  if (!days.length) { bar.innerHTML = '<p class="note">No real data in data.js yet. Run <span class="mono">python -m mm.data download</span>, then <span class="mono">python -m scripts.build_dashboard</span>.</p>'; return; }
  const syms = [...new Set(days.map(d => d.symbol))], cur = days[DAY];
  const dsOf = sym => days.map((d, i) => [d, i]).filter(x => x[0].symbol === sym);
  bar.innerHTML = `<label class="note" for="rd-sym">Coin</label><select id="rd-sym">${syms.map(x => `<option ${x === cur.symbol ? "selected" : ""}>${x}</option>`).join("")}</select>` +
    `<span class="note" style="margin-left:8px">Day:</span>` + dsOf(cur.symbol).map(([d, i]) => `<button type="button" data-day="${i}" aria-pressed="${i === DAY}">${d.date}</button>`).join("") +
    `<span class="chip" style="margin-left:8px">${cur.summary.tier || ""} cap · spread ${fmt(cur.summary.spread_bp, 2)} bp</span>`;
  document.getElementById("rd-sym").addEventListener("change", e => { DAY = dsOf(e.target.value)[0][1]; drawRealData(); });
  bar.querySelectorAll("button").forEach(b => b.addEventListener("click", () => { DAY = +b.dataset.day; drawRealData(); }));
  const d = days[DAY], s = d.summary, fc = d.fill_curve, m = d.minute;
  const tile = (k, v, sub = "") => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${sub}</div></div>`;
  document.getElementById("real-tiles").innerHTML =
    tile("Trades", fmt(s.n_trades, 0), `${fmt(s.trades_per_sec, 2)} per second`) +
    tile("USD volume", "$" + fmt(s.usd_volume / 1e6, 2) + "M", "this day, Binance spot") +
    tile("σ, whole day", fmtP(s.sigma), `USDT per √s · ${fmt(s.sigma_bp, 2)} bp`) +
    tile("Daily volatility", fmt(s.daily_vol_pct, 2) + "%", "from 1-second log returns") +
    tile("Price range", fmtP(s.price_min) + "–" + fmtP(s.price_max), "USDT") +
    tile("Fitted k", fmt(fc.k / 1e4 * s.price_last, 3), `per bp · R² ${fmt(fc.r2, 3)}`) +
    tile("Buyer-initiated", fmt(100 * s.buy_share, 1) + "%", "share of trades");

  const halfLiq = 1 / fc.k, ticks = halfLiq / s.tick, bp = halfLiq / s.price_last * 1e4;
  let pAt = null; for (let i = 0; i < fc.delta.length; i++) if (fc.delta[i] >= halfLiq) { pAt = fc.p[i]; break; }
  const p0 = fc.p[0];
  const spT = s.spread && s.tick ? Math.round(s.spread / s.tick) : 1;
  document.getElementById("real-callout").innerHTML = `With the fitted k, the model's order-flow half-spread is about 1/k = <b>${fmtP(halfLiq)} USDT</b> (${fmt(ticks, 0)} ticks, ${fmt(bp, 2)} bp) each side of the mid. The market's typical spread is ${spT} tick${spT > 1 ? "s" : ""} = ${fmt(s.spread_bp, 2)} bp. A quote at the touch is traded through in <b>${fmt(100 * p0, 0)}%</b> of seconds; one at 1/k in ${pAt === null ? "–" : fmt(100 * pAt, 1)}%. ` + (bp > 5 * (s.spread_bp || 0) ? "The model would quote far behind the best prices here." : "Here the model's quotes sit close to the real spread, which suits A-S better than BTC.");

  const t = m.t.map(x => x.slice(0, 19).replace("T", " "));
  plot("ch-price", [
    { x: t, y: m.hi, mode: "lines", line: { width: 0 }, hoverinfo: "skip", showlegend: false, yaxis: "y" },
    { x: t, y: m.lo, mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: rgba(C.accent, 0.18), name: "1-minute range", hoverinfo: "skip", yaxis: "y" },
    { x: t, y: m.mid, mode: "lines", name: "mid", line: { color: C.text, width: 1.2 }, hovertemplate: "%{y:.6g}", yaxis: "y" },
    { x: t, y: m.trades, type: "bar", name: "trades / min", marker: { color: rgba(C.accent, 0.6) }, hovertemplate: "%{y:,} trades", yaxis: "y2" },
  ], { xaxis: axis("UTC", { type: "date", anchor: "y2" }), yaxis: axis("USDT", { domain: [0.32, 1], tickformat: s.price_last >= 1000 ? ",.0f" : ".4~g" }),
       yaxis2: axis("trades / min", { domain: [0, 0.24] }), bargap: 0 });
  plot("ch-sigma", [
    { x: t, y: m.sigma_5m, name: "rolling 5 min", line: { color: rgba(C.accent, 0.45), width: 1 }, hovertemplate: "%{y:.4g}" },
    { x: t, y: m.sigma_1h, name: "rolling 1 h", line: { color: C.accent, width: 2 }, hovertemplate: "%{y:.4g}" },
    { x: [t[0], t[t.length - 1]], y: [s.sigma, s.sigma], name: "whole day", mode: "lines", line: { color: C.bench, dash: "dash" }, hovertemplate: "%{y:.4g}" },
  ], { xaxis: axis("UTC", { type: "date" }), yaxis: axis("σ (USDT / √s)", { rangemode: "tozero" }) });
  const fitX = fc.delta.filter(x => x >= fc.fit_from), fitY = fitX.map(x => fc.A * Math.exp(-fc.k * x));
  plot("ch-realfill", [
    { x: fc.delta, y: fc.lam.map(v => v > 0 ? v : null), mode: "markers", name: "measured", marker: { color: C.text, size: 6 }, hovertemplate: "δ=%{x:.4g}: λ=%{y:.4g}/s" },
    { x: fitX, y: fitY, mode: "lines", name: `fit: A·e^(−kδ), R² ${fmt(fc.r2, 3)}`, line: { color: C.accent, width: 2 }, hovertemplate: "fit %{y:.4g}" },
  ], { hovermode: "closest", xaxis: axis("δ, USDT from previous mid"), yaxis: axis("fill intensity λ (per second, log)", { type: "log" }),
       annotations: [{ x: fc.delta[0], y: Math.log10(fc.lam[0]), text: "at the touch:<br>far above the curve", showarrow: true, ax: 70, ay: 10,
                       arrowcolor: C.muted, font: { size: 11, color: C.text }, bgcolor: "rgba(0,0,0,.45)", bordercolor: C.line }] });
  let cum = 0; const flow = m.buy_vol.map((b, i) => (cum += (b || 0) - (m.sell_vol[i] || 0)));
  plot("ch-flow", [
    { x: t, y: flow, name: "cumulative buy − sell volume", line: { color: C.bid, width: 1.6 }, hovertemplate: "%{y:,.1f}" },
    { x: t, y: m.mid, name: "mid", line: { color: C.muted, width: 1 }, yaxis: "y2", hovertemplate: "%{y:,.2f}" },
  ], { xaxis: axis("UTC", { type: "date" }), yaxis: axis(d.symbol.replace("USDT", "")), yaxis2: axis("USDT", { overlaying: "y", side: "right", showgrid: false, tickformat: s.price_last >= 1000 ? ",.0f" : ".4~g" }) });

  if (D.live) {
    document.getElementById("live-card").hidden = false;
    document.getElementById("live-sub").textContent = `${fmt(D.live.updates, 0)} best bid/ask updates recorded over ${fmt(D.live.hours, 2)} hours. Share of updates by quoted spread (USDT).`;
    plot("ch-live", [{ type: "bar", x: D.live.spread_values.map(v => v.toFixed(2)), y: D.live.spread_share.map(v => 100 * v), marker: { color: C.accent }, hovertemplate: "%{y:.2f}% of updates", name: "spread" }],
         { showlegend: false, xaxis: axis("bid-ask spread (USDT)", { type: "category" }), yaxis: axis("% of updates") });
  }
}

/* ======================= Backtest views ======================= */
const BT = { day: null, rule: "through", fee: 0 };
const BT_COLORS = ["#cfd8dc", "#90a4ae", "#f5a524", "#7dd3fc", "#38bdf8", "#a78bfa"];
function drawBacktest() {
  const bar = document.getElementById("bt-bar");
  if (!D.backtest) { bar.innerHTML = '<p class="note">No backtest results yet. Run <span class="mono">python -m scripts.run_backtest</span>, then <span class="mono">python -m scripts.build_dashboard</span>.</p>'; return; }
  const runs = D.backtest.runs, dates = [...new Set(runs.map(r => r.date))];
  if (!BT.day) BT.day = dates[dates.length - 1];
  const btn = (attr, val, label, on) => `<button type="button" data-${attr}="${val}" aria-pressed="${on}">${label}</button>`;
  bar.innerHTML = '<span class="note">Day:</span>' + dates.map(d => btn("day", d, d, d === BT.day)).join("") +
    '<span class="note" style="margin-left:12px">Fills:</span>' + btn("rule", "through", "strictly through (pessimistic)", BT.rule === "through") + btn("rule", "touch", "at the price (optimistic)", BT.rule === "touch") +
    '<span class="note" style="margin-left:12px">Maker fee:</span>' + [0, 2, 10].map(f => btn("fee", f, f + " bp", BT.fee === f)).join("");
  bar.querySelectorAll("button").forEach(b => b.addEventListener("click", () => {
    if (b.dataset.day) BT.day = b.dataset.day; if (b.dataset.rule) BT.rule = b.dataset.rule; if (b.dataset.fee !== undefined) BT.fee = +b.dataset.fee;
    drawBacktest();
  }));
  const run = runs.find(r => r.date === BT.day && r.fill_rule === BT.rule), S = run.strategies;
  const net = st => st.summary.pnl + st.summary.fees - BT.fee / 1e4 * st.summary.notional_usdt;
  const best = S.reduce((a, b) => (net(b) > net(a) ? b : a));
  const asHi = S.find(st => st.name.includes("0.0001")), fx = S.find(st => st.name.includes("6.5"));
  const bp = S.map(st => st.summary.pnl_bps_of_volume);
  document.getElementById("bt-callout").innerHTML = `On ${BT.day}, <b>every strategy lost money</b>${BT.fee ? ` after a ${BT.fee} bp fee` : " before fees"}: between ${fmt(Math.min(...bp), 2)} and ${fmt(Math.max(...bp), 2)} bp per dollar traded. Fills are worth about zero at the moment of the fill and about ${fmt(S[2].summary.markout_60s_bp, 1)} bp a minute later, because quotes behind the best price are only reached by sweeps that keep going. ` +
    (asHi && fx ? `A-S with γ = 1e-4 still controls inventory: std <b>${fmt(asHi.summary.q_std, 1)}</b> lots vs ${fmt(fx.summary.q_std, 1)} for the fixed ±6.5 quoter. ` : "") + `Smallest loss: ${best.name} (${fmt(net(best), 0)} USDT).`;

  const cols = [["Strategy", st => st.name], ["P&L", st => fmt(st.summary.pnl, 0)], [`Net @ ${BT.fee} bp`, st => fmt(net(st), 0)],
    ["Spread capture", st => fmt(st.summary.spread_capture, 0)], ["Inventory P&L", st => fmt(st.summary.inventory_pnl, 0)],
    ["Fills / hour", st => fmt(st.summary.fills_per_hour, 0)], ["Volume ($M)", st => fmt(st.summary.notional_usdt / 1e6, 2)],
    ["bp of volume", st => fmt(st.summary.pnl_bps_of_volume, 2)], ["Markout 60 s", st => fmt(st.summary.markout_60s_bp, 2)],
    ["Adverse sel. (bp)", st => fmt(st.summary.adverse_selection_bp, 2)], ["Inventory std", st => fmt(st.summary.q_std, 2)], ["Max drawdown", st => fmt(st.summary.max_drawdown, 0)]];
  document.getElementById("bt-table").innerHTML = "<thead><tr>" + cols.map(c => `<th scope="col">${c[0]}</th>`).join("") + "</tr></thead><tbody>" +
    S.map((st, i) => `<tr><td style="font-family:var(--font-body)"><span class="sw" style="--c:${BT_COLORS[i]}"></span> ${st.name}</td>` + cols.slice(1).map(c => `<td>${c[1](st)}</td>`).join("") + "</tr>").join("") + "</tbody>";

  plot("ch-bt-pnl", S.map((st, i) => ({ x: st.minute.t, y: st.minute.pnl, name: st.name, mode: "lines", line: { color: BT_COLORS[i], width: st.name.startsWith("A-S") ? 2 : 1.4 }, hovertemplate: "%{y:,.0f}" })),
       { xaxis: axis("UTC", { type: "date" }), yaxis: axis("USDT"), legend: { orientation: "h", x: 0, y: 1.02, yanchor: "bottom", font: { size: 10 } } });
  plot("ch-bt-attr", [
    { type: "bar", orientation: "h", y: S.map(st => st.name), x: S.map(st => st.summary.spread_capture), name: "spread capture", marker: { color: C.bid }, hovertemplate: "%{x:,.0f}" },
    { type: "bar", orientation: "h", y: S.map(st => st.name), x: S.map(st => st.summary.inventory_pnl), name: "inventory P&L", marker: { color: C.ask }, hovertemplate: "%{x:,.0f}" },
    { type: "bar", orientation: "h", y: S.map(st => st.name), x: S.map(st => -(BT.fee / 1e4 * st.summary.notional_usdt)), name: `fees @ ${BT.fee} bp`, marker: { color: C.muted }, hovertemplate: "%{x:,.0f}", visible: BT.fee ? true : "legendonly" },
  ], { barmode: "group", hovermode: "y unified", margin: { l: 150, r: 16, t: 10, b: 44 }, xaxis: axis("USDT", { zeroline: true, zerolinecolor: C.muted }), yaxis: axis("", { autorange: "reversed" }) });
  plot("ch-bt-mk", S.map((st, i) => ({ x: st.markouts.h_s.map(h => Math.max(h, 0.3)), y: st.markouts.bp, name: st.name, mode: "lines+markers", line: { color: BT_COLORS[i] }, marker: { size: 5 },
       customdata: st.markouts.h_s, hovertemplate: "%{customdata} s: %{y:.2f} bp" })),
       { hovermode: "closest", xaxis: axis("seconds after fill (0 shown at 0.3)", { type: "log" }), yaxis: axis("markout (bp)", { zeroline: true, zerolinecolor: C.muted }), showlegend: false });
  const lv = []; for (let v = -10; v <= 10; v++) lv.push(v);
  plot("ch-bt-inv", S.map((st, i) => { const q = st.minute.q.filter(v => v !== null), n = q.length;
       return { type: "bar", x: lv, y: lv.map(v => 100 * q.filter(x => x === v).length / n), name: st.name, marker: { color: BT_COLORS[i] }, hovertemplate: "q=%{x}: %{y:.1f}%" }; }),
       { barmode: "group", bargap: 0.15, hovermode: "closest", xaxis: axis("inventory (lots of 0.001 BTC)", { dtick: 2 }), yaxis: axis("% of time"), showlegend: false });
}

/* ======================= Universe views ======================= */
const TIER_C = { large: "#e2e8f0", mid: "#38bdf8", small: "#34d399", micro: "#f87171" };
const UNI = { rule: "through", fee: 0, strat: "Join touch", coin: null, sort: null, asc: false };
function drawUniverse() {
  const U = D.universe, bar = document.getElementById("uni-bar");
  if (!U) { bar.innerHTML = '<p class="note">No universe results yet. Run <span class="mono">python -m scripts.download_universe</span> and <span class="mono">python -m scripts.run_universe</span>.</p>'; return; }
  const coins = U.coins, btn = (a, v, l, on) => `<button type="button" data-${a}="${v}" aria-pressed="${on}">${l}</button>`;
  bar.innerHTML = '<span class="note">Fills:</span>' + btn("rule", "through", "strictly through (pessimistic)", UNI.rule === "through") + btn("rule", "touch", "at the price (first in queue)", UNI.rule === "touch") +
    '<span class="note" style="margin-left:12px">Maker fee:</span>' + [0, 2, 10].map(f => btn("fee", f, f + " bp", UNI.fee === f)).join("") +
    '<span style="margin-left:12px" class="note">Tiers:</span>' + Object.entries(TIER_C).map(([t, c]) => `<span class="tier" style="--c:${c}">${t}</span>`).join(" ");
  bar.querySelectorAll("button").forEach(b => b.addEventListener("click", () => { if (b.dataset.rule) UNI.rule = b.dataset.rule; if (b.dataset.fee !== undefined) UNI.fee = +b.dataset.fee; drawUniverse(); }));
  const net = sm => sm.pnl + sm.fees - UNI.fee / 1e4 * sm.notional_usdt;
  const runsOf = c => c.runs.filter(r => r.fill_rule === UNI.rule);
  const bestOf = c => runsOf(c).reduce((a, b) => (net(b.summary) > net(a.summary) ? b : a));
  const rows = coins.map(c => { const cal = c.calibration[0], b = bestOf(c);
    return { c, cal, b, sym: c.symbol.replace("USDT", ""), tier: c.tier, vol: cal.usd_volume_day, tick: cal.tick_bp, spread: cal.spread_bp, ticks: cal.spread_ticks,
             sigma: cal.sigma_bp, k: cal.k_bp, r2: cal.r2, invk: cal.half_spread_1_over_k_bp, best: b.name, pnl: net(b.summary), bp: b.summary.pnl_bps_of_volume - UNI.fee,
             mk: b.summary.markout_60s_bp, t: b.summary.markout_60s_tstat, fills: b.summary.fills }; });
  const pos = rows.filter(r => r.pnl > 0 && Math.abs(r.t) >= 2 && r.mk > 0);
  document.getElementById("uni-callout").innerHTML = `With ${UNI.rule === "through" ? "strict" : "first-in-queue"} fills and a ${UNI.fee} bp fee, <b>${rows.filter(r => r.pnl > 0).length} of ${rows.length}</b> coins have a strategy that made money on the out-of-sample day, and <b>${pos.length}</b> of those also have positive 60-second markouts that are statistically meaningful (|t| ≥ 2)` + (pos.length ? `: ${pos.map(r => r.sym).join(", ")}` : "") +
    `. Large and mid caps lose to adverse selection; the only robust edges are on tick-constrained micro caps, where the spread is 10–30 bp and queue position decides the outcome. These are single-day results on a few hundred fills.`;
  const cols = [["sym", "Coin"], ["tier", "Tier"], ["vol", "USD vol / day"], ["tick", "Tick (bp)"], ["spread", "Spread (bp)"], ["ticks", "Spread (ticks)"], ["sigma", "σ (bp/√s)"],
    ["k", "k (per bp)"], ["r2", "Fit R²"], ["invk", "1/k (bp)"], ["best", "Best strategy"], ["pnl", "Net P&L ($/day)"], ["bp", "Net bp of volume"], ["mk", "Markout 60 s"], ["t", "t-stat"], ["fills", "Fills"]];
  if (UNI.sort) rows.sort((a, b) => { const x = a[UNI.sort], y = b[UNI.sort]; return (typeof x === "string" ? x.localeCompare(y) : (x ?? -1e18) - (y ?? -1e18)) * (UNI.asc ? 1 : -1); });
  const cell = (r, k) => k === "tier" ? `<span class="tier" style="--c:${TIER_C[r.tier]}">${r.tier}</span>` : k === "sym" ? r.sym : k === "best" ? r.best :
    k === "vol" ? "$" + fmt(r.vol / 1e6, 1) + "M" : k === "fills" ? fmt(r.fills, 0) : k === "ticks" ? fmt(r.ticks, 0) : k === "pnl" ? fmt(r.pnl, 1) :
    k === "r2" || k === "k" ? fmt(r[k], 3) : (k === "tick" || k === "spread") && r[k] < 0.1 ? fmtP(r[k]) : fmt(r[k], 2);
  const tbl = document.getElementById("uni-table");
  tbl.innerHTML = "<thead><tr>" + cols.map(c => `<th scope="col" class="sortable" data-k="${c[0]}">${c[1]}${UNI.sort === c[0] ? (UNI.asc ? " ▲" : " ▼") : ""}</th>`).join("") + "</tr></thead><tbody>" +
    rows.map(r => "<tr>" + cols.map(c => `<td${c[0] === "pnl" ? ` style="color:${r.pnl > 0 ? "var(--good)" : "var(--ask)"}"` : ""}>${cell(r, c[0])}</td>`).join("") + "</tr>").join("") + "</tbody>";
  tbl.querySelectorAll("th").forEach(th => th.addEventListener("click", () => { const k = th.dataset.k; UNI.asc = UNI.sort === k ? !UNI.asc : false; UNI.sort = k; drawUniverse(); }));

  const strats = [...new Set(coins.flatMap(c => c.runs.map(r => r.name.replace(" (k from spread)", ""))))];
  const ss = document.getElementById("uni-strat");
  ss.innerHTML = strats.map(x => `<option ${x === UNI.strat ? "selected" : ""}>${x}</option>`).join("");
  ss.onchange = e => { UNI.strat = e.target.value; drawUniverse(); };
  const pts = coins.map(c => { const r = runsOf(c).find(x => x.name.replace(" (k from spread)", "") === UNI.strat); return r ? { c, r } : null; }).filter(Boolean);
  plot("ch-uni-scatter", Object.keys(TIER_C).map(t => { const p = pts.filter(x => x.c.tier === t);
    return { x: p.map(x => x.c.calibration[0].spread_bp), y: p.map(x => x.r.summary.pnl_bps_of_volume - UNI.fee), text: p.map(x => x.c.symbol.replace("USDT", "")), name: t,
             mode: "markers+text", textposition: "top center", textfont: { size: 10, color: C.muted }, marker: { color: TIER_C[t], size: 11, line: { color: C.bg || "#0a0f16", width: 1 } },
             customdata: p.map(x => x.r.summary.fills), hovertemplate: "%{text}: spread %{x:.2f} bp, %{y:.2f} bp of volume, %{customdata} fills<extra></extra>" }; }),
    { hovermode: "closest", xaxis: axis("typical spread (bp, log scale)", { type: "log" }), yaxis: axis("net P&L (bp of volume)", { zeroline: true, zerolinecolor: C.muted }) });

  plot("ch-uni-fill", coins.map((c, i) => { const f = c.calibration[0].fill_curve;
    return { x: f.delta_bp, y: f.lam.map(v => v > 0 ? v : null), name: c.symbol.replace("USDT", ""), mode: "lines", line: { color: TIER_C[c.tier], width: 1.6 },
             opacity: 0.85, visible: ["BTCUSDT", "SOLUSDT", "ARBUSDT", "ONEUSDT", "ANKRUSDT", "IOTXUSDT"].includes(c.symbol) ? true : "legendonly", hovertemplate: "%{x:.1f} bp: %{y:.2e}/s" }; }),
    { hovermode: "closest", xaxis: axis("δ, distance from mid (bp)", { range: [0, 120] }), yaxis: axis("fill intensity λ (per s, log)", { type: "log" }), legend: { orientation: "v", x: 1, y: 1, xanchor: "right", font: { size: 10 } } });

  if (!UNI.coin) UNI.coin = (coins.find(c => c.symbol === "ANKRUSDT") || coins[0]).symbol;
  const cs = document.getElementById("uni-coin");
  cs.innerHTML = coins.map(c => `<option ${c.symbol === UNI.coin ? "selected" : ""}>${c.symbol}</option>`).join("");
  cs.onchange = e => { UNI.coin = e.target.value; drawUniverse(); };
  const coin = coins.find(c => c.symbol === UNI.coin), R = runsOf(coin), pal = ["#cfd8dc", "#f5a524", "#38bdf8", "#a78bfa"];
  plot("ch-uni-pnl", R.map((r, i) => ({ x: r.pnl.t, y: r.pnl.v, name: r.name, mode: "lines", line: { color: pal[i % 4], width: 1.8 }, hovertemplate: "%{y:,.1f}" })),
       { xaxis: axis("UTC, day 2", { type: "date" }), yaxis: axis("P&L before fees (USD)"), legend: { orientation: "h", x: 0, y: 1.02, yanchor: "bottom", font: { size: 10 } } });
  const rm = coin.random_markouts;
  plot("ch-uni-mk", [...R.map((r, i) => ({ x: r.markouts.h_s.map(h => Math.max(h, 0.3)), y: r.markouts.bp, name: r.name, mode: "lines+markers", line: { color: pal[i % 4] }, marker: { size: 5 },
       customdata: r.markouts.h_s, hovertemplate: "%{customdata} s: %{y:.2f} bp" })),
       { x: rm.h_s.map(h => Math.max(h, 0.3)), y: rm.bp, name: "random entries", mode: "lines", line: { color: C.muted, dash: "dash", width: 2 }, customdata: rm.h_s, hovertemplate: "%{customdata} s: %{y:.2f} bp" }],
       { hovermode: "closest", xaxis: axis("seconds after fill (0 shown at 0.3)", { type: "log" }), yaxis: axis("markout (bp)", { zeroline: true, zerolinecolor: C.muted }), showlegend: false });
}

/* ======================= Informed traders views ======================= */
const INF = { rule: "through", fee: 0, coin: null };
const LEVERS = [
  ["Measure it", "done", "Markouts of every fill at 1 s to 5 min, against a random-entry baseline that sits at ~0 bp."],
  ["Avoid it", "done", "Kill switch: no quotes during volatility bursts or for 5 s after a sweep. Biggest single gain."],
  ["Predict and lean", "done", "Trade imbalance predicts the next 10 s on every coin; quotes shift toward the predicted move."],
  ["Price it", "next", "Explicit adverse-selection term in the spread; widen the side under pressure and after own fills."],
  ["Structure", "next", "Low or negative fees, fast cancels, queue priority, BTC and perp lead–lag signals, smaller size at the touch."],
];
function drawInformed() {
  const W = D.walkforward, bar = document.getElementById("inf-bar");
  document.getElementById("levers").innerHTML = LEVERS.map(l => `<div class="lever"><h3>${l[0]}<span class="status ${l[1]}">${l[1] === "done" ? "tested" : "next"}</span></h3><p>${l[2]}</p></div>`).join("");
  if (!W) { bar.innerHTML = '<p class="note">No walk-forward results yet. Run <span class="mono">python -m scripts.run_walkforward</span>.</p>'; return; }
  const btn = (a, v, l, on) => `<button type="button" data-${a}="${v}" aria-pressed="${on}">${l}</button>`;
  bar.innerHTML = '<span class="note">Fills:</span>' + btn("rule", "through", "strictly through (pessimistic)", INF.rule === "through") + btn("rule", "touch", "first in queue (3 strategies)", INF.rule === "touch") +
    '<span class="note" style="margin-left:12px">Maker fee:</span>' + [0, 2, 10].map(f => btn("fee", f, f + " bp", INF.fee === f)).join("");
  bar.querySelectorAll("button").forEach(b => b.addEventListener("click", () => { if (b.dataset.rule) INF.rule = b.dataset.rule; if (b.dataset.fee !== undefined) INF.fee = +b.dataset.fee; drawInformed(); }));
  const A = W.aggregate.filter(r => r.fill_rule === INF.rule), order = W.meta.strategies.filter(n => A.some(r => r.strategy === n));
  const net = r => r.pnl_total - INF.fee / 1e4 * r.notional;
  const syms = [...new Set(W.aggregate.map(r => r.symbol))];
  const baseRule = W.aggregate.filter(r => r.fill_rule === "through" && r.strategy === "A-S (tail k)");
  const tot = order.map(n => { const rs = A.filter(r => r.strategy === n), notional = rs.reduce((x, r) => x + r.notional, 0), pnl = rs.reduce((x, r) => x + net(r), 0);
    const improves = rs.filter(r => { const b = baseRule.find(x => x.symbol === r.symbol); return b && net(r) > net(b); }).length;
    return { n, pnl, bp: pnl / notional * 1e4, fills: rs.reduce((x, r) => x + r.fills, 0), paused: rs.reduce((x, r) => x + r.paused_share, 0) / rs.length,
             pos: rs.filter(r => net(r) > 0).length, improves, coins: rs.length }; });
  const base = tot.find(t => t.n === "A-S (tail k)"), best = tot.reduce((a, b) => (b.pnl > a.pnl ? b : a));
  document.getElementById("inf-callout").innerHTML = base ? `Best here: <b>${best.n}</b>, ${fmt(best.pnl, 0)} USD vs ${fmt(base.pnl, 0)} for the Day-8 calibration (${fmt(100 * (1 - best.pnl / base.pnl), 0)}% smaller loss), and it beats that baseline on ${best.improves} of ${best.coins} coins. ` +
    `Per dollar traded the gain is smaller (${fmt(best.bp, 2)} vs ${fmt(base.bp, 2)} bp): most of it comes from not trading in the worst moments. The defences cut the damage; they do not create an edge on their own. A better-fitting fill curve (core k) made results worse, because A-S counts fills but cannot tell good fills from toxic ones.`
    : `With first-in-queue fills, tick-constrained micro caps (ANKR, SKL) turn clearly positive with join-touch quoting: queue priority is the edge there.`;
  const cols = [["Strategy", t => t.n], ["Net P&L (USD)", t => fmt(t.pnl, 0)], ["bp of volume", t => fmt(t.bp, 2)], ["Fills", t => fmt(t.fills, 0)],
                ["Time paused", t => fmt(100 * t.paused, 0) + "%"], ["Coins in profit", t => `${t.pos} / ${t.coins}`], ["Beats Day-8 A-S", t => `${t.improves} / ${t.coins}`]];
  document.getElementById("inf-table").innerHTML = "<thead><tr>" + cols.map(c => `<th scope="col">${c[0]}</th>`).join("") + "</tr></thead><tbody>" +
    tot.map(t => `<tr${t === best ? ' style="background:rgba(56,189,248,.08)"' : ""}><td style="font-family:var(--font-body)">${t.n}</td>` + cols.slice(1).map(c => `<td>${c[1](t)}</td>`).join("") + "</tr>").join("") + "</tbody>";

  const z = syms.map(sy => order.map(n => { const r = A.find(x => x.symbol === sy && x.strategy === n); return r ? net(r) / r.notional * 1e4 : null; }));
  const zu = syms.map(sy => order.map(n => { const r = A.find(x => x.symbol === sy && x.strategy === n); return r ? net(r) : null; }));
  const lim = 20;
  plot("ch-inf-heat", [{ type: "heatmap", z, x: order, y: syms.map(x => x.replace("USDT", "")), customdata: zu, zmin: -lim, zmax: lim, zmid: 0,
    colorscale: [[0, "#7f1d1d"], [0.45, "#3b1d24"], [0.5, "#142030"], [0.55, "#123b2c"], [1, "#16a34a"]],
    text: z.map(r => r.map(v => v === null ? "" : v.toFixed(1))), texttemplate: "%{text}", textfont: { family: MONO, size: 10, color: C.text },
    hovertemplate: "%{y} · %{x}<br>%{z:.2f} bp of volume<br>%{customdata:,.0f} USD<extra></extra>", colorbar: { title: { text: "bp", font: { size: 11 } }, tickfont: { family: MONO, size: 10, color: C.muted } } }],
    { showlegend: false, hovermode: "closest", margin: { l: 56, r: 16, t: 10, b: 110 }, xaxis: axis("", { tickangle: -35, showgrid: false }), yaxis: axis("", { autorange: "reversed", showgrid: false }) });

  const al = syms.map(sy => { const c = W.coins.find(x => x.symbol === sy), rs = c ? c.alpha : [];
    const avg = k => rs.reduce((x, r) => x + (r[k] ?? 0), 0) / Math.max(rs.length, 1);
    return { sy, tier: c ? c.tier : "", corr: avg("corr"), hit: avg("hit_rate"), t: avg("t_imb_5s") }; });
  plot("ch-inf-alpha", [
    { type: "bar", x: al.map(a => a.sy.replace("USDT", "")), y: al.map(a => a.corr), name: "out-of-sample correlation", marker: { color: al.map(a => TIER_C[a.tier] || C.accent) }, hovertemplate: "corr %{y:.3f}", yaxis: "y" },
    { x: al.map(a => a.sy.replace("USDT", "")), y: al.map(a => 100 * a.hit), name: "direction right (%)", mode: "markers", marker: { color: C.bench, size: 10, symbol: "diamond" }, hovertemplate: "%{y:.1f}% right", yaxis: "y2" },
  ], { hovermode: "x unified", yaxis: axis("correlation", { rangemode: "tozero" }), yaxis2: axis("direction right (%)", { overlaying: "y", side: "right", range: [45, 70], showgrid: false }),
       xaxis: axis(""), shapes: [{ type: "line", xref: "paper", x0: 0, x1: 1, yref: "y2", y0: 50, y1: 50, line: { color: C.muted, dash: "dot", width: 1 } }] });

  if (!INF.coin) INF.coin = "NEARUSDT";
  const cs = document.getElementById("inf-coin");
  cs.innerHTML = syms.map(x => `<option ${x === INF.coin ? "selected" : ""}>${x}</option>`).join("");
  cs.onchange = e => { INF.coin = e.target.value; drawInformed(); };
  const coin = W.coins.find(c => c.symbol === INF.coin), pal = { "A-S (tail k)": "#94a3b8", "A-S (core k)": "#64748b", "+ lean": "#7dd3fc", "+ kill switch": "#f5a524",
    "+ lean + kill": "#fbbf24", "Tail k + lean + kill": "#34d399", "Join touch": "#f87171", "Join + lean + kill": "#38bdf8" };
  const traces = [], dates = W.meta.test_dates;
  for (const n of order) { const cur = coin.curves[`${n}|${INF.rule}`]; if (!cur) continue;
    let off = 0; const x = [], y = [];
    cur.forEach((d, di) => { d.t_s.forEach((t, k) => { x.push(di * 24 + t / 3600); y.push(off + d.pnl[k]); }); off += d.pnl[d.pnl.length - 1]; });
    traces.push({ x, y, name: n, mode: "lines", line: { color: pal[n] || C.text, width: n.includes("lean + kill") ? 2.4 : 1.4 }, hovertemplate: "%{y:,.1f}" }); }
  plot("ch-inf-curve", traces, { xaxis: axis("hours from the start of the first test day", { dtick: 24 }), yaxis: axis("cumulative P&L (USD)"),
    shapes: dates.slice(1).map((d, i) => ({ type: "line", x0: (i + 1) * 24, x1: (i + 1) * 24, yref: "paper", y0: 0, y1: 1, line: { color: C.line, dash: "dot", width: 1 } })),
    legend: { orientation: "h", x: 0, y: 1.02, yanchor: "bottom", font: { size: 10 } } });
}

/* ======================= Tuning & signals views ======================= */
const TUN = { model: "as", metric: "pnl" };
function drawTuning() {
  const S = D.sweep, L = D.leadlag, B = D.book;
  if (!S) { document.getElementById("tun-callout").innerHTML = 'No sweep results yet. Run <span class="mono">python -m scripts.run_sweep</span>.'; return; }
  const H = S.heat, kills = ["off", "loose", "medium", "tight"], skews = S.meta.skew_mult;
  const best = H.reduce((a, b) => (b.pnl > a.pnl ? b : a)), worst = H.reduce((a, b) => (b.pnl < a.pnl ? b : a));
  const T = S.tuning_totals_days_2_4;
  document.getElementById("tun-callout").innerHTML = `Best setting: <b>${best.model === "as" ? "A-S" : "GLFT"}, ${best.skew_mult}× skew, ${best.kill} kill switch</b> at ${fmt(best.pnl, 0)} USD over 48 coin-days, against ${fmt(worst.pnl, 0)} for the worst. ` +
    `Tuning on past days only cut losses from ${fmt(T.default, 0)} to ${fmt(T.tuned_pooled, 0)} on the last 3 test days (hindsight: ${fmt(T.hindsight_best, 0)}). ` +
    `Every setting still loses 3–7 bp per dollar traded: the tools get the strategy out of the way of informed flow, they do not create an edge.`;
  const ctl = document.getElementById("tun-ctl"), btn = (a, v, l, on) => `<button type="button" data-${a}="${v}" aria-pressed="${on}">${l}</button>`;
  ctl.innerHTML = btn("model", "as", "A-S", TUN.model === "as") + btn("model", "glft", "GLFT", TUN.model === "glft") + btn("metric", "pnl", "USD", TUN.metric === "pnl") + btn("metric", "bp", "bp / $", TUN.metric === "bp");
  ctl.querySelectorAll("button").forEach(b => b.addEventListener("click", () => { if (b.dataset.model) TUN.model = b.dataset.model; if (b.dataset.metric) TUN.metric = b.dataset.metric; drawTuning(); }));
  const z = skews.map(m => kills.map(k => { const r = H.find(x => x.model === TUN.model && x.skew_mult === m && x.kill === k); return r ? r[TUN.metric] : null; }));
  const paused = kills.map(k => { const r = H.find(x => x.kill === k); return r ? Math.round(100 * r.paused) : 0; });
  const all = H.map(r => r[TUN.metric]), lo = Math.min(...all), hi = Math.max(...all);
  plot("ch-tun-heat", [{ type: "heatmap", z, x: kills.map((k, i) => `${k} (${paused[i]}% paused)`), y: skews.map(m => m + "×"), zmin: lo, zmax: hi,
    colorscale: [[0, "#7f1d1d"], [0.5, "#a16207"], [1, "#15803d"]], text: z.map(r => r.map(v => TUN.metric === "pnl" ? fmt(v, 0) : fmt(v, 2))), texttemplate: "%{text}",
    textfont: { family: MONO, size: 12, color: C.text }, hovertemplate: "skew %{y}, kill %{x}: %{z:.2f}<extra></extra>", showscale: false }],
    { showlegend: false, hovermode: "closest", xaxis: axis("kill switch"), yaxis: axis("inventory skew") });
  const tk = [["default", "Default"], ["tuned_per_coin", "Tuned<br>per coin"], ["tuned_pooled", "Tuned on<br>all coins"], ["hindsight_best", "Hindsight<br>(not achievable)"]];
  plot("ch-tun-tune", [{ type: "bar", x: tk.map(t => t[1]), y: tk.map(t => T[t[0]]), marker: { color: ["#94a3b8", "#38bdf8", "#34d399", "#475569"] },
    text: tk.map(t => fmt(T[t[0]], 0)), textposition: "inside", insidetextanchor: "end", textfont: { family: MONO, color: "#0a0f16" }, hovertemplate: "%{y:,.0f} USD<extra></extra>" }],
    { showlegend: false, xaxis: axis("", { tickangle: 0 }), yaxis: axis("P&L, test days 2–4 (USD)") });
  const sens = S.sensitivity, rq = sens.filter(r => r.latency_ms === 50).sort((a, b) => a.requote_ms - b.requote_ms), lt = sens.filter(r => r.requote_ms === 500).sort((a, b) => a.latency_ms - b.latency_ms);
  plot("ch-tun-speed", [
    { x: rq.map(r => r.requote_ms), y: rq.map(r => r.bp), name: "requote interval (latency 50 ms)", mode: "lines+markers", line: { color: C.accent }, hovertemplate: "%{x} ms: %{y:.2f} bp" },
    { x: lt.map(r => r.latency_ms), y: lt.map(r => r.bp), name: "latency (requote 500 ms)", mode: "lines+markers", line: { color: C.bench }, hovertemplate: "%{x} ms: %{y:.2f} bp" },
  ], { hovermode: "closest", xaxis: axis("milliseconds (log)", { type: "log" }), yaxis: axis("P&L per $ traded (bp)"),
       shapes: [{ type: "line", x0: 285, x1: 285, yref: "paper", y0: 0, y1: 1, line: { color: C.muted, dash: "dot" } }],
       annotations: [{ x: Math.log10(285), y: 1, yref: "paper", text: "your latency", showarrow: false, font: { size: 10, color: C.muted }, yanchor: "bottom" }] });
  if (L) { const P = L.prediction, syms = [...new Set(P.map(r => r.symbol))], fs = ["own", "+ BTC spot", "+ BTC perp", "+ both"], col = ["#94a3b8", "#38bdf8", "#f5a524", "#34d399"];
    plot("ch-tun-lead", fs.map((f, i) => ({ type: "bar", name: f, x: syms.map(x => x.replace("USDT", "")), y: syms.map(sy => { const r = P.find(x => x.symbol === sy && x.features === f); return r ? r.corr : null; }),
      marker: { color: col[i] }, hovertemplate: "%{y:.3f}" })), { barmode: "group", xaxis: axis(""), yaxis: axis("out-of-sample correlation") }); }
  if (B) { const pe = B.mid_proxy_error;
    document.getElementById("tun-book-sub").textContent = `${fmt(B.book_updates, 0)} best bid/ask updates and ${fmt(B.trades, 0)} trades over ${fmt(B.minutes, 0)} minutes. A small sample: treat as a first look.`;
    const tile = (k, v, sub) => `<div class="tile"><div class="k">${k}</div><div class="v">${v}</div><div class="s">${sub}</div></div>`;
    document.getElementById("tun-book-tiles").innerHTML = tile("Latency to your PC", fmt(B.latency_ms["50%"], 0) + " ms", `median; 95% under ${fmt(B.latency_ms["95%"], 0)} ms`) +
      tile("One-tick spread", fmt(100 * (B.spread_share["0.01"] || 0), 2) + "%", "of the time") +
      tile("Trade-based mid error", fmt(pe.mean_abs_bp, 3) + " bp", `average; 95th pct ${fmt(pe.p95_abs_bp, 2)} bp`) +
      tile("Off by > half a spread", fmt(100 * pe.share_beyond_half_spread, 0) + "%", "of 100 ms bars");
    const hs = Object.keys(B.predictive_corr).map(Number), pc = B.predictive_corr;
    plot("ch-tun-book-corr", [["book_imb", "book imbalance", "#34d399"], ["trade_imb_5s", "trade imbalance (5 s)", "#f5a524"], ["micro_dev_bp", "microprice − mid", "#a78bfa"]].map(([k, n, c]) =>
      ({ x: hs, y: hs.map(h => pc[h][k]), name: n, mode: "lines+markers", line: { color: c }, hovertemplate: "%{x} s: %{y:.3f}" })),
      { hovermode: "closest", xaxis: axis("seconds ahead"), yaxis: axis("correlation with the next move", { rangemode: "tozero" }) });
    const dec = B.imbalance_deciles;
    plot("ch-tun-book-dec", [{ type: "bar", x: dec.map(d => d.decile), y: dec.map(d => d.fwd_bp), marker: { color: dec.map(d => d.fwd_bp < 0 ? C.ask : C.bid) },
      customdata: dec.map(d => d.imb), hovertemplate: "decile %{x} (imbalance %{customdata:.2f}): %{y:.2f} bp<extra></extra>" }],
      { showlegend: false, hovermode: "closest", xaxis: axis("book-imbalance decile (0 = ask-heavy, 9 = bid-heavy)", { dtick: 1 }), yaxis: axis("mean next-5 s move (bp)", { zeroline: true, zerolinecolor: C.muted }) }); }
}

/* ======================= Header, about, routing ======================= */
function drawHeader() {
  const chips = [SITE.stage ? `<span class="chip">${esc(SITE.stage)}</span>` : `<span class="chip">Day <b>${SITE.dayOfPlan}</b> of ${SITE.planDays}</span>`];
  const nTests = SITE.testsPassed || (D && D.tests_passed);
  if (nTests) chips.push(`<span class="chip ok">${nTests} tests passing</span>`);
  chips.push('<span class="chip">Python · NumPy · pandas</span>');
  document.getElementById("chips").innerHTML = chips.join("");
  const hl = [];
  if (D) {
    const rows = D.replication.paper_table, a = rows.find(r => r.gamma === 0.1 && r.strategy === "inventory"), b = rows.find(r => r.gamma === 0.1 && r.strategy === "symmetric");
    hl.push(["Sharpe, A-S vs benchmark", `${fmt(a.mean_pnl / a.std_pnl, 1)} vs ${fmt(b.mean_pnl / b.std_pnl, 1)}`, "paper settings, 1,000 paths"]);
    hl.push(["Profit volatility cut", `−${fmt(100 * (1 - a.std_pnl / b.std_pnl), 0)}%`, `for −${fmt(100 * (1 - a.mean_pnl / b.mean_pnl), 0)}% mean profit`]);
    if (D.real_days.length) {
      const n = D.real_days.reduce((x, d) => x + d.summary.n_trades, 0), d0 = D.real_days.filter(d => d.symbol === "BTCUSDT").pop() || D.real_days[0];
      const nc = new Set(D.real_days.map(d => d.symbol)).size;
      hl.push(["Real trades analysed", fmt(n, 0), `Binance spot, ${nc} coin${nc > 1 ? "s" : ""}, ${D.real_days.length} coin-days`]);
      hl.push(["Fill model fit on BTC", `R² ${fmt(d0.fill_curve.r2, 3)}`, `λ(δ) = A·e^(−kδ), k = ${fmt(d0.fill_curve.k, 3)}/USDT`]);
    }
    if (D.backtest) {
      const all = D.backtest.runs.filter(r => r.fill_rule === "through").flatMap(r => r.strategies.map(st => st.summary));
      const bp = all.map(x => x.pnl_bps_of_volume), lo = Math.min(...bp), hi = Math.max(...bp);
      hl.push(["Real-data backtest, before fees", `${fmt(lo, 1)} to ${fmt(hi, 1)} bp`, "P&L per $ traded: adverse selection wins"]);
    }
  }
  document.getElementById("headline").innerHTML = hl.map(h => `<div class="hl"><div class="k">${h[0]}</div><div class="v">${h[1]}</div><div class="s">${h[2]}</div></div>`).join("");
  document.getElementById("roadmap").innerHTML = ROADMAP.map(r => `<li><span class="mono">${r[0]}</span><span class="status ${r[1]}">${r[1] === "done" ? "done" : r[1] === "next" ? "next" : "planned"}</span><span>${r[2]}</span></li>`).join("");
  const links = [];
  if (SITE.github) links.push(`Code: <a href="${SITE.github}">${SITE.github}</a>`);
  if (SITE.linkedin) links.push(`Author: <a href="${SITE.linkedin}">${SITE.author}</a>`);
  document.getElementById("links").innerHTML = links.join(" · ");
  document.getElementById("foot-author").textContent = SITE.author ? `Built by ${SITE.author}` : "";
  document.getElementById("foot-built").textContent = D ? `Data built ${D.built}` : "data.js not found: run python -m scripts.build_dashboard";
}

register("simulator", () => { drawKpis(); drawPath(); drawInv(); drawHist(); drawFan(); });
register("model", drawModel);
register("replication", () => D && drawReplication());
register("real-data", () => D && drawRealData());
register("backtest", () => D && drawBacktest());
register("universe", () => D && drawUniverse());
register("informed", () => D && drawInformed());
register("tuning", () => D && drawTuning());
register("about", () => {}, false);

syncControls();
document.getElementById("o-t").textContent = "0.00";
drawHeader();
SIM = simulateBoth(P, P.paths, P.seed);
