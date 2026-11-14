/* lv_exec.js: Execution tab and the tape drill-down (live spec section 7, L7 and L8). */

const FillsUI = { page: 0, side: "all", art: "all", sort: "t", dir: -1, per: 50 };
const HORIZONS = [1, 5, 30, 60, 300];

/* ----------------------------------------------------------------- tape drill-down */
const Tape = {
  pending: null,
  /* Open the tape around a fill (index) or an incident time on the Execution tab. */
  open(sid, tms, fillI) {
    Tape.pending = { sid, t: tms, i: fillI };
    Sess.select(sid);
    if (location.hash === "#l-exec") { markDirty("lv-exec"); drawTape(); } else location.hash = "#l-exec";
  },
  close() { Tape.pending = null; $("lvx-tape-card").hidden = true; },
};
function dayOfMs(ms) { return new Date(ms).toISOString().slice(0, 10); }

function drawTape() {
  const req = Tape.pending, card = $("lvx-tape-card");
  if (!req) { card.hidden = true; return; }
  card.hidden = false;
  const b = (window.SESSION_DATA || {})[req.sid];
  const fill = b && req.i !== null && req.i !== undefined ? b.fills.find(f => f.i === req.i) : null;
  const inc = b ? b.incidents.find(i => Math.abs(i.t0 - req.t) < 1500) : null;
  setSub("lvx-tape-sub", "Loading the tape…");
  const key = `${req.sid}|${dayOfMs(req.t)}`;
  const go = () => paintTape(b, req, fill, inc, (window.TAPES || {})[key]);
  if ((window.TAPES || {})[key]) return go();
  const src = `live/tape-${req.sid}-${dayOfMs(req.t)}.js`;
  const s = document.createElement("script");
  s.src = src + "?t=" + Date.now(); s.onload = go;
  s.onerror = () => paintTape(b, req, fill, inc, null);
  document.head.appendChild(s);
}

function paintTape(b, req, fill, inc, tape) {
  const el = $("lvx-tape");
  const caption = fill && fill.caption ? fill.caption : inc ? inc.sentence : "";
  const win = tape && tape.windows.find(w => req.t >= w.t0 && req.t <= w.t1);
  if (!win) {
    setSub("lvx-tape-sub", caption);
    lvEmpty("lvx-tape", (tape && tape.note) ? tape.note : `No tape is stored around ${utcStamp(req.t)}: the file for that day is missing, or the event is outside the windows kept (60 s before to 300 s after each fill or incident).`);
    return;
  }
  setSub("lvx-tape-sub", caption + (tape.note ? " " + tape.note : ""));
  const T = win.touch, tr = [];
  const x = T.map(r => isoT(r[0]));
  tr.push({ type: "scatter", mode: "lines", name: "best bid", x, y: T.map(r => r[1]), line: { color: BID_C, width: 1.5, shape: "hv" }, hovertemplate: "%{y}<extra>bid</extra>" });
  tr.push({ type: "scatter", mode: "lines", name: "best ask", x, y: T.map(r => r[2]), line: { color: ASK_C, width: 1.5, shape: "hv" }, hovertemplate: "%{y}<extra>ask</extra>" });
  if (win.trades.length) tr.push({ type: "scatter", mode: "markers", name: "trades", x: win.trades.map(r => isoT(r[0])), y: win.trades.map(r => r[1]),
    marker: { size: 4, color: win.trades.map(r => r[3] > 0 ? BID_C : ASK_C), opacity: 0.7 }, hovertemplate: "%{y} × %{customdata}<extra>trade</extra>", customdata: win.trades.map(r => r[2]) });
  const endStyle = { fill: ["solid", 1], cancel: ["dot", 0.8], reject: ["dash", 0.8], open: ["solid", 0.5] };
  win.orders.forEach((o, k) => tr.push({ type: "scatter", mode: "lines", name: "our orders", legendgroup: "orders", showlegend: k === 0, x: [isoT(o.t_place), isoT(o.t_end)], y: [o.price, o.price],
    line: { color: o.side > 0 ? BID_C : ASK_C, width: 4, dash: (endStyle[o.end] || endStyle.open)[0] }, opacity: (endStyle[o.end] || endStyle.open)[1],
    hovertemplate: `${o.side > 0 ? "buy" : "sell"} ${o.price} · ${o.end}<extra>order</extra>` }));
  const shapes = [], ann = [];
  if (fill) {
    tr.push({ type: "scatter", mode: "markers", name: "fill", x: [isoT(fill.t)], y: [fill.price], marker: { symbol: "star", size: 16, color: fill.artifact ? ART_C : "#e2e8f0", line: { width: 1, color: "#0a0f16" } }, hovertemplate: `fill ${fill.price}<extra></extra>` });
    HORIZONS.forEach(h => {
      const mk = fill["mk_" + h], t = fill.t + h * 1000;
      if (t > win.t1) return;
      shapes.push({ type: "line", xref: "x", yref: "paper", x0: isoT(t), x1: isoT(t), y0: 0, y1: 0.06, line: { color: "#94a3b8", width: 2 } });
      ann.push({ x: isoT(t), y: 0.0, yref: "paper", text: `${h} s ${isNum(mk) ? sign(mk, 1) + " bp" : "n/a"}`, showarrow: false, yanchor: "top", font: { size: 10, color: "#94a3b8" } });
    });
  } else shapes.push({ type: "line", xref: "x", yref: "paper", x0: isoT(req.t), x1: isoT(req.t), y0: 0, y1: 1, line: { color: "#facc15", width: 1.5, dash: "dash" } });
  // the stored window can be many events merged: show 60 s before to 300 s after this one
  const x0 = req.t - 60000, x1 = req.t + 300000, inX = t => t >= x0 && t <= x1;
  const ys = T.filter(r => inX(r[0])).flatMap(r => [r[1], r[2]]).concat(win.trades.filter(r => inX(r[0])).map(r => r[1]), win.orders.filter(o => o.t_end >= x0 && o.t_place <= x1).map(o => o.price), fill ? [fill.price] : []);
  const rng = fitAxis(ys);
  deskPlot("lvx-tape", tr, { shapes, annotations: ann, hovermode: "closest", xaxis: axis("", { type: "date", range: [isoT(x0), isoT(x1)] }), yaxis: axis("price", rng ? { range: rng } : {}), margin: { l: 70, r: 16, t: 10, b: 50 } });
  const offN = ys.filter(v => rng && (v < rng[0] || v > rng[1])).length;
  if (offN) $("lvx-tape-sub").textContent += " " + offNote(offN, "prices") + " Prices beyond the frame are clipped, not drawn.";
  card_scroll();
}
function card_scroll() { const c = $("lvx-tape-card"); if (c && c.scrollIntoView && !reduceMotion) c.scrollIntoView({ block: "nearest", behavior: "smooth" }); }

/* ----------------------------------------------------------------- the tab */
function drawLvExec() {
  const b = Sess.one();
  const all = ["lvx-state", "lvx-markout", "lvx-edge", "lvx-wait", "lvx-funnel", "lvx-activity", "lvx-fills"];
  if (!b) { all.forEach(lvWaiting); return; }
  const tk = b.takeaways, m = b.meta, w = Sess.windowOf(b);
  const fills = b.fills.filter(f => Sess.inWin(b, f.t));

  // quote state
  setSub("lvx-state-sub", tk.state_strip);
  const has = b.states.bid.length || b.states.ask.length;
  if (!has) { setSub("lvx-state-sub", ""); lvEmpty("lvx-state", tk.state_strip); fillLv("lvx-uptime", ""); }
  else {
    const seen = new Set(); const shapes = [];
    ["bid", "ask"].forEach((side, k) => b.states[side].forEach(iv => {
      if ((w && (iv.t1 < w[0] || iv.t0 > w[1]))) return;
      seen.add(iv.state);
      shapes.push({ type: "rect", xref: "x", yref: "y", x0: isoT(iv.t0), x1: isoT(iv.t1), y0: k ? 0.05 : 1.05, y1: k ? 0.95 : 1.95, fillcolor: STATE_COLOR[iv.state] || "#64748b", opacity: iv.state === "QUOTING" ? 0.55 : 0.95, line: { width: 0 } });
    }));
    const legend = [...seen].map(s => ({ type: "scatter", mode: "markers", x: [null], y: [null], name: stateName(s), marker: { symbol: "square", size: 10, color: STATE_COLOR[s] } }));
    deskPlot("lvx-state", legend, { shapes, height: 130, hovermode: false, xaxis: axis("", { type: "date", range: w ? [isoT(w[0]), isoT(w[1])] : undefined }),
      yaxis: axis("", { tickmode: "array", tickvals: [0.5, 1.5], ticktext: ["ask", "bid"], range: [0, 2], zeroline: false, showgrid: false }), margin: { l: 40, r: 16, t: 24, b: 30 } });
    const rows = (RANGE_H[Sess.state.range] && RANGE_H[Sess.state.range] <= 24 ? b.uptime_24h : b.uptime) || [];
    lvTable("lvx-uptime", [{ k: "side", label: "Side", left: true }, { k: "state", label: "State", left: true, f: v => statePill(v) }, { k: "seconds", label: "Time", f: v => agoText(v) }, { k: "share", label: "Share", f: v => pct(v, 1) }],
      rows, { sort: "share", empty: "No state time recorded in this range." });
  }

  // markout curves
  setSub("lvx-mk-sub", tk.markout);
  const mk = b.markout.filter(r => ["all", "buy", "sell", "JOIN", "BACK"].includes(r.group));
  if (!mk.length) lvEmpty("lvx-markout", tk.markout);
  else {
    const style = { all: ["#e2e8f0", "solid"], buy: [BID_C, "solid"], sell: [ASK_C, "solid"], JOIN: ["#2dd4bf", "dash"], BACK: ["#f472b6", "dash"] };
    const tr = [];
    ["all", "buy", "sell", "JOIN", "BACK"].forEach(g => {
      const r = mk.filter(x => x.group === g).sort((p, q) => p.h_s - q.h_s);
      if (!r.length) return;
      tr.push({ type: "scatter", mode: "lines+markers", name: g, x: r.map(x => x.h_s), y: r.map(x => x.bp), line: { color: style[g][0], dash: style[g][1], width: 2 },
        marker: { size: 8, symbol: r.map(x => x.n < 30 ? "circle-open" : "circle"), color: style[g][0], line: { width: 2, color: style[g][0] } },
        error_y: { type: "data", array: r.map(x => x.se ? 1.96 * x.se : 0), visible: true, thickness: 1, color: style[g][0] }, text: r.map(x => `n = ${x.n}`),
        hovertemplate: "%{y:.2f} bp · %{text}<extra>" + g + "</extra>" });
    });
    const lines = [{ type: "line", xref: "paper", yref: "y", x0: 0, x1: 1, y0: 0, y1: 0, line: { color: "#94a3b8", width: 1.5 } },
                   { type: "line", xref: "paper", yref: "y", x0: 0, x1: 1, y0: m.fee_bps, y1: m.fee_bps, line: { color: "#fbbf24", width: 1, dash: "dash" } }];
    deskPlot("lvx-markout", tr, { shapes: lines, xaxis: axis("seconds after the fill", { type: "log", tickvals: HORIZONS }), yaxis: axis("bp before fees"),
      annotations: [{ xref: "paper", x: 1, y: m.fee_bps, yref: "y", text: `fee ${m.fee_bps} bp`, showarrow: false, xanchor: "right", yanchor: "bottom", font: { size: 10, color: "#fbbf24" } }] });
  }

  // edge at fill
  setSub("lvx-edge-sub", tk.edge_hist);
  const edges = fills.filter(f => !f.artifact && isNum(f.edge_bp)).map(f => f.edge_bp);
  if (!edges.length) lvEmpty("lvx-edge", tk.edge_hist);
  else {
    const rng = fitAxis(edges, [0, m.fee_bps]), inr = edges.filter(v => v >= rng[0] && v <= rng[1]);
    const art = fills.filter(f => f.artifact).length, offN = edges.length - inr.length + art;
    deskPlot("lvx-edge", [{ type: "histogram", x: inr, marker: { color: "#cbd5e1" }, xbins: { start: rng[0], end: rng[1], size: (rng[1] - rng[0]) / 40 }, name: "fills", hovertemplate: "%{x} bp: %{y} fills<extra></extra>" }],
      { showlegend: false, bargap: 0.05, xaxis: axis("edge at fill, bp (vs the feed mid)", { range: rng }), yaxis: axis("fills"),
        shapes: [{ type: "line", xref: "x", yref: "paper", x0: 0, x1: 0, y0: 0, y1: 1, line: { color: "#94a3b8", width: 1.5 } }, { type: "line", xref: "x", yref: "paper", x0: m.fee_bps, x1: m.fee_bps, y0: 0, y1: 1, line: { color: "#fbbf24", width: 1, dash: "dash" } }] });
    if (offN) $("lvx-edge-sub").textContent += ` ${offN} fill${offN === 1 ? "" : "s"} off scale (${art} artifact${art === 1 ? "" : "s"}).`;
  }

  // queue wait, log-spaced
  const waits = fills.filter(f => !f.artifact && isNum(f.wait_s) && f.wait_s > 0).map(f => f.wait_s);
  setSub("lvx-wait-sub", tk.queue_wait);
  if (waits.length < 3) { setSub("lvx-wait-sub", ""); lvEmpty("lvx-wait", tk.queue_wait); fillLv("lvx-wait-table", ""); }
  else {
    const lo = Math.min(...waits), hi = Math.max(...waits) * 1.0001, n = 14, edges2 = Array.from({ length: n + 1 }, (_, i) => lo * Math.pow(hi / lo, i / n));
    const counts = Array(n).fill(0); waits.forEach(v => { let i = Math.min(n - 1, Math.floor(Math.log(v / lo) / Math.log(hi / lo) * n)); counts[i]++; });
    deskPlot("lvx-wait", [{ type: "bar", x: counts.map((_, i) => Math.sqrt(edges2[i] * edges2[i + 1])), width: counts.map((_, i) => (edges2[i + 1] - edges2[i]) * 0.9), y: counts, marker: { color: "#cbd5e1" }, hovertemplate: "%{x:.2f} s: %{y} fills<extra></extra>" }],
      { showlegend: false, xaxis: axis("seconds from place to fill (log)", { type: "log" }), yaxis: axis("fills") });
    lvTable("lvx-wait-table", [{ k: "tercile", label: "Wait tercile", left: true, f: (v, r) => `${fmt(r.wait_lo, 1)} to ${fmt(r.wait_hi, 1)} s` }, { k: "mk_60", label: "60 s markout bp", f: bpTxt }, { k: "se", label: "± 1.96 se", f: v => isNum(v) ? fmt(1.96 * v, 1) : dashes }, { k: "n", label: "n", f: v => nTxt(v) }],
      b.wait_terciles || [], { sort: "tercile", empty: "Markout by wait tercile needs at least 9 fills with exchange timing." });
  }

  // funnel
  const fu = b.funnel;
  setSub("lvx-fun-sub", tk.funnel);
  fillLv("lvx-funnel", `<table class="lv"><tbody>
    <tr><td class="l">Placed</td><td>${nTxt(fu.placed)}</td><td class="l"></td></tr>
    <tr><td class="l">→ filled</td><td>${nTxt(fu.filled)}</td><td class="l">${fu.placed ? pct(fu.filled / fu.placed, 0) : dashes} of placed</td></tr>
    <tr><td class="l">→ partially filled</td><td>${nTxt(fu.partial)}</td><td class="l"></td></tr>
    <tr><td class="l">→ cancelled</td><td>${nTxt(fu.cancelled)}</td><td class="l">${fu.placed ? pct(fu.cancelled / fu.placed, 0) : dashes} of placed</td></tr>
    <tr><td class="l">→ rejected</td><td>${nTxt(fu.rejected)}</td><td class="l">${fu.rejected ? esc(fu.reject_reasons.map(r => `${r.n} × ${r.error}`).join("; ")) : "none"}</td></tr></tbody></table>`);
  const hrs = fu.by_hour.filter(r => !w || (r.t + 36e5 > w[0] && r.t <= w[1]));
  if (!hrs.length) lvEmpty("lvx-activity", "No order activity in this range.");
  else deskPlot("lvx-activity", ["placed", "cancelled", "rejected"].map((k, i) => ({ type: "bar", name: k, x: hrs.map(r => isoT(r.t)), y: hrs.map(r => r[k] || null), marker: { color: ["#cbd5e1", "#64748b", "#facc15"][i] } })),
    { barmode: "group", yaxis: axis("orders per hour (log)", { type: "log" }), xaxis: axis("", { type: "date" }), margin: { l: 56, r: 16, t: 24, b: 36 } });

  drawFillsTable(b, fills);
  if (Tape.pending) drawTape();
}

function drawFillsTable(b, fills) {
  setSub("lvx-fills-sub", b.takeaways.fills_table);
  const f = $("lvx-fills-filter");
  f.innerHTML = `<label>Side <select id="ff-side"><option value="all">all</option><option value="buy">buy</option><option value="sell">sell</option></select></label>
    <label>Artifacts <select id="ff-art"><option value="all">included</option><option value="only">only artifacts</option><option value="none">excluded</option></select></label>`;
  $("ff-side").value = FillsUI.side; $("ff-art").value = FillsUI.art;
  $("ff-side").onchange = e => { FillsUI.side = e.target.value; FillsUI.page = 0; drawFillsTable(b, fills); };
  $("ff-art").onchange = e => { FillsUI.art = e.target.value; FillsUI.page = 0; drawFillsTable(b, fills); };
  let rows = fills.filter(r => (FillsUI.side === "all" || (FillsUI.side === "buy") === r.side > 0) && (FillsUI.art === "all" || (FillsUI.art === "only") === !!r.artifact));
  const k = FillsUI.sort;
  rows.sort((x, y) => { const a = x[k], c = y[k]; return (a === c ? 0 : a === null || a === undefined ? 1 : c === null || c === undefined ? -1 : a < c ? -1 : 1) * FillsUI.dir; });
  const pages = Math.max(1, Math.ceil(rows.length / FillsUI.per));
  FillsUI.page = Math.min(FillsUI.page, pages - 1);
  const slice = rows.slice(FillsUI.page * FillsUI.per, (FillsUI.page + 1) * FillsUI.per);
  const cols = [{ k: "t", label: "Time (UTC)", left: true, f: v => utcStamp(v) }, { k: "side", label: "Side", left: true, f: v => v > 0 ? "buy" : "sell" },
    { k: "price", label: "Price", f: v => fmtP(v) }, { k: "mid", label: "Mid", f: v => fmtP(v) }, { k: "edge_bp", label: "Edge bp", f: bpTxt },
    ...HORIZONS.map(h => ({ k: "mk_" + h, label: `${h} s`, f: bpTxt })), { k: "wait_s", label: "Wait s", f: v => isNum(v) ? fmt(v, 1) : dashes },
    { k: "lots_after", label: "Lots", f: v => nTxt(v) }, { k: "artifact", label: "", left: true, f: (v, r) => r.artifact ? '<span class="dot-art"></span>artifact' : "" }];
  lvTable("lvx-fills", cols, slice, { presorted: true, sort: k, dir: FillsUI.dir, scroll: true, rowClass: r => r.artifact ? "art" : "", onClick: r => Tape.open(b.meta.id, r.t, r.i),
    onSort: key => { FillsUI.dir = FillsUI.sort === key ? -FillsUI.dir : -1; FillsUI.sort = key; drawFillsTable(b, fills); }, empty: "No fills match this filter." });
  const pg = $("lvx-fills-pager");
  pg.innerHTML = `<button type="button" id="pg-prev"${FillsUI.page ? "" : " disabled"}>Previous</button><span>Page ${FillsUI.page + 1} of ${pages} · ${rows.length} fills · markout columns in bp, n/a where the feed had a gap</span><button type="button" id="pg-next"${FillsUI.page < pages - 1 ? "" : " disabled"}>Next</button>`;
  $("pg-prev").onclick = () => { FillsUI.page--; drawFillsTable(b, fills); };
  $("pg-next").onclick = () => { FillsUI.page++; drawFillsTable(b, fills); };
}

register("lv-exec", drawLvExec);
document.addEventListener("DOMContentLoaded", () => { const c = $("lvx-tape-close"); if (c) c.addEventListener("click", Tape.close); });
