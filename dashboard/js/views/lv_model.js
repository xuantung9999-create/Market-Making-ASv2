/* lv_model.js: Model tab. Which arm was live, the arm scores, predicted against realised edge, why it stayed out. */

const armColor = i => `hsl(${(i * 30 + 200) % 360}, 70%, 62%)`;

function drawLvModel() {
  const b = Sess.one();
  if (!b) { ["lvm-strip", "lvm-scores", "lvm-calib"].forEach(lvWaiting); fillLv("lvm-arms", ""); return; }
  const mo = b.model, tk = b.takeaways, w = Sess.windowOf(b);
  const fixed = $("lvm-fixed"), body = $("lvm-body");
  if (mo.fixed) {
    fixed.hidden = false; fixed.textContent = tk.why_out; fixed.className = "verdict amber"; body.hidden = true; return;
  }
  fixed.hidden = true; body.hidden = false;

  // live-arm strip and the menu table
  setSub("lvm-strip-sub", tk.arm_strip);
  const strip = mo.arm_strip.filter(s => !w || (s.t1 >= w[0] && s.t0 <= w[1]));
  if (!strip.length) lvEmpty("lvm-strip", "No arm history recorded yet for this session: the agent writes it every 30 minutes.");
  else {
    const shapes = strip.map(s => ({ type: "rect", xref: "x", yref: "y", x0: isoT(s.t0), x1: isoT(s.t1), y0: 0, y1: 1, fillcolor: armColor(s.arm), opacity: 0.85, line: { width: 0 } }));
    const ann = strip.map(s => ({ x: isoT((s.t0 + s.t1) / 2), y: 0.5, text: `arm ${s.arm}`, showarrow: false, font: { size: 11, color: "#0a0f16" } }));
    deskPlot("lvm-strip", [{ type: "scatter", mode: "markers", x: [isoT(strip[0].t0)], y: [0.5], marker: { opacity: 0 }, hoverinfo: "skip", showlegend: false }],
      { shapes, annotations: ann, height: 110, showlegend: false, hovermode: false, xaxis: axis("", { type: "date", range: w ? [isoT(w[0]), isoT(w[1])] : undefined }), yaxis: axis("", { range: [0, 1], showticklabels: false, showgrid: false, zeroline: false }), margin: { l: 16, r: 16, t: 8, b: 30 } });
  }
  lvTable("lvm-arms", [
    { k: "arm", label: "Arm", left: true, f: (v, r) => `${v}${r.live ? " ◀ live" : ""}` }, { k: "e_min_bp", label: "e_min bp", f: v => fmt(v, 1) }, { k: "z", label: "z", f: v => fmt(v, 1) },
    { k: "gamma_bp", label: "γ bp", f: v => fmt(v, 1) }, { k: "score_bp", label: "Score bp", f: v => isNum(v) ? `<span class="${pnlCls(v)}">${sign(v, 2)}</span>` : dashes },
    { k: "fills", label: "Fills (decayed)", f: v => isNum(v) ? fmt(v, 1) : dashes },
  ], mo.arms, { sort: "arm", rowClass: r => r.live ? "live" : "", scroll: true });
  $("lvm-arms")._sort = { k: "arm", dir: 1 };

  // arm scores over time, zero drawn
  setSub("lvm-scores-sub", tk.arm_scores);
  const h = mo.history.filter(r => !w || (r.t >= w[0] && r.t <= w[1]) || true).filter(r => r.scores);
  if (h.length < 2) lvEmpty("lvm-scores", "Fewer than two history points are recorded for this session, so no score lines can be drawn yet.");
  else {
    const n = h[0].scores.length;
    const tr = Array.from({ length: n }, (_, i) => ({ type: "scatter", mode: "lines", name: `arm ${i}`, x: h.map(r => isoT(r.t)), y: h.map(r => r.scores[i]),
      line: { color: armColor(i), width: mo.live_arm === i ? 3 : 1 }, opacity: mo.live_arm === i ? 1 : 0.7 }));
    deskPlot("lvm-scores", tr, { yaxis: axis("score, bp", { zeroline: true, zerolinewidth: 1.5, zerolinecolor: "#94a3b8" }), xaxis: axis("", { type: "date", range: w ? [isoT(w[0]), isoT(w[1])] : undefined }),
      shapes: h.filter(r => r.switched).map(r => ({ type: "line", xref: "x", yref: "paper", x0: isoT(r.t), x1: isoT(r.t), y0: 0, y1: 1, line: { color: "#facc15", width: 1, dash: "dot" } })) });
  }

  // predicted against realised edge
  setSub("lvm-calib-sub", tk.calibration);
  const cal = mo.calibration;
  if (!cal.length) { setSub("lvm-calib-sub", ""); lvEmpty("lvm-calib", tk.calibration); }
  else {
    const xs = cal.map(c => c.pred_bp), lo = Math.min(...xs, ...cal.map(c => c.real_bp), 0), hi = Math.max(...xs, ...cal.map(c => c.real_bp), 0), pad = (hi - lo) * 0.1 || 1;
    deskPlot("lvm-calib", [{ type: "scatter", mode: "markers", name: "buckets", x: xs, y: cal.map(c => c.real_bp), text: cal.map(c => `n = ${c.n}`),
      marker: { size: 11, color: "#e2e8f0", symbol: cal.map(c => c.n < 30 ? "circle-open" : "circle"), line: { width: 2, color: "#e2e8f0" } },
      error_y: { type: "data", array: cal.map(c => c.se ? 1.96 * c.se : 0), visible: true, color: "#94a3b8" }, hovertemplate: "predicted %{x:.2f} bp, realised %{y:.2f} bp, %{text}<extra></extra>" }],
      { showlegend: false, xaxis: axis("predicted net edge, bp", { range: [lo - pad, hi + pad] }), yaxis: axis("realised 60 s markout net of fee, bp", { range: [lo - pad, hi + pad], zeroline: true, zerolinecolor: "#94a3b8" }),
        shapes: [{ type: "line", xref: "x", yref: "y", x0: lo - pad, x1: hi + pad, y0: lo - pad, y1: hi + pad, line: { color: "#475569", dash: "dash", width: 1 } }, { type: "line", xref: "x", yref: "paper", x0: 0, x1: 0, y0: 0, y1: 1, line: { color: "#94a3b8", width: 1 } }] });
  }
  setSub("lvm-why", tk.why_out);
}

register("lv-model", drawLvModel);
