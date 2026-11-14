/* book.js: Market book > Order book (Dashboard Redesign R6).
   Reads only the book bundle (runs/book-<date>.js, built by scripts/build_book_bundle.py). The left card shows the
   last recorded sample; the live heartbeat feed arrives with Task R7. */

const BOOK = { coin: null, minutes: 360 };
const BOOK_RANGES = [["6h", 360], ["1h", 60], ["15m", 15]];
const bq4 = x => isNum(x) ? Number(x.toPrecision(4)).toString() : "–";

function bookBundle() {
  const host = $("desk-msg-book"), body = $("desk-body-book");
  const b = Source.book;
  const msg = b ? "" : (Source.bookError || "Loading recorded book…");
  host.textContent = msg; host.hidden = !msg; body.hidden = !!msg;
  return msg ? null : b;
}

function bookControls(b) {
  const sel = $("bk-coin");
  if (!sel.options.length) {
    sel.innerHTML = b.symbols.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
    sel.addEventListener("change", () => { BOOK.coin = sel.value; markDirty("book"); });
    $("bk-range").innerHTML = BOOK_RANGES.map(([l, m]) => `<button type="button" data-m="${m}" aria-pressed="${m === BOOK.minutes}">${l}</button>`).join("");
    $("bk-range").addEventListener("click", e => {
      const m = e.target.dataset && e.target.dataset.m;
      if (!m) return;
      BOOK.minutes = +m; markDirty("book");
    });
  }
  if (!BOOK.coin || !b.symbols.includes(BOOK.coin)) BOOK.coin = b.symbols[0];
  sel.value = BOOK.coin;
  $("bk-range").querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", String(+x.dataset.m === BOOK.minutes)));
  $("bk-meta").textContent = `${b.built_utc} UTC · ${ago(b.built_utc)} · ${b.symbols.length} coins`;
}

function lastOf(a) { return a[a.length - 1]; }

function drawBookNow(b) {
  const t = b.touch[BOOK.coin], p = (b.profile || []).find(r => r.symbol === BOOK.coin) || {};
  if (!t || !t.t.length) return emptyPanel("bk-now", "No samples for this coin");
  const bid = lastOf(t.bid), ask = lastOf(t.ask), bQ = lastOf(t.bid_qty), aQ = lastOf(t.ask_qty);
  const mid = (bid + ask) / 2, tot = bQ + aQ, imb = tot > 0 ? (bQ - aQ) / tot : 0;
  const micro = tot > 0 ? (bid * aQ + ask * bQ) / tot : mid;
  const spBp = (ask - bid) / mid * 1e4;
  const ticks = isNum(p.tick_bp) && p.tick_bp > 0 ? spBp / p.tick_bp : null;
  fillHtml("bk-now", `<h2>${esc(BOOK.coin)}</h2><p class="sub">Last recorded sample · ${esc(lastOf(t.t).replace("T", " ").replace("Z", ""))} UTC</p>
    <div style="display:flex;justify-content:space-between"><div><div class="k note">BID</div><div class="px" style="color:${BID_C}">${fmtP(bid)}</div><div class="note">${bq4(bQ)} units</div></div>
      <div style="text-align:right"><div class="k note">ASK</div><div class="px" style="color:${ASK_C}">${fmtP(ask)}</div><div class="note">${bq4(aQ)} units</div></div></div>
    <div class="imbbar" aria-hidden="true"><i style="width:${(100 * bQ / (tot || 1)).toFixed(1)}%;background:${BID_C}"></i><i style="width:${(100 * aQ / (tot || 1)).toFixed(1)}%;background:${ASK_C}"></i></div>
    <dl><dt>Imbalance</dt><dd>${sign(imb, 2)}</dd>
      <dt>Spread</dt><dd>${ticks !== null ? fmt(ticks, 0) + (Math.round(ticks) === 1 ? " tick" : " ticks") + " = " : ""}${fmt(spBp, 1)} bp</dd>
      <dt>Microprice − mid</dt><dd>${sign((micro - mid) / mid * 1e4, 1)} bp</dd>
      <dt>Queue at the touch</dt><dd>${isNum(p.touch_in_trades) ? fmt(p.touch_in_trades, 0) + " median trades" : "–"}</dd>
      <dt>Updates per minute</dt><dd>${isNum(p.updates_per_min) ? fmt(p.updates_per_min, 0) : "–"}</dd>
      <dt>Best price lasts</dt><dd>${isNum(p.deplete_s_med) ? fmt(p.deplete_s_med, 1) + " s (median)" : "–"}</dd></dl>`);
}

function windowRange(t) {
  const end = Date.parse(lastOf(t.t));
  return [new Date(end - BOOK.minutes * 60000).toISOString(), new Date(end).toISOString()];
}

function drawBookPrice(b) {
  const t = b.touch[BOOK.coin], tr = (b.trades || {})[BOOK.coin];
  if (!t || !t.t.length) return emptyPanel("bk-price");
  const data = [
    { x: t.t, y: t.bid, name: "Best bid", mode: "lines", line: { shape: "hv", width: 1.4, color: BID_C }, hovertemplate: "bid %{y}<extra></extra>" },
    { x: t.t, y: t.ask, name: "Best ask", mode: "lines", line: { shape: "hv", width: 1.4, color: ASK_C }, hovertemplate: "ask %{y}<extra></extra>" },
  ];
  if (tr && tr.t.length) {
    const mx = Math.max(...tr.qty, 1e-12);
    data.push({ x: tr.t, y: tr.price, name: "Trades", mode: "markers", marker: { size: tr.qty.map(q => 3 + 12 * Math.sqrt(q / mx)),
                color: tr.side.map(s => s > 0 ? BID_C : ASK_C), opacity: 0.65, line: { width: 0 } },
                customdata: tr.qty, hovertemplate: "%{y} · %{customdata} units<extra>trade</extra>" });
  }
  deskPlot("bk-price", data, { xaxis: axis("UTC", { type: "date", range: windowRange(t) }), yaxis: axis("price"), hovermode: "x" });
}

function drawBookSize(b) {
  const t = b.touch[BOOK.coin];
  if (!t || !t.t.length) return emptyPanel("bk-size");
  const imb = t.bid_qty.map((q, i) => { const s = q + t.ask_qty[i]; return s > 0 ? (q - t.ask_qty[i]) / s : 0; });
  deskPlot("bk-size", [
    { x: t.t, y: t.bid_qty, name: "Bid size", mode: "lines", line: { shape: "hv", width: 0.5, color: BID_C }, fill: "tozeroy", fillcolor: rgba(BID_C, 0.35) },
    { x: t.t, y: t.ask_qty.map(q => -q), name: "Ask size", mode: "lines", line: { shape: "hv", width: 0.5, color: ASK_C }, fill: "tozeroy", fillcolor: rgba(ASK_C, 0.35),
      customdata: t.ask_qty, hovertemplate: "%{customdata}<extra>ask size</extra>" },
    { x: t.t, y: imb, name: "Imbalance", mode: "lines", yaxis: "y2", line: { shape: "hv", width: 1, color: C.text } },
  ], { xaxis: axis("UTC", { type: "date", range: windowRange(t) }), yaxis: axis("units", { zeroline: true, zerolinecolor: C.muted }),
       yaxis2: axis("imbalance", { overlaying: "y", side: "right", range: [-1, 1], showgrid: false }) });
}

function drawBookImb(b) {
  const rows = (b.imb_curve || []).filter(r => r.symbol === BOOK.coin);
  if (!rows.length) return emptyPanel("bk-imb", "Not enough clean hours yet");
  const hs = [...new Set(rows.map(r => r.h_s))].sort((a, c) => a - c), tr = [];
  hs.forEach((h, i) => {
    const r = rows.filter(x => x.h_s === h).sort((a, c) => a.bucket - c.bucket), col = SERIES[(i + 2) % SERIES.length];
    tr.push({ x: r.map(x => x.imb_mid), y: r.map(x => x.move_bp + 1.96 * x.se), mode: "lines", line: { width: 0 }, showlegend: false, hoverinfo: "skip", legendgroup: "h" + h });
    tr.push({ x: r.map(x => x.imb_mid), y: r.map(x => x.move_bp - 1.96 * x.se), mode: "lines", line: { width: 0 }, fill: "tonexty", fillcolor: rgba(col, 0.15),
              showlegend: false, hoverinfo: "skip", legendgroup: "h" + h });
    tr.push({ x: r.map(x => x.imb_mid), y: r.map(x => x.move_bp), name: h + " s", mode: "lines+markers", line: { width: 1.8, color: col }, marker: { size: 5 }, legendgroup: "h" + h,
              customdata: r.map(x => x.n), hovertemplate: `after ${h} s: %{y:.2f} bp (n=%{customdata})<extra></extra>` });
  });
  const tot = rows.reduce((a, r) => a + (r.h_s === hs[0] ? r.n : 0), 0);
  $("bk-imb-sub").textContent = `Mid move after 1, 5 and 30 s by imbalance decile, bp, band ±1.96 se (a lower bound: neighbouring seconds overlap); ${fmt(tot, 0)} samples`;
  deskPlot("bk-imb", tr, { xaxis: axis("imbalance at the touch (bid − ask) / (bid + ask)", { zeroline: true, zerolinecolor: C.muted }),
                           yaxis: axis("mid move (bp)", { zeroline: true, zerolinecolor: C.muted, zerolinewidth: 1.5 }) });
}

function drawBookSpread(b) {
  const h = (b.spread_hist || {})[BOOK.coin];
  if (!h || !h.ticks.length) return emptyPanel("bk-spread");
  deskPlot("bk-spread", [{ type: "bar", x: h.ticks.map(t => t === 10 ? "10+" : String(t)), y: h.share.map(x => 100 * x), marker: { color: C.accent },
                           hovertemplate: "%{x} ticks: %{y:.1f}%<extra></extra>" }],
           { showlegend: false, xaxis: axis("spread (ticks)", { type: "category" }), yaxis: axis("% of time") });
}

const NO_DEPTH = "No depth recorded. Start the recorder with --depth (run_recorder_multi_depth.bat), then run_build_book.bat.";

function drawBookDepth(b) {
  const d = b.depth && b.depth[BOOK.coin];
  if (!d || !d.ladder) { emptyPanel("bk-ladder", NO_DEPTH); emptyPanel("bk-depth", NO_DEPTH); return; }
  const u = d.ladder.usd_per_unit || 1, lad = d.ladder;
  const side = (rows, color, name) => ({ type: "scatter", mode: "lines", name, x: rows.map(r => r.bp), y: rows.map(r => r.cum * u),
    line: { shape: "hv", color, width: 2 }, fill: "tozeroy", fillcolor: rgba(color, 0.18), customdata: rows.map(r => [r.px, r.qty]),
    hovertemplate: `${name} %{customdata[0]:.6g}: %{customdata[1]:.6g} units here, $%{y:,.0f} cumulative<extra></extra>` });
  deskPlot("bk-ladder", [side(lad.bids.slice().reverse(), PROFIT, "Bids"), side(lad.asks, LOSS, "Asks")],
    { xaxis: axis("distance from the mid (bp)", { zeroline: true, zerolinecolor: C.muted }), yaxis: axis("cumulative size (USD)"), hovermode: "closest" });
  if (!d.heat) return emptyPanel("bk-depth", "Too few snapshots for a heatmap");
  deskPlot("bk-depth", [{ type: "heatmap", x: d.heat.t, y: d.heat.y, z: d.heat.z, colorscale: [[0, "#0b1220"], [0.3, "#1e3a5f"], [0.7, "#38bdf8"], [1, "#e0f2fe"]],
    colorbar: { title: { text: "USD", side: "right" }, thickness: 10 }, hovertemplate: "%{x} UTC, %{y:.1f} bp: $%{z:,.0f}<extra></extra>", zsmooth: false }],
    { xaxis: axis("UTC", { type: "category", nticks: 6 }), yaxis: axis("distance from the mid (bp)"), hovermode: "closest" });
}

function drawBookProfile(b) {
  const rows = b.profile || [];
  if (!rows.length) return emptyPanel("bk-profile");
  const cols = [["symbol", "Coin", r => esc(r.symbol)], ["tick_bp", "Tick (bp)", r => isNum(r.tick_bp) ? fmt(r.tick_bp, 1) : "–"],
    ["spread_ticks_med", "Spread (ticks, median)", r => isNum(r.spread_ticks_med) ? fmt(r.spread_ticks_med, 0) : "–"],
    ["share_one_tick", "Time at 1 tick", r => pct(r.share_one_tick)], ["touch_qty_med", "Touch size (units)", r => bq4(r.touch_qty_med)],
    ["touch_in_trades", "Queue (median trades)", r => isNum(r.touch_in_trades) ? fmt(r.touch_in_trades, 0) : "–"],
    ["updates_per_min", "Updates / min", r => isNum(r.updates_per_min) ? fmt(r.updates_per_min, 0) : "–"],
    ["trades_per_min", "Trades / min", r => isNum(r.trades_per_min) ? fmt(r.trades_per_min, 1) : "–"],
    ["deplete_s_med", "Best price lasts (s)", r => isNum(r.deplete_s_med) ? fmt(r.deplete_s_med, 1) : "–"]];
  const state = drawBookProfile.sort || (drawBookProfile.sort = { k: "symbol", dir: 1 });
  const sorted = rows.slice().sort((a, c) => { const x = a[state.k], y = c[state.k]; return (x === y ? 0 : x === null || x === undefined ? 1 : y === null || y === undefined ? -1 : x < y ? -1 : 1) * state.dir; });
  fillHtml("bk-profile", `<table><thead><tr>${cols.map(c => `<th class="sortable" data-k="${c[0]}">${c[1]}</th>`).join("")}</tr></thead>
    <tbody>${sorted.map(r => `<tr>${cols.map(c => `<td>${c[2](r)}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
  $("bk-profile").querySelectorAll("th.sortable").forEach(th => th.addEventListener("click", () => {
    state.dir = state.k === th.dataset.k ? -state.dir : 1; state.k = th.dataset.k; drawBookProfile(b);
  }));
}

function drawBook() {
  const b = bookBundle();
  if (!b) return;
  bookControls(b);
  drawBookNow(b); drawBookPrice(b); drawBookSize(b); drawBookImb(b); drawBookSpread(b); drawBookDepth(b); drawBookProfile(b);
}
register("book", drawBook);
