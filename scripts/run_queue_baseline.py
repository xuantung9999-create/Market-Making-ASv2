"""v2 Task 7: does the micro-cap edge survive a queue?

For every v2-universe coin (results/screen.csv) and every downloaded day: infer the book from
trades, run "Join touch" (always rest at the best bid and ask) through the queue engine with
the fixed scenario (10 bp fee, 300 ms latency, $100 lots, |q| <= 10) at three queue
assumptions: 0.5x (optimistic), 1.0x (headline), 2.0x (stress) the displayed size ahead of us.
A fourth run, queue 0 + 100 ms latency, is a bridge to v1's optimistic "touch" fill rule.

Nothing is tuned here. This is the first honest look at the edge.

    python -m scripts.run_queue_baseline
Writes results/queue_baseline.csv and prints one table per variant.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from datetime import datetime, timezone

from mm import report
from mm.metrics import summarize
from mm.queue_sim import JoinTouch, QSConfig, run_queue_sim
from scripts.v2_common import fee_note, load_day, symbol_days, t_stat, v2_universe

FEES = (0.0, 7.5, 10.0)
VARIANTS = [("q1.0", dict(queue_mult=1.0)), ("q0.5", dict(queue_mult=0.5)), ("q2.0", dict(queue_mult=2.0)),
            ("bridge q0 lat100", dict(queue_mult=0.0, latency_ms=100))]


def run(symbols, data_dir="data", keep: list | None = None) -> pd.DataFrame:
    """One row per symbol, day and variant. If ``keep`` is a list, (symbol, day, variant, result)
    tuples are appended to it for the dashboard bundle."""
    rows = []
    for sym in symbols:
        last_tick = None
        for day in symbol_days(sym, data_dir):
            got = load_day(sym, day, data_dir)
            if got is None:
                continue
            trades, tick, tape = got
            if last_tick is not None and not np.isclose(tick, last_tick):
                print(f"WARNING {sym} {day}: tick changed {last_tick:g} -> {tick:g}")
            last_tick = tick
            for name, kw in VARIANTS:
                cfg = replace(QSConfig(), **kw)
                res = run_queue_sim(tape, trades, JoinTouch(), cfg, tick)
                s = summarize(res, fee_bps_scenarios=FEES)
                f = res.fills
                s.update(symbol=sym, day=day, variant=name, queue_mult=cfg.queue_mult, latency_ms=cfg.latency_ms,
                         tick=tick, net_edge_bp_mean=float(np.nanmean(f["net_edge_bp"])) if len(f) and f["net_edge_bp"].notna().any() else np.nan,
                         wait_s_median=float(f["wait_s"].median()) if len(f) else np.nan)
                rows.append(s)
                if keep is not None:
                    keep.append((sym, day, name, res))
            print(f"done {sym} {day}", flush=True)
    return pd.DataFrame(rows)


def per_symbol(df: pd.DataFrame) -> pd.DataFrame:
    out = []
    for (variant, sym), g in df.groupby(["variant", "symbol"], sort=False):
        notional = g["notional_usdt"].sum()
        out.append({"variant": variant, "symbol": sym, "days": len(g),
                    "fills_per_day": g["fills"].mean(),
                    "net_usd_per_day": g["net_10bp"].mean(),
                    "net_bp_per_usd": g["net_10bp"].sum() / notional * 1e4 if notional else np.nan,
                    "net7.5_usd_per_day": g["net_7.5bp"].mean(),
                    "net_edge_bp_mean": g["net_edge_bp_mean"].mean(),
                    "positive_days": (g["net_10bp"] > 0).mean(),
                    "t": t_stat(g["net_10bp"])})
    return pd.DataFrame(out)


def sanity_check(df: pd.DataFrame, wf_csv="results/walkforward.csv") -> None:
    p = Path(wf_csv)
    row = df[(df["symbol"] == "ANKRUSDT") & (df["day"] == "2026-11-10") & (df["variant"] == "bridge q0 lat100")]
    if not p.exists() or row.empty:
        print("sanity check skipped (needs ANKRUSDT 2026-11-10 and results/walkforward.csv)")
        return
    wf = pd.read_csv(p)
    v1 = wf[(wf["symbol"] == "ANKRUSDT") & (wf["test_date"] == "2026-11-10") & (wf["strategy"] == "Join touch")
            & (wf["fill_rule"] == "touch")]
    if v1.empty:
        print("sanity check skipped (no v1 Join touch / touch row for ANKRUSDT 2026-11-10)")
        return
    a, b = row.iloc[0], v1.iloc[0]
    same_sign = np.sign(a["net_10bp"]) == np.sign(b["net_10bp"])
    print(f"\nSanity check ANKRUSDT 2026-11-10, v2 bridge (queue 0, 100 ms) vs v1 Join touch 'touch':\n"
          f"  fills  v2 {int(a['fills'])}  v1 {int(b['fills'])}\n"
          f"  net 10bp USD  v2 {a['net_10bp']:.2f}  v1 {b['net_10bp']:.2f}\n"
          f"  same sign: {same_sign}" + ("" if same_sign else "   -> STOP AND REPORT (guide Task 7)"))


class _Fills:
    """Minimal result-like object so mm.report.markout_rows can pool fills over many days."""
    def __init__(self, fills):
        self.fills, self.markouts = fills, None


def write_dashboard_bundle(kept: list, screen_csv: str = "results/screen.csv", out_dir: str = "dashboard/runs"):
    """Dashboard Guide D12: run id qb-<UTC date>, kind backtest, one variant per queue assumption."""
    if not kept:
        return None
    cfg = QSConfig()
    days, curves, hourly, markouts, wait = [], {}, {}, [], {}
    groups: dict = {}
    for sym, day, var, res in kept:
        days.append(report.day_row(res, sym, day, var))
        groups.setdefault((sym, var), []).append(res)
    for (sym, var), results in groups.items():
        key = f"{sym}|{var}"
        curves[key] = report.curve(results)
        hourly[key] = report.hourly(results)
        fills = pd.concat([r.fills for r in results if len(r.fills)], ignore_index=True) if any(len(r.fills) for r in results) else pd.DataFrame()
        if len(fills):
            markouts += report.markout_rows(_Fills(fills), sym, var)
            if var == "q1.0":
                wait[sym] = report.wait_hist_of(fills)
    screen = report.screen_rows(pd.read_csv(screen_csv)) if Path(screen_csv).exists() else None
    date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    b = report.build_bundle(f"qb-{date}", "backtest", f"Queue baseline: Join touch ({len(groups) // len(VARIANTS)} coins)",
                            {"maker_fee_bps": cfg.maker_fee_bps, "latency_ms": cfg.latency_ms, "queue_mult": cfg.queue_mult,
                             "lot_usd": cfg.lot_usd, "q_max": cfg.q_max, "decision_ms": cfg.decision_ms},
                            days, curves=curves, hourly=hourly, markouts=markouts, wait_hist=wait, screen=screen)
    path = report.write_bundle(b, out_dir)
    print(f"dashboard bundle -> {path}")
    return path


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m scripts.run_queue_baseline")
    ap.add_argument("--data", default="data")
    ap.add_argument("--symbols", default=None, help="comma list; default = v2 universe from results/screen.csv")
    ap.add_argument("--out", default="results/queue_baseline.csv")
    args = ap.parse_args(argv)
    syms = args.symbols.split(",") if args.symbols else v2_universe()
    print(f"v2 universe: {', '.join(syms)}")
    kept: list = []
    df = run(syms, args.data, keep=kept)
    if df.empty:
        print("no usable days")
        return
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    tab = per_symbol(df)
    with pd.option_context("display.width", 160, "display.float_format", "{:,.2f}".format):
        for v, g in tab.groupby("variant", sort=False):
            print(f"\n== Join touch, {v} ==")
            print(g.drop(columns="variant").to_string(index=False))
    print("\n" + fee_note())
    sanity_check(df)
    print(f"saved -> {args.out}")
    write_dashboard_bundle(kept)


if __name__ == "__main__":
    main()
