/* explainers.js: graphics for the Story and the Method and limits page.
   - ICONS: one line-icon set (24 px grid, stroke = currentColor), shared by the Story stack boxes and the Method page.
   - Method pipeline: the numbered Method list in index.html stays the single source of the text. This file reads its
     items, draws them as a row of clickable steps grouped by phase, and shows one step's detail at a time. Without
     JavaScript the plain list shows.
   - Limitations: each bullet of "Known limitations" gets an icon card.
   Figures stay where they are written (the HTML list, or the Python story bundle); this file only arranges them. */

const ICON_PATHS = {
  data:        '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>',
  calibration: '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>',
  simulator:   '<rect x="3" y="4" width="18" height="4" rx="1"/><rect x="3" y="10" width="13" height="4" rx="1"/><rect x="3" y="16" width="8" height="4" rx="1"/>',
  agent:       '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="0.8" fill="currentColor"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
  paper:       '<path d="M6 3h9l4 4v14H6z"/><path d="M15 3v4h4"/><path d="M9 13l2 2 4-5"/>',
  testnet:     '<path d="M4 12h5l2-6 3 12 2-6h4"/>',
  derivation:  '<path d="M17 4H7l6 8-6 8h10"/>',
  engine:      '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="10" y="10" width="4" height="4"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
  replication: '<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V5a1 1 0 0 0-1-1H5a1 1 0 0 0-1 1v10a1 1 0 0 0 1 1h3"/>',
  backtest:    '<path d="M3 12a9 9 0 1 0 3-6.7"/><path d="M3 4v5h5"/><path d="M12 8v4l3 2"/>',
  informed:    '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
  tuning:      '<path d="M3 17l5-5 4 4 8-9"/><path d="M15 7h5v5"/>',
  queue:       '<path d="M9 6h11M9 12h11M9 18h11"/><circle cx="4.5" cy="6" r="1.5"/><circle cx="4.5" cy="12" r="1.5"/><circle cx="4.5" cy="18" r="1.5"/>',
  verdict:     '<path d="M9 3h6M10 3v6L4 19a1 1 0 0 0 1 2h14a1 1 0 0 0 1-2l-6-10V3"/><path d="M7 15h10"/>',
  gate:        '<path d="M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6z"/><path d="M9 9l6 6M15 9l-6 6"/>',
  next:        '<circle cx="12" cy="12" r="9"/><path d="M10 8l4 4-4 4"/>',
  warning:     '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18v0.5"/>',
  book:        '<path d="M4 6h7M4 10h5M4 14h8M4 18h4"/><path d="M13 6h7M15 10h5M12 14h8M16 18h4"/>',
  tick:        '<path d="M4 4v16M10 4v16M16 4v16M4 20h16"/><path d="M12 9h7"/><circle cx="19" cy="9" r="1.5"/>',
  adverse:     '<path d="M3 7l6 6 4-4 8 8"/><path d="M21 12v5h-5"/>',
};
/* An inline icon, sized by CSS (.icon). Unknown names draw nothing. */
function explainIcon(name, cls = "") {
  const p = ICON_PATHS[name];
  return p ? `<svg class="icon ${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${p}</svg>` : "";
}

/* One entry per Method list item, in order: icon, short name for the node, phase, where the evidence is, and a status
   (done, loss, fail, next) that colours the node. The long text comes from the list item itself. */
const METHOD_STEPS = [
  { icon: "derivation",  short: "Derive",          phase: "Build the model", href: "#simulator/model",       status: "done" },
  { icon: "engine",      short: "Quote engine",    phase: "Build the model", href: "#simulator",             status: "done" },
  { icon: "replication", short: "Replicate paper", phase: "Build the model", href: "#simulator/replication", status: "done" },
  { icon: "data",        short: "Real data",       phase: "Real data",       href: "#data/health",           status: "done" },
  { icon: "backtest",    short: "Backtest",        phase: "Real data",       href: "#backtests",             status: "done" },
  { icon: "calibration", short: "Calibrate 12 coins", phase: "Real data",    href: "#backtests/universe",    status: "done" },
  { icon: "informed",    short: "Informed flow",   phase: "Hunt for edge",   href: "#archive/informed",      status: "done" },
  { icon: "tuning",      short: "Tune and signals", phase: "Hunt for edge",  href: "#backtests/tuning",      status: "done" },
  { icon: "queue",       short: "Queue model",     phase: "Hunt for edge",   href: "#fills",                 status: "done" },
  { icon: "verdict",     short: "60-day test",     phase: "Verdict",         href: "#verdict",               status: "loss" },
  { icon: "gate",        short: "Gate A",          phase: "Verdict",         href: "#archive/model-health",  status: "fail" },
  { icon: "next",        short: "Next",            phase: "Next",            href: "#book",                  status: "next" },
];
const METHOD_STATUS_LABEL = { done: "built", loss: "loses money", fail: "gate failed", next: "planned" };
const METHOD_EVIDENCE_LABEL = { "#simulator/model": "How it quotes", "#simulator": "Simulator", "#simulator/replication": "Paper replication",
  "#data/health": "Recorder health", "#backtests": "Backtests", "#backtests/universe": "BTC to micro caps", "#archive/informed": "Informed traders",
  "#backtests/tuning": "Tuning and signals", "#fills": "Fill economics", "#verdict": "Verdict", "#archive/model-health": "Agent edge table",
  "#book": "Market book" };

const MethodUI = { sel: 0 };
function drawMethodPipeline() {
  const list = document.getElementById("method-list"), host = document.getElementById("method-pipe");
  if (!list || !host) return;
  const items = [...list.children].filter(li => li.tagName === "LI");
  if (!items.length || items.length !== METHOD_STEPS.length) { host.hidden = true; list.hidden = false; return; }   // list and table out of step: show the plain list
  const steps = items.map((li, i) => {
    const b = li.querySelector("b"), title = b ? b.textContent.replace(/[.:]\s*$/, "") : METHOD_STEPS[i].short;
    const body = li.innerHTML.replace(/^\s*<b>[\s\S]*?<\/b>\s*/, "");
    return { ...METHOD_STEPS[i], title, body, n: i + 1 };
  });
  const phases = [];
  steps.forEach(s => { const last = phases[phases.length - 1]; if (last && last.name === s.phase) last.steps.push(s); else phases.push({ name: s.phase, steps: [s] }); });
  host.innerHTML = `<div class="pipe" role="tablist" aria-label="Method steps">${phases.map(ph => `
      <div class="pipe-phase"><div class="pipe-phase-name">${esc(ph.name)}</div><div class="pipe-nodes">${ph.steps.map(s => `
        <button type="button" class="pipe-node" role="tab" data-i="${s.n - 1}" data-s="${s.status}" aria-selected="false" aria-controls="pipe-detail" title="${esc(s.title)}">
          <span class="pipe-ico">${explainIcon(s.icon)}</span><span class="pipe-n">${s.n}</span><span class="pipe-short">${esc(s.short)}</span>
        </button>`).join("")}</div></div>`).join("")}
    </div>
    <div class="pipe-progress" aria-hidden="true"><span></span></div>
    <div class="pipe-detail card" id="pipe-detail" role="tabpanel" aria-live="polite"></div>`;
  list.hidden = true;
  const nodes = [...host.querySelectorAll(".pipe-node")];
  const select = (i, focus) => {
    MethodUI.sel = Math.max(0, Math.min(steps.length - 1, i));
    const s = steps[MethodUI.sel];
    nodes.forEach((n, k) => { n.setAttribute("aria-selected", String(k === MethodUI.sel)); n.tabIndex = k === MethodUI.sel ? 0 : -1; n.classList.toggle("past", k < MethodUI.sel); });
    if (focus) nodes[MethodUI.sel].focus();
    host.querySelector(".pipe-progress span").style.width = `${(MethodUI.sel / (steps.length - 1)) * 100}%`;
    const d = host.querySelector(".pipe-detail");
    d.dataset.s = s.status;
    d.innerHTML = `<div class="pipe-detail-head"><span class="pipe-ico big">${explainIcon(s.icon)}</span>
        <div><div class="eyebrow">Step ${s.n} of ${steps.length} · ${esc(s.phase)}</div><h3>${esc(s.title)}</h3></div>
        <span class="pipe-status" data-s="${s.status}">${esc(METHOD_STATUS_LABEL[s.status])}</span></div>
      <p>${s.body}</p>
      <div class="pipe-detail-foot">
        <button type="button" data-go="-1"${MethodUI.sel ? "" : " disabled"}>← Previous</button>
        <a href="${esc(s.href)}">See the evidence: ${esc(METHOD_EVIDENCE_LABEL[s.href] || s.href)} →</a>
        <button type="button" data-go="1"${MethodUI.sel < steps.length - 1 ? "" : " disabled"}>Next →</button>
      </div>`;
    d.querySelectorAll("[data-go]").forEach(btn => btn.addEventListener("click", () => select(MethodUI.sel + Number(btn.dataset.go))));
  };
  nodes.forEach((n, k) => {
    n.addEventListener("click", () => select(k));
    n.addEventListener("keydown", e => {                   // arrow keys move between steps (tablist pattern)
      const go = { ArrowRight: 1, ArrowDown: 1, ArrowLeft: -1, ArrowUp: -1 }[e.key];
      if (go) { e.preventDefault(); select(MethodUI.sel + go, true); }
      else if (e.key === "Home") { e.preventDefault(); select(0, true); }
      else if (e.key === "End") { e.preventDefault(); select(steps.length - 1, true); }
    });
  });
  select(MethodUI.sel);
}

/* Known limitations as icon cards; the icon is picked from the bullet's own words. */
const LIMIT_ICONS = [[/simulated market|sharpe/i, "warning"], [/order book|book imbalance/i, "book"], [/tick/i, "tick"], [/adverse/i, "adverse"]];
function drawLimitCards() {
  const ul = document.getElementById("limits-list");
  if (!ul || ul.dataset.done) return;
  ul.classList.add("limit-cards");
  [...ul.children].forEach(li => {
    const hit = LIMIT_ICONS.find(([re]) => re.test(li.textContent));
    li.innerHTML = `<span class="limit-ico">${explainIcon(hit ? hit[1] : "warning")}</span><span>${li.innerHTML}</span>`;
  });
  ul.dataset.done = "1";
}

function drawMethodGraphics() { drawMethodPipeline(); drawLimitCards(); }
