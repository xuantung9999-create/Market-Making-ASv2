/* pcstatus.js: Live > PC status. What the 24/7 PC is doing right now: the supervisor and its processes,
   the testnet traders (real orders, fake money) and the order-book recorder.
   Data: live/status.js (window.LIVE), written every minute by scripts/build_live.py (run by
   scripts/supervise_live.py). Re-read every 30 s. Not in git: open the dashboard on the PC to see it. */

const LIVE_REFRESH_MS = 30000;
let liveLoadedOnce = false, liveError = "";

function loadLive() {
  const old = document.getElementById("live-src");
  if (old) old.remove();
  const s = document.createElement("script");
  s.id = "live-src";
  s.src = `live/status.js?t=${Date.now()}`;
  s.onload = () => { liveLoadedOnce = true; liveError = ""; markDirty("pcstatus"); };
  s.onerror = () => { liveError = "No live data yet. Start run_24x7.bat on the PC, then open this page on that PC (live numbers are not published to GitHub)."; markDirty("pcstatus"); };
  document.head.appendChild(s);
}

const ageText = s => !isNum(s) ? "–" : s < 90 ? `${Math.round(s)} s` : s < 5400 ? `${Math.round(s / 60)} min` : s < 172800 ? `${fmt(s / 3600, 1)} h` : `${fmt(s / 86400, 1)} d`;
const dot = (ok, warn) => `<span class="live-dot" style="--c:${ok ? "#22c55e" : warn ? "#f5a524" : "#ef4444"}"></span>`;
const utc = ms => isNum(ms) ? new Date(ms).toISOString().replace("T", " ").slice(0, 19) : "–";
const sideTxt = s => s > 0 ? '<span style="color:var(--bid)">BUY</span>' : s < 0 ? '<span style="color:var(--ask)">SELL</span>' : "–";

function drawLiveHeader(L) {
  const sup = L.supervisor, now = Date.now();
  const supAge = sup ? (now - sup.updated_ms) / 1000 : null;
  const supOk = sup && !sup.stopped && supAge < 180;
  const tn = L.testnet || [];
  const pnl = tn.reduce((a, t) => a + (t.status && isNum(t.status.pnl) ? t.status.pnl : 0), 0);
  const fills = tn.reduce((a, t) => a + (t.fills_24h || 0), 0);
  const rec = L.recorder || [];
  const recOk = rec.filter(r => r.book && isNum(r.book.age_s) && r.book.age_s < 180).length;
  const tiles = [
    ["Supervisor", sup ? (supOk ? "RUNNING" : sup.stopped ? "STOPPED" : "NOT RESPONDING") : "–", supOk ? "pos" : "neg",
     sup ? `${sup.host || "PC"} · last heartbeat ${ageText(supAge)} ago` : "no heartbeat file yet"],
    ["Up since", sup ? utc(sup.since_ms).slice(5, 16) : "–", "", "UTC"],
    ["Recorder streams live", rec.length ? `${recOk} / ${rec.length}` : "–", rec.length && recOk === rec.length ? "pos" : rec.length ? "neg" : "", "book updated in the last 3 min"],
    ["Page data", ageText((now - L.built_ms) / 1000) + " old", (now - L.built_ms) < 180000 ? "" : "neg", "refreshes every 30 s"],
    ["Open on phone / laptop", sup && sup.dashboard_urls && sup.dashboard_urls.length ? `<span style="font-size:15px">${esc(sup.dashboard_urls[0].replace("http://", ""))}</span>` : "–", "", "same Wi-Fi as the PC"],
  ];
  fillHtml("live-tiles", tiles.map(t => `<div class="tile"><div class="k">${t[0]}</div><div class="v ${t[2]}">${t[1]}</div><div class="s">${t[3]}</div></div>`).join(""));

  if (!sup) return emptyPanel("live-procs", "The supervisor has not written a heartbeat yet");
  const rows = sup.processes.map(p => `<tr><td>${dot(p.running, p.waiting)} ${esc(p.name)}</td>
    <td>${p.running ? "running" : p.waiting ? esc(p.waiting) : "restarting"}</td><td>${p.running ? ageText(p.uptime_s) : "–"}</td>
    <td>${fmt(p.restarts, 0)}</td><td>${p.last_exit === null || p.last_exit === undefined ? "–" : esc(p.last_exit) + " at " + esc(p.last_exit_utc)}</td>
    <td style="font-size:12px;color:var(--muted)">${esc(p.cmd)}</td></tr>`).join("");
  fillHtml("live-procs", `<table><thead><tr><th>Process</th><th>State</th><th>Uptime</th><th>Restarts</th><th>Last exit (code, UTC)</th><th>Command</th></tr></thead><tbody>${rows}</tbody></table>`
    + (sup.keys ? "" : '<p class="sub" style="margin-top:8px">Testnet traders are waiting: put BINANCE_TESTNET_API_KEY and BINANCE_TESTNET_API_SECRET in .env on the PC. They start within a minute.</p>'));
}

function drawLiveRecorder(L) {
  const rec = L.recorder || [];
  if (!rec.length) return emptyPanel("live-rec", "The recorder has not written any files yet");
  const cell = k => { const a = k && k.age_s; return `${dot(isNum(a) && a < 180, isNum(a) && a < 600)} ${ageText(a)}`; };
  const rows = rec.map(r => `<tr><td>${esc(r.symbol)}</td><td>${cell(r.book)}</td><td>${cell(r.trades)}</td>
    <td>${fmt(r.book.parts_24h, 0)}</td><td class="${r.book.gaps_24h ? "neg" : ""}">${fmt(r.book.gaps_24h, 0)}</td><td>${fmt(r.book.gap_minutes_24h, 1)}</td>
    <td>${isNum(r.book.rows_last_part) ? fmt(r.book.rows_last_part, 0) : "–"}</td><td>${isNum(r.trades.rows_last_part) ? fmt(r.trades.rows_last_part, 0) : "–"}</td>
    <td>${fmt(r.book.total_parts, 0)}</td></tr>`).join("");
  fillHtml("live-rec", `<table><thead><tr><th>Symbol</th><th>Book: last write</th><th>Trades: last write</th><th>Book files 24 h</th><th>Gaps &gt;3 min (24 h)</th><th>Gap minutes</th><th>Book rows, last file</th><th>Trade rows, last file</th><th>Book files total</th></tr></thead><tbody>${rows}</tbody></table>`);
}

register("pcstatus", () => {
  const msg = $("pcs-msg"), body = $("pcs-body");
  const L = window.LIVE;
  if (!L && window.PUBLIC_SITE) { msg.textContent = 'This is the public copy of the dashboard. The live feed comes from the order-book recorder and two testnet traders that run 24/7 on my PC, and those numbers are not published. Every other tab shows the recorded results.'; msg.hidden = false; body.hidden = true; return; }
  if (!L) { msg.textContent = liveError || "Loading live status…"; msg.hidden = false; body.hidden = true; return; }
  msg.hidden = true; body.hidden = false;
  drawLiveHeader(L); drawLiveRecorder(L);      // the testnet panels moved to Overview, P&L and Execution (live spec L10)
});
if (!window.PUBLIC_SITE) { loadLive(); setInterval(loadLive, LIVE_REFRESH_MS); }
