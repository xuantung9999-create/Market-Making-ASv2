/* lv_health.js: Market & health tab (live spec L10). The Market feed cards and the PC status tables are one
   tab (both sections stacked); this adds the feed-gap table from the session bundles. */

function drawHealthGaps() {
  if (!$("hl-gaps")) return;
  const bs = (Sess.state.list || []).map(s => (window.SESSION_DATA || {})[s.id]).filter(Boolean);
  const rows = [];
  bs.forEach(b => b.incidents.filter(i => i.kind === "feed_gap").forEach(i => rows.push({ ...i, label: `${b.meta.source} ${b.meta.symbol}` })));
  rows.sort((a, b) => b.t0 - a.t0);
  setSub("hl-gaps-sub", rows.length ? `${rows.length} stretch${rows.length === 1 ? "" : "es"} of more than 2 minutes without a book update in the recorded feeds of the sessions.`
    : bs.length ? "No stretch of more than 2 minutes without a book update in the recorded session feeds." : "");
  if (!bs.length) { lvEmpty("hl-gaps", Sess.state.error || "Session files are still loading."); return; }
  lvTable("hl-gaps", [{ k: "t0", label: "From (UTC)", left: true, f: v => utcStamp(v) }, { k: "t1", label: "To (UTC)", left: true, f: v => utcStamp(v) },
    { k: "dur", label: "Length", v: r => r.t1 - r.t0, f: v => agoText(v / 1000) }, { k: "label", label: "Feed", left: true }, { k: "sentence", label: "", left: true, f: v => esc(v) }],
    rows, { sort: "t0", scroll: true, empty: "No feed gaps." });
}

/* the two old views are one tab now: drawing either draws both, and the page shows them stacked */
(function () {
  const drawLive = draw["live"], drawPc = draw["pcstatus"];
  const both = () => { drawLive(); drawPc(); drawHealthGaps(); };
  draw["live"] = both; draw["pcstatus"] = both;
})();
