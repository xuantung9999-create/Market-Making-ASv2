"""v2 Task 9: is the book we infer from trades close enough to the real one?

All of Tasks 7-8 run on a book INFERRED from trades with an ASSUMED queue size. The recorder
(Task 1) saves the real best bid/ask and their displayed sizes. For every recorded coin-day this
runs Join touch (headline config) twice on the same recorded trades: once on the real book,
once on the book inferred from those trades, and compares fills, net edge and queue wait.

Hours containing a recording gap longer than 120 s (the PC slept, the connection dropped) are
removed from both runs before comparing.

Verdict (pooled over days): "inferred tape acceptable" if fills agree within +/-30% and the
fill-weighted net edge within 2 bp. Otherwise the measured level-size ratio is reported, and
you decide whether to re-run Tasks 7-8 with level_qty scaled by it.

    python -m scripts.validate_tape                     # reads data/live/<SYMBOL>/book|trades
    python -m scripts.validate_tape --live data/paper/feed
Writes results/tape_validation.csv.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from mm.calibrate import infer_tick
from mm.queue_sim import JoinTouch, QSConfig, run_queue_sim
from mm.recorder import load_live
from mm.tape import book_from_recorder, book_from_trades, default_level_qty, typical_level_qty

DAY_US, HOUR_US = 86_400_000_000, 3_600_000_000
FILL_TOL, EDGE_TOL_BP = 0.30, 2.0


def drop_gap_hours(book: pd.DataFrame, trades: pd.DataFrame, max_gap_s: float = 120.0):
    """Remove every UTC hour that contains a gap longer than ``max_gap_s`` between consecutive
    events (book and trades together). Returns (book, trades, hours kept)."""
    ts = np.sort(np.concatenate([book["ts_us"].to_numpy(np.int64), trades["ts_us"].to_numpy(np.int64)]))
    if ts.size == 0:
        return book, trades, 0
    hours = set(range(int(ts[0] // HOUR_US), int(ts[-1] // HOUR_US) + 1))
    bad = set()
    gaps = np.flatnonzero(np.diff(ts) > max_gap_s * 1e6)
    for g in gaps:
        bad.update(range(int(ts[g] // HOUR_US), int(ts[g + 1] // HOUR_US) + 1))
    keep = hours - bad
    kb = book["ts_us"].floordiv(HOUR_US).isin(keep).to_numpy()
    kt = trades["ts_us"].floordiv(HOUR_US).isin(keep).to_numpy()
    return book[kb].reset_index(drop=True), trades[kt].reset_index(drop=True), len(keep)


def verdict(df: pd.DataFrame) -> tuple[bool, dict]:
    fr, fi = float(df["fills_real"].sum()), float(df["fills_inf"].sum())
    w_real = (df["net_edge_real"] * df["fills_real"]).sum() / fr if fr else np.nan
    w_inf = (df["net_edge_inf"] * df["fills_inf"]).sum() / fi if fi else np.nan
    ratio = fi / fr if fr else np.nan
    ok = bool(np.isfinite(ratio) and abs(ratio - 1) <= FILL_TOL and abs(w_inf - w_real) <= EDGE_TOL_BP)
    return ok, {"fill_ratio": ratio, "net_edge_real": float(w_real), "net_edge_inf": float(w_inf),
                "edge_diff_bp": float(w_inf - w_real)}


def _summ(res) -> tuple[int, float, float]:
    f = res.fills
    edge = float(np.nanmean(f["net_edge_bp"])) if len(f) and f["net_edge_bp"].notna().any() else np.nan
    return int(len(f)), edge, float(f["wait_s"].median()) if len(f) else np.nan


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m scripts.validate_tape")
    ap.add_argument("--live", default="data/live")
    ap.add_argument("--out", default="results/tape_validation.csv")
    ap.add_argument("--min-hours", type=int, default=6, help="skip coin-days with fewer usable hours")
    args = ap.parse_args(argv)
    cfg = QSConfig()
    rows = []
    for folder in sorted(p for p in Path(args.live).iterdir() if p.is_dir()) if Path(args.live).exists() else []:
        sym = folder.name
        try:
            book_all = book_from_recorder(load_live(folder / "book"))
            tr = load_live(folder / "trades")
        except FileNotFoundError:
            print(f"skip {sym}: book or trades missing")
            continue
        trades_all = tr.assign(ts_us=tr["recv_us"])[["ts_us", "price", "qty", "side"]]   # same clock as the book
        trades_all = trades_all.sort_values("ts_us", kind="stable").reset_index(drop=True)
        for day_no in sorted(set(book_all["ts_us"] // DAY_US) & set(trades_all["ts_us"] // DAY_US)):
            day = pd.Timestamp(day_no * DAY_US, unit="us", tz="UTC").strftime("%Y-%m-%d")
            b = book_all[book_all["ts_us"] // DAY_US == day_no]
            t = trades_all[trades_all["ts_us"] // DAY_US == day_no]
            b, t, hours = drop_gap_hours(b, t)
            if hours < args.min_hours or len(t) < 50 or t["side"].nunique() < 2:
                print(f"skip {sym} {day}: {hours} usable hours, {len(t)} trades")
                continue
            tick = infer_tick(np.concatenate([t["price"].to_numpy(float), b["bid"].to_numpy(float), b["ask"].to_numpy(float)]))
            inferred = book_from_trades(t, tick, default_level_qty(t))
            if inferred.empty:
                print(f"skip {sym} {day}: no inferred book")
                continue
            fr, er, wr = _summ(run_queue_sim(b, t, JoinTouch(), cfg, tick))
            fi, ei, wi = _summ(run_queue_sim(inferred, t, JoinTouch(), cfg, tick))
            rows.append({"symbol": sym, "date": day, "hours": hours, "fills_real": fr, "fills_inf": fi,
                         "net_edge_real": er, "net_edge_inf": ei, "wait_med_real": wr, "wait_med_inf": wi,
                         "fill_ratio": fi / fr if fr else np.nan, "edge_diff_bp": ei - er,
                         "level_ratio": typical_level_qty(b) / default_level_qty(t)})
            print(f"done {sym} {day}", flush=True)
    if not rows:
        print(f"no recorded coin-days with >= {args.min_hours} usable hours in {args.live}. "
              f"Run run_recorder_multi.bat for at least 3 days first.")
        return
    df = pd.DataFrame(rows)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.out, index=False)
    with pd.option_context("display.width", 160, "display.float_format", "{:,.2f}".format):
        print(df.to_string(index=False))
    ok, nums = verdict(df)
    print(f"\npooled: fills inferred/real = {nums['fill_ratio']:.2f}, net edge real {nums['net_edge_real']:.2f} bp, "
          f"inferred {nums['net_edge_inf']:.2f} bp (difference {nums['edge_diff_bp']:+.2f} bp)")
    if ok:
        print("VERDICT: inferred tape acceptable")
    else:
        print(f"VERDICT: inferred tape NOT acceptable. Measured level-size ratio (real / assumed): "
              f"median {df['level_ratio'].median():.2f}. You decide whether to re-run Tasks 7-8 with level_qty scaled by it.")
    n_days = df["date"].nunique()
    if n_days < 3:
        print(f"note: only {n_days} recorded day(s); the guide asks for at least 3 before trusting this verdict")
    print(f"saved -> {args.out}")


if __name__ == "__main__":
    main()
