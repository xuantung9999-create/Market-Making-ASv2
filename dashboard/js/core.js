/* core.js: shared theme, formatters, Plotly helpers and the tab router.
   Loaded after Plotly and data.js, before any js/views/*.js file. */
/* ---------- Edit these for your CV / website ---------- */
const SITE = {
  stage: "v2 · Gate A evaluated",
  testsPassed: 329,
  author: "Xuân Tùng",
  github: "",      // e.g. "https://github.com/your-name/as-market-maker"
  linkedin: "",    // e.g. "https://www.linkedin.com/in/your-name"
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
const TABS = {
  "overview":     { label: "Verdict", views: ["overview"] },
  "live":         { label: "Live", views: [["live", "Market feed"], ["pcstatus", "PC status"]] },
  "book":         { label: "Market book", views: [["book", "Order book"], ["market", "Universe"]] },
  "pnl":          { label: "P&L", views: ["pnl"] },
  "execution":    { label: "Execution", views: ["execution"] },
  "risk":         { label: "Risk", views: ["risk"] },
  "model-health": { label: "Model", views: [["model-health", "Edge table"], ["signals", "Signals"]] },
  "data":         { label: "Data", views: [["health", "Recorder health"], ["simlive", "Sim vs live"]] },
  "simulator":    { label: "Simulator", views: [["simulator", "Playground"], ["model", "How it quotes"], ["replication", "Paper replication"]] },
  "archive":      { label: "Research archive", views: [["real-data", "Real data"], ["backtest", "Backtest"], ["universe", "BTC to micro caps"],
                                                       ["informed", "Informed traders"], ["tuning", "Tuning and signals"]] },
  "about":        { label: "About", views: ["about"] },
};
const viewIds = t => TABS[t].views.map(v => Array.isArray(v) ? v[0] : v);
const VIEW_TAB = {};
Object.keys(TABS).forEach(t => viewIds(t).forEach(v => { VIEW_TAB[v] = t; }));
const DEFAULT_VIEW = { name: "overview" };
function register(name, fn, initiallyDirty = true) {
  if (!VIEWS.includes(name)) VIEWS.push(name);
  draw[name] = fn; dirty[name] = initiallyDirty;
}
function markDirty(name) { dirty[name] = true; if (name === current) renderVisible(); }
let current = null, currentTab = null;
function renderVisible() { if (current && dirty[current]) { dirty[current] = false; draw[current](); } }
/* "#simulator/replication" | "#replication" | "#simulator" -> {tab, view} */
function resolveHash(h) {
  const [a, b] = String(h || "").replace(/^#/, "").split("/");
  let tab = TABS[a] ? a : VIEW_TAB[a], view = null;
  if (!tab) return { tab: DEFAULT_VIEW.name, view: DEFAULT_VIEW.name };
  const ids = viewIds(tab);
  if (!TABS[a]) view = a;
  else if (b && ids.includes(b)) view = b;
  return { tab, view: view || ids[0] };
}
/* Segmented control that shows one nested view of a tab; the choice lives in the hash. */
function subtabs(hostId, items, tab) {
  const host = $(hostId);
  if (!host) return;
  host.innerHTML = items.map(([id, label]) => `<a href="#${tab}/${id}" data-sub="${id}" role="tab">${esc(label)}</a>`).join("");
}
function show(hash) {
  const { tab, view } = resolveHash(hash);
  current = view; currentTab = tab;
  document.body.classList.toggle("desk-mode", DESK_VIEWS.includes(view));
  document.body.classList.toggle("verdict-mode", tab === "overview");
  document.querySelectorAll("div.tab-wrap").forEach(w => w.classList.toggle("active", w.dataset.tab === tab));
  document.querySelectorAll("section.view").forEach(s => s.classList.toggle("active", s.id === "view-" + view));
  document.querySelectorAll("nav.tabs a").forEach(a => { if (a.dataset.view === tab) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
  document.querySelectorAll(`#sub-${tab} a`).forEach(a => { if (a.dataset.sub === view) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
  if (dirty[view]) renderVisible();
  else document.querySelectorAll(`#view-${view} .chart`).forEach(el => el.data && Plotly.Plots.resize(el));
}
window.addEventListener("hashchange", () => show(location.hash));
function boot() {
  Object.keys(TABS).forEach(t => { if (TABS[t].views.some(Array.isArray)) subtabs("sub-" + t, TABS[t].views.map(v => Array.isArray(v) ? v : [v, TABS[t].label]), t); });
  initShell();
  show(location.hash || "#" + DEFAULT_VIEW.name);
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
const SERIES = ["#38bdf8", "#f5a524", "#a78bfa", "#e2e8f0", "#f472b6", "#2dd4bf", "#fb923c", "#818cf8"];
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
