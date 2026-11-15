/* story.js: the Story page (showcase spec section 6).
   Reads only window.STORY (runs/pub-story.js, written by scripts/build_story.py). Python writes every sentence and
   every number; this file formats and draws. A section whose source is missing shows the one sentence the bundle gives.
   Rule (tests/test_dashboard_static.py): no string literal in this file contains a digit, except between the two
   "format helpers" markers below. */

/* ---- format helpers: the only place a literal may hold a digit ---- */
const STORY_TILE_FORMAT = {
  net: v => sign(v, 1), t: v => sign(v, 1), agent_fills: v => fmt(v, 0),
};
const storyMarkoutNote = v => `60 s markout ${sign(v, 1)} bp`;
const storyFeeNote = v => `${fmt(v, 0)} bp fee`;
const storyCount = v => fmt(v, 0);
const STORY_HOVER = { y: " %{y:.1f} bp<extra></extra>", x: " %{x:.1f} bp<extra></extra>" };
const STORY_FOREST_AXIS = "bp per dollar traded (95% interval on net)";
const STORY_POOLED_ROWS = 8;
const STORY_HORIZONS = [1, 5, 30, 60, 300];                     // seconds after the fill that carry a markout tick                                  // the forest shows at most this many rows (spec section 6)
/* ---- end format helpers ---- */

const storyEl = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html !== undefined) e.innerHTML = html; return e; };
const storyLink = l => l && l.href ? `<p class="story-link"><a href="${esc(l.href)}">${esc(l.label || l.href)}</a></p>` : "";

/* Charts on this page look static: no mode bar, no zoom, hover only. */
function storyPlot(id, data, lay) {
  const fixed = o => Object.assign({ fixedrange: true }, o);
  const l = Object.assign({ dragmode: false, hovermode: "closest" }, lay);
  l.xaxis = fixed(l.xaxis); l.yaxis = fixed(l.yaxis);
  return Plotly.react(id, data, layout(l), Object.assign({}, CONFIG, { displayModeBar: false, scrollZoom: false, doubleClick: false }));
}

/* One section frame: heading that states the finding, one or two sentences, one figure, one link. */
function storySection(host, sec, opts = {}) {
  const el = storyEl("section", "story-sec");
  el.innerHTML = `<h2>${esc(sec.title || "")}</h2>`;
  if (opts.label) el.querySelector("h2").insertAdjacentHTML("afterend", `<p class="story-label"><span class="story-badge">${esc(opts.label)}</span></p>`);
  host.appendChild(el);
  if (sec.status !== "ok") {
    el.appendChild(storyEl("p", "story-text story-missing", esc(sec.sentence || "")));
    return null;
  }
  if (sec.sentence) el.appendChild(storyEl("p", "story-text", esc(sec.sentence)));
  return el;
}
function storyChart(sec, id, h) {
  const d = storyEl("div", "chart story-chart"); d.id = id; d.style.height = h + "px";
  sec.appendChild(d);
  return d;
}
const storyAfter = (sec, link) => { if (link) sec.insertAdjacentHTML("beforeend", storyLink(link)); };

function storyHero(host, S) {
  const sec = S.sections.hero;
  const el = storyEl("section", "story-hero");
  host.appendChild(el);
  if (sec.status !== "ok") { el.appendChild(storyEl("p", "story-text story-missing", esc(sec.sentence || ""))); return; }
  el.appendChild(storyEl("p", "story-lede", esc(sec.sentence)));
  const tiles = (sec.tiles || []).map(t => {
    const f = STORY_TILE_FORMAT[t.key];
    const shown = isNum(t.value) ? (f ? f(t.value) : fmt(t.value, 1)) : esc(t.value === undefined || t.value === null ? "" : t.value);
    const cls = t.key === "net" ? pnlCls(t.value) : "";
    return `<div class="tile"><div class="k">${esc(t.label)}</div><div class="v ${cls}">${shown}</div><div class="s">${esc(t.context || "")}</div></div>`;
  }).join("");
  el.appendChild(storyEl("div", "tiles story-tiles", tiles));
  if (sec.facts_line) el.appendChild(storyEl("p", "story-facts", esc(sec.facts_line)));
}

function storyStack(host, S) {
  const sec = storySection(host, S.sections.stack);
  if (!sec) return;
  const boxes = (S.sections.stack.boxes || []).map(b => {
    const n = b.number && isNum(b.number.value) ? `<div class="stack-n"><span class="num">${storyCount(b.number.value)}</span> ${esc(b.number.label || "")}</div>` : "";
    return `<a class="stack-box" href="${esc(b.href)}"><h3>${esc(b.name)}</h3><p>${esc(b.line)}</p>${n}<code>${esc(b.module)}</code></a>`;
  }).join("");
  sec.appendChild(storyEl("div", "stack-row", boxes));
}

function storyForest(host, S) {
  const s = S.sections.assumptions, sec = storySection(host, s);
  if (!sec) return;
  const rows = (s.rows || []).filter(r => isNum(r.net_bp)).slice(0, STORY_POOLED_ROWS);
  if (!rows.length) { sec.appendChild(storyEl("p", "story-text story-missing", esc(s.sentence || ""))); return; }
  storyChart(sec, "story-forest", Math.max(260, 34 * rows.length + 80));
  const cats = rows.map(r => r.label);
  const gap = { type: "scatter", mode: "lines", hoverinfo: "skip", showlegend: false, line: { width: 3, color: C.line },
                x: rows.flatMap(r => [r.gross_bp, r.net_bp, null]), y: rows.flatMap(r => [r.label, r.label, null]) };
  const net = { type: "scatter", mode: "markers", name: "Net of fees", x: rows.map(r => r.net_bp), y: cats,
    error_x: { type: "data", array: rows.map(r => isNum(r.net_se) ? 1.96 * r.net_se : 0), color: C.muted, thickness: 1.2, width: 4 },
    marker: { size: 10, color: rows.map(r => pnlColor(r.net_bp)) },
    hovertemplate: "%{y}<br>net" + STORY_HOVER.x };
  const gross = { type: "scatter", mode: "markers", name: "Before fees", x: rows.map(r => r.gross_bp), y: cats,
    marker: { size: 9, symbol: "diamond-open", color: C.text, line: { width: 1.5, color: C.text } },
    hovertemplate: "%{y}<br>before fees" + STORY_HOVER.x };
  const note = isNum(s.fee_bp) ? [{ x: (rows[0].gross_bp + rows[0].net_bp) / 2, y: cats[0], xref: "x", yref: "y", yshift: 16, showarrow: false,
                                     text: storyFeeNote(s.fee_bp), font: { size: 11, color: C.muted } }] : [];
  storyPlot("story-forest", [gap, net, gross], {
    margin: { l: 250, r: 16, t: 10, b: 44 }, annotations: note,
    xaxis: axis(STORY_FOREST_AXIS, { zeroline: true, zerolinecolor: C.muted, zerolinewidth: 1.5 }),
    yaxis: Object.assign(axis("", { automargin: true }), { autorange: "reversed", type: "category", categoryorder: "array", categoryarray: cats }),
  });
  storyAfter(sec, s.link);
}

function storyWaterfall(host, S) {
  const s = S.sections.waterfall, sec = storySection(host, s);
  if (!sec) return;
  storyChart(sec, "story-waterfall", 300);
  const terms = s.terms || [];
  const note = isNum(s.markout_60_bp) ? [{ xref: "paper", yref: "paper", x: 1, y: 1, xanchor: "right", yanchor: "top", showarrow: false,
                                           text: storyMarkoutNote(s.markout_60_bp), font: { size: 12, color: C.muted } }] : [];
  storyPlot("story-waterfall", [{
    type: "waterfall", orientation: "v", x: terms.map(t => t.label).concat(["Net"]),
    measure: terms.map(() => "relative").concat(["total"]), y: terms.map(t => t.bp).concat([s.net_bp]),
    text: terms.map(t => sign(t.bp, 1)).concat([sign(s.net_bp, 1)]), textposition: "outside", cliponaxis: false,
    connector: { line: { color: C.line } },
    increasing: { marker: { color: PROFIT } }, decreasing: { marker: { color: LOSS } }, totals: { marker: { color: pnlColor(s.net_bp) } },
    hovertemplate: "%{x}<br>" + STORY_HOVER.y,
  }], {
    showlegend: false, annotations: note, margin: { l: 56, r: 16, t: 30, b: 70 },
    xaxis: axis(""), yaxis: axis("bp per dollar traded", { zeroline: true, zerolinecolor: C.muted, zerolinewidth: 1.5 }),
  });
  storyAfter(sec, s.link);
}

function storyLadder(host, S) {
  const s = S.sections.ladder, sec = storySection(host, s);
  if (!sec) return;
  storyChart(sec, "story-ladder", 340);
  const pts = s.points || [];
  const wrap = l => String(l).replace(" (", "<br>(").replace(", ", "<br>");
  const x = pts.map(p => wrap(p.label));
  const mk = (name, key, symbol) => ({ type: "scatter", mode: "lines+markers", name, x, y: pts.map(p => p[key]),
    line: { width: 1.5, color: C.muted, dash: "dot" },
    marker: { size: 11, symbol, color: pts.map(p => pnlColor(p[key])), line: { width: 2, color: pts.map(p => pnlColor(p[key])) } },
    hovertemplate: "%{x}<br>" + name + STORY_HOVER.y });
  storyPlot("story-ladder", [mk("Before fees", "gross_bp", "diamond-open"), mk("After fees", "net_bp", "circle")], {
    margin: { l: 56, r: 16, t: 30, b: 90 },
    xaxis: axis("", { type: "category" }), yaxis: axis("bp per dollar traded", { zeroline: true, zerolinecolor: C.muted, zerolinewidth: 1.5 }),
  });
  storyAfter(sec, s.link);
}

function storyAgent(host, S) {
  const s = S.sections.agent, sec = storySection(host, s);
  if (!sec) return;
  if (s.paper_line) sec.appendChild(storyEl("p", "story-text", esc(s.paper_line)));
  else if (s.paper_line_missing) sec.appendChild(storyEl("p", "story-text story-missing", esc(s.paper_line_missing)));
  const mark = p => p === true ? '<span class="mark pass">PASS</span>' : p === false ? '<span class="mark fail">FAIL</span>' : '<span class="mark na"></span>';
  const rows = ((s.gate || {}).conditions || []).map(c =>
    `<tr><td class="mono">${esc(c.id)}</td><td>${esc(c.text)}</td><td>${esc(c.value_text || "")}</td><td>${mark(c.pass)}</td></tr>`).join("");
  sec.appendChild(storyEl("div", "table-wrap", `<table class="gates story-gates"><thead><tr><th>Condition</th><th>Rule</th><th>What happened</th><th>Result</th></tr></thead><tbody>${rows}</tbody></table>`));
  storyAfter(sec, s.link);
}

function storyExecution(host, S) {
  const s = S.sections.execution, sec = storySection(host, s, { label: s.label });
  if (!sec) return;
  const n = s.numbers || {};
  const left = [["Orders placed", n.placed], ["Orders filled", n.filled], ["Orders rejected", n.rejected]]
    .map(([k, v]) => `<div class="tile"><div class="k">${k}</div><div class="v">${isNum(v) ? storyCount(v) : ""}</div></div>`).join("");
  const caught = (s.caught || []).length
    ? `<ul class="story-caught">${s.caught.map(c => `<li>${esc(c.text || c.finding || "")}</li>`).join("")}</ul>`
    : `<p class="story-text story-missing">${esc(s.caught_missing || "")}</p>`;
  const grid = storyEl("div", "story-exec");
  grid.appendChild(storyEl("div", "tiles story-tiles", left));
  grid.appendChild(storyEl("div", "story-caught-wrap", `<h3>What the test caught</h3>${caught}`));
  sec.appendChild(grid);
  if (s.tape && s.tape.window) {
    storyChart(sec, "story-tape", 320);
    sec.appendChild(storyEl("p", "story-text story-caption", esc(s.tape.caption || "")));
    storyTape(s.tape);
  } else if (s.tape_missing) sec.appendChild(storyEl("p", "story-text story-missing", esc(s.tape_missing)));
  storyAfter(sec, s.link);
}

/* The tape around one real fill: the touch, the trades, our orders, the fill and (when the fill has them) its markout ticks. */
function storyTape(tp) {
  const w = tp.window, f = tp.fill, T = w.touch, x = T.map(r => isoT(r[0]));
  const tr = [
    { type: "scatter", mode: "lines", name: "best bid", x, y: T.map(r => r[1]), line: { color: BID_C, width: 1.5, shape: "hv" }, hovertemplate: "%{y}<extra>bid</extra>" },
    { type: "scatter", mode: "lines", name: "best ask", x, y: T.map(r => r[2]), line: { color: ASK_C, width: 1.5, shape: "hv" }, hovertemplate: "%{y}<extra>ask</extra>" },
  ];
  if (w.trades.length) tr.push({ type: "scatter", mode: "markers", name: "trades", x: w.trades.map(r => isoT(r[0])), y: w.trades.map(r => r[1]),
    marker: { size: 4, color: w.trades.map(r => r[3] > 0 ? BID_C : ASK_C), opacity: 0.7 }, hovertemplate: "%{y}<extra>trade</extra>" });
  const endDash = { fill: "solid", cancel: "dot", reject: "dash", open: "solid" };
  w.orders.forEach((o, k) => tr.push({ type: "scatter", mode: "lines", name: "our orders", legendgroup: "orders", showlegend: k === 0, x: [isoT(o.t_place), isoT(o.t_end)], y: [o.price, o.price],
    line: { color: o.side > 0 ? BID_C : ASK_C, width: 4, dash: endDash[o.end] || "solid" }, hovertemplate: `${o.side > 0 ? "buy" : "sell"} ${o.price}<extra>order</extra>` }));
  tr.push({ type: "scatter", mode: "markers", name: "the fill", x: [isoT(f.t)], y: [f.price], marker: { symbol: "star", size: 16, color: f.artifact ? ART_C : C.text, line: { width: 1, color: C.panel } },
    hovertemplate: `fill ${f.price}<extra></extra>` });
  const shapes = [], ann = [];
  STORY_HORIZONS.forEach((h, k) => {
    const v = f["mk_" + h], at = f.t + h * 1000;
    if (!isNum(v) || at > w.t1) return;
    const y = 0.97 - 0.07 * (k % 3);
    shapes.push({ type: "line", xref: "x", yref: "paper", x0: isoT(at), x1: isoT(at), y0: 0, y1: y, line: { color: C.line, width: 1, dash: "dot" } });
    ann.push({ x: isoT(at), y, yref: "paper", text: `${h} s: ${sign(v, 1)} bp`, showarrow: false, xanchor: "left", font: { size: 10, color: C.muted } });
  });
  const ys = T.flatMap(r => [r[1], r[2]]).concat(w.trades.map(r => r[1]), w.orders.map(o => o.price), [f.price]);
  const rng = typeof fitAxis === "function" ? fitAxis(ys) : null;
  storyPlot("story-tape", tr, { shapes, annotations: ann, margin: { l: 70, r: 16, t: 10, b: 50 },
    xaxis: axis("", { type: "date", range: [isoT(w.t0), isoT(w.t1)] }), yaxis: axis("price", rng ? { range: rng } : {}) });
}

function storyNext(host, S) {
  const s = S.sections.next, sec = storySection(host, s);
  if (!sec) return;
  if ((s.limits || []).length) sec.appendChild(storyEl("ul", "story-limits", s.limits.map(l => `<li>${esc(l)}</li>`).join("")));
  if ((s.links || []).length) sec.insertAdjacentHTML("beforeend", `<p class="story-link">${s.links.map(l => `<a href="${esc(l.href)}">${esc(l.label)}</a>`).join(" · ")}</p>`);
}

function drawStory() {
  const host = $("story-body"), S = window.STORY;
  host.innerHTML = "";
  if (!S || !S.sections) { host.appendChild(storyEl("p", "story-text story-missing", "The story bundle runs/pub-story.js was not found: run python -m scripts.build_story.")); return; }
  storyHero(host, S);
  [storyStack, storyForest, storyWaterfall, storyLadder, storyAgent, storyExecution, storyNext].forEach(f => f(host, S));
}
register("story", drawStory);
