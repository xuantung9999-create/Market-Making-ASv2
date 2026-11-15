/* session_chart.js: one animated, layered chart of a trading session (price with quotes and fills,
   quotes in bp, inventory against its cap, cumulative P&L), a row of tiles that follow a replay slider,
   and a Play button. It draws a "model" object and knows nothing about where the numbers come from;
   see docs/DASHBOARD_SESSION_CHART_SPEC.md section 6. Loaded after core.js, before every view.
   frameIndex and check take plain data and touch no DOM, so node can run them. */

const MAX_FRAMES = 200;

/* The point indices (inclusive ends) of the replay frames: at most 200, strictly increasing, the last one
   is n - 1, and the first one is at least 1 (two points) whenever n >= 2. */
function frameIndex(n) {
  if (!(n >= 1)) return [];
  if (n === 1) return [0];
  const F = Math.min(MAX_FRAMES, n - 1), out = [];
  for (let k = 0; k < F; k++) out.push(F === 1 ? n - 1 : Math.round(1 + k * (n - 2) / (F - 1)));
  return out;
}

/* Problems found in a model, as strings (empty list = fine). */
function check(model) {
  const bad = [], n = model && model.x ? model.x.length : 0;
  if (!n) return ["x is empty"];
  const len = (name, a) => { if (a != null && a.length !== n) bad.push(`${name} has ${a.length} points, x has ${n}`); };
  for (const k of ["mid", "res", "inventory", "inventoryBench", "pnl", "pnlPeak", "pnlAlt", "pnlBench"]) len(k, model[k]);
  if (model.band) { len("band.bid", model.band.bid); len("band.ask", model.band.ask); }
  if (model.quotes) { len("quotes.bid", model.quotes.bid); len("quotes.ask", model.quotes.ask); }
  if (model.tiles) for (const [k, a] of Object.entries(model.tiles)) len("tiles." + k, a);
  for (let i = 1; i < n; i++) if (!(model.x[i] > model.x[i - 1])) { bad.push(`x is not increasing at point ${i}`); break; }
  const panels = model.panels || [], has = p => panels.indexOf(p) >= 0;
  if (has("quotes") !== !!model.quotes) bad.push("panels and quotes disagree");
  if (has("pnl") !== !!model.pnl) bad.push("panels and pnl disagree");
  if (has("inventory") !== !!model.inventory) bad.push("panels and inventory disagree");
  if (has("price") && !model.mid) bad.push("price panel without mid");
  if ((model.events || []).length > 3) bad.push(`${model.events.length} events, at most 3 allowed`);
  if (model.kind === "sim" && model.band && model.res) {
    for (let i = 0; i < n; i++) {
      if (!(model.band.bid[i] < model.res[i] && model.res[i] < model.band.ask[i])) { bad.push(`bid < r < ask fails at point ${i}`); break; }
    }
  }
  return bad;
}

/* The value Plotly gets for an x: an ISO UTC string on a date axis (Plotly reads a number there as
   local time), the number itself on a linear axis. Not finite -> null. */
function plotX(xType, v) {
  if (typeof v !== "number" || !isFinite(v)) return null;
  return xType === "date" ? new Date(v).toISOString() : v;
}

const SessionChart = (function () {
  const WIDE = 900, NO_NOTES = 600, FRAME_MS = 40;
  const mounts = {};                                   // rootId -> state of the chart now drawn there

  const tcss = n => (typeof css === "function" ? css(n) : "");
  const escHtml = s => String(s).replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
  const num = x => typeof x === "number" && isFinite(x);
  const sgn = (x, d = 0) => !num(x) ? "–" : (x > 0 ? "+" : x < 0 ? "−" : "") + fmt(Math.abs(x), d);

  /* Wrap a sentence with <br> to about `chars` characters per line. */
  function wrap(text, chars) {
    const words = String(text || "").split(/\s+/).filter(Boolean), lines = []; let cur = "";
    for (const w of words) {
      if (cur && (cur + " " + w).length > chars) { lines.push(cur); cur = w; } else cur = cur ? cur + " " + w : w;
    }
    if (cur) lines.push(cur);
    return lines;
  }

  function utcLabel(ms) {
    const d = new Date(ms), M = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][d.getUTCMonth()];
    const p = v => String(v).padStart(2, "0");
    return `${d.getUTCDate()} ${M} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())} UTC`;
  }
  const xLabel = (m, v) => m.xType === "date" ? utcLabel(v) : "t = " + fmt(v, 2);

  /* ---------- layout ---------- */
  // Rows of panels by the panels present, and the share of the plot height of each row.
  function rowPlan(m, wide) {
    const p = m.panels, has = k => p.indexOf(k) >= 0, rows = [], weights = [];
    const lower = ["inventory", "pnl"].filter(has);
    if (wide) {
      rows.push(["price"]);
      if (has("quotes")) rows.push(["quotes"]);
      if (lower.length) rows.push(lower);
      const key = rows.map(r => r.length).join("");
      const W = { "1": [1], "12": [58, 42], "11": [58, 42], "111": [52, 18, 30], "112": [46, 16, 38] }[key];
      const fallback = rows.map(() => 1);
      return { rows, weights: W && W.length === rows.length ? W : fallback };
    }
    for (const k of p) { rows.push([k]); weights.push(k === "price" ? 2 : k === "quotes" ? 0.8 : 1); }
    return { rows, weights };
  }

  function buildLayout(m, width, wide) {
    const plan = rowPlan(m, wide);
    const wideRows = rowPlan(m, true).rows.length;
    const hWide = m.panels.length === 1 ? 420 : m.kind === "sim" ? 660 : m.panels.indexOf("pnl") >= 0 ? 700 : 640;
    const H = wide ? hWide : hWide + 160 * (plan.rows.length - wideRows);
    const mb = 48, plotW = Math.max(width - 56 - 70, 120);
    const colGap = 0.1;
    const colW = nCols => (nCols === 1 ? plotW : plotW * (1 - colGap) / nCols);
    const chars = nCols => Math.max(Math.floor(colW(nCols) / 8), 14);
    const titleLines = {};
    let maxLines = 1;
    plan.rows.forEach(row => row.forEach(k => {
      titleLines[k] = wrap(m.titles && m.titles[k], chars(row.length)); maxLines = Math.max(maxLines, titleLines[k].length);
    }));
    const band = lines => 8 + 16 * Math.max(lines, 1);
    const legendItems = 3 + (m.band ? 1 : 0) + (m.res ? 1 : 0), legendRows = Math.ceil(legendItems * 190 / Math.max(width - 20, 100));
    const mt = 12 + 22 * legendRows + band(titleLines.price ? titleLines.price.length : 1);
    const gaps = plan.rows.map((row, i) => i === 0 ? 0 : band(Math.max(...row.map(k => titleLines[k].length))));
    const plotH = H - mt - mb, avail = Math.max(plotH - gaps.reduce((a, b) => a + b, 0), 80);
    const wsum = plan.weights.reduce((a, b) => a + b, 0);
    const lay = { height: H, width: width, margin: { l: 56, r: 70, t: mt, b: mb }, annotations: [], shapes: [], showlegend: true,
                  legend: { orientation: "h", x: 0, y: 1, yref: "container", yanchor: "top", font: { size: 11 } } };
    const axisId = {}, geo = {}; let ax = 0, top = 1;                  // top in paper units
    const lastRow = plan.rows.length - 1;
    plan.rows.forEach((row, ri) => {
      top -= gaps[ri] / plotH;
      const h = avail * plan.weights[ri] / wsum / plotH, bottom = top - h;
      row.forEach((k, ci) => {
        const n = ++ax, suffix = n === 1 ? "" : String(n), nc = row.length;
        // two columns share the row: [0, 0.45] and [0.55, 1]
        const dom = nc === 1 ? [0, 1] : ci === 0 ? [0, 0.5 - colGap / 2] : [0.5 + colGap / 2, 1];
        axisId[k] = { x: "x" + suffix, y: "y" + suffix, xn: "xaxis" + suffix, yn: "yaxis" + suffix };
        geo[k] = { dom, top, bottom, px: colW(nc), lines: titleLines[k] };
      });
      top = bottom;
    });
    return { lay, axisId, geo, plan, H, lastRow, maxLines, wide };
  }

  /* Fixed axis ranges, from the whole series, before the first frame. */
  const finite = a => (a || []).filter(num);
  function extent(arrs, pad) {
    let lo = Infinity, hi = -Infinity;
    for (const a of arrs) for (const v of finite(a)) { if (v < lo) lo = v; if (v > hi) hi = v; }
    if (!isFinite(lo)) return null;
    if (lo === hi) { lo -= 1; hi += 1; }
    const p = (hi - lo) * pad; return [lo - p, hi + p];
  }

  function ranges(m) {
    const r = {};
    r.x = [m.x[0], m.x[m.x.length - 1]];
    r.price = (m.axes && m.axes.price) || extent(m.band ? [m.band.bid, m.band.ask, m.mid] : [m.mid], 0.05);
    r.bp = (m.axes && m.axes.bp) || (m.quotes ? extent([m.quotes.bid, m.quotes.ask, (m.fills || []).map(f => f.bp)], 0.1) : null);
    const q = m.qMax ? [-m.qMax, m.qMax] : [];
    r.inv = extent([m.inventory, m.inventoryBench, q], 0.1);
    if (r.inv && m.qMax) { r.inv[0] = Math.min(r.inv[0], -m.qMax * 1.1); r.inv[1] = Math.max(r.inv[1], m.qMax * 1.1); }
    r.pnl = m.pnl ? extent([m.pnl, m.pnlPeak, m.pnlAlt, m.pnlBench], 0.1) : null;
    return r;
  }

  /* ---------- traces for one frame ---------- */
  const pal = (m, k, dflt) => (m.palette && m.palette[k]) || dflt;

  function fillMarkers(m, win, axes, yOf, range, hoverName) {
    // Fills inside the window, split by side and by artifact; out-of-range ones sit on the edge, hollow.
    const out = [], P = m.palette || {}, bg = tcss("--bg") || "#0a0f16";
    const defs = [["buy", "triangle-up", P.buy], ["sell", "triangle-down", P.sell]];
    for (const art of [false, true]) {
      for (const [side, symbol, color] of defs) {
        const col = art ? P.artifact : color;
        if (art && !col) continue;
        const f = win.filter(v => v.side === side && !!v.artifact === art);
        if (!f.length) continue;
        for (const hollow of [false, true]) {
          const g = f.filter(v => { const y = yOf(v); const off = range && num(y) && (y < range[0] || y > range[1]); return off === hollow; });
          if (!g.length) continue;
          const ys = g.map(v => { const y = yOf(v); return hollow ? Math.min(Math.max(y, range[0]), range[1]) : y; });
          out.push({
            x: g.map(v => plotX(m.xType, v.x)), y: ys, mode: "markers", xaxis: axes.x, yaxis: axes.y, showlegend: false,
            name: (art ? "artifact " : "") + (side === "buy" ? "buy" : "sell") + " fill",
            customdata: g.map(v => [yOf(v), v.text || ""]),
            marker: hollow ? { symbol, size: m.kind === "sim" ? 9 : 8, color: "rgba(0,0,0,0)", line: { color: col, width: 1.5 } }
                           : { symbol, size: m.kind === "sim" ? 9 : 8, color: col, line: { color: bg, width: 1 } },
            hovertemplate: hoverName + " %{customdata[0]:" + m._hov.pf + "}" + (m._hov.fillUnit || "") + "<extra></extra>",
          });
        }
      }
    }
    return out;
  }

  function tracesFor(m, plan, ids, idx) {
    const T = [], cut = a => a == null ? null : a.slice(0, idx + 1), x = m.x.slice(0, idx + 1).map(v => plotX(m.xType, v));
    const xEnd = m.x[idx], win = (m.fills || []).filter(f => f.x <= xEnd);
    const P = m.palette || {}, H = m._hov, R = m._ranges;
    const live = m.kind === "live";
    const first = (t) => Object.assign({ showlegend: false }, t);
    // ----- price panel
    const a = ids.price;
    if (m.band) {
      T.push(first({ x, y: cut(m.band.ask), xaxis: a.x, yaxis: a.y, mode: "lines", line: { width: 0 }, hoverinfo: "skip" }));
      T.push({ x, y: cut(m.band.bid), xaxis: a.x, yaxis: a.y, mode: "lines", line: { width: 0 }, fill: "tonexty",
               fillcolor: rgba(C.accent, 0.13), name: "quoted band", hoverinfo: "skip" });
    }
    T.push({ x, y: cut(m.mid), xaxis: a.x, yaxis: a.y, mode: "lines", name: "mid", connectgaps: false,
             line: { color: pal(m, "mid", C.text), width: 1.8 }, hovertemplate: "%{y:" + H.pf + "}" + H.price });
    if (m.res) T.push({ x, y: cut(m.res), xaxis: a.x, yaxis: a.y, mode: "lines", name: "reservation r",
                        line: { color: pal(m, "res", C.accent), width: 1.4, dash: "dash" }, hovertemplate: "%{y:" + H.pf + "}" + H.price });
    const priceFills = fillMarkers(m, win, a, f => f.y, R.price, "@");
    priceFills.forEach(t => { t.showlegend = false; });
    // legend entries for the fill symbols (price panel only)
    for (const t of priceFills) T.push(t);
    for (const [side, sym, col, label] of (m.fills && m.fills.length ? [["buy", "triangle-up", P.buy, "bid filled (buy)"], ["sell", "triangle-down", P.sell, "ask filled (sell)"]] : [])) {
      T.push({ x: [null], y: [null], xaxis: a.x, yaxis: a.y, mode: "markers", name: label, hoverinfo: "skip",
               marker: { symbol: sym, size: 8, color: col } });
    }
    // ----- quotes in bp
    if (ids.quotes && m.quotes) {
      const q = ids.quotes;
      T.push(first({ x, y: cut(m.quotes.ask), xaxis: q.x, yaxis: q.y, mode: "lines", name: "ask", connectgaps: false,
                     line: { color: pal(m, "ask", C.ask), width: 1.2 }, hovertemplate: "%{y:+.1f} bp" }));
      T.push(first({ x, y: cut(m.quotes.bid), xaxis: q.x, yaxis: q.y, mode: "lines", name: "bid", connectgaps: false,
                     line: { color: pal(m, "bid", C.bid), width: 1.2 }, fill: "tonexty", fillcolor: rgba(C.accent, 0.13),
                     hovertemplate: "%{y:+.1f} bp" }));
      for (const t of fillMarkers(m, win, q, f => f.bp, R.bp, "fill at")) T.push(t);
    }
    // ----- inventory
    if (ids.inventory) {
      const i = ids.inventory;
      if (m.inventoryBench) T.push(first({ x, y: cut(m.inventoryBench), xaxis: i.x, yaxis: i.y, mode: "lines", name: nm(m, "inventoryBench"),
                                           line: { color: pal(m, "bench", C.muted), width: 1, shape: "hv" }, hovertemplate: "%{y:+.0f}" + H.inventory }));
      T.push(first({ x, y: cut(m.inventory), xaxis: i.x, yaxis: i.y, mode: "lines", name: nm(m, "inventory"),
                     line: { color: pal(m, "inventory", m.kind === "live" ? "#cbd5e1" : C.accent), width: live ? 1.5 : 1.6, shape: "hv" }, hovertemplate: "%{y:+.0f}" + H.inventory }));
    }
    // ----- P&L
    if (ids.pnl && m.pnl) {
      const p = ids.pnl;
      if (m.pnlBench) T.push(first({ x, y: cut(m.pnlBench), xaxis: p.x, yaxis: p.y, mode: "lines", name: nm(m, "pnlBench"),
                                     line: { color: pal(m, "bench", C.muted), width: 1 }, hovertemplate: "%{y:+.2f}" + H.pnl }));
      if (m.pnlPeak) T.push(first({ x, y: cut(m.pnlPeak), xaxis: p.x, yaxis: p.y, mode: "lines", line: { width: 0 }, hoverinfo: "skip" }));
      T.push(first({ x, y: cut(m.pnl), xaxis: p.x, yaxis: p.y, mode: "lines", name: nm(m, "pnl"),
                     line: { color: pal(m, "pnl", m.kind === "live" ? "#e2e8f0" : C.text), width: live ? 2 : 1.8 },
                     fill: m.pnlPeak ? "tonexty" : "none", fillcolor: rgba(C.ask, 0.12), hovertemplate: "%{y:+.2f}" + H.pnl }));
      if (m.pnlAlt) T.push(first({ x, y: cut(m.pnlAlt), xaxis: p.x, yaxis: p.y, mode: "lines", name: nm(m, "pnlAlt"),
                                   line: { color: pal(m, "pnl", m.kind === "live" ? "#e2e8f0" : C.text), width: 1.5, dash: "dash" }, hovertemplate: "%{y:+.2f}" + H.pnl }));
    }
    return T;
  }

  const LABELS = { inventory: "inventory", inventoryBench: "benchmark", pnl: "P&L", pnlBench: "benchmark", pnlAlt: "net excl. artifacts" };
  const lab = (m, k) => (m.labels && m.labels[k]) || LABELS[k];                       // direct label at the right end of a line
  const NAMES = { inventory: "inventory", inventoryBench: "benchmark inventory", pnl: "P&L", pnlBench: "benchmark P&L", pnlAlt: "net excl. artifacts" };
  const nm = (m, k) => (m.names && m.names[k]) || NAMES[k];                            // name carried by a hover line

  /* ---------- annotations, shapes, axes ---------- */
  function decorate(m, L, idx, showNotes) {
    const lay = Object.assign({}, L.lay), ids = L.axisId, geo = L.geo, R = m._ranges;
    const ann = [], shapes = [];
    // panel titles (the finding), top-left of each panel
    for (const k of m.panels) {
      const g = geo[k], t = m.titles && m.titles[k]; if (!t) continue;
      ann.push({ xref: "paper", yref: "paper", x: g.dom[0], y: g.top, xanchor: "left", yanchor: "bottom", yshift: 5, showarrow: false, align: "left",
                 text: g.lines.join("<br>"), font: { size: 13, color: C.text } });
    }
    const xEnd = m.x[idx];
    // direct labels at the right end of each line in the lower panels
    const endLab = (panel, arr, key, color, dy) => {
      if (!arr || !geo[panel]) return;
      const v = arr[idx]; if (!num(v)) return;
      ann.push({ xref: ids[panel].x, yref: ids[panel].y, x: plotX(m.xType, xEnd), y: v, xanchor: "left", yanchor: "middle", xshift: 5, yshift: dy, showarrow: false,
                 text: lab(m, key), font: { size: 10, color, family: MONO } });
    };
    // the main line's label sits a little above its end and the secondary one a little below, so ends that meet stay readable
    if (geo.inventory) { endLab("inventory", m.inventory, "inventory", pal(m, "inventory", m.kind === "live" ? "#cbd5e1" : C.accent), 7); endLab("inventory", m.inventoryBench, "inventoryBench", pal(m, "bench", C.muted), -7); }
    if (geo.pnl && m.pnl) { endLab("pnl", m.pnl, "pnl", pal(m, "pnl", m.kind === "live" ? "#e2e8f0" : C.text), 7); endLab("pnl", m.pnlBench, "pnlBench", pal(m, "bench", C.muted), -7); endLab("pnl", m.pnlAlt, "pnlAlt", pal(m, "pnl", m.kind === "live" ? "#e2e8f0" : C.text), -7); }
    // event annotations, once the replay has reached them
    if (showNotes) {
      const span = (R.x[1] - R.x[0]) || 1;
      for (const e of (m.events || []).slice(0, 3)) {
        if (!ids[e.panel] || !(e.x <= xEnd)) continue;
        const late = (e.x - R.x[0]) / span > 0.6;
        const yr = e.panel === "price" ? R.price : e.panel === "quotes" ? R.bp : e.panel === "inventory" ? R.inv : R.pnl;
        const high = yr && (e.y - yr[0]) / ((yr[1] - yr[0]) || 1) > 0.65;          // near the top of its panel: put the note below the point
        ann.push({ xref: ids[e.panel].x, yref: ids[e.panel].y, x: plotX(m.xType, e.x), y: e.y, text: e.text, showarrow: true, arrowcolor: C.muted, arrowwidth: 1,
                   arrowhead: 2, ax: late ? -50 : 50, ay: high ? 34 : -34, xanchor: late ? "right" : "left", font: { size: 11, color: C.text, family: MONO },
                   bgcolor: "rgba(0,0,0,0)" });
      }
    }
    lay.annotations = ann;
    // inventory cap lines
    if (geo.inventory && m.qMax) {
      for (const s of [m.qMax, -m.qMax]) shapes.push({ type: "line", xref: ids.inventory.x + " domain", x0: 0, x1: 1, yref: ids.inventory.y, y0: s, y1: s,
                                                      line: { color: pal(m, "limit", "#818cf8"), width: 1, dash: "dot" } });
    }
    // shapes written for the price panel (quote-state background, markers); the adapter leaves refs off
    for (const s of [].concat(m.bands || [], m.lines || [])) {
      const g = geo.price, sh = Object.assign({ xref: ids.price.x }, s);
      if (sh.yref === "paper") { sh.y0 = g.bottom + sh.y0 * (g.top - g.bottom); sh.y1 = g.bottom + sh.y1 * (g.top - g.bottom); }   // 0 to 1 means the price panel, not the figure
      shapes.push(sh);
    }
    lay.shapes = shapes;
    // axes
    const zero = pal(m, "zero", "#64748b");
    const unit = m.units || {};
    const bottoms = new Set(L.plan.rows[L.lastRow]);
    const xRange = R.x.map(v => plotX(m.xType, v));                 // R.x stays numeric for the arithmetic above
    for (const k of m.panels) {
      const g = geo[k], id = ids[k];
      const isBottom = L.wide ? bottoms.has(k) : k === L.plan.rows[L.lastRow][0];
      const base = { domain: g.dom, anchor: id.y, showticklabels: isBottom, range: xRange, type: m.xType === "date" ? "date" : "linear", automargin: true };
      if (id.x !== "x") base.matches = "x";
      lay[id.xn] = axis(isBottom ? (m.xType === "date" ? "" : (m.xTitle || "time t")) : "", base);
      const yr = k === "price" ? R.price : k === "quotes" ? R.bp : k === "inventory" ? R.inv : R.pnl;
      const title = k === "price" ? (unit.price || "price") : k === "quotes" ? (unit.bp || "bp from mid") : k === "inventory" ? (unit.inventory || "inventory") : (unit.pnl || "P&L");
      const yx = { domain: [g.bottom, g.top], anchor: id.x, automargin: true };
      if (yr) yx.range = yr;
      if (k !== "price") { yx.zeroline = true; yx.zerolinecolor = zero; yx.zerolinewidth = 1; }
      lay[id.yn] = axis(title, yx);
    }
    return lay;
  }

  /* ---------- tiles ---------- */
  function tileDefs(m, i) {
    const T = m.tiles || {}, live = m.kind === "live", at = "at " + xLabel(m, m.x[i]);
    const has = k => m.panels.indexOf(k) >= 0;
    const defs = [];
    defs.push({ k: "Mid", v: num(T.mid[i]) ? (live ? fmtP(T.mid[i]) : fmt(T.mid[i], 3)) : "–", s: at });
    if (!has("inventory")) return defs;
    defs.push({ k: "Inventory", v: sgn(T.inventory[i], 0), s: live ? (m.qMax ? `of ±${fmt(m.qMax, 0)} lots` : "lots") : (m.qMax ? `units, cap ±${fmt(m.qMax, 0)}` : "units") });
    if (has("pnl") && T.pnl) defs.push({ k: "P&L", v: sgn(T.pnl[i], 2), cls: typeof pnlCls === "function" ? pnlCls(T.pnl[i]) : "", s: at });
    defs.push({ k: "Fills", v: fmt(T.fills[i], 0), s: `${fmt(T.buys[i], 0)} buys, ${fmt(T.sells[i], 0)} sells` });
    defs.push({ k: "Max |inventory|", v: fmt(T.maxAbs[i], 0), s: live ? "so far in the range" : "so far" });
    const sp = T.spread[i];
    defs.push({ k: live ? "Quote width" : "Spread", v: num(sp) ? (live ? fmt(sp, 1) + " bp" : fmt(sp, 2)) : "not quoting", s: at });
    return defs;
  }
  function drawTiles(st, i) {
    st.tilesEl.innerHTML = tileDefs(st.m, i).map(t =>
      `<div class="tile"><div class="k">${escHtml(t.k)}</div><div class="v ${t.cls || ""}">${escHtml(t.v)}</div><div class="s">${escHtml(t.s)}</div></div>`).join("");
  }

  /* ---------- mounting ---------- */
  function drawFrame(st, k) {
    const m = st.m, idx = st.frames[k];
    st.pos = k;
    const lay = decorate(m, st.L, idx, st.showNotes);
    Plotly.react(st.figEl, tracesFor(m, st.L.plan, st.L.axisId, idx), layout(lay), CONFIG);
    st.slider.value = k;
    st.slider.setAttribute("aria-valuetext", xLabel(m, m.x[idx]));
    st.readout.textContent = xLabel(m, m.x[idx]);
    drawTiles(st, idx);
  }

  function relayout(st) {
    const w = st.figEl.clientWidth || st.root.clientWidth || 900;
    const wide = w >= WIDE;
    st.L = buildLayout(st.m, w, wide);
    st.showNotes = w >= NO_NOTES;
    st.figEl.style.height = st.L.H + "px";
    st.width = w;
    st.notesEl.innerHTML = st.showNotes ? "" : (st.m.events || []).map(e => `<li>${escHtml(e.text)}</li>`).join("");
    st.notesEl.hidden = st.showNotes || !(st.m.events || []).length;
  }

  function stop(rootId) {
    const st = mounts[rootId]; if (!st) return;
    if (st.timer) { clearTimeout(st.timer); st.timer = null; }
    if (st.playBtn) st.playBtn.textContent = "Play";
    st.playing = false;
  }

  function mount(rootId, model) {
    const root = document.getElementById(rootId); if (!root) return;
    const old = mounts[rootId];
    if (old) { stop(rootId); if (old.ro) old.ro.disconnect(); try { Plotly.purge(old.figEl); } catch (e) { /* nothing drawn yet */ } }
    delete mounts[rootId];
    const m = model, problems = check(m);
    problems.forEach(p => console.error("SessionChart.check: " + p));
    m._ranges = ranges(m);
    const liveKind = m.kind === "live";
    m._hov = Object.assign({ price: "", inventory: liveKind ? " lots" : " units", pnl: liveKind ? " USDT" : "", fillUnit: "", pf: liveKind ? ".6~g" : ".3f" }, m.hover || {});
    const t = m.titles || {};
    const hasMotion = !(typeof reduceMotion !== "undefined" && reduceMotion);
    root.innerHTML = `<h2>${escHtml(t.card || "")}</h2><p class="sub">${escHtml(t.sub || "")}</p>
      <div class="sc-ctl"><button type="button" class="sc-play"${hasMotion ? "" : " hidden"}>Play</button>
        <label class="sc-slide"><span>Replay position</span><input type="range" class="sc-range" min="0" step="1"></label>
        <output class="sc-readout mono"></output></div>
      <div class="tiles sc-tiles"></div><div class="sc-fig"></div>
      <p class="note sc-off"></p><ul class="sc-notes note" hidden></ul>`;
    const q = s => root.querySelector(s);
    const st = { root, m, frames: frameIndex(m.x.length), pos: 0, timer: null, playing: false,
                 figEl: q(".sc-fig"), tilesEl: q(".sc-tiles"), slider: q(".sc-range"), readout: q(".sc-readout"),
                 playBtn: q(".sc-play"), notesEl: q(".sc-notes") };
    mounts[rootId] = st;
    q(".sc-off").textContent = m.offScale || "";
    st.slider.max = String(st.frames.length - 1);
    relayout(st);
    drawFrame(st, st.frames.length - 1);

    st.slider.addEventListener("input", () => { stop(rootId); drawFrame(st, +st.slider.value); });
    st.playBtn.addEventListener("click", () => {
      if (st.playing) { stop(rootId); return; }
      if (st.pos >= st.frames.length - 1) drawFrame(st, 0);
      st.playing = true; st.playBtn.textContent = "Pause";
      const step = () => {
        if (!st.playing) return;
        if (st.pos >= st.frames.length - 1) { stop(rootId); return; }
        drawFrame(st, st.pos + 1);
        if (st.pos >= st.frames.length - 1) { stop(rootId); return; }
        st.timer = setTimeout(step, FRAME_MS);
      };
      st.timer = setTimeout(step, FRAME_MS);
    });
    if (typeof ResizeObserver !== "undefined") {
      st.ro = new ResizeObserver(() => {
        const w = st.figEl.clientWidth; if (!w || w === st.width) return;
        relayout(st); drawFrame(st, st.pos);
      });
      st.ro.observe(st.figEl);
    }
  }

  return { mount, check, frameIndex, plotX, stop };
})();

if (typeof module !== "undefined") module.exports = { frameIndex, check, plotX };
