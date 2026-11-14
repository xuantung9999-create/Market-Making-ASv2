/* live.js: the Live tab and the only file that calls fetch() (Dashboard Redesign R7).
   Polls three kinds of file, only when the page is served over http(s):
     /data/live/heartbeat.json            every 2 s   (written by mm/recorder.py)
     /data/paper/snapshot.json            every 10 s  (paper trader, when running)
     /data/testnet/<SYM>/status.json      every 10 s  (testnet trader, when running)
   One failed read keeps the screen as it was; three in a row show "no live feed". */

const LIVE_EVERY = { heartbeat: 2000, other: 10000 };
const LIVE_GIVE_UP = 3;

function newSource() { return { data: null, fails: 0, okAt: null }; }
function record(s, ok, data, now) {
  if (ok) { s.data = data; s.fails = 0; s.okAt = now; } else s.fails += 1;
  return s;
}
/* waiting: nothing read yet | ok | retry: last read failed, old data kept | nofeed: three failures in a row */
function status(s) {
  if (s.fails >= LIVE_GIVE_UP) return "nofeed";
  if (!s.data) return "waiting";
  return s.fails > 0 ? "retry" : "ok";
}
function ageClass(sec) { return sec === null || sec === undefined || !isFinite(sec) ? "na" : sec > 60 ? "red" : sec > 10 ? "amber" : "ok"; }

if (typeof module !== "undefined") module.exports = { newSource, record, status, ageClass };

if (typeof document !== "undefined") (function () {
  const heartbeat = newSource(), paper = newSource(), testnet = {};
  let timers = [], running = false;

  const ageSec = iso => { const t = Date.parse(iso); return isFinite(t) ? Math.max(0, (Date.now() - t) / 1000) : null; };
  const ageText = s => s === null ? "–" : s < 90 ? `${Math.round(s)} s ago` : s < 5400 ? `${Math.round(s / 60)} min ago` : `${(s / 3600).toFixed(1)} h ago`;
  const ageHtml = (iso, cls) => { const s = ageSec(iso); return `<span class="age ${cls || ageClass(s)}">${ageText(s)}</span>`; };

  async function get(url) {
    const r = await fetch(url, { cache: "no-store" });
    if (!r.ok) throw new Error(url + " " + r.status);
    return r.json();
  }
  async function poll(src, url, after) {
    try { record(src, true, await get(url), Date.now()); } catch (e) { record(src, false, null, Date.now()); }
    if (after) after();
    renderLive();
    if (typeof window.onLiveStatus === "function") window.onLiveStatus();
  }
  function pollTestnet() {
    const syms = new Set(heartbeat.data ? Object.keys(heartbeat.data.symbols || {}) : []);
    ((window.LIVE && window.LIVE.testnet) || []).forEach(t => t.symbol && syms.add(t.symbol));   // traders outside the recorded coins (PC status data)
    syms.forEach(sym => { const s = testnet[sym] || (testnet[sym] = newSource()); poll(s, `/data/testnet/${encodeURIComponent(sym)}/status.json`); });
  }

  function startLive() {
    if (running || !/^https?:$/.test(location.protocol)) return;
    running = true;
    poll(heartbeat, "/data/live/heartbeat.json", pollTestnet);
    poll(paper, "/data/paper/snapshot.json");
    timers = [setInterval(() => poll(heartbeat, "/data/live/heartbeat.json"), LIVE_EVERY.heartbeat),
              setInterval(() => { poll(paper, "/data/paper/snapshot.json"); pollTestnet(); }, LIVE_EVERY.other),
              setInterval(renderLive, 1000)];
  }

  const num = (x, d = 2) => isNum(x) ? fmt(x, d) : "–";
  const g = (cls, html) => `<div class="${cls}">${html}</div>`;

  function feedCard(sym, r, dim) {
    const spBp = isNum(r.bid) && isNum(r.ask) && r.bid > 0 ? (r.ask - r.bid) / ((r.ask + r.bid) / 2) * 1e4 : null;
    const tot = (r.bid_qty || 0) + (r.ask_qty || 0), imb = tot > 0 ? (r.bid_qty - r.ask_qty) / tot : null;
    const trades = (r.last_trades || []).slice(-6).reverse().map(t =>
      `<tr><td>${esc(String(t.t).slice(11, 23))}</td><td style="color:${t.side > 0 ? SERIES[0] : SERIES[1]}">${t.side > 0 ? "buy" : "sell"}</td><td>${fmtP(t.price)}</td><td>${fmtP(t.qty)}</td></tr>`).join("");
    return `<div class="card live-card${dim ? " dim" : ""}"><div class="card-head"><h2>${esc(sym)}</h2>${ageHtml(r.last_book_utc)}</div>
      <div class="live-px"><span style="color:${SERIES[0]}">${isNum(r.bid) ? fmtP(r.bid) : "–"}</span><span class="note"> / </span><span style="color:${SERIES[1]}">${isNum(r.ask) ? fmtP(r.ask) : "–"}</span></div>
      <dl class="kv"><dt>Size bid / ask</dt><dd>${fmtP(r.bid_qty)} / ${fmtP(r.ask_qty)}</dd><dt>Imbalance</dt><dd>${imb === null ? "–" : sign(imb, 2)}</dd>
      <dt>Spread</dt><dd>${spBp === null ? "–" : fmt(spBp, 1) + " bp"}</dd><dt>Book updates / min</dt><dd>${num(r.book_per_min, 0)}</dd>
      <dt>Trades / min</dt><dd>${num(r.trades_per_min, 0)}</dd><dt>Last trade</dt><dd>${ageHtml(r.last_trade_utc)}</dd></dl>
      <table class="mini"><tbody>${trades || '<tr><td class="note">no trades yet</td></tr>'}</tbody></table></div>`;
  }

  function renderFeed() {
    const st = status(heartbeat), host = $("lv-feed"), bar = $("lv-status");
    if (!/^https?:$/.test(location.protocol)) {
      bar.innerHTML = '<span class="age na">Not served over http</span> The live feed needs the dashboard served by a web server (docker compose up dashboard, then open http://localhost:8000/dashboard/index.html).';
      host.innerHTML = ""; return;
    }
    if (st === "waiting") { bar.innerHTML = '<span class="age na">Waiting</span> Reading the recorder heartbeat…'; host.innerHTML = ""; return; }
    const hb = heartbeat.data;
    if (st === "nofeed" && !hb) {
      bar.innerHTML = '<span class="age red">No live feed</span> Nothing at data/live/heartbeat.json. Is the recorder running (run_recorder_multi.bat)?';
      host.innerHTML = ""; return;
    }
    const age = ageSec(hb.ts_utc), cls = st === "nofeed" ? "red" : ageClass(age);
    bar.innerHTML = `<span class="age ${cls}">${st === "nofeed" ? "No live feed" : st === "retry" ? "Retrying" : cls === "ok" ? "Live" : "Stale"}</span> Recorder heartbeat ${ageHtml(hb.ts_utc, cls)}` +
      (st === "nofeed" ? ", showing the last values (greyed)" : "");
    host.className = "live-grid" + (st === "nofeed" ? " dim" : "");
    host.innerHTML = Object.keys(hb.symbols || {}).sort().map(s => feedCard(s, hb.symbols[s], st === "nofeed")).join("") || '<p class="note">The heartbeat lists no symbols.</p>';
  }

  function renderTestnet() {
    const host = $("lv-testnet");
    const rows = Object.keys(testnet).filter(s => testnet[s].data).sort();
    if (!rows.length) { host.innerHTML = '<p class="empty-line">No testnet trader running (nothing at data/testnet/&lt;coin&gt;/status.json).</p>'; return; }
    host.innerHTML = rows.map(sym => {
      const r = testnet[sym].data, dim = status(testnet[sym]) === "nofeed";
      return `<div class="card live-card${dim ? " dim" : ""}"><div class="card-head"><h2>${esc(sym)}</h2><span class="badge" style="--c:#f5a524">TESTNET</span></div>
        <p class="note cap">TESTNET: execution test, not a result</p>
        <dl class="kv"><dt>Inventory (lots)</dt><dd>${num(r.lots, 0)}</dd><dt>P&amp;L (USD)</dt><dd class="${pnlCls(r.pnl)}">${isNum(r.pnl) ? sign(r.pnl) : "–"}</dd>
        <dt>Fills / rejects</dt><dd>${num(r.fills, 0)} / ${num(r.rejects, 0)}</dd><dt>Live arm</dt><dd>${isNum(r.live_arm) ? r.live_arm : "–"}</dd>
        <dt>Resting bid / ask</dt><dd>${r.open ? `${r.open.bid === null || r.open.bid === undefined ? "–" : fmtP(r.open.bid)} / ${r.open.ask === null || r.open.ask === undefined ? "–" : fmtP(r.open.ask)}` : "–"}</dd>
        <dt>Loss stop</dt><dd class="${r.stopped ? "flag-on" : ""}">${r.stopped ? "STOP" : "no"}</dd><dt>Updated</dt><dd>${ageHtml(r.ts)}</dd></dl></div>`;
    }).join("");
  }

  function renderPaper() {
    const host = $("lv-paper"), p = paper.data;
    if (!p) { host.innerHTML = '<p class="empty-line">No paper trader running (nothing at data/paper/snapshot.json).</p>'; return; }
    const dim = status(paper) === "nofeed";
    host.innerHTML = Object.keys(p.symbols || {}).sort().map(sym => {
      const r = p.symbols[sym], o = r.orders || {}, q = side => o[side] ? `${fmtP(o[side].price)} (queue ${fmtP(o[side].queue_ahead)})` : "–";
      return `<div class="card live-card${dim ? " dim" : ""}"><div class="card-head"><h2>${esc(sym)}</h2><span class="badge" style="--c:#f5a524">${esc(String(p.kind || "paper").toUpperCase())}</span></div>
        <dl class="kv"><dt>Bid / ask</dt><dd>${fmtP(r.bid)} / ${fmtP(r.ask)}</dd><dt>Inventory (lots)</dt><dd>${num(r.q, 0)}</dd>
        <dt>P&amp;L today (USD)</dt><dd class="${pnlCls(r.pnl_day)}">${isNum(r.pnl_day) ? sign(r.pnl_day) : "–"}</dd><dt>Fills today</dt><dd>${num(r.fills_day, 0)}</dd>
        <dt>Resting bid</dt><dd>${q("bid")}</dd><dt>Resting ask</dt><dd>${q("ask")}</dd>
        <dt>Live arm</dt><dd>${isNum(r.live_arm) ? r.live_arm : "–"}</dd><dt>Loss stop</dt><dd class="${r.loss_stop ? "flag-on" : ""}">${r.loss_stop ? "STOP" : "no"}</dd>
        <dt>Updated</dt><dd>${ageHtml(p.ts_utc)}</dd></dl></div>`;
    }).join("") || '<p class="empty-line">The paper snapshot lists no symbols.</p>';
  }

  function renderLive() {
    if (typeof current === "undefined" || (current !== "live" && current !== "pcstatus")) return;
    renderFeed(); renderTestnet(); renderPaper();
  }
  register("live", () => {
    if (window.PUBLIC_SITE) {
      $("lv-status").innerHTML = '<span class="age amber">Not published</span> ' + esc('This is the public copy of the dashboard. The live feed comes from the order-book recorder and two testnet traders that run 24/7 on my PC, and those numbers are not published. Every other tab shows the recorded results.');
      ["lv-feed", "lv-testnet", "lv-paper"].forEach(id => { $(id).innerHTML = ""; });
      return;
    }
    startLive(); renderLive();
  });
  window.startLive = startLive;
  /* Fresh numbers for the live tabs' state strip: the newest status.json / paper snapshot read, with its age. */
  window.liveStatusFor = (source, sym) => {
    if (source === "paper") { const r = paper.data && paper.data.symbols && paper.data.symbols[sym]; return r ? { ...r, ts: paper.data.ts_utc } : null; }
    return testnet[sym] && testnet[sym].data ? testnet[sym].data : null;
  };
})();
