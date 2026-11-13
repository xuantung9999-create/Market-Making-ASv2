"""Export everything the dashboard shows into dashboard/data.js.

Run from the repo root whenever results change:
    python -m scripts.build_dashboard

The dashboard (dashboard/index.html) is a static page: open it in a browser, host it
on GitHub Pages, or embed it on a website. It needs no server. All numbers it shows
come from this file, except the live simulator, which runs in the browser.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from mm.calibrate import calibrate
from mm.data import load_trades, summarize, trades_to_bars
from mm.simulator import SimConfig, compare, paper_table, simulate
from mm.strategy import ASParams, PAPER_PARAMS

OUT = Path("dashboard/data.js")
DATA_DIR = Path("data")


def sig(x, digits=6):
    """Round to significant digits (keeps micro-cap prices like 0.003852 intact)."""
    a = np.asarray(x, dtype=float)
    out = []
    for v in a:
        if not np.isfinite(v):
            out.append(None)
        elif v == 0:
            out.append(0.0)
        else:
            out.append(float(f"{v:.{digits}g}"))
    return out


def r(x, n=4):
    """Round floats (and arrays) for a compact JSON file; NaN -> None."""
    if isinstance(x, (list, tuple, np.ndarray, pd.Series)):
        return [r(v, n) for v in np.asarray(x, dtype=float)]
    x = float(x)
    return None if not np.isfinite(x) else round(x, n)


# --------------------------------------------------------------------------- simulation
def replication() -> dict:
    table = paper_table(n_paths=1000, seed=0)
    exp_path = Path("results/day4_experiments.csv")
    experiments = pd.read_csv(exp_path).to_dict("records") if exp_path.exists() else []

    base = dict(gamma=0.1, sigma=2.0, k=1.5, A=140.0)
    cfg = SimConfig(n_paths=1000, seed=0)
    caps = []
    for qm in (1, 2, 3, 4, 5, 6, 8, 10, 15):
        s = simulate(ASParams(**base, q_max=qm), cfg, "symmetric").summary()
        caps.append({"q_max": qm, "mean": r(s["mean_pnl"], 2), "std": r(s["std_pnl"], 2),
                     "sharpe": r(s["mean_pnl"] / s["std_pnl"], 3)})
    a = simulate(ASParams(**base), cfg, "inventory").summary()

    crn = []
    p = ASParams(**base)
    for seed in range(20):
        same = compare(p, SimConfig(n_paths=100, seed=seed)).set_index("strategy")["mean_pnl"]
        indep = (simulate(p, SimConfig(n_paths=100, seed=seed), "symmetric").summary()["mean_pnl"]
                 - simulate(p, SimConfig(n_paths=100, seed=1000 + seed), "inventory").summary()["mean_pnl"])
        crn.append({"seed": seed, "same": r(same["symmetric"] - same["inventory"], 3), "indep": r(indep, 3)})

    return {
        "paper_table": [{k: (r(v, 3) if isinstance(v, (float, np.floating)) else v)
                         for k, v in row.items()} for row in table.to_dict("records")],
        "experiments": [{k: (r(v, 3) if isinstance(v, (float, np.floating)) else v)
                         for k, v in row.items()} for row in experiments],
        "cap_sweep": caps,
        "as_reference": {"mean": r(a["mean_pnl"], 2), "std": r(a["std_pnl"], 2),
                         "sharpe": r(a["mean_pnl"] / a["std_pnl"], 3)},
        "crn": crn,
    }


# --------------------------------------------------------------------------- real data
def real_day(path: Path) -> dict:
    trades = load_trades(path)
    info = summarize(trades)
    sec = trades_to_bars(trades, freq_ms=1000)
    sec["time"] = pd.to_datetime(sec["ts_us"], unit="us", utc=True)
    s = sec.set_index("time")
    m = pd.DataFrame({
        "mid": s["mid"].resample("1min").last(),
        "hi": s["mid"].resample("1min").max(),
        "lo": s["mid"].resample("1min").min(),
        "trades": s["n_trades"].resample("1min").sum(),
        "buy_vol": s["buy_vol"].resample("1min").sum(),
        "sell_vol": s["sell_vol"].resample("1min").sum(),
        "sigma_1h": s["mid"].diff().rolling(3600, min_periods=600).std().resample("1min").last(),
        "sigma_5m": s["mid"].diff().rolling(300, min_periods=60).std().resample("1min").last(),
    })
    cal = calibrate(trades)
    f = cal["fill_curve"]
    fc = {"delta": r(f["delta"], 6), "p": r(f["p"], 6), "lam": r(f["lam"], 6), "k": r(f["k"], 6),
          "A": r(f["A"], 6), "r2": r(f["r2"], 4), "fit_from": r(f["fit_from"], 8)}
    sizes = trades["qty"].to_numpy()
    q = np.quantile(sizes, [0.5, 0.9, 0.99, 0.999])
    return {
        "symbol": path.stem.split("_")[0],
        "date": str(info["start_utc"].date()),
        "summary": {
            "n_trades": int(info["n_trades"]),
            "buy_share": r(info["buy_share"], 4),
            "volume_base": r(info["volume_base"], 2),
            "usd_volume": r(float((trades["price"] * trades["qty"]).sum()), 0),
            "price_min": sig([info["price_min"]])[0], "price_max": sig([info["price_max"]])[0],
            "price_last": sig([info["price_last"]])[0],
            "tick": cal["tick"], "spread": cal["spread"], "spread_bp": r(cal["spread_bp"], 3), "tier": cal["tier"],
            "trades_per_sec": r(info["trades_per_sec"], 2),
            "sigma": sig([info["sigma_usdt_per_sqrt_s"]], 4)[0],
            "sigma_bp": r(info["sigma_usdt_per_sqrt_s"] / info["price_last"] * 1e4, 3),
            "daily_vol_pct": r(info["daily_vol_pct"], 3),
            "size_q50": r(q[0], 5), "size_q90": r(q[1], 5), "size_q99": r(q[2], 5), "size_q999": r(q[3], 5),
        },
        "minute": {
            "t": [t.strftime("%Y-%m-%dT%H:%M:%SZ") for t in m.index],
            **{c: sig(m[c].to_numpy(), 6) for c in m.columns},
        },
        "fill_curve": fc,
    }


def live_snapshot() -> dict | None:
    """Summary of the live recorder's top-of-book data, if any has been recorded."""
    book_dir = DATA_DIR / "live" / "BTCUSDT" / "book"
    if not book_dir.exists() or not any(book_dir.glob("*.parquet")):
        return None
    from mm.recorder import load_live
    b = load_live(book_dir)
    spread = (b["ask"] - b["bid"]).round(2)
    counts = spread.value_counts().sort_index().head(10)
    hours = (b["recv_us"].iloc[-1] - b["recv_us"].iloc[0]) / 3.6e9
    return {"updates": int(len(b)), "hours": r(hours, 2),
            "spread_values": r(counts.index.to_numpy(), 2),
            "spread_share": r((counts / len(b)).to_numpy(), 4)}


def backtest_runs() -> dict | None:
    """Day 7 results written by scripts/run_backtest.py. Minute curves are thinned to
    every 5 minutes to keep the page light; summaries are exact."""
    path = Path("results/backtest_runs.json")
    if not path.exists():
        return None
    bt = json.loads(path.read_text())
    for run in bt["runs"]:
        for st in run["strategies"]:
            m = st["minute"]
            idx = list(range(0, len(m["t"]), 5))
            if idx[-1] != len(m["t"]) - 1:
                idx.append(len(m["t"]) - 1)
            st["minute"] = {k: [v[i] for i in idx] for k, v in m.items()}
    return bt


def universe_runs() -> dict | None:
    """Day 8 results written by scripts/run_universe.py (already thinned to 5-minute curves)."""
    path = Path("results/universe_runs.json")
    return json.loads(path.read_text()) if path.exists() else None


def walkforward_runs() -> dict | None:
    """Day 9 results written by scripts/run_walkforward.py (curves every 30 minutes)."""
    path = Path("results/walkforward_runs.json")
    return json.loads(path.read_text()) if path.exists() else None


def _json_or_none(path: str):
    p = Path(path)
    return json.loads(p.read_text()) if p.exists() else None


def tests_passed() -> int | None:
    try:
        out = subprocess.run([sys.executable, "-m", "pytest", "-q"], capture_output=True, text=True, timeout=300)
        for tok in out.stdout.split():
            if tok.isdigit():
                last = int(tok)
        return last if "passed" in out.stdout else None
    except Exception:
        return None


def main() -> None:
    by_sym: dict[str, list[Path]] = {}
    for p in sorted(DATA_DIR.glob("*_trades.parquet")):
        by_sym.setdefault(p.stem.split("_")[0], []).append(p)
    recent = [p for ps in by_sym.values() for p in ps[-2:]]          # last 2 days per coin keeps the page light
    days = [real_day(p) for p in recent]
    days.sort(key=lambda d: (d["symbol"] != "BTCUSDT", d["symbol"], d["date"]))
    payload = {
        "built": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "tests_passed": tests_passed(),
        "paper_params": {"gamma": PAPER_PARAMS.gamma, "sigma": PAPER_PARAMS.sigma,
                         "k": PAPER_PARAMS.k, "A": PAPER_PARAMS.A, "T": PAPER_PARAMS.T, "dt": 0.005},
        "replication": replication(),
        "real_days": days,
        "live": live_snapshot(),
        "backtest": backtest_runs(),
        "universe": universe_runs(),
        "walkforward": walkforward_runs(),
        "sweep": _json_or_none("results/sweep_runs.json"),
        "leadlag": _json_or_none("results/leadlag_runs.json"),
        "book": _json_or_none("results/book_study.json"),
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text("// Generated by scripts/build_dashboard.py. Do not edit by hand.\n"
                   "window.DASH = " + json.dumps(payload, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e3:.0f} kB): {len(days)} real day(s), "
          f"tests passed: {payload['tests_passed']}")
    for d in days:
        fc = d["fill_curve"]
        print(f"  {d['date']}: sigma {d['summary']['sigma']}, fill fit k={fc['k']} /USDT, "
              f"A={fc['A']} /s, R2={fc['r2']}")


if __name__ == "__main__":
    main()
