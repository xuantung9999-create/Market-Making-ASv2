/* compare.js: the arithmetic behind Data > Sim vs live (Dashboard Guide D11). No DOM: runs in the page and under node.
   compareRuns(a, b, va, vb): run a's variant va against run b's variant vb on the (symbol, date) pairs both have.
   Verdict rule (Build Guide): fills within +/-30 percent and net edge within 2 bp reads "consistent". */
(function () {
  const FILL_TOL = 0.30, EDGE_TOL_BP = 2.0;
  const num = x => typeof x === "number" && isFinite(x);

  function metrics(rows) {
    const n = rows.length, sum = k => rows.reduce((s, r) => s + (num(r[k]) ? r[k] : 0), 0);
    const fills = sum("fills"), notional = sum("notional"), pnl = sum("pnl");
    const w = rows.filter(r => num(r.net_edge_bp) && r.fills > 0);
    const wf = w.reduce((s, r) => s + r.fills, 0);
    return {
      n, fills, fills_day: n ? fills / n : null, notional_day: n ? notional / n : null, pnl_total: pnl,
      net_bp: notional > 0 ? pnl / notional * 1e4 : null,
      edge: wf > 0 ? w.reduce((s, r) => s + r.net_edge_bp * r.fills, 0) / wf : null,
    };
  }

  function curve(rows, dates) {
    const byDate = {};
    rows.forEach(r => { byDate[r.date] = (byDate[r.date] || 0) + (num(r.pnl) ? r.pnl : 0); });
    let c = 0;
    return dates.map(d => (c += byDate[d] || 0));
  }

  function compareRuns(a, b, va, vb) {
    const pick = (run, v) => ((run && run.days) || []).filter(d => d.variant === v);
    const A = pick(a, va), B = pick(b, vb);
    const key = d => d.symbol + "|" + d.date;
    const inB = new Set(B.map(key)), inA = new Set(A.map(key));
    const ca = A.filter(d => inB.has(key(d))), cb = B.filter(d => inA.has(key(d)));
    const dates = [...new Set(ca.map(d => d.date))].sort();
    const ma = metrics(ca), mb = metrics(cb);
    const rows = [
      { label: "Fills per coin-day", a: ma.fills_day, b: mb.fills_day },
      { label: "Notional per coin-day (USD)", a: ma.notional_day, b: mb.notional_day },
      { label: "Net P&L total (USD)", a: ma.pnl_total, b: mb.pnl_total },
      { label: "Net P&L per $ traded (bp)", a: ma.net_bp, b: mb.net_bp },
      { label: "Net edge per fill (bp)", a: ma.edge, b: mb.edge },
    ].map(r => ({ ...r, diff: num(r.a) && num(r.b) ? r.b - r.a : null }));
    let verdict;
    if (!ca.length) verdict = { state: "no-overlap" };
    else if (!(ma.fills > 0) || !(mb.fills > 0)) verdict = { state: "no-fills", sim_fills: ma.fills, live_fills: mb.fills };
    else {
      const ratio = mb.fills / ma.fills, diff = num(ma.edge) && num(mb.edge) ? mb.edge - ma.edge : null;
      const ok = Math.abs(ratio - 1) <= FILL_TOL && num(diff) && Math.abs(diff) <= EDGE_TOL_BP;
      verdict = { state: ok ? "consistent" : "disagree", fills_ratio: ratio, edge_diff_bp: diff };
    }
    return { common_days: ca.length, rows, verdict, curves: { dates, a: curve(ca, dates), b: curve(cb, dates) },
             fills_by_date: { dates, a: dates.map(d => ca.filter(r => r.date === d).reduce((s, r) => s + r.fills, 0)),
                                     b: dates.map(d => cb.filter(r => r.date === d).reduce((s, r) => s + r.fills, 0)) } };
  }

  const api = { compareRuns, FILL_TOL, EDGE_TOL_BP };
  if (typeof module !== "undefined" && module.exports) module.exports = api; else window.Compare = api;
})();
