"""v2 Task 11: the daily supervisor for the paper trader.

For every paper coin and every closed UTC day it has not checked yet:

1. REPLAY. Re-run the day from the agent's saved start-of-day state, the recorded feed and the
   paper trader's own timer schedule. Fills and net P&L must match the paper log exactly; any
   difference is a bug to report, not noise to average away.
2. CALIBRATION. Compare the realised net edge of the day's live fills with what the edge table
   predicted for them: z = (realised - predicted) / standard error. Fills in hours with a
   recording gap longer than 120 s are left out of this comparison.
3. COIN STATE. z < -2 (the model was too optimistic) halves the size for that coin; two such days
   in a row disable it; three normal days restore full size. The paper trader reads
   data/paper/coin_state.json at start and at every UTC midnight.
4. REPORT. results/paper_report_<date>.md, and Gate B numbers once 14 paper days exist.

    python -m scripts.daily_supervisor
"""
from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

from mm import report as rep
from mm.agent import AgentConfig
from mm.edge import EdgeTable
from mm.paper import DAY_US, replay_day
from mm.recorder import load_live
from mm.tape import book_from_recorder
from scripts.validate_tape import drop_gap_hours

DAY_RE = re.compile(r"^day_(\d{4}-\d{2}-\d{2})\.json$")
GATE_B_DAYS = 14
MIN_FILLS = 20


def update_coin_state(prev: dict, z: float) -> dict:
    """One day's update of a coin's size and on/off switch from its calibration z-score."""
    st = {"size_mult": 1.0, "enabled": True, "bad": 0, "good": 0, **prev}
    if not (isinstance(z, (int, float)) and math.isfinite(z)):
        return dict(prev) if prev else st
    if z < -2:
        st["bad"], st["good"] = st["bad"] + 1, 0
        st["size_mult"] = 0.5
        if st["bad"] >= 2:
            st["enabled"] = False
    else:
        st["good"], st["bad"] = st["good"] + 1, 0
        if st["good"] >= 3:
            st["size_mult"], st["enabled"] = 1.0, True
    return st


def z_score(fills: pd.DataFrame) -> float:
    if not {"net_edge_bp", "pred_edge_bp"} <= set(fills.columns):
        return float("nan")
    f = fills[["net_edge_bp", "pred_edge_bp"]].astype(float)
    f = f[np.isfinite(f["net_edge_bp"]) & np.isfinite(f["pred_edge_bp"])]
    if len(f) < 2 or f["net_edge_bp"].std(ddof=1) == 0:
        return float("nan")
    se = f["net_edge_bp"].std(ddof=1) / math.sqrt(len(f))
    return float((f["net_edge_bp"].mean() - f["pred_edge_bp"].mean()) / se)


def gate_b(rows: list[dict]) -> dict | None:
    """Gate B numbers (no pass rule is pre-registered yet: the scoreboard shows n/a)."""
    dates = {r["date"] for r in rows}
    if len(dates) < GATE_B_DAYS:
        return None
    counted = [r for r in rows if r.get("fills", 0) >= MIN_FILLS]
    x = np.array([r["pnl"] for r in counted], float)
    t = float(x.mean() / (x.std(ddof=1) / math.sqrt(x.size))) if x.size > 1 and x.std(ddof=1) > 0 else None
    match = float(np.mean([bool(r.get("match")) for r in rows])) if rows else None
    conds = [
        {"id": "B1", "text": "mean daily net P&L across coin-days (USD)", "value": float(x.mean()) if x.size else None, "pass": None},
        {"id": "B2", "text": "t-statistic of daily net P&L", "value": t, "pass": None},
        {"id": "B3", "text": "share of positive coin-days", "value": float((x > 0).mean()) if x.size else None, "pass": None},
        {"id": "B4", "text": "replay match rate", "value": match, "pass": None},
    ]
    return {"paper_days": len(dates), "coin_days": int(x.size), "conditions": conds, "pass": None}


def _day_feed(feed_dir: Path, sym: str, day: str):
    d0 = pd.Timestamp(day, tz="UTC").value // 1000
    book = book_from_recorder(load_live(feed_dir / sym / "book"))
    tr = load_live(feed_dir / sym / "trades")
    trades = tr.assign(ts_us=tr["recv_us"])[["ts_us", "price", "qty", "side"]].sort_values("ts_us", kind="stable")
    inday = lambda df: df[(df["ts_us"] >= d0) & (df["ts_us"] < d0 + DAY_US)].reset_index(drop=True)
    return inday(book), inday(trades)


def supervise(paper_dir="data/paper", state_dir="data/paper/state", results_dir="results",
              agent_cfg: AgentConfig = AgentConfig(), write_bundle: bool = True) -> list[dict]:
    paper_dir, state_dir, results_dir = Path(paper_dir), Path(state_dir), Path(results_dir)
    log_path = paper_dir / "supervisor_log.json"
    log = json.loads(log_path.read_text()) if log_path.exists() else {"rows": []}
    done = {(r["symbol"], r["date"]) for r in log["rows"]}
    cs_path = paper_dir / "coin_state.json"
    coin_state = json.loads(cs_path.read_text()) if cs_path.exists() else {}
    new_rows = []
    for folder in sorted(p for p in paper_dir.iterdir() if p.is_dir() and p.name not in ("feed", "state")) if paper_dir.exists() else []:
        sym = folder.name
        for f in sorted(folder.glob("day_*.json")):
            day = DAY_RE.match(f.name).group(1)
            if (sym, day) in done:
                continue
            info = json.loads(f.read_text())
            start_p = state_dir / f"{sym}_start_{day}.json"
            if not start_p.exists():
                print(f"skip {sym} {day}: no start-of-day state")
                continue
            start = json.loads(start_p.read_text())
            book, trades = _day_feed(paper_dir / "feed", sym, day)
            res = replay_day(start, book, trades, info, agent_cfg)
            match = bool(len(res.fills) == info["fills"] and abs(res.totals["pnl"] - info["pnl"]) < 1e-6)
            fp = folder / f"fills_{day}.parquet"
            fills = pd.read_parquet(fp) if fp.exists() else pd.DataFrame()
            if len(fills):                                   # leave out fills in hours with recorder gaps
                _, kept, _ = drop_gap_hours(book, fills[["ts_us"]].assign(price=0.0, qty=0.0, side=0))
                fills = fills[fills["ts_us"].isin(kept["ts_us"])]
            z = z_score(fills)
            before = coin_state.get(sym, {})
            coin_state[sym] = update_coin_state(before, z)
            changed = (before.get("size_mult", 1.0), before.get("enabled", True)) != (coin_state[sym]["size_mult"], coin_state[sym]["enabled"])
            notional = float(res.totals.get("notional", 0.0))
            row = {"symbol": sym, "date": day, "fills": int(info["fills"]), "pnl": float(info["pnl"]),
                   "net_bp_per_usd": info["pnl"] / notional * 1e4 if notional else None,
                   "replay_fills": int(len(res.fills)), "replay_pnl": float(res.totals["pnl"]), "match": match,
                   "live_arm": info.get("live_arm"), "z": z if math.isfinite(z) else None,
                   "size_mult": coin_state[sym]["size_mult"], "enabled": coin_state[sym]["enabled"], "state_changed": changed,
                   "day_row": rep.day_row(res, sym, day, "agent", {"live_arm": info.get("live_arm")})}
            print(f"{sym} {day}: fills {row['fills']} (replay {row['replay_fills']}), pnl {row['pnl']:.2f} "
                  f"(replay {row['replay_pnl']:.2f}) -> {'MATCH' if match else 'MISMATCH: report this as a bug'}; z = {z:.2f}")
            new_rows.append(row)
    if not new_rows:
        print("no new closed paper days to check")
        return []
    log["rows"] += new_rows
    log_path.write_text(json.dumps(log, indent=1))
    cs_path.write_text(json.dumps(coin_state, indent=1))
    _write_report(log["rows"], new_rows, results_dir)
    if write_bundle:
        _write_paper_bundle(log["rows"], state_dir, paper_dir)
    return new_rows


def _fmt(x, nd=2):
    return "–" if x is None or (isinstance(x, float) and not math.isfinite(x)) else (f"{x:,.{nd}f}" if isinstance(x, float) else str(x))


def _write_report(all_rows: list[dict], new_rows: list[dict], results_dir: Path) -> Path:
    day = max(r["date"] for r in new_rows)
    lines = [f"# Paper trading report, {day} (UTC)", "", "No orders were sent: this is paper trading on live public data.", "",
             "## Days checked in this run", "",
             "| Symbol | Date | Fills | Net P&L (USD) | Net bp per $ | Live arm | z (realised vs predicted) | Replay | Size × | Enabled | State change |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in new_rows:
        lines.append(f"| {r['symbol']} | {r['date']} | {r['fills']} | {_fmt(r['pnl'])} | {_fmt(r['net_bp_per_usd'])} | {_fmt(r['live_arm'])} | "
                     f"{_fmt(r['z'])} | {'match' if r['match'] else '**MISMATCH**'} | {r['size_mult']:g} | {r['enabled']} | {'yes' if r['state_changed'] else ''} |")
    lines += ["", "## All paper days", "", "| Symbol | Date | Fills | Net P&L (USD) | z | Replay |", "|---|---|---|---|---|---|"]
    for r in sorted(all_rows, key=lambda r: (r["date"], r["symbol"])):
        lines.append(f"| {r['symbol']} | {r['date']} | {r['fills']} | {_fmt(r['pnl'])} | {_fmt(r['z'])} | {'match' if r['match'] else 'MISMATCH'} |")
    g = gate_b(all_rows)
    lines += ["", "## Gate B", ""]
    if g is None:
        lines.append(f"Not yet: {len({r['date'] for r in all_rows})} of {GATE_B_DAYS} paper days so far.")
    else:
        for c in g["conditions"]:
            lines.append(f"- {c['id']} {c['text']}: {_fmt(c['value'], 3)}")
        lines.append("")
        lines.append("Only after you have looked at these numbers do the deferred items (legal route, risk budget, server, real orders) come back on the table.")
    mism = [r for r in all_rows if not r["match"]]
    if mism:
        lines += ["", f"**{len(mism)} replay mismatch(es): a bug to investigate before trusting any paper result.**"]
    results_dir.mkdir(parents=True, exist_ok=True)
    out = results_dir / f"paper_report_{day}.md"
    out.write_text("\n".join(lines) + "\n")
    print(f"report -> {out}")
    return out


def _write_paper_bundle(all_rows: list[dict], state_dir: Path, paper_dir: Path) -> None:
    """Dashboard Guide D12: one growing paper bundle, rewritten daily."""
    days = [r["day_row"] for r in all_rows if r.get("day_row")]
    if not days:
        return
    edge, agent = [], []
    for sym in sorted({r["symbol"] for r in all_rows}):
        t = state_dir / f"{sym}_table.json"
        if t.exists():
            edge += rep.edge_rows(EdgeTable.from_dict(json.loads(t.read_text())), sym)
        for h in sorted((paper_dir / sym).glob("history_*.jsonl")):
            agent += rep.agent_rows([json.loads(x) for x in h.read_text().splitlines() if x.strip()], sym)
    g = gate_b(all_rows)
    first = min(r["date"] for r in all_rows)
    b = rep.build_bundle(f"paper-{first}", "paper", f"Paper trading since {first}",
                         {"maker_fee_bps": 10.0, "latency_ms": 300, "lot_usd": 100.0, "q_max": 10, "decision_ms": 1000},
                         days, edge=edge or None, agent=agent or None, gates={"B": g} if g else None)
    print(f"dashboard bundle -> {rep.write_bundle(b)}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m scripts.daily_supervisor")
    ap.add_argument("--paper", default="data/paper")
    ap.add_argument("--state", default="data/paper/state")
    ap.add_argument("--results", default="results")
    args = ap.parse_args(argv)
    supervise(args.paper, args.state, args.results)


if __name__ == "__main__":
    main()
