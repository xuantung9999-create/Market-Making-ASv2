/* live_sessions.js: the live tabs' shell (live spec L5): session list, selector, range buttons, the live
   headline, and the helpers every live view shares. Bundles are written by scripts/build_session.py and load by
   script tag (no fetch): live/sessions.js -> window.SESSIONS, live/session-<id>.js -> window.SESSION_DATA[id].
   Python computes every number and sentence; this file only formats and draws. */

const RANGE_H = { "6h": 6, "24h": 24, "3d": 72, all: null };
const Sess = (() => {
  const S = { list: [], sel: null, last: null, range: "all", loading: {}, errors: {}, tab: null, timer: null };
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private window: the page still works */ } },
  };
  const dirtyLive = () => ["lv-overview", "lv-pnl", "lv-exec", "lv-model", "live"].forEach(markDirty);

  function loadScript(src, ok, fail) {
    const old = document.querySelector(`script[data-live-src="${src}"]`);
    if (old) old.remove();
    const s = document.createElement("script");
    s.src = src + "?t=" + Date.now(); s.dataset.liveSrc = src;
    s.onload = ok; s.onerror = fail || (() => {});
    document.head.appendChild(s);
  }
  function loadSessions() {
    loadScript("live/sessions.js", () => {
      S.list = window.SESSIONS || [];
      fillSelect();
      S.list.forEach(s => ensure(s.id));
    }, () => { S.error = "No session files yet. Start run_24x7.bat on the PC; the supervisor writes them every 5 minutes."; fillSelect(); dirtyLive(); });
  }
  function ensure(id) {
    if (S.loading[id] === "loading") return;
    S.loading[id] = "loading";
    loadScript(`live/session-${id}.js`, () => { S.loading[id] = "done"; delete S.errors[id]; updateHeader(); dirtyLive(); },
               () => { S.loading[id] = "error"; S.errors[id] = true; dirtyLive(); });
  }
  function refresh() {                       // new bundles land every 5 minutes: re-read the list and the loaded bundles
    if (window.PUBLIC_SITE) return;
    loadScript("live/sessions.js", () => {
      S.list = window.SESSIONS || S.list;
      S.list.forEach(s => { S.loading[s.id] = null; ensure(s.id); });
      fillSelect();
    });
  }
  function fillSelect() {
    const sel = $("sess-select");
    if (!sel) return;
    const opts = S.list.map(s => `<option value="${esc(s.id)}">${esc(s.source)} · ${esc(s.symbol)} · ${esc(s.policy)}</option>`);
    const all = S.tab === "l-overview" ? '<option value="ALL">All sessions</option>' : "";      // Overview only
    sel.innerHTML = (S.list.length ? all + opts.join("") : '<option value="">No sessions yet</option>');
    if (!S.sel || (S.sel !== "ALL" && !S.list.some(s => s.id === S.sel))) {
      const saved = store.get("lv-session");
      S.sel = S.list.some(s => s.id === saved) ? saved : (S.list.find(s => s.n_fills > 0) || S.list[0] || {}).id || null;
    }
    if (S.sel === "ALL" && !all) S.sel = S.last || (S.list[0] || {}).id || null;
    sel.value = S.sel || "";
    if (S.sel && S.sel !== "ALL") S.last = S.sel;
    updateHeader();
  }
  /* The session(s) a view should draw: one bundle, or all of them on Overview. */
  function active() {
    const data = window.SESSION_DATA || {};
    if (S.sel === "ALL" && S.tab === "l-overview") return S.list.map(s => data[s.id]).filter(Boolean);
    const id = S.sel === "ALL" ? S.last : S.sel;
    return data[id] ? [data[id]] : [];
  }
  function one() { const a = active(); return a.length ? a[0] : null; }
  /* [t0, t1] in ms of the range buttons, ending at the newest data in the bundle; null = everything. */
  function windowOf(b) {
    const h = RANGE_H[S.range];
    const end = (b && b.meta && b.meta.last_ms) || Date.now();
    return h ? [end - h * 3.6e6, end] : null;
  }
  const inWin = (b, t) => { const w = windowOf(b); return !w || (t >= w[0] && t <= w[1]); };
  function updateHeader() {
    const heads = active();
    if (!$("live-headline") || !$("sess-label")) return;
    $("live-headline").textContent = S.error && !S.list.length ? S.error
      : !S.list.length ? "No sessions yet: the supervisor writes the session files every 5 minutes."
      : !heads.length ? "Loading the session…"
      : heads.length === 1 ? heads[0].headline : heads.map(b => b.headline.split(". ")[0]).join(" · ");
    const b = one(), lab = $("sess-label");
    lab.textContent = b && S.sel !== "ALL" ? b.meta.label : "";
    lab.hidden = !lab.textContent;
    lab.style.setProperty("--c", b && b.meta.source === "paper" ? "#2dd4bf" : "#f5a524");
  }
  function onShow(tab) {
    const was = S.tab; S.tab = tab;
    if (RESEARCH_TABS.includes(tab) || was === tab) return;
    if (was === null || was === "l-overview" || tab === "l-overview" || (RESEARCH_TABS.includes(was))) fillSelect();
    updateHeader();
  }
  function init() {
    const sel = $("sess-select");
    sel.addEventListener("change", () => { S.sel = sel.value; if (S.sel !== "ALL") { S.last = S.sel; store.set("lv-session", S.sel); } updateHeader(); dirtyLive(); });
    S.range = store.get("lv-range") && RANGE_H.hasOwnProperty(store.get("lv-range")) ? store.get("lv-range") : "all";
    const setBtns = () => $("live-range").querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.r === S.range)));
    setBtns();
    $("live-range").addEventListener("click", e => {
      const r = e.target.dataset && e.target.dataset.r;
      if (!r) return;
      S.range = r; store.set("lv-range", r); setBtns(); dirtyLive();
    });
    if (window.PUBLIC_SITE) {
      $("live-headline").textContent = "The live sessions are not published. This copy shows the recorded backtest results under Research.";
      return;
    }
    loadSessions();
    S.timer = setInterval(refresh, 60000);
    if (typeof window.startLive === "function") window.startLive();     // fresh state for the strip, same pollers as Market feed
  }
  /* Programmatic choice of a session (from a click on an incident or fill): same effects as the selector. */
  function select(id) {
    if (S.sel === id) return;
    S.sel = id; S.last = id; store.set("lv-session", id);
    const sel = $("sess-select"); if (sel) sel.value = id;
    updateHeader(); dirtyLive();
  }
  return { init, onShow, active, one, windowOf, inWin, state: S, ensure, refresh, select };
})();

/* ======================= shared helpers for the live views ======================= */
const isoT = ms => new Date(ms).toISOString();
const dashes = "–";
function pctile(arr, p) {
  const a = arr.filter(isNum).sort((x, y) => x - y);
  if (!a.length) return NaN;
  const i = (a.length - 1) * p, lo = Math.floor(i), hi = Math.ceil(i);
  return a[lo] + (a[hi] - a[lo]) * (i - lo);
}
/* Rule 3: a value axis spans the 1st to 99th percentile of the visible data, padded 10%. */
function fitAxis(vals, include = []) {
  const lo0 = pctile(vals, 0.01), hi0 = pctile(vals, 0.99);
  let lo = Math.min(lo0, ...include), hi = Math.max(hi0, ...include);
  if (!isFinite(lo) || !isFinite(hi)) return null;
  if (lo === hi) { lo -= 1; hi += 1; }
  const pad = (hi - lo) * 0.1;
  return [lo - pad, hi + pad];
}
/* Points outside [lo, hi] drawn at the edge as hollow triangles, true value on hover. */
function offScale(xs, ys, rng, color = ART_C, name = "off scale") {
  const x = [], y = [], t = [];
  ys.forEach((v, i) => { if (isNum(v) && (v < rng[0] || v > rng[1])) { x.push(xs[i]); y.push(v < rng[0] ? rng[0] : rng[1]); t.push(v); } });
  return { count: x.length, trace: { x, y, text: t.map(v => fmt(v, 1)), mode: "markers", name, hovertemplate: "off scale: %{text}<extra></extra>",
           marker: { symbol: y.map(v => v === rng[0] ? "triangle-down-open" : "triangle-up-open"), size: 10, color, line: { width: 1.5, color } } } };
}
function offNote(n, unit = "points") { return n ? `${n} ${unit} off scale (hollow triangles at the edge; true value on hover).` : ""; }
/* Rule 4: bid and ask state bands drawn as two thin strips at the top of the chart (paper coordinates). */
function stateBands(b, top = 1.0, h = 0.035) {
  const out = [];
  [["bid", top], ["ask", top - h]].forEach(([side, y1]) => {
    ((b.states || {})[side] || []).forEach(iv => {
      if (iv.state === "QUOTING") { out.push(band(iv, y1, h, STATE_COLOR.QUOTING, 0.35)); return; }
      out.push(band(iv, y1, h, STATE_COLOR[iv.state] || "#64748b", 0.9));
    });
  });
  return out;
}
const band = (iv, y1, h, color, op) => ({ type: "rect", xref: "x", yref: "paper", x0: isoT(iv.t0), x1: isoT(iv.t1), y0: y1 - h, y1, fillcolor: color, opacity: op, line: { width: 0 }, layer: "below" });
function markerLines(b, kinds = ["restart", "loss_stop", "day", "incident"]) {
  const col = { restart: "#e2e8f0", loss_stop: "#fb923c", day: "#334155", incident: "#facc15" };
  const dash = { restart: "dot", loss_stop: "solid", day: "dot", incident: "dash" };
  return (b.markers || []).filter(m => kinds.includes(m.kind) && Sess.inWin(b, m.t)).map(m => ({ type: "line", xref: "x", yref: "paper", x0: isoT(m.t), x1: isoT(m.t), y0: 0, y1: 1,
    line: { color: col[m.kind] || "#64748b", width: m.kind === "day" ? 1 : 1.5, dash: dash[m.kind] || "dot" }, layer: "below" }));
}
function lvRange(b) { const w = Sess.windowOf(b); return w ? [isoT(w[0]), isoT(w[1])] : null; }
function setSub(id, text) { const el = $(id); if (el) el.textContent = text || ""; }
/* Rule 1: an empty panel says why, and since when. */
function lvEmpty(id, msg) { emptyPanel(id, msg); }
function lvWaiting(id) { return lvEmpty(id, Sess.state.error || (Sess.state.list.length ? "Loading the session…" : "No sessions yet: the supervisor writes the session files every 5 minutes.")); }
function fillLv(id, html) { const el = $(id); el.classList.remove("is-empty"); el.innerHTML = html; }
const stateName = s => String(s || "UNKNOWN").replace(/_/g, " ").toLowerCase();
function agoText(sec) { return sec === null || sec === undefined || !isFinite(sec) ? dashes : sec < 90 ? `${Math.round(sec)} s` : sec < 5400 ? `${Math.round(sec / 60)} min` : sec < 172800 ? `${(sec / 3600).toFixed(1)} h` : `${Math.round(sec / 86400)} d`; }
const utcStamp = ms => isNum(ms) ? new Date(ms).toISOString().slice(5, 16).replace("T", " ") + " UTC" : dashes;
/* The reason behind a state, from its logged detail (formatting only). */
function reasonText(st, lots, qMax) {
  if (!st) return "";
  const d = st.detail;
  switch (st.state) {
    case "INV_CAP": return `at inventory cap (${isNum(lots) ? lots : (d && d.lots)} of ${qMax} lots)`;
    case "NO_BALANCE": return d && typeof d === "object" ? `blocked by balance: need ${fmtP(d.need)}, free ${fmtP(d.free)} ${d.asset || ""}` : "blocked by balance";
    case "LOSS_STOP": return d && isNum(d.pnl_day) ? `daily loss stop (day ${sign(d.pnl_day)} of −${d.max_loss} USDT)` : "daily loss stop";
    case "POLICY_OUT": return "the policy stays out" + (d && d.live_arm !== undefined && d.live_arm !== null ? ` (arm ${d.live_arm}${isNum(d.score_bp) ? `, score ${sign(d.score_bp)} bp` : ""})` : "");
    case "REJECTED": return "last order rejected: " + esc(String(d || "").slice(0, 80));
    case "WARMUP": return "warming up";
    case "STALE_FEED": return "no recent book update";
    case "EXCHANGE_ERROR": return "exchange error: " + esc(String(d || "").slice(0, 80));
    case "BELOW_MIN": return "below the exchange minimum";
    case "QUOTING": return "order resting";
    default: return typeof d === "string" ? esc(d) : "reason not recorded yet";
  }
}
const statePill = s => `<span class="pill" style="--c:${STATE_COLOR[s] || STATE_COLOR.UNKNOWN}">${esc(stateName(s))}</span>`;

/* Sortable table: rows = objects, cols = [{k, label, f(value,row), left}], optional row class and click. */
function lvTable(hostId, cols, rows, opt = {}) {
  const host = $(hostId);
  host.classList.remove("is-empty");
  if (!rows.length) { lvEmpty(hostId, opt.empty || "Nothing to show."); return; }
  const st = host._sort || (host._sort = { k: opt.sort || null, dir: -1 });
  let r = rows.slice();
  if (opt.presorted) st.k = opt.sort, st.dir = opt.dir || -1;
  else if (st.k) { const c = cols.find(c => c.k === st.k); r.sort((a, b) => { const x = c.v ? c.v(a) : a[st.k], y = c.v ? c.v(b) : b[st.k]; return (x === y ? 0 : x === null || x === undefined ? 1 : y === null || y === undefined ? -1 : x < y ? -1 : 1) * st.dir; }); }
  const head = cols.map(c => `<th class="${c.left ? "l" : ""}" data-k="${esc(c.k)}">${esc(c.label)}${st.k === c.k ? (st.dir < 0 ? " ↓" : " ↑") : ""}</th>`).join("");
  const body = r.map((row, i) => `<tr class="${opt.rowClass ? opt.rowClass(row) : ""}${opt.onClick ? " click" : ""}" data-i="${i}">` +
    cols.map(c => `<td class="${c.left ? "l" : ""}">${c.f ? c.f(c.v ? c.v(row) : row[c.k], row) : esc(row[c.k] ?? dashes)}</td>`).join("") + "</tr>").join("");
  host.innerHTML = `<div class="table-wrap${opt.scroll ? " scroll" : ""}"><table class="lv"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
  host.querySelectorAll("th").forEach(th => th.addEventListener("click", () => {
    if (opt.onSort) { opt.onSort(th.dataset.k); return; }
    st.dir = st.k === th.dataset.k ? -st.dir : -1; st.k = th.dataset.k; lvTable(hostId, cols, rows, opt);
  }));
  if (opt.onClick) host.querySelectorAll("tbody tr").forEach(tr => tr.addEventListener("click", () => opt.onClick(r[+tr.dataset.i])));
}
const bpTxt = x => isNum(x) ? sign(x, 1) : dashes;
const usdTxt = x => isNum(x) ? sign(x, 2) : dashes;
const nTxt = (x, d = 0) => isNum(x) ? fmt(x, d) : dashes;
