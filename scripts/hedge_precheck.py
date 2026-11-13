"""v2.1 Task 17: can a BTC perpetual hedge help this coin at all?

Per coin, from the Join-touch fills at the headline queue (1x) and the BTCUSDT perpetual trades:

  1. inventory half-life: the time for a position to halve (AR(1) on the minute-sampled inventory);
  2. R2 of the coin's returns on BTC perpetual returns at that horizon (at least 5 minutes).

STOP if the half-life is under 5 minutes (positions are gone before a hedge could act) or R2 is under
0.15 (BTC explains too little of the coin). Otherwise GO to Task 18 for that coin. Expected for micro caps
in calm markets: stop. Needs data/futures/BTCUSDT_<date>_trades.parquet (run_futures_download.bat).

    python -m scripts.hedge_precheck                     # or run_hedge_precheck.bat
Writes results/hedge_precheck.json.
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

from mm.queue_sim import JoinTouch, QSConfig, run_queue_sim
from scripts.v2_common import load_day, symbol_days, v2_universe

MIN_US = 60 * 1_000_000
MIN_HALF_LIFE_MIN = 5.0
MIN_R2 = 0.15
MIN_OBS = 20


def inventory_path(fills: pd.DataFrame, start_us: int, end_us: int) -> np.ndarray:
    """Inventory in lots at the end of each minute from ``start_us`` to ``end_us``."""
    n = int((end_us - start_us) // MIN_US) + 1
    q = np.zeros(n)
    if len(fills):
        m = ((fills["ts_us"].to_numpy(np.int64) - start_us) // MIN_US).clip(0, n - 1)
        np.add.at(q, m, fills["side"].to_numpy(float))
    return np.cumsum(q)


def half_life_minutes(paths: list) -> float:
    """Pooled AR(1) half-life of minute-sampled inventory. 0 if it flips sign every minute, inf if it
    never decays, nan if no inventory was ever held."""
    num = den = 0.0
    for q in paths:
        q = np.asarray(q, float)
        num += float((q[:-1] * q[1:]).sum())
        den += float((q[:-1] ** 2).sum())
    if den <= 0:
        return float("nan")
    phi = num / den
    if phi <= 0:
        return 0.0
    if phi >= 1:
        return float("inf")
    return float(math.log(0.5) / math.log(phi))


def _returns(coin: pd.DataFrame, btc: pd.DataFrame, horizon_min: float) -> tuple[np.ndarray, np.ndarray]:
    """Non-overlapping log returns over ``horizon_min`` of both series on one shared grid."""
    h = int(round(horizon_min * MIN_US))
    series = []
    for df in (coin, btc):
        s = pd.Series(df["price"].to_numpy(float), index=df["ts_us"].to_numpy(np.int64) // h).groupby(level=0).last()
        series.append(s)
    lo, hi = max(s.index.min() for s in series), min(s.index.max() for s in series)
    if hi <= lo:
        return np.array([]), np.array([])
    grid = np.arange(lo, hi + 1)
    px = [np.log(s.reindex(grid).ffill()) for s in series]
    return np.diff(px[0].to_numpy()), np.diff(px[1].to_numpy())


def _ols(rc: np.ndarray, rb: np.ndarray) -> dict:
    if len(rc) < MIN_OBS or rb.var() <= 0 or rc.var() <= 0:
        return {"beta": float("nan"), "r2": float("nan"), "n": int(len(rc))}
    beta = float(np.cov(rc, rb, ddof=0)[0, 1] / rb.var())
    return {"beta": beta, "r2": float(np.corrcoef(rc, rb)[0, 1] ** 2), "n": int(len(rc))}


def r2_vs_btc(coin: pd.DataFrame, btc: pd.DataFrame, horizon_min: float) -> dict:
    return _ols(*_returns(coin, btc, horizon_min))


def decide(half_life_min: float, r2: float) -> tuple[str, str]:
    if not (half_life_min == half_life_min) or not (r2 == r2):
        return "not evaluated", "no inventory or no overlapping BTC perp data"
    if half_life_min < MIN_HALF_LIFE_MIN:
        return "stop", f"inventory half-life {half_life_min:.1f} min is under {MIN_HALF_LIFE_MIN:g} min: positions are gone before a hedge could act"
    if r2 < MIN_R2:
        return "stop", f"R2 {r2:.3f} is under {MIN_R2:g}: BTC explains too little of this coin's returns"
    return "go", f"half-life {half_life_min:.1f} min and R2 {r2:.3f} clear both thresholds"


def _btc_day(fut_dir: str, day: str):
    p = Path(fut_dir) / f"BTCUSDT_{day}_trades.parquet"
    return pd.read_parquet(p) if p.exists() else None


def precheck(sym: str, data_dir: str = "data", fut_dir: str = "data/futures", queue_mult: float = 1.0) -> dict:
    cfg = replace(QSConfig(), queue_mult=queue_mult)
    paths, days, per_day = [], [], []
    for day in symbol_days(sym, data_dir):
        btc = _btc_day(fut_dir, day)
        got = load_day(sym, day, data_dir)
        if btc is None or got is None:
            continue
        trades, tick, tape = got
        res = run_queue_sim(tape, trades, JoinTouch(), cfg, tick)
        if len(res.fills):
            paths.append(inventory_path(res.fills, int(trades["ts_us"].min()), int(trades["ts_us"].max())))
        days.append(day)
        per_day.append((trades, btc))
    hl = half_life_minutes(paths) if paths else float("nan")
    horizon = min(max(hl, MIN_HALF_LIFE_MIN), 60.0) if hl == hl else MIN_HALF_LIFE_MIN
    rets = [_returns(c, b, horizon) for c, b in per_day]
    ols = _ols(np.concatenate([r[0] for r in rets]), np.concatenate([r[1] for r in rets])) if rets else {"beta": float("nan"), "r2": float("nan"), "n": 0}
    decision, reason = decide(hl, ols["r2"])
    if not days:
        reason = "no days with both the coin's trades and BTC perp trades (run_futures_download.bat)"
    return {"symbol": sym, "days": len(days), "half_life_min": hl, "horizon_min": horizon, "r2": ols["r2"],
            "beta": ols["beta"], "n_returns": ols["n"], "decision": decision, "reason": reason}


def _clean(d: dict) -> dict:
    return {k: (None if isinstance(v, float) and not math.isfinite(v) else v) for k, v in d.items()}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m scripts.hedge_precheck")
    ap.add_argument("--symbols", default=None)
    ap.add_argument("--data", default="data")
    ap.add_argument("--futures", default="data/futures")
    ap.add_argument("--out", default="results/hedge_precheck.json")
    args = ap.parse_args(argv)
    syms = args.symbols.split(",") if args.symbols else v2_universe()
    out = {}
    print(f"{'coin':<10}{'days':>5}{'half-life':>11}{'horizon':>9}{'R2':>8}{'beta':>7}  decision")
    for sym in syms:
        r = precheck(sym, args.data, args.futures)
        out[sym] = _clean(r)
        hl = "never" if r["half_life_min"] == float("inf") else f"{r['half_life_min']:.1f}m"
        print(f"{sym:<10}{r['days']:>5}{hl:>11}{r['horizon_min']:>8.0f}m{r['r2']:>8.3f}{r['beta']:>7.2f}  {r['decision'].upper()}: {r['reason']}")
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(out, indent=2))
    go = [s for s, r in out.items() if r["decision"] == "go"]
    print(f"\nGO for: {', '.join(go) if go else 'no coin'} -> " + ("Task 18 (mm/hedge.py) may proceed for these." if go else "stop; do not build the hedge."))
    print(f"saved -> {args.out}")


if __name__ == "__main__":
    main()
