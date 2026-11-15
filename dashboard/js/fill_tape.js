/* fill_tape.js: the tape around one fill, used by the Execution test drill-down and the Story.
   Two panels, both in bp from the mid at the moment of the fill, so a glitch hundreds of bp away no longer flattens
   everything else into one line:
     left:  10 s either side of the fill (best bid and ask, the trades, our orders, the fill itself);
     right: the 5 minutes after it (the mid against the fill price, with the markout read off at 1, 5, 30, 60, 300 s).
   A markout is the gap between the mid and the dashed fill-price line; + means the mid moved our way. */
const TAPE_HORIZONS = [1, 5, 30, 60, 300];
const TAPE_NEAR_S = 10;

function tapeMidAt(touch, t) {
  let r = null;
  for (const row of touch) { if (row[0] <= t) r = row; else break; }
  r = r || touch[0];
  return r && isNum(r[1]) && isNum(r[2]) ? (r[1] + r[2]) / 2 : NaN;
}

/* Rows of `rows` (sorted by time in column 0) inside [a, b] ms, plus the last one before a so a step line starts at a. */
function tapeRowsIn(rows, a, b) {
  const out = [];
  let before = null;
  for (const r of rows) { if (r[0] < a) before = r; else if (r[0] <= b) out.push(r); }
  return before ? [before].concat(out) : out;
}

/* -> { data, layout, readout, offscale } for Plotly. `win` is a stored tape window, `fill` the fill (or null for an
   incident), `tRef` the time to centre on when there is no fill. */
function fillTapeFigure(win, fill, tRef, opts = {}) {
  const t0 = fill ? fill.t : tRef, near = opts.near || TAPE_NEAR_S;
  const after = Math.min(300, Math.max(near, (win.t1 - t0) / 1000));
  const T = win.touch || [];
  const mid0 = fill && isNum(fill.mid) ? fill.mid : tapeMidAt(T, t0);
  const bp = p => (p / mid0 - 1) * 1e4, sec = t => (t - t0) / 1000;
  const good = PROFIT, bad = LOSS;
  const data = [];
  const hov = name => `%{y:+.1f} bp · %{customdata}<extra>${name}</extra>`;

  // ---- left panel: the book around the fill
  const L = tapeRowsIn(T, t0 - near * 1000, t0 + near * 1000);
  const lx = L.map(r => Math.max(-near, sec(r[0])));
  data.push({ type: "scatter", mode: "lines", name: "best bid", x: lx, y: L.map(r => bp(r[1])), customdata: L.map(r => fmtP(r[1])),
              line: { color: BID_C, width: 1.5, shape: "hv" }, hovertemplate: hov("bid") });
  data.push({ type: "scatter", mode: "lines", name: "best ask", x: lx, y: L.map(r => bp(r[2])), customdata: L.map(r => fmtP(r[2])),
              line: { color: ASK_C, width: 1.5, shape: "hv" }, hovertemplate: hov("ask") });
  const tr = (win.trades || []).filter(r => Math.abs(sec(r[0])) <= near);
  if (tr.length) data.push({ type: "scatter", mode: "markers", name: "trades", x: tr.map(r => sec(r[0])), y: tr.map(r => bp(r[1])),
    customdata: tr.map(r => `${fmtP(r[1])} × ${r[2]} ${r[3] > 0 ? "buyer" : "seller"}-initiated`),
    marker: { size: 5, color: tr.map(r => r[3] > 0 ? BID_C : ASK_C), opacity: 0.75, line: { width: 0 } }, hovertemplate: hov("trade") });
  const endDash = { fill: "solid", cancel: "dot", reject: "dash", open: "solid" };
  let firstOrder = true;
  (win.orders || []).forEach(o => {
    const a = Math.max(-near, sec(o.t_place)), b = Math.min(near, sec(o.t_end));
    if (b < a) return;
    data.push({ type: "scatter", mode: "lines", name: "our orders", legendgroup: "orders", showlegend: firstOrder, x: [a, b], y: [bp(o.price), bp(o.price)],
      customdata: [`${o.side > 0 ? "buy" : "sell"} ${fmtP(o.price)}, ${o.end}`, `${o.side > 0 ? "buy" : "sell"} ${fmtP(o.price)}, ${o.end}`],
      line: { color: o.side > 0 ? BID_C : ASK_C, width: 4, dash: endDash[o.end] || "solid" }, opacity: o.end === "fill" ? 1 : 0.6, hovertemplate: hov("our order") });
    firstOrder = false;
  });
  const fillBp = fill ? bp(fill.price) : null;
  if (fill) data.push({ type: "scatter", mode: "markers", name: "our fill", x: [0], y: [fillBp], customdata: [`${fill.side > 0 ? "bought" : "sold"} at ${fmtP(fill.price)}`],
    marker: { symbol: "star", size: 16, color: fill.artifact ? ART_C : "#e2e8f0", line: { width: 1, color: "#0a0f16" } }, hovertemplate: hov("fill") });

  // ---- right panel: the mid after the fill, against the fill price
  // log time, like the markout chart above it: 1, 5, 30, 60 and 300 s sit evenly apart instead of piling up at 0
  const X0 = 0.5, R = tapeRowsIn(T, t0 + X0 * 1000, t0 + after * 1000);
  const rmid = R.map(r => (r[1] + r[2]) / 2);
  data.push({ type: "scatter", mode: "lines", name: "mid", xaxis: "x2", yaxis: "y2", x: R.map(r => Math.max(X0, sec(r[0]))), y: rmid.map(bp),
              customdata: rmid.map(fmtP), line: { color: "#cbd5e1", width: 1.5, shape: "hv" }, hovertemplate: hov("mid") });
  const mkPts = [], readout = [];
  if (fill) TAPE_HORIZONS.forEach(h => {
    const v = fill["mk_" + h];
    readout.push(`${h} s ${isNum(v) ? sign(v, 1) : "n/a"}`);
    if (!isNum(v) || h > after) return;
    mkPts.push({ h, v, y: bp(tapeMidAt(T, t0 + h * 1000)) });
  });
  if (fill && !fill.artifact) data.push({ type: "scatter", mode: "lines", name: "fill price", xaxis: "x2", yaxis: "y2", x: [X0, after], y: [fillBp, fillBp],
    customdata: [fmtP(fill.price), fmtP(fill.price)], line: { color: "#e2e8f0", width: 1, dash: "dash" }, hovertemplate: hov("fill price") });
  if (mkPts.length) data.push({ type: "scatter", mode: "markers+text", name: "markout", xaxis: "x2", yaxis: "y2", x: mkPts.map(p => p.h), y: mkPts.map(p => p.y),
    text: mkPts.map(p => `${p.h}s ${sign(p.v, 1)}`), textposition: mkPts.map((p, k) => k % 2 ? "bottom center" : "top center"),
    textfont: { size: 10, color: mkPts.map(p => p.v >= 0 ? good : bad) }, customdata: mkPts.map(p => `${sign(p.v, 1)} bp markout after ${p.h} s`),
    marker: { size: 9, color: mkPts.map(p => p.v >= 0 ? good : bad), line: { width: 1, color: "#0a0f16" } }, hovertemplate: hov("markout"), cliponaxis: false });

  // ---- y ranges: each panel fits its own data; a glitch fill stays on the left, never squashes the right
  const lv = L.flatMap(r => [bp(r[1]), bp(r[2])]).concat(tr.map(r => bp(r[1])));
  const lr = fitAxis(lv, [0].concat(fill ? [fillBp] : []));
  const rv = rmid.map(bp).concat(mkPts.map(p => p.y));
  const rr = fitAxis(rv, [0].concat(fill && !fill.artifact ? [fillBp] : []));
  const offscale = lr ? lv.filter(v => v < lr[0] || v > lr[1]).length : 0;

  const fixed = opts.fixed ? { fixedrange: true } : {};
  const yl = "bp from the mid at the fill";
  const lay = {
    hovermode: "closest", showlegend: true, legend: { orientation: "h", x: 0, y: 1.14, yanchor: "bottom", font: { size: 11 } },
    margin: { l: 64, r: 16, t: 56, b: 46 },
    xaxis: axis("seconds from the fill", Object.assign({ domain: [0, 0.44], range: [-near, near], zeroline: true, zerolinecolor: "#64748b" }, fixed)),
    yaxis: axis(yl, Object.assign(lr ? { range: lr } : {}, { zeroline: true, zerolinecolor: "#475569" }, fixed)),
    xaxis2: axis("seconds after the fill (log)", Object.assign({ domain: [0.54, 1], anchor: "y2", type: "log", range: [Math.log10(X0), Math.log10(after * 1.15)],
                 tickvals: TAPE_HORIZONS.filter(h => h <= after), ticktext: TAPE_HORIZONS.filter(h => h <= after).map(h => h + " s") }, fixed)),
    yaxis2: axis("", Object.assign({ anchor: "x2" }, rr ? { range: rr } : {}, { zeroline: true, zerolinecolor: "#475569" }, fixed)),
    annotations: [
      { xref: "paper", yref: "paper", x: 0, y: 1.0, xanchor: "left", yanchor: "bottom", showarrow: false, text: `<b>Around the fill</b> (±${near} s)`, font: { size: 11, color: "#cbd5e1" } },
      { xref: "paper", yref: "paper", x: 0.54, y: 1.0, xanchor: "left", yanchor: "bottom", showarrow: false, text: fill && !fill.artifact ? "<b>After the fill</b>: mid vs our price (dashed)" : "<b>After</b>: the mid", font: { size: 11, color: "#cbd5e1" } },
    ],
  };
  if (opts.narrow) {                       // phone width: stack the panels instead of squeezing them side by side
    Object.assign(lay.xaxis, { domain: [0, 1] }); Object.assign(lay.yaxis, { domain: [0.6, 0.94] });
    Object.assign(lay.xaxis2, { domain: [0, 1], tickangle: 0 }); Object.assign(lay.yaxis2, { domain: [0, 0.38], title: { text: yl, font: lay.yaxis.title.font } });
    lay.annotations[0].y = 0.95; lay.annotations[1].x = 0; lay.annotations[1].y = 0.39;
    lay.height = 620; lay.legend.y = 1.0;
  }
  if (fill && fill.artifact) lay.annotations.push({ xref: "paper", yref: "paper", x: 0.995, y: 0.02, xanchor: "right", yanchor: "bottom", showarrow: false,
    bgcolor: "rgba(16,24,35,.85)", text: opts.narrow ? `fill at ${sign(fillBp, 0)} bp: off scale` : `our fill at ${sign(fillBp, 0)} bp is off this scale: the mid never went there`,
    font: { size: 11, color: ART_C } });
  return { data, layout: lay, readout: fill ? `Markout in bp, + = the mid moved our way: ${readout.join(" · ")}.` : "", offscale };
}
