/* data.js: Data > Recorder health (Dashboard Redesign R8). Reads the book bundle's coverage, the run index and SITE. */

function drawDataTiles() {
  const b = Source.book, cov = (b && b.coverage) || [];
  const clean = cov.reduce((a, r) => a + r.hours, 0), gapMin = cov.reduce((a, r) => a + r.gap_minutes, 0);
  const days = new Set(cov.map(r => r.date)).size;
  const tiles = [
    ["Coins recorded", b ? fmt(b.symbols.length, 0) : "–", "", b ? "in the newest book bundle" : "no book bundle yet"],
    ["Days recorded", b ? fmt(days, 0) : "–", "", "UTC dates with any data"],
    ["Clean hours", b ? fmt(clean, 0) : "–", "", "all coins together"],
    ["Gap time", b ? fmt(gapMin / 60, 1) + " h" : "–", "", "book gaps over 120 s"],
    ["Tests passing", isNum(SITE.testsPassed) ? fmt(SITE.testsPassed, 0) : "–", "", "set in js/core.js at build time"],
  ];
  fillHtml("dh-tiles", tiles.map(t => `<div class="tile"><div class="k">${t[0]}</div><div class="v ${t[2]}">${t[1]}</div><div class="s">${t[3]}</div></div>`).join(""));
}

function drawDataCoverage() {
  const cov = Source.book && Source.book.coverage;
  if (!cov || !cov.length) return emptyPanel("dh-cov", Source.bookError || "No recorded book yet. Run the recorder, then run_build_book.bat.");
  const syms = [...new Set(cov.map(r => r.symbol))].sort(), dates = [...new Set(cov.map(r => r.date))].sort();
  const z = syms.map(s => dates.map(d => { const r = cov.find(x => x.symbol === s && x.date === d); return r ? r.hours : null; }));
  const text = syms.map(s => dates.map(d => { const r = cov.find(x => x.symbol === s && x.date === d); return r ? `${r.hours} clean hours, ${fmt(r.gap_minutes, 1)} min of gaps` : "no data"; }));
  deskPlot("dh-cov", [{ type: "heatmap", x: dates, y: syms, z, text, hoverinfo: "text", zmin: 0, zmax: 24, xgap: 2, ygap: 2,
    colorscale: [[0, "#1a2433"], [0.5, "#2b6cb0"], [0.83, "#38bdf8"], [1, "#e0f2fe"]], colorbar: { title: { text: "clean hours", side: "right" }, thickness: 10, tickvals: [0, 12, 20, 24] } }],
    { height: Math.max(180, 44 * syms.length + 100), margin: { l: 90, r: 16, t: 10, b: 60 }, hovermode: "closest",
      xaxis: axis("UTC date", { type: "category" }), yaxis: Object.assign(axis(""), { autorange: "reversed" }) });
}

function drawDataBundles() {
  const rows = Source.list().slice().sort((a, c) => a.built_utc < c.built_utc ? 1 : -1);
  if (!rows.length) return emptyPanel("dh-bundles");
  fillHtml("dh-bundles", `<table><thead><tr><th>Bundle</th><th>Kind</th><th>Built (UTC)</th><th>Age</th><th>Days</th><th>Coins</th></tr></thead><tbody>${rows.map(r =>
    `<tr><td>${esc(r.run_id)}</td><td>${badge(r.kind)}</td><td>${esc(r.built_utc)}</td><td>${esc(ago(r.built_utc).replace("built ", ""))}</td><td>${isNum(r.n_days) ? fmt(r.n_days, 0) : "–"}</td><td>${(r.symbols || []).length}</td></tr>`).join("")}</tbody></table>`);
}

function drawDataTape() {
  const tv = Source.book && Source.book.tape_validation;
  if (!tv) { $("dh-tape-verdict").innerHTML = ""; return emptyPanel("dh-tape", "No tape validation yet. Record at least 3 days, then run run_validate_tape.bat and run_build_book.bat."); }
  const p = tv.pooled, line = `fills on the inferred book are ${fmt(p.fill_ratio, 2)}x the real book's, net edge ${sign(p.edge_diff_bp, 1)} bp apart, over ${fmt(p.days, 0)} recorded day${p.days === 1 ? "" : "s"}`;
  $("dh-tape-verdict").innerHTML = p.ok
    ? `<div class="verdict ok"><b>Inferred tape acceptable</b>: ${line} (rule: fills within ±30% and edge within 2 bp).</div>`
    : `<div class="verdict amber"><b>Inferred tape not acceptable</b>: ${line}. Median level size, real over assumed: ${fmt(p.level_ratio_median, 2)}. Re-run the v2 results with the level size scaled by it.</div>`;
  fillHtml("dh-tape", `<table><thead><tr><th>Coin</th><th>Date</th><th>Hours</th><th>Fills (real)</th><th>Fills (inferred)</th><th>Edge real (bp)</th><th>Edge inferred (bp)</th></tr></thead><tbody>${tv.rows.map(r =>
    `<tr><td>${esc(r.symbol)}</td><td>${esc(r.date)}</td><td>${fmt(r.hours, 0)}</td><td>${fmt(r.fills_real, 0)}</td><td>${fmt(r.fills_inf, 0)}</td><td>${fmt(r.net_edge_real, 2)}</td><td>${fmt(r.net_edge_inf, 2)}</td></tr>`).join("")}</tbody></table>`);
}

function drawData() {
  const body = $("desk-body-health"), msg = $("desk-msg-health");
  msg.hidden = true; body.hidden = false;
  drawDataTiles(); drawDataCoverage(); drawDataTape(); drawDataBundles();
}
register("health", drawData);
