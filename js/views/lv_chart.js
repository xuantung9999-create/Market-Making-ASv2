/* lv_chart.js: the live adapter of the session chart (docs/DASHBOARD_SESSION_CHART_SPEC.md 6.1, 7.2).
   Python wrote every number and every sentence into live/chart-<id>.js (scripts/build_session.py); this file copies
   arrays and strings into the model of js/session_chart.js. It does no arithmetic on a displayed value: it indexes,
   filters fills to the window, and hands over. */

/* The fills of the bundle that the chart draws: inside the range, and in the list Python kept when there were too many. */
function lvChartFills(b, entry) {
  const keep = entry.fill_ids ? new Set(entry.fill_ids) : null;
  return b.fills.filter(f => Sess.inWin(b, f.t) && (!keep || keep.has(f.i))).map(f => ({
    x: f.t, y: f.price, side: f.side > 0 ? "buy" : "sell", bp: f.dist_bp, artifact: !!f.artifact, text: f.caption || "",
  }));
}

function liveModel(b, entry) {
  const quotes = entry.panels.includes("quotes") ? { bid: entry.bid_bp, ask: entry.ask_bp } : null;
  const hasInv = entry.panels.includes("inventory"), hasPnl = entry.panels.includes("pnl");
  const w = Sess.windowOf(b);
  return {
    kind: "live", xType: "date", x: entry.t, panels: entry.panels,
    units: { price: "USDT", bp: "bp from mid", inventory: "lots", pnl: "USDT" },
    labels: { inventory: "lots", pnl: "P&L", pnlAlt: "excl. artifacts" },
    names: { inventory: "inventory", pnl: "P&L", pnlAlt: "net excluding artifacts" },
    mid: entry.mid, res: null, band: null, quotes,
    fills: lvChartFills(b, entry),
    inventory: hasInv ? entry.lots : null, inventoryBench: null, qMax: b.meta.q_max,
    pnl: hasPnl ? entry.pnl : null, pnlPeak: hasPnl ? entry.pnl_peak : null, pnlAlt: hasPnl ? entry.pnl_ex_artifact : null, pnlBench: null,
    tiles: { mid: entry.mid, inventory: entry.lots, pnl: hasPnl ? entry.pnl : null, fills: entry.fills_cum, buys: entry.buys_cum,
             sells: entry.sells_cum, maxAbs: entry.max_abs_lots, spread: entry.width_bp },
    titles: entry.titles,
    events: entry.events.map(e => ({ panel: e.panel, x: e.t, y: e.y, text: e.text })),
    axes: entry.axes, offScale: entry.empty || entry.off_scale,
    bands: stateBands(b, 1.0, 0.035), lines: markerLines(b, ["restart", "loss_stop", "day"]),
    palette: { mid: C.text, buy: BID_C, sell: ASK_C, artifact: ART_C, bid: BID_C, ask: ASK_C },
  };
}

function lvChartSay(root, text) {
  SessionChart.stop(root.id);
  root.innerHTML = "";
  const p = document.createElement("p");
  p.className = "note";
  p.textContent = text;
  root.appendChild(p);
}

/* Draw the chart card `rootId` (lvc-exec or lvc-agent) for the selected session and range. */
function drawLvChart(rootId) {
  const root = $(rootId);
  if (!root) return;
  const b = Sess.one();
  if (!b) { lvChartSay(root, Sess.state.error || "Loading the session…"); return; }
  const id = b.meta.id, state = (Sess.state.charts || {})[id], file = (window.SESSION_CHART || {})[id];
  if (!file) { lvChartSay(root, state === "error" || state === "done" ? "The session chart is written with the next 5-minute build." : "Loading the session chart…"); return; }
  const entry = file.by_range && file.by_range[Sess.state.range];
  if (!entry) { lvChartSay(root, "The session chart is written with the next 5-minute build."); return; }
  if (entry.empty && !entry.t.length) { lvChartSay(root, entry.empty); return; }
  SessionChart.mount(rootId, liveModel(b, entry));
}
