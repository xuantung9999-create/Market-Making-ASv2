/* lv_pnl.js: P&L tab. Attribution waterfall, attribution over time, per-day table, worst and best fills. */

const TERMS = [["edge", "Edge"], ["adverse", "Adverse selection"], ["carry", "Carry"], ["fees", "Fees (estimated)"], ["artifact", "Artifact"]];
const TERM_COLOR = { edge: "#e2e8f0", adverse: "#f472b6", carry: "#2dd4bf", fees: "#94a3b8", artifact: ART_C };

function fillScore(f) { return isNum(f.edge_bp) ? f.edge_bp + (isNum(f.mk_60) ? f.mk_60 : 0) : null; }
function openFill(b, f) { if (typeof Tape !== "undefined") Tape.open(b.meta.id, f.t, f.i); }

function drawLvPnl() {
  const b = Sess.one();
  if (!b) { ["lvp-waterfall", "lvp-time", "lvp-days", "lvp-worst", "lvp-best"].forEach(lvWaiting); return; }
  const s = sumRange(b), tk = b.takeaways;
  if (!b.fills.length) {
    ["lvp-waterfall", "lvp-time", "lvp-days", "lvp-worst", "lvp-best"].forEach(id => lvEmpty(id, `No fills yet in ${b.meta.id}, so there is nothing to attribute. ${tk.cum_pnl}`));
    ["lvp-wf-sub", "lvp-time-sub", "lvp-days-sub", "lvp-worst-sub"].forEach(id => setSub(id, tk.waterfall)); return;
  }
  // ---- waterfall (stacked bars with an invisible base so every bar can have its own colour)
  const notional = s.notional || b.attribution.total.notional || 1;
  let run = 0; const names = [], base = [], len = [], col = [], txt = [];
  TERMS.forEach(([k, label]) => {
    const v = s[k] || 0;
    names.push(label); base.push(Math.min(run, run + v)); len.push(Math.abs(v)); run += v;
    col.push(k === "artifact" ? ART_C : v >= 0 ? PROFIT : LOSS);
    txt.push(`${sign(v)} USDT<br>${sign(v / notional * 1e4, 1)} bp`);
  });
  names.push("Net"); base.push(Math.min(0, s.net)); len.push(Math.abs(s.net)); col.push(s.net >= 0 ? PROFIT : LOSS);
  txt.push(`${sign(s.net)} USDT<br>${sign(s.net / notional * 1e4, 1)} bp`);
  setSub("lvp-wf-sub", tk.waterfall);
  deskPlot("lvp-waterfall", [
    { type: "bar", x: names, y: base, marker: { color: "rgba(0,0,0,0)" }, hoverinfo: "skip", showlegend: false },
    { type: "bar", x: names, y: len, marker: { color: col }, text: txt, textposition: "outside", cliponaxis: false, hoverinfo: "text", showlegend: false },
  ], { barmode: "stack", showlegend: false, yaxis: axis("USDT", { zeroline: true, zerolinewidth: 1.5, zerolinecolor: "#94a3b8" }), xaxis: axis(""), margin: { l: 56, r: 16, t: 28, b: 40 } });
  const th = b.meta.thresholds;
  $("lvp-thresholds").textContent = `Artifact fill: more than max(${th.artifact_bp} bp, ${th.artifact_spread_mult} × the median spread of the previous ${th.spread_window_s / 60} min) from the mid. ` +
    `Artifact jump: the mid moves more than ${th.jump_bp} bp between two book updates less than ${th.jump_gap_s} s apart. Adverse selection looks ${th.adverse_s} s ahead. Fees are estimated at ${b.meta.fee_bps} bp.`;

  // ---- attribution over time
  const w = Sess.windowOf(b);
  const spanH = b.attribution.by_hour.length;
  const useDay = spanH > 72 || (!w && spanH > 72);
  const rows = (useDay ? b.attribution.by_day.map(r => ({ ...r, t: Date.parse(r.date + "T00:00:00Z") })) : b.attribution.by_hour).filter(r => !w || (r.t + (useDay ? 864e5 : 36e5) > w[0] && r.t <= w[1]));
  setSub("lvp-time-sub", tk.attr_time + (useDay ? " (per day)" : " (per hour)"));
  if (!rows.length) lvEmpty("lvp-time", "No fills in this range.");
  else {
    const tr = TERMS.map(([k, label]) => ({ type: "bar", name: label, x: rows.map(r => isoT(r.t)), y: rows.map(r => r[k]), marker: { color: TERM_COLOR[k] } }));
    tr.push({ type: "scatter", mode: "lines+markers", name: "net", x: rows.map(r => isoT(r.t)), y: rows.map(r => r.net), line: { color: "#dbe6f2", width: 1.5, dash: "dot" }, marker: { size: 4 } });
    deskPlot("lvp-time", tr, { barmode: "relative", yaxis: axis("USDT", { zeroline: true, zerolinewidth: 1.5, zerolinecolor: "#94a3b8" }), xaxis: axis("", { type: "date" }) });
  }

  // ---- per-day table
  setSub("lvp-days-sub", tk.day_table);
  lvTable("lvp-days", [
    { k: "date", label: "Day (UTC)", left: true }, { k: "fills", label: "Fills", f: v => nTxt(v) }, { k: "notional", label: "Notional", f: v => nTxt(v) },
    ...TERMS.map(([k, label]) => ({ k, label: label.replace(" (estimated)", ""), f: v => usdTxt(v) })),
    { k: "net", label: "Net", f: v => `<b class="${pnlCls(v)}">${usdTxt(v)}</b>` },
    { k: "loss_stop", label: "Loss stop", left: true, v: r => r.loss_stop ? 1 : 0, f: (v, r) => r.loss_stop ? '<span class="flag-on">yes</span>' : "no" },
  ], b.attribution.by_day.slice().reverse(), { sort: "date" });

  // ---- worst and best 20
  const fl = b.fills.filter(f => Sess.inWin(b, f.t) && fillScore(f) !== null).map(f => ({ ...f, score: fillScore(f) }));
  const cols = [
    { k: "t", label: "Time (UTC)", left: true, f: v => utcStamp(v) }, { k: "side", label: "Side", left: true, f: v => v > 0 ? "buy" : "sell" },
    { k: "price", label: "Price", f: v => fmtP(v) }, { k: "mid", label: "Mid", f: v => fmtP(v) }, { k: "edge_bp", label: "Edge bp", f: bpTxt },
    { k: "mk_60", label: "60 s bp", f: bpTxt }, { k: "score", label: "Edge + 60 s", f: bpTxt }, { k: "lots_after", label: "Lots", f: v => nTxt(v) },
    { k: "artifact", label: "", left: true, v: r => r.artifact ? 1 : 0, f: (v, r) => r.artifact ? '<span class="dot-art"></span>artifact' : "" },
  ];
  const opt = o => ({ ...o, rowClass: r => r.artifact ? "art" : "", onClick: f => openFill(b, f), empty: "No fills with a markout in this range." });
  const worst = fl.slice().sort((x, y) => x.score - y.score).slice(0, 20), best = fl.slice().sort((x, y) => y.score - x.score).slice(0, 20);
  setSub("lvp-worst-sub", tk.worst_fills + " Artifact rows are tinted purple; click a row to open the tape.");
  $("lvp-worst")._sort = $("lvp-worst")._sort || { k: "score", dir: 1 };      // worst first
  lvTable("lvp-worst", cols, worst, opt({ sort: "score" }));
  $("lvp-best")._sort = $("lvp-best")._sort || { k: "score", dir: -1 };       // best first
  lvTable("lvp-best", cols, best, opt({ sort: "score" }));
}

register("lv-pnl", drawLvPnl);
