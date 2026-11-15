"""The story bundle behind the Story page (showcase spec sections 3 and 6).

    python -m scripts.build_story          # writes dashboard/runs/pub-story.js  (window.STORY = {...})

Every number and every sentence of the Story page is computed here from files that already exist:

    dashboard/runs/pub-verdict.js      forest, compare and gates of the 60-day test        (scripts/build_verdict.py)
    dashboard/runs/wf-*.js             agent walk-forward days per queue assumption (Gate A values, edge table)
    results/queue_baseline.csv         spread, inventory and fee terms behind the waterfall
    results/universe_backtest.csv      the v1 one-day result (ANKR, no queue model)
    results/gate_a.json                fallback for the Gate A conditions
    results/tests_passed.json          size of the last green suite (written by conftest.py)
    docs/SPEC_V2_1.md                  whether v2.1 has been evaluated
    dashboard/index.html               the "Known limitations" list of the About page
    dashboard/live/session-*.js        the live sessions, when present (the frozen snapshot on the public copy)

If a source is missing, the sections that need it carry ``status: "missing"`` and one sentence saying what is
missing. A missing source never produces a number, and nothing here is typed in as a result.
"""
from __future__ import annotations

import html as htmllib
import json
import math
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

from mm.agent import MENU
from mm.report import HEADLINE_QUEUE, MIN_DAYS_SHARPE, MIN_FILLS, VERDICT_ID

TITLE = "Crypto market making: from Avellaneda–Stoikov to a queue-aware agent"
OUT_NAME = "pub-story.js"
V1_FILL_RULE = "through"            # the Day-8 headline rule behind the +16 bp ANKR day
V1_COIN = "ANKRUSDT"
V1_STRATEGY = "Join touch"
HEADLINE_STRATEGY = "join_touch"
TAPE_HORIZONS = (1, 5, 30, 60, 300)  # the markout ticks the Story tape draws; the curated fill must carry all of them


# ---------------------------------------------------------------------- loading
class Missing(Exception):
    """A source file the bundle needs is not there (or not readable)."""

    def __init__(self, source: str):
        super().__init__(source)
        self.source = source


def load_js(path: Path):
    """The object assigned in a ``window.X ... = {...};`` bundle file."""
    try:
        s = path.read_text(encoding="utf-8")
        return json.loads(s[s.index("= {") + 2: s.rstrip().rstrip(";").rindex("}") + 1])
    except (OSError, ValueError):
        raise Missing(str(path.as_posix()))


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise Missing(str(path.as_posix()))


def load_csv(path: Path) -> pd.DataFrame:
    try:
        return pd.read_csv(path)
    except (OSError, ValueError, pd.errors.EmptyDataError):
        raise Missing(str(path.as_posix()))


def finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def clean(o):
    """JSON-safe: non-finite floats become None, numpy scalars become python, floats keep 10 significant digits."""
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if hasattr(o, "item") and not isinstance(o, (str, bytes)):
        o = o.item()
    if isinstance(o, float):
        return float(f"{o:.10g}") if math.isfinite(o) else None
    return o


def missing_section(title: str, sources: list[str], needs: str) -> dict:
    where = ", ".join(sources)
    return {"status": "missing", "title": title, "missing": sources,
            "sentence": f"This section needs {needs}, which is not available: {where} is missing or unreadable."}


def day_label(ts_ms: Optional[float]) -> Optional[str]:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%d %b").lstrip("0") if finite(ts_ms) else None


def stamp(ts_ms: Optional[float]) -> Optional[str]:
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if finite(ts_ms) else None


# ---------------------------------------------------------------------- sources
class Sources:
    """Everything the builder reads, each piece loaded once; a missing piece is remembered, not raised."""

    def __init__(self, base: Path, live: bool = True):
        self.base = Path(base)
        self.runs = self.base / "dashboard" / "runs"
        self.errors: dict[str, str] = {}
        self.verdict = self._try("verdict", lambda: load_js(self.runs / f"{VERDICT_ID}.js"))
        self.wf = self._try("wf", self._load_wf) or {}
        self.queue = self._try("queue", lambda: load_csv(self.base / "results" / "queue_baseline.csv"))
        self.universe = self._try("universe", lambda: load_csv(self.base / "results" / "universe_backtest.csv"))
        try:                                                     # optional: only a fallback for the Gate A conditions
            self.gate_file = load_json(self.base / "results" / "gate_a.json")
        except Missing:
            self.gate_file = None
        self.tests = self._try("tests", lambda: load_json(self.base / "results" / "tests_passed.json"))
        self.spec_v21 = self._try("spec_v21", lambda: self._read(self.base / "docs" / "SPEC_V2_1.md"))
        self.about = self._try("about", lambda: self._read(self.base / "dashboard" / "index.html"))
        self.sessions = self._load_sessions() if live else []          # live=False: the public copy without a snapshot

    def _try(self, key: str, fn):
        try:
            return fn()
        except Missing as e:
            self.errors[key] = e.source
            return None

    @staticmethod
    def _read(p: Path) -> str:
        try:
            return p.read_text(encoding="utf-8")
        except OSError:
            raise Missing(str(p.as_posix()))

    def _load_wf(self) -> dict:
        out = {}
        for p in sorted(self.runs.glob("wf-*.js")):
            try:
                r = load_js(p)
            except Missing:
                continue
            q = (r.get("config") or {}).get("queue_mult")
            if finite(q):
                out[float(q)] = r
        if not out:
            raise Missing("dashboard/runs/wf-*.js")
        return out

    def _load_sessions(self) -> list[dict]:
        out = []
        for p in sorted((self.base / "dashboard" / "live").glob("session-*.js")):
            try:
                out.append(load_js(p))
            except Missing:
                continue
        return out


# ---------------------------------------------------------------------- the 60-day test
def pooled(forest: list[dict], variant: str, qm: float) -> Optional[dict]:
    return next((r for r in forest if r.get("symbol") == "ALL" and r.get("variant") == variant
                 and r.get("queue_mult") == qm and "net_bp" in r), None)


def latency_of(row: dict) -> Optional[int]:
    m = re.search(r"lat(\d+)", str(row.get("series", "")) + " " + str(row.get("scenario", "")))
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*ms", str(row.get("scenario", "")))
    return int(m.group(1)) if m else None


def test_facts(src: Sources) -> dict:
    """The rows the hero, the forest, the ladder and the first two conclusions read."""
    v = src.verdict
    if not v:
        raise Missing(src.errors.get("verdict", "dashboard/runs/pub-verdict.js"))
    forest = v.get("forest") or []
    cfg = v.get("config") or {}
    q1 = pooled(forest, HEADLINE_STRATEGY, HEADLINE_QUEUE)
    if q1 is None or not finite(cfg.get("maker_fee_bps")) or not finite(q1.get("gross_bp")):
        raise Missing("pub-verdict forest row (join touch, queue 1x)")
    front = next((r for r in forest if r.get("symbol") == "ALL" and r.get("variant") == HEADLINE_STRATEGY
                  and r.get("queue_mult") == 0.0 and finite(r.get("gross_bp"))), None)
    agent = next((r for r in forest if r.get("symbol") == "ALL" and r.get("variant") == "agent"
                  and r.get("queue_mult") == HEADLINE_QUEUE), None)
    coins = sorted({r["symbol"] for r in forest if r.get("symbol") != "ALL"})
    return {"forest": forest, "cfg": cfg, "q1": q1, "front": front, "agent": agent, "coins": coins,
            "built": v.get("built_utc"), "compare": v.get("compare") or [], "gates": ((v.get("gates") or {}).get("A") or {})}


# ---------------------------------------------------------------------- Gate A values (spec C7)
def counted(days: list[dict]) -> list[dict]:
    return [d for d in days if d.get("fills", 0) >= MIN_FILLS and d.get("notional", 0) > 0]


def mean_t(vals: list[float]) -> tuple[Optional[float], Optional[float]]:
    if not vals:
        return None, None
    m = sum(vals) / len(vals)
    if len(vals) < max(2, MIN_DAYS_SHARPE):
        return m, None
    sd = math.sqrt(sum((x - m) ** 2 for x in vals) / (len(vals) - 1))
    return m, (m / (sd / math.sqrt(len(vals))) if sd > 0 else None)


def gate_rows(src: Sources, facts: dict) -> Optional[list[dict]]:
    """Every Gate A condition with its pass flag, its value and a sentence that says how far it missed."""
    conds = facts["gates"].get("conditions")
    if not conds:
        gf = src.gate_file
        conds = gf.get("conditions") if gf and gf.get("coin_days") else None
    if not conds:
        return None

    def agent(qm: float) -> list[dict]:
        return [d for d in (src.wf.get(qm) or {}).get("days", []) if d.get("variant") == "agent"]

    def why_none(qm: float) -> str:
        days = agent(qm)
        return (f"no counted coin-days at queue {qm:g}x: the agent made {sum(d.get('fills', 0) for d in days):,} fills in {len(days)} coin-days"
                if days else f"the queue {qm:g}x walk-forward run is not available")

    jt = [d for d in (src.wf.get(HEADLINE_QUEUE) or {}).get("days", []) if d.get("variant") == "join_touch"]
    a1 = counted(agent(HEADLINE_QUEUE))
    out = []
    for c in conds:
        cid, ok, text = c.get("id"), bool(c.get("pass")), c.get("text", "")
        value, vtext = c.get("value"), None
        if cid == "A1":
            m, t = mean_t([d["pnl"] for d in a1])
            value = m
            vtext = (f"mean {m:+.2f} USD a day over {len(a1)} counted coin-days" + (f", t = {t:.1f}" if t is not None else ", t not defined")
                     if m is not None else why_none(HEADLINE_QUEUE))
        elif cid == "A2":
            tot: dict = {}
            for d in agent(HEADLINE_QUEUE):
                tot[d["symbol"]] = tot.get(d["symbol"], 0.0) + d.get("pnl", 0.0)
            pos = sum(1 for v in tot.values() if v > 0)
            value = pos
            vtext = f"{pos} of {len(tot)} coins with positive total net P&L" if tot else why_none(HEADLINE_QUEUE)
        elif cid == "A3":
            share = (sum(1 for d in a1 if d["pnl"] > 0) / len(a1)) if a1 else None
            value = share
            vtext = f"{share:.0%} of {len(a1)} counted coin-days positive" if share is not None else why_none(HEADLINE_QUEUE)
        elif cid == "A4":
            a4 = counted(agent(2.0))
            m, _ = mean_t([d["pnl"] for d in a4])
            value = m
            vtext = f"mean {m:+.2f} USD a day over {len(a4)} counted coin-days at queue 2x" if m is not None else why_none(2.0)
        elif cid == "A5":
            at, jt_total = sum(d.get("pnl", 0.0) for d in agent(HEADLINE_QUEUE)), sum(d.get("pnl", 0.0) for d in jt)
            value = at
            vtext = f"agent {at:+,.2f} USD against join touch {jt_total:+,.0f} USD over the same days"
        out.append({"id": cid, "text": text, "pass": ok, "value": value if finite(value) else None,
                    "value_text": vtext or ("passed" if ok else "not met")})
    return out


# ---------------------------------------------------------------------- pieces
def waterfall_terms(src: Sources) -> dict:
    """Spread captured, inventory and adverse selection, fee and net in bp per dollar traded at the headline queue,
    counted the way the Verdict counts (portfolio days with enough fills)."""
    q = src.queue
    if q is None:
        raise Missing(src.errors.get("queue", "results/queue_baseline.csv"))
    dcol = "date" if "date" in q else "day"
    need = {"variant", dcol, "pnl", "spread_capture", "inventory_pnl", "fees", "notional_usdt", "fills"}
    if not need <= set(q.columns):
        raise Missing("results/queue_baseline.csv (columns)")
    g = q[q["variant"] == f"q{HEADLINE_QUEUE:.1f}"]
    day = g.groupby(dcol).agg(spread=("spread_capture", "sum"), inv=("inventory_pnl", "sum"), fees=("fees", "sum"),
                              pnl=("pnl", "sum"), notional=("notional_usdt", "sum"), fills=("fills", "sum"))
    day = day[(day["fills"] >= MIN_FILLS) & (day["notional"] > 0)]
    n = float(day["notional"].sum())
    if not len(day) or n <= 0:
        raise Missing("results/queue_baseline.csv (no counted days at the headline queue)")
    spread, inv, fee = (float(day[c].sum()) / n * 1e4 for c in ("spread", "inv", "fees"))
    return {"spread": spread, "inventory": inv, "fee": -fee, "net": float(day["pnl"].sum()) / n * 1e4, "days": int(len(day))}


def v1_point(src: Sources, fee_bps: float) -> dict:
    u = src.universe
    if u is None:
        raise Missing(src.errors.get("universe", "results/universe_backtest.csv"))
    r = u[(u["symbol"] == V1_COIN) & (u["strategy"] == V1_STRATEGY) & (u["fill_rule"] == V1_FILL_RULE)]
    if r.empty or not float(r["notional_usdt"].iloc[0]) > 0:
        raise Missing("results/universe_backtest.csv (ANKR join-touch row)")
    r = r.iloc[0]
    gross = float(r["net_0bp"]) / float(r["notional_usdt"]) * 1e4
    return {"symbol": V1_COIN, "date": str(r["date"]), "gross_bp": gross, "net_bp": gross - fee_bps,
            "fills": int(r["fills"]), "fill_rule": V1_FILL_RULE}


def live_facts(src: Sources) -> dict:
    """Counts from the live session bundles (the frozen snapshot on the public copy). Empty dict when there are none."""
    ss = src.sessions
    if not ss:
        return {}
    tn = [b for b in ss if b["meta"]["source"] == "testnet"]
    pa = [b for b in ss if b["meta"]["source"] == "paper"]
    built = [b["meta"].get("built_ms") for b in ss if finite(b["meta"].get("built_ms"))]
    firsts = [b["meta"].get("first_ms") for b in (pa or ss) if finite(b["meta"].get("first_ms"))]
    firsts += [iv["t0"] for b in (pa or ss) for side in ("bid", "ask") for iv in (b.get("states") or {}).get(side, [])[:1] if finite(iv.get("t0"))]
    return {"testnet": tn, "paper": pa, "built_ms": max(built) if built else None,
            "orders_placed": sum(b["funnel"]["placed"] for b in tn), "orders_filled": sum(b["funnel"]["filled"] for b in tn),
            "orders_rejected": sum(b["funnel"]["rejected"] for b in tn), "testnet_fills": sum(len(b["fills"]) for b in tn),
            "paper_fills": sum(len(b["fills"]) for b in pa), "paper_since_ms": min(firsts) if firsts else None,
            "caught": [c for b in tn for c in (b.get("caught") or [])]}


def caught_items(rows: list[dict]) -> list[dict]:
    """One line per finding for the Story page: the sessions' rows grouped by id, counts added, the status in words."""
    order: list[str] = []
    agg: dict[str, dict] = {}
    for r in rows:
        a = agg.get(r["id"])
        if a is None:
            a = agg[r["id"]] = {"id": r["id"], "finding": r["finding"], "status": r["status"], "task": r.get("task"),
                                "unit": r["unit"], "n": 0, "usd": None}
            order.append(r["id"])
        a["n"] += int(r.get("n") or 0)
        if finite(r.get("usd")):
            a["usd"] = (a["usd"] or 0.0) + r["usd"]
    out = []
    for k in order:
        a = agg[k]
        status = f"fixed, {a['task']}" if a["status"] == "fixed" and a["task"] else a["status"]
        usd = f", {a['usd']:+.2f} USDT" if a["usd"] is not None else ""
        out.append({**a, "text": f"{a['finding']}: {a['n']:,} {a['unit']}{usd}. Status: {status}."})
    return out


STORY_HIDDEN = {"book_glitch"}      # a venue artifact, not a finding about the code; the Execution test page still lists it


def plural(n: int, one: str, many: Optional[str] = None) -> str:
    return f"{n:,} {one if n == 1 else (many or one + 's')}"


def story_caught(rows: list[dict]) -> tuple[list[dict], Optional[str]]:
    """The Story's "What the test caught" (amendment of 16 Nov 2026): without book glitches, which become one footnote with
    the count and no USDT figure; an open finding reads as a known limitation that is logged, not as "Status: open"."""
    items = []
    for it in caught_items([r for r in rows if r["id"] not in STORY_HIDDEN]):
        if it["status"] == "open":
            usd = f", {it['usd']:+.2f} USDT" if it["usd"] is not None else ""
            it = {**it, "text": f"{it['finding']}: {it['n']:,} {it['unit']}{usd}. Status: known limitation; each one is logged as an incident."}
        items.append(it)
    n_gl = sum(int(r.get("n") or 0) for r in rows if r["id"] in STORY_HIDDEN)
    foot = (f"{plural(n_gl, 'fill')} that the thin testnet book printed far from the mid "
            f"{'is' if n_gl == 1 else 'are'} kept out of every strategy number (details on the Execution test page).") if n_gl else None
    return items, foot


def order_lifecycle(tn: list[dict]) -> dict:
    """Every testnet order attempt and where it ended, added across the sessions, with one sentence (amendment of 16 Nov 2026)."""
    tot = {k: sum(int(b["funnel"].get(k) or 0) for b in tn) for k in ("placed", "filled", "partial", "cancelled", "rejected")}
    still = max(0, tot["placed"] - tot["filled"] - tot["cancelled"])
    rep = [{"coin": coin_name(str(b["meta"].get("symbol", ""))), "median_s": b["funnel"]["median_replace_s"]}
           for b in tn if finite(b["funnel"].get("median_replace_s"))]
    s = (f"{plural(tot['placed'], 'order')} placed: {tot['filled']:,} filled, {tot['cancelled']:,} cancelled, "
         f"{'none' if still == 0 else f'{still:,}'} still open.")
    if tot["partial"]:
        s += f" {plural(tot['partial'], 'partial fill')} along the way."
    post = sum(int(r.get("n") or 0) for b in tn for r in b["funnel"].get("reject_reasons") or [] if "immediately match" in str(r.get("error")))
    why = " (post-only orders that would have taken liquidity)" if tot["rejected"] and post == tot["rejected"] else ""
    s += (" No order attempt was rejected." if not tot["rejected"] else
          f" {plural(tot['rejected'], 'attempt')} rejected before reaching the book{why}.")
    if rep:
        s += " A resting quote was replaced every " + ", ".join(f"{r['median_s']:.1f} s on {r['coin']}" for r in rep) + " (median)."
    return {**tot, "open": still, "attempts": tot["placed"] + tot["rejected"], "replace": rep, "sentence": s}


def tape_example(src: Sources, live: dict) -> tuple[Optional[dict], Optional[str]]:
    """The curated tape (spec section 7, item 6; owner's answer to open question 2, 15 Nov 2026): a typical ordinary fill,
    not a book glitch. Candidates are the testnet fills that are not artifacts, carry every markout and have a stored tape
    window covering 60 s before to 300 s after them; the agent's sessions are preferred over the join baseline. The pick is
    the fill whose 60 s markout is closest to the median of the candidates (the latest on a tie), so it is neither the best
    nor the worst fill. Returns (example, None) or (None, the reason there is none)."""
    need = ("price", "mid", "qty", "t") + tuple(f"mk_{h}" for h in TAPE_HORIZONS)
    tapes: dict[Path, Optional[dict]] = {}

    def window_of(b: dict, f: dict):
        day = datetime.fromtimestamp(f["t"] / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
        path = src.base / "dashboard" / "live" / f"tape-{b['meta']['id']}-{day}.js"
        if path not in tapes:
            try:
                tapes[path] = load_js(path)
            except Missing:
                tapes[path] = None
        tape = tapes[path] or {}
        win = next((w for w in tape.get("windows", []) if w["t0"] <= f["t"] - 60_000 and f["t"] + 300_000 <= w["t1"]), None)
        return day, path, win

    cands, why = [], "no ordinary fill with all its markouts in the testnet session bundles"
    for b in live.get("testnet", []):
        for f in b.get("fills", []):
            if f.get("artifact") or not all(finite(f.get(k)) for k in need):
                continue
            day, path, win = window_of(b, f)
            if win is None:
                why = f"a stored tape window around an ordinary fill (none in {path.name})"
                continue
            cands.append((str(b["meta"]["id"]).endswith("-agent"), b, f, day, win))
    if not cands:
        return None, why
    if any(c[0] for c in cands):
        cands = [c for c in cands if c[0]]
    marks = sorted(c[2]["mk_60"] for c in cands)
    med = marks[len(marks) // 2] if len(marks) % 2 else (marks[len(marks) // 2 - 1] + marks[len(marks) // 2]) / 2
    _, b, f, day, win = min(cands, key=lambda c: (abs(c[2]["mk_60"] - med), -c[2]["t"]))
    sid = b["meta"]["id"]
    lo, hi = f["t"] - 60_000, f["t"] + 300_000
    keep = {"t0": max(win["t0"], lo), "t1": min(win["t1"], hi),
            "touch": [r for r in win["touch"] if lo <= r[0] <= hi],
            "trades": [r for r in win["trades"] if lo <= r[0] <= hi],
            "orders": [o for o in win["orders"] if o["t_end"] >= lo and o["t_place"] <= hi]}
    fill = {k: f.get(k) for k in ("i", "t", "side", "price", "qty", "mid", "artifact", "mk_1", "mk_5", "mk_30", "mk_60", "mk_300")}
    return {"session": sid, "symbol": b["meta"]["symbol"], "day": day, "t": f["t"], "i": f.get("i"),
            "caption": f.get("caption") or "", "fill": fill, "window": keep}, None


def edge_cells(src: Sources) -> Optional[dict]:
    r = src.wf.get(HEADLINE_QUEUE)
    # a cell with no observations only holds the prior; it says nothing about whether a state loses money
    cells = [c for c in (r or {}).get("edge", []) if finite(c.get("mean")) and finite(c.get("n")) and c["n"] > 0]
    if not cells:
        return None
    return {"cells": len(cells), "positive": sum(1 for c in cells if c["mean"] > 0)}


# ---------------------------------------------------------------------- the five conclusions (spec section 3)
def agent_conclusion(facts: dict, edge: Optional[dict], gates: Optional[list[dict]]) -> dict:
    ag = facts["agent"]
    if ag is None or gates is None:
        return {"id": 4, "key": "agent_refused", "status": "missing", "missing": ["pub-verdict agent row or Gate A conditions"],
                "text": "The agent result is not available: its row or the Gate A conditions are missing from the verdict bundle."}
    met = sum(1 for c in gates if c["pass"])
    gate = f"Gate A: {'pass' if facts['gates'].get('pass') else 'fail'}, {met} of {len(gates)} conditions."
    states = ""
    if edge and edge["cells"]:
        states = ("It learned that every market state it could see loses money and " if edge["positive"] == 0 else
                  f"It learned that {edge['positive']} of {edge['cells']} market states it could see make money and ")
    if ag["fills"] == 0:
        lead = "The agent was right to refuse. " if facts["q1"]["net_bp"] < 0 else ""
        text = f"{lead}{states or 'It '}made no fills in {ag['days_total']} test days. {gate}"
    else:
        text = f"The agent made {ag['fills']:,} fills in {ag['days_total']} days. {gate}"
    return {"id": 4, "key": "agent_refused", "status": "ok", "text": text, "fills": ag["fills"], "days": ag["days_total"],
            "gate_met": met, "gate_total": len(gates), "gate_pass": bool(facts["gates"].get("pass"))}


def v21_conclusion(src: Sources) -> dict:
    base = ("Book imbalance is a real open bet. v2 ran on a book inferred from trades, so it was blind to imbalance and true queue "
            "size. v2.1 tests that on recorded depth, with pass rules already fixed (docs/SPEC_V2_1.md).")
    spec = src.spec_v21
    if spec is None:
        return {"id": 5, "key": "open_bet", "status": "missing", "missing": [src.errors.get("spec_v21", "docs/SPEC_V2_1.md")],
                "text": "The status of v2.1 is not available: docs/SPEC_V2_1.md is missing or unreadable."}
    if re.search(r"no pass rule has been evaluated", re.sub(r"\s+", " ", spec)):
        return {"id": 5, "key": "open_bet", "status": "ok", "evaluated": False, "text": base + " Not yet evaluated."}
    return {"id": 5, "key": "open_bet", "status": "missing", "missing": ["docs/SPEC_V2_1.md (status line)"],
            "text": "The status of v2.1 is not stated in docs/SPEC_V2_1.md in a form this builder can read."}


def conclusions(facts: dict, v1: Optional[dict], v1_err: Optional[str], agent_sent: dict, v21: dict) -> list[dict]:
    q1, front, fee = facts["q1"], facts["front"], facts["cfg"]["maker_fee_bps"]
    out = []
    g, n = q1["gross_bp"], q1["net_bp"]
    if g < 0:
        t1 = (f"Even at zero fee, joining the best price loses {abs(g):.1f} bp per dollar traded at a realistic queue position; "
              f"the {fee:g} bp maker fee {'more than doubles it' if abs(n) > 2 * abs(g) else 'makes it worse'} to {n:.1f} bp.")
    else:
        t1 = (f"Before fees, joining the best price made {g:+.1f} bp per dollar traded at a realistic queue position; "
              f"the {fee:g} bp maker fee turns it into {n:+.1f} bp, so on this run fees decide the result.")
    out.append({"id": 1, "key": "adverse_first", "status": "ok", "text": t1, "adverse_first": g < 0})
    if front is not None:
        lat, fg = latency_of(front), front["gross_bp"]
        near = "near break-even" if abs(fg) <= 2.0 else "at"
        t2 = (f"At the front of the queue with {lat} ms latency the same strategy is {near} before fees ({fg:+.1f} bp); "
              f"behind the displayed size it is {g:+.1f} bp.") if lat else (
              f"At the front of the queue the same strategy is {fg:+.1f} bp before fees; behind the displayed size it is {g:+.1f} bp.")
        out.append({"id": 2, "key": "queue_position", "status": "ok", "text": t2})
    else:
        out.append({"id": 2, "key": "queue_position", "status": "missing", "missing": ["pub-verdict forest row (front of queue)"],
                    "text": "The front-of-queue comparison is not available: its row is missing from the verdict bundle."})
    if v1 is not None:
        out.append({"id": 3, "key": "simulator_realism", "status": "ok",
                    "text": (f"A backtest with no queue model manufactured a {v1['gross_bp']:+.0f} bp edge on {v1['symbol'][:-4]} from one day. "
                             f"The queue model, latency, fees and a gate fixed in advance removed it.")})
    else:
        src_name = v1_err or "results/universe_backtest.csv"
        out.append({"id": 3, "key": "simulator_realism", "status": "missing", "missing": [src_name],
                    "text": f"The one-day no-queue result is not available: {src_name} is missing or unreadable."})
    out += [agent_sent, v21]
    return out


def limits(src: Sources) -> Optional[list[str]]:
    """Three limits from the About page's "Known limitations" list, each cut to its first sentence."""
    if src.about is None:
        return None
    m = re.search(r"Known limitations[^<]*</h2>\s*<ul[^>]*>(.*?)</ul>", src.about, re.S)
    if not m:
        return None
    items = [htmllib.unescape(re.sub(r"<[^>]+>", "", li)).strip() for li in re.findall(r"<li>(.*?)</li>", m.group(1), re.S)]
    items = [re.split(r"(?<=[.!?])\s", re.sub(r"\s+", " ", it), maxsplit=1)[0] for it in items if it]
    return items[:3] if len(items) >= 3 else None


SHORT_MAX = 18          # recruiter-ready spec 5.1: a forest label that fits a phone


def coin_name(symbol: str) -> str:
    return symbol[:-4] if symbol.endswith("USDT") else symbol


def label_short(row: dict) -> str:
    """The forest row's label for narrow screens, at most SHORT_MAX characters: 'Front, 100 ms', 'Queue 1x', 'Agent, 1x' for the
    pooled rows, 'ANKR 1x', 'ANKR front', 'ANKR agent 1x' per coin. The long label stays for hover and wide screens."""
    qm, var, sym = row.get("queue_mult"), str(row.get("variant", "")), str(row.get("symbol", ""))
    front = qm == 0.0 and var != "agent"
    q = f"{qm:g}x" if finite(qm) else ""
    if sym == "ALL":
        if front:
            lat = latency_of(row)
            s = f"Front, {lat} ms" if lat else "Front of queue"
        elif var == "agent":
            s = f"Agent, {q}" if q else "Agent"
        elif var == HEADLINE_STRATEGY or not var:
            s = f"Queue {q}" if q else var
        else:
            s = f"{var} {q}".strip()
    else:
        c = coin_name(sym)
        s = f"{c} front" if front else f"{c} agent {q}".strip() if var == "agent" else f"{c} {q}".strip()
    return s[:SHORT_MAX]


def add_short_labels(forest: list[dict]) -> list[dict]:
    """Every forest row with its label_short (written into the verdict bundle by scripts/build_verdict.py)."""
    return [{**r, "label_short": label_short(r)} for r in forest]


def agent_days(forest: list[dict], coins: list[str]) -> Optional[dict]:
    """The agent's test days and coin-days (spec 5.2): '53 test days (159 coin-days)'. Coin-days add the per-coin agent rows;
    without them, days times coins."""
    ag = next((r for r in forest if r.get("symbol") == "ALL" and r.get("variant") == "agent" and r.get("queue_mult") == HEADLINE_QUEUE), None)
    if ag is None or not finite(ag.get("days_total")):
        return None
    per = [r["days_total"] for r in forest if r.get("symbol") != "ALL" and r.get("variant") == "agent"
           and r.get("queue_mult") == HEADLINE_QUEUE and finite(r.get("days_total"))]
    days, n = int(ag["days_total"]), len(coins)
    coin_days = int(sum(per)) if per else days * n
    return {"fills": int(ag.get("fills") or 0), "days": days, "coins": n, "coin_days": coin_days,
            "context": f"in {days} test days ({coin_days:,} coin-days)",
            "text": f"{int(ag.get('fills') or 0):,} fills · {days} test days ({coin_days:,} coin-days)"}


def forest_rows(facts: dict) -> list[dict]:
    rows = []
    for qm in (0.0, 0.5, 1.0, 2.0):
        r = pooled(facts["forest"], HEADLINE_STRATEGY, qm)
        if r:
            rows.append({**r, "label": "All coins, " + str(r.get("scenario")), "pooled": True})
    for coin in facts["coins"]:
        r = next((x for x in facts["forest"] if x.get("symbol") == coin and x.get("variant") == HEADLINE_STRATEGY
                  and x.get("queue_mult") == HEADLINE_QUEUE and "net_bp" in x), None)
        if r:
            rows.append({**r, "label": f"{coin_name(coin)}, queue {HEADLINE_QUEUE:g}x", "pooled": False})
    keep = ("label", "label_short", "scenario", "symbol", "queue_mult", "net_bp", "gross_bp", "net_se", "gross_se", "t", "n_days", "fills", "pooled")
    return [{k: r.get(k) for k in keep} for r in ({**r, "label_short": label_short(r)} for r in rows[:8])]


STACK = [
    ("data", "Data", "Binance trades from the archive and a live order-book recorder.", "mm/data.py", "#about"),
    ("calibration", "Calibration", "Fits volatility and the fill-rate curve per coin.", "mm/calibrate.py", "#simulator"),
    ("simulator", "Queue-aware simulator", "Replays the tape with queue position, latency and fees.", "mm/queue_sim.py", "#fills"),
    ("agent", "Edge table and agent", "Learns what a fill is worth per market state and picks a setting.", "mm/agent.py", "#agent"),
    ("paper", "Paper trader", "Runs the agent on live data with simulated fills.", "mm/paper.py", "#agent/lv-model"),
    ("testnet", "Testnet executor", "Places real orders on the exchange testnet.", "mm/testnet.py", "#exec-test"),
]


def stack_boxes(src: Sources, facts: Optional[dict], live: dict) -> list[dict]:
    n_cal = int(src.universe["symbol"].nunique()) if src.universe is not None and "symbol" in src.universe else None
    q1 = facts["q1"] if facts else {}
    nums = {
        "data": (q1["days_total"], "days of trades tested") if finite(q1.get("days_total")) else None,
        "calibration": (n_cal, "coins calibrated") if n_cal else None,
        "simulator": (q1["fills"], "simulated fills at queue 1x") if finite(q1.get("fills")) else None,
        "agent": (len(MENU), "settings it chooses between"),
        "paper": (len(live["paper"]), "coins on live data") if live.get("paper") else None,
        "testnet": (live["orders_placed"], "orders placed on testnet") if live.get("testnet") else None,
    }
    where = {"data": "the verdict bundle", "calibration": "results/universe_backtest.csv", "simulator": "the verdict bundle",
             "paper": "the live sessions", "testnet": "the live sessions"}
    boxes = []
    for key, name, line, module, href in STACK:
        n = nums.get(key)
        box = {"key": key, "name": name, "line": line, "module": module, "href": href,
               "number": {"value": n[0], "label": n[1]} if n else None}
        if n is None:
            box["missing"] = where.get(key, "its source")
        boxes.append(box)
    return boxes


# ---------------------------------------------------------------------- the bundle
def build_story(base: Path = Path("."), now: Optional[float] = None, live: bool = True) -> dict:
    src = Sources(base, live)
    sections: dict = {}
    story: dict = {"schema": 1, "title": TITLE,
                   "built_utc": datetime.fromtimestamp(now or time.time(), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
    missing_src = set(src.errors.values())
    live = live_facts(src)
    try:
        facts = test_facts(src)
    except Missing as e:
        facts = None
        missing_src.add(e.source)
    built = facts["built"] if facts else None
    story["provenance"] = {"backtest_built": (built if not built or "UTC" in built else built + " UTC"), "live_snapshot": stamp(live.get("built_ms")) if live else None}

    v1, v1_err = None, None
    if facts:
        try:
            v1 = v1_point(src, facts["cfg"]["maker_fee_bps"])
        except Missing as e:
            v1_err = e.source
            missing_src.add(e.source)
    edge = edge_cells(src)
    gates = gate_rows(src, facts) if facts else None
    verdict_src = src.errors.get("verdict", "dashboard/runs/pub-verdict.js")

    def nofacts(title: str) -> dict:
        return missing_section(title, [verdict_src], "the 60-day verdict bundle")

    # ---- the five conclusions (section 3)
    v21 = v21_conclusion(src)
    if facts:
        concl = conclusions(facts, v1, v1_err, agent_conclusion(facts, edge, gates), v21)
    else:
        concl = [{"id": i, "status": "missing", "missing": [verdict_src],
                  "text": "This conclusion needs the 60-day verdict bundle, which is not available."} for i in range(1, 5)] + [v21]
    story["conclusions"] = concl
    by_id = {c["id"]: c for c in concl}

    # ---- 1 hero
    if facts:
        q1, ag = facts["q1"], facts["agent"]
        tests = (src.tests or {}).get("passed")
        coins = len(facts["coins"])
        agd = agent_days(facts["forest"], facts["coins"])
        tiles = [
            {"key": "net", "label": "Net, bp per dollar traded", "value": q1["net_bp"],
             "context": f"queue {HEADLINE_QUEUE:g}x, after fees, {q1['n_days']} dates, {coins} coins"},
            {"key": "t", "label": "t-statistic", "value": q1.get("t"), "context": f"{q1['n_days']} dates, {coins} coins"},
            {"key": "agent_fills", "label": "Agent fills", "value": ag["fills"] if ag else None,
             "context": agd["context"] if agd else "the agent row is missing from the verdict bundle",
             **({k: agd[k] for k in ("days", "coins", "coin_days", "text")} if agd else {})},
            {"key": "gate", "label": "Gate A", "context": "fixed before the test",
             "value": ("PASS" if facts["gates"].get("pass") else "FAIL") if facts["gates"] else None},
        ]
        parts = []
        if finite(tests):
            parts.append({"key": "tests", "value": int(tests), "label": "tests"})
        parts.append({"key": "days", "value": q1["n_days"], "label": f"days and {coins} coins tested"})
        parts.append({"key": "sim_fills", "value": q1["fills"], "label": "simulated fills"})
        if live.get("testnet"):
            parts.append({"key": "orders", "value": live["orders_placed"], "label": "real orders sent on testnet"})
        sections["hero"] = {
            "status": "ok", "title": TITLE, "tiles": tiles, "facts": parts,
            "facts_line": " · ".join(f"{p['value']:,} {p['label']}" for p in parts),
            "sentence": ("A market-making stack built from the 2008 paper up to live testnet orders. Its "
                         f"{q1['days_total']}-day pre-registered test said {'no' if q1['net_bp'] < 0 else 'yes'}: "
                         f"{q1['net_bp']:.1f} bp per dollar traded after fees.")}
    else:
        sections["hero"] = nofacts(TITLE)

    # ---- 2 stack
    sections["stack"] = {"status": "ok", "title": "What was built.", "boxes": stack_boxes(src, facts, live)}

    # ---- 3 assumptions
    if facts:
        rows = forest_rows(facts)
        pooled_rows = [r for r in rows if r["pooled"]]
        allneg = bool(pooled_rows) and all(r["net_bp"] < 0 for r in pooled_rows)
        sections["assumptions"] = {"status": "ok", "title": "Every assumption loses money." if allneg else "The assumptions disagree.",
                                   "sentence": by_id[1]["text"], "rows": rows, "fee_bp": facts["cfg"]["maker_fee_bps"],
                                   "link": {"href": "#verdict", "label": "See the evidence →"}}
    else:
        sections["assumptions"] = nofacts("Every assumption loses money.")

    # ---- 4 waterfall
    try:
        if not facts:
            raise Missing(verdict_src)
        wf = waterfall_terms(src)
        mk = next((r for r in facts["compare"] if r.get("symbol") == "ALL" and r.get("variant") == HEADLINE_STRATEGY
                   and r.get("queue_mult") == HEADLINE_QUEUE and finite(r.get("mk_60"))), None)
        sections["waterfall"] = {
            "status": "ok", "title": "Where a fill's money goes.", "net_bp": wf["net"], "days": wf["days"],
            "terms": [{"key": "spread", "label": "Spread captured", "label_short": "Spread<br>captured", "bp": wf["spread"]},
                      {"key": "inventory", "label": "Inventory and adverse selection", "label_short": "Inventory,<br>adverse<br>selection",
                       "bp": wf["inventory"]},
                      {"key": "fee", "label": "Fee", "label_short": "Fee", "bp": wf["fee"]}],
            "net_label_short": "Net",
            "markout_60_bp": mk["mk_60"] if mk else None,
            "sentence": (f"At queue {HEADLINE_QUEUE:g}x, per dollar traded: {wf['spread']:+.1f} bp of spread captured, "
                         f"{wf['inventory']:+.1f} bp lost to the price moving against the fill and to inventory, "
                         f"{wf['fee']:+.1f} bp of fee, {wf['net']:+.1f} bp net."),
            "link": {"href": "#fills", "label": "See the evidence →"}}
    except Missing as e:
        sections["waterfall"] = missing_section("Where a fill's money goes.", [e.source], "the spread, inventory and fee terms of the 60-day test")

    # ---- 5 ladder
    title5 = "The edge that was not there."
    if facts and v1 is not None:
        lat = facts["cfg"].get("latency_ms")
        suffix = f", {lat:g} ms" if finite(lat) else ""
        pts = [{"key": "v1", "label": f"v1 backtest, no queue model ({v1['symbol'][:-4]}, one day, {v1['date']})",
                "label_short": f"v1, no queue<br>{coin_name(v1['symbol'])}, 1 day",
                "gross_bp": v1["gross_bp"], "net_bp": v1["net_bp"], "one_day": True}]
        for key, qm in (("front", 0.0), ("q1", 1.0), ("q2", 2.0)):
            r = pooled(facts["forest"], HEADLINE_STRATEGY, qm)
            if r is None:
                break
            fl = latency_of(r)
            label = (f"front of queue{f', {fl} ms' if fl else ''}" if key == "front" else f"queue {qm:g}x{suffix}")
            short = (f"Front{f'<br>{fl} ms' if fl else ' of queue'}" if key == "front"
                     else f"Queue {qm:g}x" + (f"<br>{lat:g} ms" if finite(lat) else ""))
            pts.append({"key": key, "label": label, "label_short": short, "gross_bp": r["gross_bp"], "net_bp": r["net_bp"], "one_day": False})
        if len(pts) == 4:
            sections["ladder"] = {"status": "ok", "title": title5, "points": pts, "sentence": by_id[3]["text"],
                                  "link": {"href": "#verdict", "label": "See the evidence →"}}
        else:
            sections["ladder"] = missing_section(title5, ["pub-verdict forest rows"], "the front-of-queue and queue rows of the verdict bundle")
    else:
        sections["ladder"] = missing_section(title5, [v1_err or verdict_src], "the v1 one-day result and the 60-day rows")

    # ---- 6 agent
    title6 = "The agent declined to trade."
    if facts and gates is not None and by_id[4]["status"] == "ok":
        paper = live.get("paper")
        line = None
        if paper:
            since = day_label(live.get("paper_since_ms"))
            best = max(paper, key=lambda b: len(b["fills"]))
            line = (f"On live data{f' since {since}' if since else ''}, the paper trader ({len(paper)} coins) has made "
                    f"{live['paper_fills']:,} fills. {best['takeaways'].get('why_out', '')}").strip()
        sections["agent"] = {"status": "ok", "title": title6 if facts["agent"]["fills"] == 0 else "The agent traded.",
                             "sentence": by_id[4]["text"], "gate": {"pass": bool(facts["gates"].get("pass")), "conditions": gates},
                             "paper_line": line, "paper_line_missing": None if line else "the live sessions",
                             "link": {"href": "#agent", "label": "See the evidence →"}}
    else:
        sections["agent"] = missing_section(title6, by_id[4].get("missing") or [verdict_src], "the agent row and the Gate A conditions")

    # ---- 7 execution
    if live.get("testnet"):
        tape_ex, _ = tape_example(src, live)            # the Execution test page opens on it; the Story no longer draws it
        caught, foot = story_caught(live["caught"])
        sections["execution"] = {
            "status": "ok", "title": "It sends real orders.", "label": "TESTNET: execution test, not a result",
            "sentence": ("Testnet is for one question: are orders placed, replaced, filled, counted and cancelled correctly? "
                         "Its book is thin and moved by other people's test bots, so its P&L is noise."),
            "numbers": {"placed": live["orders_placed"], "filled": live["orders_filled"], "rejected": live["orders_rejected"],
                        "fills": live["testnet_fills"]},
            "caught": caught, "caught_footnote": foot,
            "caught_missing": None if caught else "the session bundles carry no list of what the test caught yet",
            "lifecycle": order_lifecycle(live["testnet"]),
            "link": {"href": "#exec-test", "label": "See the evidence →"}}
        story["tape_example"] = ({k: tape_ex[k] for k in ("session", "symbol", "day", "t", "i", "caption")} if tape_ex else None)
    else:
        sections["execution"] = missing_section("It sends real orders.", ["dashboard/live/session-*.js"], "the testnet session bundles")

    # ---- 8 next (recruiter-ready spec 5.4): the next experiment only; the simulator caveats live on the Method and limits page
    title8 = "What is next."
    lim, nxt = limits(src), by_id[5]
    if nxt["status"] == "ok":
        sections["next"] = {"status": "ok", "title": title8, "sentence": nxt["text"],
                            "limits_line": {"lead": "What these simulations cannot show:", "href": "#about", "label": "Method and limits"},
                            "links": [{"href": "https://github.com/xuantung9999-create/Market-Making-ASv2/blob/main/docs/SPEC_V2_1.md",
                                       "label": "docs/SPEC_V2_1.md"}]}
    else:
        sections["next"] = missing_section(title8, nxt.get("missing", []), "the v2.1 status")
    if lim:
        story["about_limits"] = {"title": "What this cannot show", "items": lim}
    else:
        story["about_limits"] = None
        missing_src.add(src.errors.get("about", "dashboard/index.html (Known limitations)"))

    story["sections"] = sections
    story["sources_missing"] = sorted(missing_src | {s for sec in sections.values() for s in sec.get("missing", [])})
    return clean(relative_to(story, Path(base)))


def relative_to(o, base: Path):
    """Every string with the absolute project folder taken off its front, so a "missing" sentence names dashboard/live/..., not a
    path on this PC (the Story is published)."""
    prefix = Path(base).resolve().as_posix().rstrip("/") + "/"
    if isinstance(o, dict):
        return {k: relative_to(v, base) for k, v in o.items()}
    if isinstance(o, list):
        return [relative_to(v, base) for v in o]
    if isinstance(o, str):
        return o.replace(prefix, "").replace(prefix.replace("/", "\\"), "")
    return o


def write_story(story: dict, out_dir: Path) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / OUT_NAME
    text = "window.STORY = " + json.dumps(story, separators=(",", ":"), allow_nan=False, ensure_ascii=False) + ";\n"
    tmp = path.with_suffix(".js.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return path


def main(argv: Optional[list[str]] = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    base = Path(args[0]) if args else Path(".")
    story = build_story(base)
    path = write_story(story, base / "dashboard" / "runs")
    miss = [k for k, s in story["sections"].items() if s["status"] == "missing"]
    print(f"story -> {path} ({path.stat().st_size / 1e3:.0f} kB)" + (f"; missing sections: {', '.join(miss)}" if miss else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
