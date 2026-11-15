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
const STORY_TICK_PX = { narrow: 10, wide: 11 };
const STORY_HORIZONS = [1, 5, 30, 60, 300];                     // seconds after the fill that carry a markout tick                                  // the forest shows at most this many rows (spec section 6)
/* ---- end format helpers ---- */

const storyEl = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html !== undefined) e.innerHTML = html; return e; };
/* Category tick labels: a size smaller on a phone so the bundle's two- and three-line labels do not touch. */
const storyTickFont = () => ({ family: MONO, size: isNarrow() ? STORY_TICK_PX.narrow : STORY_TICK_PX.wide, color: C.muted });
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
    const ico = typeof explainIcon === "function" ? explainIcon(b.key, "stack-ico") : "";      // icon set in explainers.js
    return `<a class="stack-box" href="${esc(b.href)}">${ico}<h3>${esc(b.name)}</h3><p>${esc(b.line)}</p>${n}<code>${esc(b.module)}</code></a>`;
  }).join("");
  sec.appendChild(storyEl("div", "stack-row", boxes));
}

function storyForest(host, S) {
  const s = S.sections.assumptions, sec = storySection(host, s);
  if (!sec) return;
  const rows = (s.rows || []).filter(r => isNum(r.net_bp)).slice(0, STORY_POOLED_ROWS);
  if (!rows.length) { sec.appendChild(storyEl("p", "story-text story-missing", esc(s.sentence || ""))); return; }
  storyChart(sec, "story-forest", Math.max(260, 34 * rows.length + 80));
  const cats = rows.map(catLabel), long = rows.map(r => r.label);
  const gap = { type: "scatter", mode: "lines", hoverinfo: "skip", showlegend: false, line: { width: 3, color: C.line },
                x: rows.flatMap(r => [r.gross_bp, r.net_bp, null]), y: rows.flatMap(r => [catLabel(r), catLabel(r), null]) };
  const net = { type: "scatter", mode: "markers", name: "Net of fees", x: rows.map(r => r.net_bp), y: cats, customdata: long,
    error_x: { type: "data", array: rows.map(r => isNum(r.net_se) ? 1.96 * r.net_se : 0), color: C.muted, thickness: 1.2, width: 4 },
    marker: { size: 10, color: rows.map(r => pnlColor(r.net_bp)) },
    hovertemplate: "%{customdata}<br>net" + STORY_HOVER.x };
  const gross = { type: "scatter", mode: "markers", name: "Before fees", x: rows.map(r => r.gross_bp), y: cats, customdata: long,
    marker: { size: 9, symbol: "diamond-open", color: C.text, line: { width: 1.5, color: C.text } },
    hovertemplate: "%{customdata}<br>before fees" + STORY_HOVER.x };
  const note = isNum(s.fee_bp) ? [{ x: (rows[0].gross_bp + rows[0].net_bp) / 2, y: cats[0], xref: "x", yref: "y", yshift: 16, showarrow: false,
                                     text: storyFeeNote(s.fee_bp), font: { size: 11, color: C.muted } }] : [];
  storyPlot("story-forest", [gap, net, gross], {
    margin: { l: catMargin(cats), r: 16, t: 10, b: 44 }, annotations: note,
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
  // headroom so the value printed outside the lowest bar never touches the category labels under the axis
  const levels = terms.reduce((acc, t) => acc.concat([acc[acc.length - 1] + t.bp]), [0]).concat([s.net_bp]).filter(isNum);
  const lo = Math.min(...levels), hi = Math.max(...levels), pad = (hi - lo) * 0.18;
  const note = isNum(s.markout_60_bp) ? [{ xref: "paper", yref: "paper", x: 1, y: 1, xanchor: "right", yanchor: "top", showarrow: false,
                                           text: storyMarkoutNote(s.markout_60_bp), font: { size: 12, color: C.muted } }] : [];
  storyPlot("story-waterfall", [{
    type: "waterfall", orientation: "v", x: terms.map(t => t.label_short || t.label).concat([s.net_label_short || "Net"]),
    measure: terms.map(() => "relative").concat(["total"]), y: terms.map(t => t.bp).concat([s.net_bp]),
    text: terms.map(t => sign(t.bp, 1)).concat([sign(s.net_bp, 1)]), textposition: "outside", cliponaxis: false,
    connector: { line: { color: C.line } },
    increasing: { marker: { color: PROFIT } }, decreasing: { marker: { color: LOSS } }, totals: { marker: { color: pnlColor(s.net_bp) } },
    hovertemplate: "%{x}<br>" + STORY_HOVER.y,
  }], {
    showlegend: false, annotations: note, margin: { l: 56, r: 16, t: 30, b: 80 },
    xaxis: axis("", { tickangle: 0, tickfont: storyTickFont() }), yaxis: axis("bp per dollar traded", { range: [lo - pad, hi + pad], zeroline: true, zerolinecolor: C.muted, zerolinewidth: 1.5 }),
  });
  storyAfter(sec, s.link);
}

function storyLadder(host, S) {
  const s = S.sections.ladder, sec = storySection(host, s);
  if (!sec) return;
  storyChart(sec, "story-ladder", 340);
  const pts = s.points || [];
  const wrap = l => String(l).replace(" (", "<br>(").replace(", ", "<br>");
  const x = pts.map(p => p.label_short || wrap(p.label));
  const mk = (name, key, symbol) => ({ type: "scatter", mode: "lines+markers", name, x, y: pts.map(p => p[key]),
    line: { width: 1.5, color: C.muted, dash: "dot" },
    marker: { size: 11, symbol, color: pts.map(p => pnlColor(p[key])), line: { width: 2, color: pts.map(p => pnlColor(p[key])) } },
    hovertemplate: "%{x}<br>" + name + STORY_HOVER.y });
  storyPlot("story-ladder", [mk("Before fees", "gross_bp", "diamond-open"), mk("After fees", "net_bp", "circle")], {
    margin: { l: 56, r: 16, t: 30, b: 90 },
    xaxis: axis("", { type: "category", tickangle: 0, tickfont: storyTickFont() }), yaxis: axis("bp per dollar traded", { zeroline: true, zerolinecolor: C.muted, zerolinewidth: 1.5 }),
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
    `<tr><td class="mono" data-label="Condition">${esc(c.id)}</td><td data-label="Rule">${esc(c.text)}</td><td data-label="What happened">${esc(c.value_text || "")}</td><td data-label="Result">${mark(c.pass)}</td></tr>`).join("");
  sec.appendChild(storyEl("div", "table-wrap", `<table class="gates story-gates stack"><thead><tr><th>Condition</th><th>Rule</th><th>What happened</th><th>Result</th></tr></thead><tbody>${rows}</tbody></table>`));
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

/* The tape around one real fill: the book around it on the left, the mid and its markouts after it on the right. */
function storyTape(tp) {
  const el = $("story-tape"), narrow = el && el.clientWidth > 0 && el.clientWidth < 640;
  const fig = fillTapeFigure(tp.window, tp.fill, tp.t, { fixed: true, narrow });      // the shared two-panel tape (fill_tape.js)
  if (el) el.style.height = fig.layout.height ? fig.layout.height + "px" : "";
  Plotly.react("story-tape", fig.data, layout(Object.assign({ dragmode: false }, fig.layout)),
               Object.assign({}, CONFIG, { displayModeBar: false, scrollZoom: false, doubleClick: false }));
}

function storyNext(host, S) {
  const s = S.sections.next, sec = storySection(host, s);
  if (!sec) return;
  if ((s.links || []).length) sec.insertAdjacentHTML("beforeend", `<p class="story-link">${s.links.map(l => `<a href="${esc(l.href)}">${esc(l.label)}</a>`).join(" · ")}</p>`);
  const ll = s.limits_line;
  if (ll) sec.insertAdjacentHTML("beforeend", `<p class="story-text story-limits-line">${esc(ll.lead)} <a href="${esc(ll.href)}">${esc(ll.label)}</a>.</p>`);
}

/* The top of the Method and limits page (recruiter-ready spec 5.4): the three simulator caveats, worded by the story bundle. */
function drawAboutLimits() {
  const host = $("about-cannot"), L = (window.STORY || {}).about_limits;
  if (!host) return;
  host.hidden = !(L && (L.items || []).length);
  if (host.hidden) { host.innerHTML = ""; return; }
  host.innerHTML = `<h2>${esc(L.title)}</h2><ul class="story-limits">${L.items.map(l => `<li>${esc(l)}</li>`).join("")}</ul>`;
}

function drawStory() {
  const host = $("story-body"), S = window.STORY;
  host.innerHTML = "";
  if (!S || !S.sections) { host.appendChild(storyEl("p", "story-text story-missing", "The story bundle runs/pub-story.js was not found: run python -m scripts.build_story.")); return; }
  storyHero(host, S);
  [storyStack, storyForest, storyWaterfall, storyLadder, storyAgent, storyExecution, storyNext].forEach(f => f(host, S));
}
register("story", drawStory);
