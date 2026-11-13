"""Day 7: first real-data backtest of A-S against fixed-spread benchmarks.

Run from the repo root (takes about a minute per day):
    python -m scripts.run_backtest

Parameters are deliberately rough (Day 8 calibrates properly):
  sigma  EWMA of 100 ms mid changes, 30-minute half-life, past data only
  k      0.15 per USDT, from the 9 Nov fill-curve fit (so 10 Nov is out of sample)
  gamma  1e-5 and 1e-4 per (USDT x lot); horizon resets every hour
  lot    0.001 BTC per fill, inventory cap 10 lots, requote every 500 ms, 50 ms latency

Each strategy is run under two fill rules that bracket reality:
  through  a quote fills only if a trade prints strictly beyond it (pessimistic)
  touch    a trade at our price is enough (optimistic: as if first in the queue)

Writes:
  results/backtest_summary.csv           one row per day x fill rule x strategy
  results/backtest_runs.json             minute-level curves for the dashboard
  results/day7_<date>_backtest.png       P&L, attribution, markouts, inventory
"""
from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from mm.backtest import ASQuoter, BTConfig, FixedSpread, prepare_bars, run_backtest
from mm.data import load_trades
from mm.metrics import summarize

K_CAL = 0.15
STRATEGIES = [
    FixedSpread(0.5), FixedSpread(2.0), FixedSpread(6.5),
    ASQuoter(gamma=1e-5, k=K_CAL), ASQuoter(gamma=1e-4, k=K_CAL), ASQuoter(gamma=1e-5, k=1.5),
]
RULES = ("through", "touch")
COLORS = ["#b0bec5", "#90a4ae", "#f5a524", "#38bdf8", "#0ea5e9", "#a78bfa"]


def r2(a, n=3):
    return [None if not np.isfinite(v) else round(float(v), n) for v in np.asarray(a, float)]


def main() -> None:
    files = sorted(Path("data").glob("*_trades.parquet"))
    if not files:
        raise SystemExit("no data: run  python -m mm.data download --symbol BTCUSDT --date 2026-11-09 --days 2")
    base = BTConfig()
    rows, runs = [], []
    for path in files:
        date = path.stem.split("_")[1]
        t0 = time.time()
        bars = prepare_bars(load_trades(path), base)
        t_start = pd.Timestamp(int(bars["ts_us"].iloc[0]), unit="us", tz="UTC")
        for rule in RULES:
            cfg = replace(base, fill_rule=rule)
            day_runs = []
            for q in STRATEGIES:
                res = run_backtest(bars, q, cfg)
                s = summarize(res)
                rows.append({"date": date, "fill_rule": rule, **s})
                m = res.minute
                day_runs.append({
                    "name": res.name, "summary": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in s.items()},
                    "minute": {"t": [(t_start + pd.Timedelta(seconds=float(x))).strftime("%Y-%m-%d %H:%M") for x in m["t_s"]],
                               "pnl": r2(m["pnl"], 2), "q": r2(m["q"], 0),
                               "spread_capture": r2(m["spread_capture"], 2), "inventory_pnl": r2(m["inventory_pnl"], 2)},
                    "markouts": {"h_s": res.markouts["h_s"].tolist(), "bp": r2(res.markouts["markout_bp"], 3)},
                })
                if rule == "through":
                    plot_rows = day_runs
            runs.append({"date": date, "fill_rule": rule, "strategies": day_runs})
        print(f"{date}: done in {time.time() - t0:.0f}s")
        plot_day(date, [r for r in runs if r["date"] == date and r["fill_rule"] == "through"][0]["strategies"])

    df = pd.DataFrame(rows)
    df.to_csv("results/backtest_summary.csv", index=False)
    meta = {"k": K_CAL, "lot_btc": base.lot, "q_max_lots": 10, "requote_ms": base.requote_ms,
            "latency_ms": base.latency_ms, "bar_ms": base.bar_ms, "sigma_halflife_s": base.sigma_halflife_s,
            "horizon_s": 3600}
    Path("results/backtest_runs.json").write_text(json.dumps({"meta": meta, "runs": runs}, separators=(",", ":")))
    cols = ["date", "fill_rule", "strategy", "pnl", "spread_capture", "inventory_pnl", "fills_per_hour",
            "pnl_bps_of_volume", "edge_bp", "markout_60s_bp", "adverse_selection_bp", "max_drawdown", "q_std", "net_2bp"]
    pd.set_option("display.width", 250)
    print(df[cols].round(2).to_string(index=False))


def plot_day(date: str, strat_runs: list) -> None:
    fig, ax = plt.subplots(2, 2, figsize=(14, 9))
    for c, r in zip(COLORS, strat_runs):
        m = r["minute"]
        x = np.arange(len(m["pnl"])) / 60
        ax[0, 0].plot(x, m["pnl"], color=c, label=r["name"], lw=1.3)
        ax[1, 0].plot(r["markouts"]["h_s"], r["markouts"]["bp"], "o-", color=c, ms=3)
    ax[0, 0].set(title=f"P&L, USDT ({date}, strict fills, no fees)", xlabel="hours (UTC)")
    ax[0, 0].legend(fontsize=8)
    names = [r["name"] for r in strat_runs]
    sc = [r["summary"]["spread_capture"] for r in strat_runs]
    ip = [r["summary"]["inventory_pnl"] for r in strat_runs]
    y = np.arange(len(names))
    ax[0, 1].barh(y - 0.2, sc, 0.4, color="#34d399", label="spread capture")
    ax[0, 1].barh(y + 0.2, ip, 0.4, color="#f87171", label="inventory P&L")
    ax[0, 1].set_yticks(y, names, fontsize=8)
    ax[0, 1].axvline(0, color="#999", lw=0.8)
    ax[0, 1].invert_yaxis()
    ax[0, 1].set(title="Where the P&L came from (USDT)")
    ax[0, 1].legend(fontsize=8)
    ax[1, 0].axhline(0, color="#999", lw=0.8)
    ax[1, 0].set_xscale("symlog", linthresh=1)
    ax[1, 0].set_xlim(0, 330)
    ax[1, 0].set(title="Markout after fill (bp): falling = adverse selection", xlabel="seconds after fill")
    lots = np.arange(-10, 11)
    w = 0.8 / len(strat_runs)
    for j, (c, r) in enumerate(zip(COLORS, strat_runs)):
        qv = np.asarray(r["minute"]["q"], float)
        share = [(qv == v).mean() * 100 for v in lots]
        ax[1, 1].bar(lots - 0.4 + (j + 0.5) * w, share, w, color=c)
    ax[1, 1].set(title="Time spent at each inventory level (% of minutes)", xlabel="inventory (lots of 0.001 BTC)")
    fig.tight_layout()
    out = Path("results") / f"day7_{date}_backtest.png"
    fig.savefig(out, dpi=120)
    plt.close(fig)
    print(f"saved {out}")


if __name__ == "__main__":
    main()
