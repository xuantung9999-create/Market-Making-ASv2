/* source.js: where the Desk views get their data.

   Runs are listed in runs/index.js (window.RUN_INDEX) and each run lives in runs/<run_id>.js,
   which sets window.RUNS[run_id]. Runs are loaded on demand by inserting a <script> tag, so the
   page works when opened as a file (no server, no fetch).

   Source.list()            -> index entries, newest first
   Source.load(runId)       -> Promise<bundle>
   Source.current           -> the selected bundle (or null)
   Source.compare           -> the "compare with" bundle (or null)
   Source.filter            -> {symbol: "ALL" | "<SYM>", variant: "<name>"}
   Source.select(id), Source.selectCompare(id | ""), Source.setFilter({...})
   document fires "runchange" whenever any of the above changes. */
const Source = (() => {
  window.RUNS = window.RUNS || {};
  const pending = {};
  const ID_RE = /^[a-z0-9][a-z0-9._-]{0,79}$/;

  function list() { return Array.isArray(window.RUN_INDEX) ? window.RUN_INDEX.slice() : []; }

  function load(runId) {
    if (window.RUNS[runId]) return Promise.resolve(window.RUNS[runId]);
    if (!ID_RE.test(runId) || !list().some(r => r.run_id === runId)) return Promise.reject(new Error(`unknown run ${runId}`));
    if (pending[runId]) return pending[runId];
    pending[runId] = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = `runs/${runId}.js`;
      s.onload = () => window.RUNS[runId] ? resolve(window.RUNS[runId]) : reject(new Error(`runs/${runId}.js did not define the run`));
      s.onerror = () => { delete pending[runId]; reject(new Error(`could not load runs/${runId}.js`)); };
      document.head.appendChild(s);
    });
    return pending[runId];
  }

  const VERDICT_ID = "pub-verdict";
  /* The queue baseline is the run the detail tabs open on; the verdict bundle and the demo run are never the default. */
  function defaultRunId(allowDemo = false) {
    const runs = list().filter(r => r.run_id !== VERDICT_ID && r.kind !== "book" && (allowDemo || r.kind !== "demo"));
    const qb = runs.find(r => r.kind === "backtest");
    return ((qb || runs[0] || {}).run_id) || null;
  }

  function variantsOf(b) {
    const v = [];
    for (const d of (b && b.days) || []) if (!v.includes(d.variant)) v.push(d.variant);
    return v;
  }
  function symbolsOf(b) {
    const s = [];
    for (const d of (b && b.days) || []) if (!s.includes(d.symbol)) s.push(d.symbol);
    return s;
  }
  function defaultVariant(b) { const v = variantsOf(b); return v.includes("q1.0") ? "q1.0" : v.includes("agent") ? "agent" : (v[0] || null); }

  const api = {
    current: null, compare: null, error: null, verdict: null, verdictError: null, book: null, bookError: null, VERDICT_ID,
    filter: { symbol: "ALL", variant: null },
    list, load, defaultRunId, variantsOf, symbolsOf,
    fire() { document.dispatchEvent(new CustomEvent("runchange")); },
    async loadVerdict() {
      if (!list().some(r => r.run_id === VERDICT_ID)) { api.verdictError = "No verdict bundle yet. Run run_build_verdict.bat."; api.fire(); return; }
      try { api.verdict = await load(VERDICT_ID); } catch (e) { api.verdictError = String(e.message || e); }
      api.fire();
    },
    /* The newest recorded-book bundle, if the index lists one. */
    async loadBook() {
      const entry = list().find(r => r.kind === "book");
      if (!entry) { api.bookError = "No recorded book yet. Run the recorder for a few days, then run_build_book.bat."; api.fire(); return; }
      try { api.book = await load(entry.run_id); } catch (e) { api.bookError = String(e.message || e); }
      api.fire();
    },
    async select(runId) {
      api.error = null;
      try {
        api.current = runId ? await load(runId) : null;
      } catch (e) { api.current = null; api.error = String(e.message || e); }
      const b = api.current;
      if (b) {
        if (!variantsOf(b).includes(api.filter.variant)) api.filter.variant = defaultVariant(b);
        if (api.filter.symbol !== "ALL" && !symbolsOf(b).includes(api.filter.symbol)) api.filter.symbol = "ALL";
      }
      api.fire();
    },
    async selectCompare(runId) {
      try { api.compare = runId ? await load(runId) : null; }
      catch (e) { api.compare = null; api.error = String(e.message || e); }
      api.fire();
    },
    setFilter(f) { Object.assign(api.filter, f); api.fire(); },
  };
  return api;
})();
