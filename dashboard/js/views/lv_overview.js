/* lv_overview.js: Overview tab (live spec section 7). Incidents and state first, the money below. */

/* The terms of the selected range, as Python computed them (bundle.by_range[range].tiles). */
function sumRange(b) {
  const e = rangeEntry(b);
  return e ? { ...e.tiles } : { ...b.attribution.total, fills: b.fills.length };
}
function liveFor(b) { return typeof window.liveStatusFor === "function" ? window.liveStatusFor(b.meta.source, b.meta.symbol) : null; }

function stateCard(b) {
  const m = b.meta, n = b.now, live = liveFor(b);
  const st = live && live.state && live.state.bid ? live.state : n.state;
  const lots = live ? (isNum(live.lots) ? live.lots : isNum(live.q) ? live.q : n.lots) : n.lots;
  const open = live && live.open ? (m.source === "paper" ? { bid: live.open.bid && live.open.bid.price, ask: live.open.ask && live.open.ask.price } : live.open) : n.open;
  const sideRow = (name, s0) => {
    const own = n.state && n.state[name];                // the bundle's own state carries Python's reason sentence
    const s = s0 && !s0.reason && own && own.reason && own.state === s0.state ? { ...s0, reason: own.reason } : s0;
    const since = s && s.since_us ? ` for ${agoText((Date.now() * 1000 - s.since_us) / 1e6)}` : "";
    return `<div class="side"><b>${name}</b>${statePill(s ? s.state : "UNKNOWN")}<span>${esc(reasonText(s, lots, m.q_max))}${since}</span></div>`;
  };
  const span = Math.max(m.q_max * 1.5, Math.abs(lots || 0) * 1.1, 1);
  const pos = v => 50 + 50 * v / span;
  const barL = Math.min(pos(0), pos(lots || 0)), barW = Math.abs(pos(lots || 0) - pos(0));
  const over = Math.abs(lots || 0) > m.q_max;
  const lastFill = n.last_fill_ms ? agoText((Date.now() - n.last_fill_ms) / 1000) + " ago" : "no fills yet";
  // process: the supervisor's own file (re-read every 30 s) beats the bundle, which is up to 5 minutes old
  const sup = window.LIVE && window.LIVE.supervisor;
  const sp = sup && (sup.processes || []).find(p => m.source === "paper" ? / mm\.paper /.test(" " + p.cmd + " ") && p.cmd.includes(m.symbol)
                                                                     : p.cmd.includes(`--symbols ${m.symbol} `) || p.cmd.endsWith(`--symbols ${m.symbol}`));
  const pr = sp ? { running: sp.running, uptime_s: sp.uptime_s, restarts: sp.restarts } : (n.process || {});
  const proc = pr.running === null || pr.running === undefined ? "process state unknown" : pr.running ? `up ${agoText(pr.uptime_s)}, ${pr.restarts} restart${pr.restarts === 1 ? "" : "s"}` : "not running";
  return `<div class="card state-card"><div class="card-head"><h2>${esc(m.symbol)} · ${esc(m.policy)}</h2></div>
    ${sideRow("bid", st && st.bid)}${sideRow("ask", st && st.ask)}
    <div class="capbar${over ? " over" : ""}" title="${lots} lots, cap ±${m.q_max}"><i style="left:${barL}%;width:${barW}%"></i><em style="left:${pos(-m.q_max)}%"></em><em style="left:${pos(m.q_max)}%"></em></div>
    <p class="legend-note">Inventory ${lots} lots against a cap of ±${m.q_max} (one lot = ${m.lot_usd} USDT)</p>
    <dl class="kv"><dt>Resting bid / ask</dt><dd>${open && isNum(open.bid) ? fmtP(open.bid) : "none"} / ${open && isNum(open.ask) ? fmtP(open.ask) : "none"}</dd>
    <dt>Last fill</dt><dd>${esc(lastFill)}</dd><dt>Process</dt><dd>${esc(proc)}</dd></dl></div>`;
}

/* Page head of the Execution test: the TESTNET label, the purpose line (Python's sentence), what the test caught, the P&L fold summary. */
function drawExecHead() {
  const b = Sess.one(), ex = (((window.STORY || {}).sections || {}).execution) || {};
  const badge = $("xt-badge"), purpose = $("xt-purpose");
  badge.textContent = ex.label || (b ? b.meta.label : ""); badge.hidden = !badge.textContent;
  purpose.textContent = ex.sentence || ""; purpose.hidden = !purpose.textContent;
  if (!b) { fillLv("xt-caught", ""); return; }
  const rows = b.caught || [];
  setSub("xt-caught-sub", tkOf(b).caught || "");
  if (!rows.length) lvEmpty("xt-caught", tkOf(b).caught || "Nothing is recorded as caught for this session yet.");
  else fillLv("xt-caught", `<table class="xt-caught stack"><thead><tr><th>Finding</th><th>Evidence</th><th>Status</th></tr></thead><tbody>${rows.map(r => {
    const st = r.status === "fixed" && r.task ? `fixed, ${r.task}` : r.status;
    return `<tr><td data-label="Finding">${esc(r.finding)}</td><td data-label="Evidence">${esc(r.evidence)}</td><td data-label="Status"><span class="xt-status" data-s="${esc(r.status)}">${esc(st)}</span></td></tr>`; }).join("")}</tbody></table>`);
  const sum = tkOf(b).pnl_summary;
  $("xt-pnl-summary").textContent = sum ? `P&L, for reconciliation only. ${sum}` : "P&L, for reconciliation only";
}

function drawLvOverview() {
  drawLvChart("lvc-exec");
  const bs = Sess.active();
  if (!bs.length) { ["ov2-timeline", "ov2-incidents", "ov2-cum"].forEach(lvWaiting); fillLv("ov2-state", ""); fillLv("ov2-tiles", ""); return; }
  fillLv("ov2-state", bs.map(stateCard).join(""));

  // tiles
  const sums = bs.map(sumRange);
  const tot = k => sums.reduce((a, s) => a + (s[k] || 0), 0);
  const quoting = bs.map(b => (rangeEntry(b) || { tiles: {} }).tiles.quoting_share).filter(isNum);
  const openInc = bs.reduce((a, b) => a + ((rangeEntry(b) || { counts: {} }).counts.open_incidents || 0), 0);
  const win = rangeLabel(bs[0]);                          // every tile names its range (spec 9.1)
  const tile = (k, v, s, cls = "") => `<div class="tile"><div class="k">${k}</div><div class="v ${cls}">${v}</div><div class="s">${s}</div></div>`;
  fillLv("ov2-tiles", [
    tile("Net P&amp;L (USDT)", usdTxt(tot("net")), `${esc(win)}, estimated fees included`, pnlCls(tot("net"))),
    tile("Net excluding artifacts", usdTxt(tot("net") - tot("artifact")), `${esc(win)}, artifacts ${usdTxt(tot("artifact"))}`, pnlCls(tot("net") - tot("artifact"))),
    tile("Fees (estimated)", usdTxt(tot("fees")), `${esc(win)}, at the maker fee, both sides`),
    tile("Fills", nTxt(tot("fills")), `${esc(win)}, ` + (bs.length > 1 ? `${bs.length} sessions` : esc(bs[0].meta.id))),
    tile("Share of time quoting", quoting.length ? pct(quoting.reduce((a, x) => a + x, 0) / quoting.length) : dashes, quoting.length ? `${esc(win)}, average of bid and ask` : "state log starts at the next trader restart"),
    tile("Open incidents", nTxt(openInc), `high or medium, ${esc(win)}`, openInc ? "neg" : ""),
  ].join(""));

  drawTimeline(bs);
  drawIncidentList(bs);
  drawCum(bs);
}

function allIncidents(bs) {
  const out = [];
  bs.forEach(b => b.incidents.filter(i => Sess.inWin(b, i.t0)).forEach(i => out.push({ ...i, sid: b.meta.id, label: `${b.meta.symbol} ${b.meta.policy}`, b })));
  return out.sort((a, b) => b.t0 - a.t0);
}

function drawTimeline(bs) {
  const inc = allIncidents(bs);
  setSub("ov2-tl-sub", bs.length === 1 ? tkOf(bs[0]).state_strip : "One row per session; marks are incidents coloured by severity, over the quote-state band.");
  const traces = ["high", "medium", "low", "info"].map(sev => {
    const r = inc.filter(i => i.severity === sev);
    return { type: "scatter", mode: "markers", name: sev, x: r.map(i => isoT(i.t0)), y: r.map(i => bs.findIndex(b => b.meta.id === i.sid)),
             text: r.map(i => `${esc(i.kind.replace(/_/g, " "))}: ${esc(i.sentence)}`), customdata: r.map(i => i.id + "|" + i.sid), hovertemplate: "%{text}<extra></extra>",
             marker: { color: SEVERITY_COLOR[sev], size: 11, line: { width: 1, color: "#0a0f16" } } };
  });
  const shapes = [];
  bs.forEach((b, row) => ["bid", "ask"].forEach((side, k) => ((b.states || {})[side] || []).forEach(iv => {
    if (!Sess.inWin(b, iv.t1) && !Sess.inWin(b, iv.t0)) return;
    shapes.push({ type: "rect", xref: "x", yref: "y", x0: isoT(iv.t0), x1: isoT(iv.t1), y0: row + (k ? -0.38 : 0.02), y1: row + (k ? -0.02 : 0.38),
                  fillcolor: STATE_COLOR[iv.state] || "#64748b", opacity: iv.state === "QUOTING" ? 0.3 : 0.85, line: { width: 0 }, layer: "below" });
  })));
  const w = bs.length ? Sess.windowOf(bs[0]) : null;
  const lay = { height: Math.max(130, 80 + bs.length * 44), showlegend: true, shapes, hovermode: "closest",
    xaxis: axis("", { type: "date", range: w ? [isoT(w[0]), isoT(w[1])] : undefined }),
    yaxis: axis("", { tickmode: "array", tickvals: bs.map((_, i) => i), ticktext: bs.map(b => `${b.meta.symbol} ${b.meta.policy}`), range: [-0.7, bs.length - 0.3], zeroline: false }),
    margin: { l: 110, r: 16, t: 10, b: 36 } };
  if (!inc.length && !shapes.length) { lvEmpty("ov2-timeline", "No incidents and no state log in this range."); return; }
  $("ov2-timeline").style.height = lay.height + "px";          // one band per session, no empty floor
  deskPlot("ov2-timeline", traces, lay).then(el => {
    el.removeAllListeners && el.removeAllListeners("plotly_click");
    el.on("plotly_click", ev => { const cd = ev.points[0].customdata; if (cd) { const [id, sid] = cd.split("|"); const i = inc.find(x => x.id === id && x.sid === sid); if (i) openIncident(i); } });
  });
}

function openIncident(i) { if (typeof Tape !== "undefined") Tape.open(i.sid, i.t0, i.fills && i.fills[0] !== undefined ? i.fills[0] : null); }

function drawIncidentList(bs) {
  const inc = allIncidents(bs);
  // the counts are Python's (one rule: "open" = high or medium severity), summed over the sessions shown
  const cnt = k => bs.reduce((a, b) => a + ((rangeEntry(b) || { counts: {} }).counts[k] || 0), 0);
  const nInc = cnt("incidents"), nOpen = cnt("open_incidents"), win = rangeLabel(bs[0]);
  setSub("ov2-inc-sub", nInc ? `${nInc} incident${nInc === 1 ? "" : "s"} in ${win}, ${nOpen} of them open (high or medium), newest first. Click one to open the tape around it.` : `No incidents in ${win}.`);
  if (!inc.length) { lvEmpty("ov2-incidents", `No incidents in ${win}: nothing stopped, breached or glitched.`); return; }
  lvTable("ov2-incidents", [
    { k: "t0", label: "Time (UTC)", left: true, f: v => utcStamp(v) },
    { k: "label", label: "Session", left: true },
    { k: "severity", label: "Severity", left: true, v: r => ["info", "low", "medium", "high"].indexOf(r.severity), f: (v, r) => `<span class="sev" style="--c:${SEVERITY_COLOR[r.severity]}">${esc(r.severity)}</span>` },
    { k: "sentence", label: "What happened", left: true, f: v => esc(v) },
    { k: "cost_usd", label: "Cost (USDT, + = lost)", f: v => isNum(v) ? fmt(v, 2) : dashes },
    { k: "open", label: "", left: true, v: () => 0, f: () => "open tape" },
  ], inc.slice(0, 300), { sort: "t0", scroll: true, stack: true, onClick: openIncident });
}

function drawCum(bs) {
  setSub("ov2-cum-sub", bs.length === 1 ? tkOf(bs[0]).cum_pnl : "Net P&L of each session; the dashed line leaves the artifact fills out.");
  const traces = [], shapes = [];
  const single = bs.length === 1;
  bs.forEach((b, k) => {
    const c = b.curve, w = Sess.windowOf(b);
    const idx = c.t.map((t, i) => i).filter(i => !w || (c.t[i] >= w[0] && c.t[i] <= w[1]));
    if (!idx.length) return;
    const base = w && idx.length ? 0 : 0;
    const col = single ? "#e2e8f0" : SERIES[k % SERIES.length];
    traces.push({ type: "scatter", mode: "lines", name: single ? "net" : b.meta.symbol, x: idx.map(i => isoT(c.t[i])), y: idx.map(i => c.pnl[i] - base),
                  line: { color: col, width: 2 }, hovertemplate: "%{y:.2f} USDT<extra>net</extra>" });
    traces.push({ type: "scatter", mode: "lines", name: single ? "net excluding artifacts" : b.meta.symbol + " ex-artifact", x: idx.map(i => isoT(c.t[i])), y: idx.map(i => c.pnl_ex_artifact[i] - base),
                  line: { color: col, width: 1.5, dash: "dash" }, hovertemplate: "%{y:.2f} USDT<extra>ex-artifact</extra>" });
    if (single) {
      traces.push({ type: "scatter", mode: "lines", name: "inventory (lots)", x: idx.map(i => isoT(c.t[i])), y: idx.map(i => c.lots[i]), xaxis: "x", yaxis: "y2",
                    line: { color: "#cbd5e1", width: 1.5, shape: "hv" }, hovertemplate: "%{y} lots<extra></extra>" });
      markerLines(b, ["restart", "loss_stop", "day"]).forEach(s => shapes.push(s));   // incidents are on the timeline above
      stateBands(b, 1.0, 0.03).forEach(s => shapes.push(s));
      [-b.meta.q_max, b.meta.q_max].forEach(q => shapes.push({ type: "line", xref: "paper", yref: "y2", x0: 0, x1: 1, y0: q, y1: q, line: { color: "#818cf8", width: 1, dash: "dot" } }));
    }
  });
  if (!traces.length) { lvEmpty("ov2-cum", "No fills in this range, so there is no P&L curve."); return; }
  const w = bs.length ? Sess.windowOf(bs[0]) : null;
  const lay = single
    ? { shapes, yaxis: axis("USDT", { domain: [0.3, 1], zeroline: true, zerolinewidth: 1.5, zerolinecolor: "#64748b" }), yaxis2: axis("lots", { domain: [0, 0.2], zeroline: true }),
        xaxis: axis("", { type: "date", anchor: "y2", range: w ? [isoT(w[0]), isoT(w[1])] : undefined }), margin: { l: 56, r: 16, t: 10, b: 36 } }
    : { yaxis: axis("USDT", { zeroline: true, zerolinecolor: "#64748b" }), xaxis: axis("", { type: "date", range: w ? [isoT(w[0]), isoT(w[1])] : undefined }) };
  deskPlot("ov2-cum", traces, lay);
}

register("lv-overview", drawLvOverview);
/* A new status.json / snapshot read (every 10 s) refreshes only the state strip, not the charts. */
window.onLiveStatus = () => {
  if (typeof current === "undefined" || current !== "lv-overview") return;
  const bs = Sess.active();
  if (bs.length) fillLv("ov2-state", bs.map(stateCard).join(""));
};
