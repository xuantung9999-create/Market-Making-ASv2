/* core.js: shared theme, formatters, Plotly helpers and the tab router.
   Loaded after Plotly and data.js, before any js/views/*.js file. */
/* ---------- Edit these for your CV / website ---------- */
const SITE = {
  stage: "v2 · Gate A evaluated",
  author: "Xuân Tùng",
  github: "https://github.com/xuantung9999-create/Market-Making-ASv2",
  linkedin: "https://www.linkedin.com/in/tungtea-nguyen",
  dayOfPlan: 10,
  planDays: 14,
};
const ROADMAP = [
  ["D1", "done", "Derivation of the reservation price and spread"],
  ["D2", "done", "Quoting engine + unit tests"],
  ["D3", "done", "Paper replication simulator"],
  ["D4", "done", "Monte Carlo and stress experiments"],
  ["D5", "done", "Binance data pipeline and live recorder"],
  ["D6", "done", "Event-driven backtester with fees and latency"],
  ["D7", "done", "First real-data run, metrics and week-1 review"],
  ["D8", "done", "Calibration of σ, A, k, tick and spread for 12 coins, BTC to micro caps"],
  ["D9", "done", "Walk-forward calibration (3 days → next day), two-part fill curve, flow model, kill switch"],
  ["D9b", "done", "GLFT quotes and a 32-setting parameter sweep, tuned only on past days"],
  ["D10", "done", "Cross-asset signals (BTC spot and perp), live order-book study, latency measured"],
  ["D10–11", "done", "Dashboard (pulled forward), extended as results arrive"],
  ["v2 0–8", "done", "Queue engine, coin screener, edge table, self-calibrating agent; first honest test: join-the-best loses once the queue is modelled"],
  ["v2 9–11", "done", "Tape check against the real book, paper trader, daily supervisor (built and tested; waiting for live data)"],
  ["Gate A", "done", "60-day walk-forward: FAIL, the agent found no edge and stayed out (pre-registered, not tuned)"],
  ["Live data", "next", "Record the real order book for 3+ days; validate the inferred book; re-test with book imbalance"],
  ["Gate B", "todo", "Paper trading only if a re-test passes Gate A"],
  ["Write-up", "todo", "Write-up and release"],
];
/* ------------------------------------------------------ */

const D = window.DASH || null;
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const C = { text: css("--text"), muted: css("--muted"), line: css("--line"), grid: css("--grid"), panel: css("--panel"),
            accent: css("--accent"), bench: css("--bench"), bid: css("--bid"), ask: css("--ask") };
const MONO = "IBM Plex Mono, Consolas, monospace";
const fmtP = x => (x === null || x === undefined || !isFinite(x)) ? "–" : Math.abs(x) >= 1000 ? Number(x).toLocaleString("en-US", { maximumFractionDigits: 0 }) : Number(Number(x).toPrecision(5)).toString();
const fmt = (x, d = 2) => (x === null || x === undefined || !isFinite(x)) ? "–" : Number(x).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const rgba = (hex, a) => { const n = parseInt(hex.slice(1), 16); return `rgba(${n >> 16},${(n >> 8) & 255},${n & 255},${a})`; };
const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function axis(title, extra = {}) {
  return Object.assign({ title: { text: title, font: { size: 12, color: C.muted } }, gridcolor: C.grid, zerolinecolor: C.line,
                         linecolor: C.line, tickfont: { family: MONO, size: 11, color: C.muted }, automargin: true }, extra);
}
function layout(extra = {}) {
  const lay = baseLayout(extra);
  // log axes: label powers of ten only (Plotly's default labels every 2 and 5 in between, which reads as noise)
  Object.keys(lay).forEach(k => {
    const a = lay[k];
    if (/^[xy]axis\d*$/.test(k) && a && a.type === "log" && a.tickvals === undefined && a.dtick === undefined) { a.dtick = 1; a.minor = { showgrid: false }; }
  });
  return lay;
}
function baseLayout(extra = {}) {
  return Object.assign({
    paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "IBM Plex Sans, system-ui, sans-serif", color: C.muted, size: 12 },
    margin: { l: 56, r: 16, t: 10, b: 44 }, showlegend: true,
    legend: { orientation: "h", x: 0, y: 1.02, yanchor: "bottom", font: { size: 11 } },
    hoverlabel: { bgcolor: C.panel, bordercolor: C.line, font: { family: MONO, color: C.text, size: 12 } },
    hovermode: "x unified",
  }, extra);
}
const CONFIG = { displaylogo: false, responsive: true, modeBarButtonsToRemove: ["lasso2d", "select2d", "autoScale2d"] };
const plot = (id, data, lay) => Plotly.react(id, data, layout(lay), CONFIG);

/* ======================= Router =======================
   Views register themselves: register(name, drawFn). A view is drawn the first time it is shown
   and again only after markDirty(name). Tabs group views: a tab with several views shows them as
   sub-tabs, and the hash is #tab or #tab/view. Old hashes (#model, #signals, #real-data ...) still work. */
const VIEWS = [];
const dirty = {};
const draw = {};
/* Showcase shell (spec section 5): Story, then Evidence (Verdict, Fill economics, Agent, Execution test), then an
   Appendix menu. Every view id stays; the old tab keys that disappeared resolve through ALIASES, so every old hash works.
   "live" and "pcstatus" are Operations (localhost only on the public copy). */
const TABS = {
  "story":        { label: "Story", views: ["story"] },
  "verdict":      { label: "Verdict", views: ["overview"] },
  "fills":        { label: "Fill economics", views: ["execution"] },
  "agent":        { label: "Agent", views: [["model-health", "Edge table"], ["signals", "Signals"], ["lv-model", "Live on real data"]] },
  "exec-test":    { label: "Execution test", views: ["lv-overview"] },       // one page; its P&L and tape are sections (#exec-test/pnl, #exec-test/tape)
  "l-health":     { label: "Operations", views: [["live", "Market feed"], ["pcstatus", "PC status"]] },
  "book":         { label: "Market book", views: [["book", "Order book"], ["market", "Universe"]] },
  "pnl":          { label: "Backtest P&L", views: ["pnl"] },
  "risk":         { label: "Risk", views: ["risk"] },
  "data":         { label: "Data", views: [["health", "Recorder health"], ["simlive", "Sim vs live"]] },
  "simulator":    { label: "Simulator", views: [["simulator", "Playground"], ["model", "How it quotes"], ["replication", "Paper replication"]] },
  "archive":      { label: "Research archive", views: [["real-data", "Real data"], ["backtest", "Backtest"], ["universe", "BTC to micro caps"],
                                                       ["informed", "Informed traders"], ["tuning", "Tuning and signals"]] },
  "about":        { label: "Method and limits", views: ["about"] },
};
/* Old first hash segments that are no longer a tab key -> "tab" or "tab/view". */
const ALIASES = {
  "overview": "verdict", "execution": "fills", "model-health": "agent",
  "l-overview": "exec-test", "l-pnl": "exec-test/pnl", "l-exec": "exec-test/tape", "l-model": "agent/lv-model",
};
const viewIds = t => TABS[t].views.map(v => Array.isArray(v) ? v[0] : v);
const VIEW_TAB = {};
Object.keys(TABS).forEach(t => viewIds(t).forEach(v => { VIEW_TAB[v] = t; }));
const EVIDENCE_TABS = ["verdict", "fills", "agent", "exec-test"];
const APPENDIX_TABS = ["pnl", "risk", "book", "data", "simulator", "archive", "about", "l-health"];
const LIVE_VIEWS = ["lv-overview", "lv-pnl", "lv-exec", "lv-model"];     // the views that use the session selector and range buttons
const DEFAULT_VIEW = { tab: "story", view: "story" };/* Quote-state palette, defined once. Green and red are reserved for profit and loss, bid blue and ask amber for
   the two sides, purple for artifacts only. */
const BID_C = "#38bdf8", ASK_C = "#f5a524", ART_C = "#a78bfa";
const STATE_COLOR = { QUOTING: "#475569", WARMUP: "#94a3b8", POLICY_OUT: "#2dd4bf", LOSS_STOP: "#fb923c", INV_CAP: "#818cf8",
                      NO_BALANCE: "#f472b6", BELOW_MIN: "#cbd5e1", REJECTED: "#e879f9", STALE_FEED: "#64748b",
                      EXCHANGE_ERROR: "#facc15", UNKNOWN: "#334155" };
const SEVERITY_COLOR = { high: "#fb923c", medium: "#facc15", low: "#94a3b8", info: "#64748b" };
function register(name, fn, initiallyDirty = true) {
  if (!VIEWS.includes(name)) VIEWS.push(name);
  draw[name] = fn; dirty[name] = initiallyDirty;
}
function markDirty(name) { dirty[name] = true; if (name === current) renderVisible(); }
let current = null, currentTab = null;
function renderVisible() { if (current && dirty[current]) { dirty[current] = false; draw[current](); } }
/* "#simulator/replication" | "#replication" | "#simulator" | "#l-exec" -> {tab, view, section}. A second segment that is not
   a view of the tab is a section anchor ("#exec-test/tape"): the page scrolls to it instead of to the top. */
function resolveHash(h) {
  let [a, b] = String(h || "").replace(/^#/, "").split("/");
  if (ALIASES[a]) { const [a2, b2] = ALIASES[a].split("/"); a = a2; b = b || b2; }
  const tab = TABS[a] ? a : VIEW_TAB[a];
  if (!tab || (typeof window !== "undefined" && window.PUBLIC_SITE && tab === "l-health")) return { tab: DEFAULT_VIEW.tab, view: DEFAULT_VIEW.view, section: null };
  const ids = viewIds(tab);
  let view = null, section = null;
  if (!TABS[a]) view = a;
  else if (b && ids.includes(b)) view = b;
  else if (b) section = b;
  return { tab, view: view || ids[0], section };
}
/* Segmented control that shows one nested view of a tab; the choice lives in the hash. */
function subtabs(hostId, items, tab) {
  const host = $(hostId);
  if (!host) return;
  host.innerHTML = items.map(([id, label]) => `<a href="#${tab}/${id}" data-sub="${id}" role="tab">${esc(label)}</a>`).join("");
}
/* One provenance line, and only the parts that apply to the page (spec section 6, B11): the backtest build for the
   backtest pages, the live data (or the frozen snapshot on the public copy) for the live ones, both on the Story. */
function drawFooter() {
  const el = $("foot-built");
  if (!el) return;
  const live = LIVE_VIEWS.includes(current) || ["live", "pcstatus"].includes(current), story = current === "story";
  const stamp = ms => new Date(ms).toISOString().slice(0, 16).replace("T", " ") + " UTC";
  const parts = [];
  if (story || !live) parts.push(D ? `Backtest built ${D.built}` : "data.js not found: run python -m scripts.build_dashboard");
  if (story || live) {
    const ms = (typeof Sess !== "undefined" && Sess.builtMs()) || (window.LIVE && window.LIVE.built_ms) || null;
    if (ms) parts.push((window.PUBLIC_SITE ? "Live snapshot frozen " : "Live data built ") + stamp(ms));
  }
  el.textContent = parts.join(" · ");
}
/* Every page that shows snapshot data says so (spec section 8); the owner's page, served live, shows no banner. */
function drawSnapshotBanner(tab, view) {
  const el = $("snapshot-banner");
  if (!el) return;
  const at = window.PUBLIC_SITE && window.SNAPSHOT_AT;
  const on = !!at && (tab === "story" || tab === "exec-test" || view === "lv-model");
  el.hidden = !on;
  if (on) el.textContent = `Snapshot frozen ${at} UTC. Not live.`;
}
/* The Agent pages show the agent's edge table, which only a walk-forward run carries: open on the headline queue run rather than
   on the baseline, so a visitor never lands on "Not in this run". */
const AGENT_VIEWS = ["model-health", "signals"];
function ensureAgentRun() {
  if (!AGENT_VIEWS.includes(current) || typeof Source === "undefined" || !Source.current || Source.current.kind === "walkforward") return;
  const wf = selectableRuns().filter(r => r.kind === "walkforward");
  const pick = wf.find(r => /-q1$/.test(r.run_id)) || wf[0];
  if (!pick) return;
  const sel = $("run-select");
  if (sel) sel.value = pick.run_id;
  Source.select(pick.run_id);
}
function closeAppendix() { const d = $("appendix-menu"); if (d) d.open = false; }
function placeAppendixMenu() {              // the nav scrolls sideways, so the menu is fixed under its summary
  const d = $("appendix-menu"), m = d && d.querySelector(".menu");
  if (!d || !d.open || !m) return;
  const r = d.querySelector("summary").getBoundingClientRect();
  m.style.top = r.bottom + 4 + "px"; m.style.left = Math.max(8, Math.min(r.left, innerWidth - m.offsetWidth - 8)) + "px";
}
function initAppendixMenu() {
  const d = $("appendix-menu");
  if (!d) return;
  if (window.PUBLIC_SITE) d.querySelectorAll("[data-local-only]").forEach(a => a.remove());      // no Operations on the public copy
  d.addEventListener("toggle", placeAppendixMenu);
  d.querySelectorAll(".menu a").forEach(a => a.addEventListener("click", closeAppendix));
  document.addEventListener("click", e => { if (!d.contains(e.target)) closeAppendix(); });
  document.addEventListener("keydown", e => { if (e.key === "Escape") closeAppendix(); });
  window.addEventListener("resize", placeAppendixMenu);
}
let shownView = null;
function show(hash) {
  const { tab, view, section } = resolveHash(hash);
  const changed = view !== shownView;
  shownView = view; current = view; currentTab = tab;
  document.body.classList.toggle("desk-mode", DESK_VIEWS.includes(view));
  document.body.classList.toggle("verdict-mode", tab === "verdict");
  document.body.classList.toggle("live-view", LIVE_VIEWS.includes(view));
  document.querySelectorAll("div.tab-wrap").forEach(w => w.classList.toggle("active", w.dataset.tab === tab));
  document.querySelectorAll("section.view").forEach(s => s.classList.toggle("active", s.id === "view-" + view));
  document.querySelectorAll("nav.tabs > a").forEach(a => { if (a.dataset.tab === tab) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
  const sum = document.querySelector("#appendix-menu summary");
  if (sum) { if (APPENDIX_TABS.includes(tab)) sum.setAttribute("aria-current", "page"); else sum.removeAttribute("aria-current"); }
  document.querySelectorAll("#appendix-menu .menu a").forEach(a => {
    const [t2, v2] = a.getAttribute("href").slice(1).split("/");
    if (t2 === tab && (v2 ? v2 === view : view === viewIds(tab)[0])) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  });
  closeAppendix();
  if (typeof Sess !== "undefined") Sess.onShow(view);
  document.querySelectorAll(`#sub-${tab} a`).forEach(a => { if (a.dataset.sub === view) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
  if (dirty[view]) renderVisible();
  else document.querySelectorAll(`#view-${view} .chart`).forEach(el => el.data && Plotly.Plots.resize(el));
  drawFooter();
  drawSnapshotBanner(tab, view);
  ensureAgentRun();
  const target = section && ($("sec-" + section) || $(section));       // a deep link scrolls to its section, a new page to the top
  if (target && target.tagName === "DETAILS") target.open = true;
  if (target) target.scrollIntoView({ block: "start" });
  else if (changed) window.scrollTo(0, 0);
}
window.addEventListener("hashchange", () => show(location.hash));
function boot() {
  Object.keys(TABS).forEach(t => { if (TABS[t].views.some(Array.isArray)) subtabs("sub-" + t, TABS[t].views.map(v => Array.isArray(v) ? v : [v, TABS[t].label]), t); });
  initAppendixMenu();
  initShell();
  if (typeof Sess !== "undefined") Sess.init();
  show(location.hash || "#" + DEFAULT_VIEW.tab);
}
/* ======================= Desk helpers =======================
   Shared by every Desk view. Profit green and loss red are used for nothing else on Desk views. */
const DESK_VIEWS = ["pnl", "execution", "risk", "model-health", "signals", "simlive", "market"];   // views that read the selected run
const PROFIT = "#22c55e", LOSS = "#ef4444";
const KIND = {
  backtest:    { label: "SIM",          c: "#94a3b8" },
  walkforward: { label: "WALK-FORWARD", c: "#a78bfa" },
  paper:       { label: "PAPER",        c: "#f5a524" },
  live:        { label: "LIVE",         c: "#22d3ee" },
  demo:        { label: "DEMO",         c: "#e879f9" },
};
/* Categorical colours for coins, sessions and variants. None of them is bid blue, ask amber, artifact purple or
   profit/loss green/red, so a coloured line never reads as one of those meanings. */
const SERIES = ["#2dd4bf", "#f472b6", "#facc15", "#818cf8", "#e2e8f0", "#fb923c", "#94a3b8", "#c084fc"];
const esc = x => String(x).replace(/[&<>"']/g, ch => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
const isNum = x => typeof x === "number" && isFinite(x);
const sign = (x, d = 2) => isNum(x) ? (x > 0 ? "+" : x < 0 ? "−" : "") + fmt(Math.abs(x), d) : "–";
const pnlCls = x => isNum(x) ? (x > 0 ? "pos" : x < 0 ? "neg" : "") : "";
const pnlColor = x => isNum(x) && x < 0 ? LOSS : PROFIT;
const pct = (x, d = 0) => isNum(x) ? fmt(100 * x, d) + "%" : "–";
const badge = kind => { const k = KIND[kind] || { label: String(kind).toUpperCase(), c: C.muted }; return `<span class="badge" style="--c:${k.c}">${esc(k.label)}</span>`; };
const $ = id => document.getElementById(id);

/* Returns the section, or null when the run does not have it (missing, empty list or empty object). */
function section(b, name) {
  if (!b || b[name] === undefined || b[name] === null) return null;
  const s = b[name];
  if (Array.isArray(s)) return s.length ? s : null;
  if (typeof s === "object") return Object.keys(s).length ? s : null;
  return s;
}
/* One grey line in place of a panel whose data is not in this run. */
function emptyPanel(el, msg = "Not in this run") {
  el = typeof el === "string" ? $(el) : el;
  if (!el) return;
  if (el.data) Plotly.purge(el);
  el.classList.add("is-empty");
  el.innerHTML = `<p class="empty-line">${esc(msg)}</p>`;
}
/* Plot into a Desk panel, clearing any "Not in this run" line first. */
function deskPlot(id, data, lay) {
  const el = $(id);
  if (el.classList.contains("is-empty")) { el.classList.remove("is-empty"); el.innerHTML = ""; }
  return plot(id, data, lay);
}
function fillHtml(id, html) { const el = $(id); el.classList.remove("is-empty"); el.innerHTML = html; }
function ago(builtUtc) {
  const t = Date.parse(String(builtUtc).replace(" ", "T") + ":00Z");
  if (!isFinite(t)) return "";
  const h = (Date.now() - t) / 3.6e6;
  if (h < 1) return `built ${Math.max(1, Math.round(h * 60))} min ago`;
  if (h < 48) return `built ${Math.round(h)} h ago`;
  return `built ${Math.round(h / 24)} days ago`;
}
/* Rows of a run for the current filter. */
function filteredDays(b) {
  const f = Source.filter;
  return (section(b, "days") || []).filter(d => d.variant === f.variant && (f.symbol === "ALL" || d.symbol === f.symbol));
}
function summaryRow(b, symbol, variant) {
  return (section(b, "summary") || []).find(r => r.symbol === symbol && r.variant === variant) || null;
}
/* Common top-of-view state: returns the bundle, or renders a message into the view and returns null. */
function deskBundle(view) {
  const host = $("desk-msg-" + view);
  const b = Source.current;
  let msg = "";
  if (!Source.list().length) msg = "No runs yet. Run a backtest or python -m mm.report to write runs/*.js.";
  else if (Source.error) msg = Source.error;
  else if (!b) msg = "Loading run…";
  if (host) { host.textContent = msg; host.hidden = !msg; }
  const body = $("desk-body-" + view);
  if (body) body.hidden = !!msg;
  return msg ? null : b;
}

/* ======================= Desk shell: run selector, compare, filters ======================= */
const SHOW_DEMO = /[?&]demo=1\b/.test(location.search);
function selectableRuns() {
  return Source.list().filter(r => r.run_id !== Source.VERDICT_ID && r.kind !== "book" && (SHOW_DEMO || r.kind !== "demo"));
}
/* Shared time range for the over-time charts (P&L daily, Risk inventory and drawdown): 3d / 14d / all, default all. */
const RANGE = { days: "all" };
function rangeX(lastIso) {
  if (RANGE.days === "all" || !lastIso) return null;
  const end = Date.parse(String(lastIso).length <= 10 ? lastIso + "T23:59:59Z" : lastIso);
  return isFinite(end) ? [new Date(end - RANGE.days * 864e5).toISOString(), new Date(end).toISOString()] : null;
}
function initRange() {
  const bar = document.querySelector(".runbar");
  if (!bar || $("range-btns")) return;
  const wrap = document.createElement("span");
  wrap.id = "range-btns"; wrap.className = "range-btns"; wrap.setAttribute("role", "group"); wrap.setAttribute("aria-label", "Time range");
  wrap.innerHTML = '<span class="run-meta">Range</span>' + [["3d", 3], ["14d", 14], ["all", "all"]].map(([l, d]) => `<button type="button" data-d="${d}" aria-pressed="${String(d) === String(RANGE.days)}">${l}</button>`).join("");
  wrap.addEventListener("click", e => {
    const d = e.target.dataset && e.target.dataset.d;
    if (!d) return;
    RANGE.days = d === "all" ? "all" : +d;
    wrap.querySelectorAll("button").forEach(b => b.setAttribute("aria-pressed", String(b.dataset.d === d)));
    ["pnl", "risk"].forEach(markDirty);
  });
  bar.appendChild(wrap);
}
function initShell() {
  initRange();
  if (typeof Source === "undefined") return;
  const runs = selectableRuns();
  const sel = $("run-select"), cmp = $("run-compare");
  if (!sel) return;
  const opt = r => `<option value="${esc(r.run_id)}">${esc(r.label)} · ${esc((KIND[r.kind] || {}).label || r.kind)} · ${esc(r.built_utc)} UTC</option>`;
  sel.innerHTML = runs.length ? runs.map(opt).join("") : '<option value="">No runs</option>';
  cmp.innerHTML = '<option value="">None</option>' + runs.map(opt).join("");
  sel.addEventListener("change", () => Source.select(sel.value));
  cmp.addEventListener("change", () => Source.selectCompare(cmp.value));
  $("f-symbol").addEventListener("change", e => Source.setFilter({ symbol: e.target.value }));
  $("f-variant").addEventListener("change", e => Source.setFilter({ variant: e.target.value }));
  document.addEventListener("runchange", onRunChange);
  Source.loadVerdict();
  Source.loadBook();
  const first = Source.defaultRunId(SHOW_DEMO);
  if (first) { sel.value = first; Source.select(first); }
  else onRunChange();
}
function onRunChange() {
  const b = Source.current;
  if (b && AGENT_VIEWS.includes(current) && b.kind !== "walkforward") { ensureAgentRun(); return; }
  $("run-badge").innerHTML = b ? badge(b.kind) : "";
  $("run-meta").textContent = b ? `${b.built_utc} UTC · ${ago(b.built_utc)} · ${Source.symbolsOf(b).length} symbols · ${new Set(b.days.map(d => d.date)).size} days` : "";
  $("demo-banner").hidden = !(b && b.kind === "demo");
  const vt = Source.verdict && Source.verdict.takeaways && Source.verdict.takeaways.headline;
  $("bar-verdict").textContent = vt || "";
  const cb = Source.compare;
  $("compare-badge").innerHTML = cb ? badge(cb.kind) : "";
  const fs = $("f-symbol"), fv = $("f-variant");
  const syms = Source.symbolsOf(b), vars = Source.variantsOf(b);
  fs.innerHTML = '<option value="ALL">All symbols</option>' + syms.map(s => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
  fs.value = Source.filter.symbol;
  fv.innerHTML = vars.map(v => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
  if (Source.filter.variant) fv.value = Source.filter.variant;
  DESK_VIEWS.concat(["overview", "book", "health"]).forEach(v => { if (draw[v]) dirty[v] = true; });
  renderVisible();
}
