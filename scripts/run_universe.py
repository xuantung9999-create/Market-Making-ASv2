"""Day 8: calibrate every coin on day 1, backtest it out of sample on day 2.

Run from the repo root after scripts/download_universe.py (a few minutes):
    python -m scripts.run_universe

Per coin, everything is sized in dollars and basis points so coins are comparable:
  lot            $100 of the coin per fill, inventory cap 10 lots ($1,000)
  Join touch     fixed quotes at the typical spread (the best bid/ask)
  Fixed 1/k      fixed quotes at the calibrated A-S order-flow half-spread
  A-S            calibrated k and sigma (30-min EWMA), gamma from a target skew:
                 at full inventory the reservation price moves max(10 bp, 2 spreads)
  A-S fast σ     same, sigma with a 5-minute half-life so quotes widen faster in spikes
Each is run with strict ("through") and optimistic ("touch") fills. On tick-constrained coins
the gap between the two is the value of queue position.

Writes results/universe_calibration.csv, results/universe_backtest.csv,
results/universe_runs.json (dashboard), results/day8_fill_fits.png, results/day8_universe.png.
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
from mm.calibrate import calibrate, gamma_from_skew, random_entry_markouts
from mm.data import load_trades
from mm.metrics import summarize

LOT_USD, Q_MAX, HORIZON = 100.0, 10, 3600.0
TIER_ORDER = {"large": 0, "mid": 1, "small": 2, "micro": 3}


def rnd(x, n=4):
    if isinstance(x, (list, tuple, np.ndarray, pd.Series)):
        return [rnd(v, n) for v in np.asarray(x, float)]
    x = float(x)
    return None if not np.isfinite(x) else round(x, n)


def strategies(cal: dict) -> list:
    tick, spread, k = cal["tick"], cal["spread"], cal["k"]
    k_ok = np.isfinite(k) and k > 0
    k_use = k if k_ok else 2.0 / spread                 # fallback: order-flow half-spread = half a spread
    skew_bp = max(10.0, 2 * cal["spread_bp"])
    g = gamma_from_skew(skew_bp, cal["price"], cal["sigma"], Q_MAX, HORIZON)
    tag = "" if k_ok else " (k from spread)"
    out = [FixedSpread(spread / 2, q_max=Q_MAX, tick=tick, name="Join touch")]
    if k_ok:
        out.append(FixedSpread(1 / k, q_max=Q_MAX, tick=tick, name="Fixed 1/k"))
    out.append(ASQuoter(gamma=g, k=k_use, horizon_s=HORIZON, q_max=Q_MAX, tick=tick, name="A-S" + tag))
    out.append(ASQuoter(gamma=g, k=k_use, horizon_s=HORIZON, q_max=Q_MAX, tick=tick, name="A-S fast σ" + tag))
    return out


def main() -> None:
    files = sorted(Path("data").glob("*_trades.parquet"))
    by_sym: dict[str, list[Path]] = {}
    for p in files:
        by_sym.setdefault(p.stem.split("_")[0], []).append(p)
    cal_rows, bt_rows, coins = [], [], []
    for sym, paths in sorted(by_sym.items()):
        if len(paths) < 2:
            print(f"{sym}: needs 2 days, skipping")
            continue
        t0 = time.time()
        (d1, d2) = paths[:2]
        cals = []
        for p in (d1, d2):
            c = calibrate(load_trades(p), sym, p.stem.split("_")[1])
            cals.append(c)
            cal_rows.append({k: v for k, v in c.items() if k != "fill_curve"})
        c1 = cals[0]
        trades2 = load_trades(d2)
        lot = LOT_USD / c1["price"]
        base = BTConfig(lot=lot)
        bars = prepare_bars(trades2, base)
        bars_fast = bars.copy()
        bars_fast["sigma"] = prepare_bars(trades2, replace(base, sigma_halflife_s=300.0))["sigma"]
        rand = random_entry_markouts(bars, base.bar_ms, horizons_s=(0, 1, 5, 10, 30, 60, 120, 300))
        coin = {"symbol": sym, "tier": c1["tier"], "days": [c["date"] for c in cals],
                "calibration": [{**{k: (rnd(v, 6) if isinstance(v, float) else v) for k, v in c.items() if k != "fill_curve"},
                                 "fill_curve": {"delta_bp": rnd(c["fill_curve"]["delta"] / c["price"] * 1e4, 3),
                                                "lam": rnd(c["fill_curve"]["lam"], 6),
                                                "fit_from_bp": rnd(c["fill_curve"]["fit_from"] / c["price"] * 1e4, 3)}}
                                for c in cals],
                "random_markouts": {"h_s": rand["h_s"].tolist(), "bp": rnd(rand["markout_bp"], 3)},
                "runs": []}
        t_start = pd.Timestamp(int(bars["ts_us"].iloc[0]), unit="us", tz="UTC")
        for rule in ("through", "touch"):
            cfg = replace(base, fill_rule=rule)
            for q in strategies(c1):
                res = run_backtest(bars_fast if "fast" in q.name else bars, q, cfg)
                s = summarize(res)
                s["pnl_per_1k_capital"] = s["pnl"] / (LOT_USD * Q_MAX) * 1000
                bt_rows.append({"symbol": sym, "tier": c1["tier"], "date": c2date(d2), "fill_rule": rule,
                                "spread_bp": c1["spread_bp"], "tick_bp": c1["tick_bp"], **s})
                m = res.minute
                idx = list(range(0, len(m), 5)) + ([len(m) - 1] if (len(m) - 1) % 5 else [])
                coin["runs"].append({
                    "fill_rule": rule, "name": res.name,
                    "summary": {k: (rnd(v, 4) if isinstance(v, (float, np.floating)) else v) for k, v in s.items()},
                    "pnl": {"t": [(t_start + pd.Timedelta(seconds=float(m["t_s"].iloc[i]))).strftime("%Y-%m-%d %H:%M") for i in idx],
                            "v": rnd(m["pnl"].iloc[idx], 3)},
                    "markouts": {"h_s": res.markouts["h_s"].tolist(), "bp": rnd(res.markouts["markout_bp"], 3)},
                })
        coins.append(coin)
        print(f"{sym:9s} {c1['tier']:5s} spread {c1['spread_bp']:6.2f} bp  k_bp {c1['k_bp']:.3f}  "
              f"R2 {c1['r2']:.3f}  ({time.time() - t0:.0f}s)", flush=True)

    coins.sort(key=lambda c: (TIER_ORDER[c["tier"]], -c["calibration"][0]["usd_volume_day"]))
    cal_df, bt_df = pd.DataFrame(cal_rows), pd.DataFrame(bt_rows)
    cal_df.to_csv("results/universe_calibration.csv", index=False)
    bt_df.to_csv("results/universe_backtest.csv", index=False)
    Path("results/universe_runs.json").write_text(json.dumps(
        {"meta": {"lot_usd": LOT_USD, "q_max_lots": Q_MAX, "horizon_s": HORIZON, "calibrated_on": "day 1",
                  "tested_on": "day 2"}, "coins": coins}, separators=(",", ":")))
    plot_fits(coins)
    plot_universe(bt_df)
    cols = ["symbol", "tier", "fill_rule", "strategy", "pnl", "pnl_bps_of_volume", "fills_per_hour",
            "markout_60s_bp", "adverse_selection_bp", "q_std", "net_2bp"]
    pd.set_option("display.width", 250)
    print(bt_df[cols].round(2).to_string(index=False))


def c2date(p: Path) -> str:
    return p.stem.split("_")[1]


def plot_fits(coins: list) -> None:
    n = len(coins)
    cols = 4
    rows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(rows, cols, figsize=(16, 3.4 * rows), squeeze=False)
    for ax, coin in zip(axes.ravel(), coins):
        c = coin["calibration"][0]
        fc = c["fill_curve"]
        x = np.array([np.nan if v is None else v for v in fc["delta_bp"]], float)
        y = np.array([np.nan if v is None else v for v in fc["lam"]], float)
        ok = y > 0
        ax.semilogy(x[ok], y[ok], "o", ms=3, color="#333")
        if c["k_bp"] and c["A"]:
            xf = x[(x >= (fc["fit_from_bp"] or 0)) & ok]
            ax.semilogy(xf, c["A"] * np.exp(-c["k_bp"] * xf), color="#0ea5e9", lw=2)
        r2 = f"{c['r2']:.3f}" if c["r2"] is not None else "n/a"
        kb = f"{c['k_bp']:.3f}" if c["k_bp"] is not None else "n/a"
        ax.set_title(f"{coin['symbol']} ({coin['tier']}): k={kb}/bp, R²={r2}", fontsize=10)
        ax.set_xlabel("δ (bp from mid)", fontsize=8)
    for ax in axes.ravel()[n:]:
        ax.axis("off")
    fig.suptitle("Fill intensity λ(δ) per second vs distance from mid, with exponential fit (day 1)")
    fig.tight_layout()
    fig.savefig("results/day8_fill_fits.png", dpi=110)
    plt.close(fig)


def plot_universe(bt: pd.DataFrame) -> None:
    fig, ax = plt.subplots(1, 2, figsize=(14, 5))
    colors = {"large": "#111", "mid": "#2563eb", "small": "#16a34a", "micro": "#dc2626"}
    for rule, mk in (("through", "o"), ("touch", "^")):
        d = bt[(bt.fill_rule == rule) & (bt.strategy == "Join touch")]
        for _, r in d.iterrows():
            ax[0].scatter(r.spread_bp, r.pnl_bps_of_volume, marker=mk, color=colors[r.tier], s=50)
            ax[0].annotate(r.symbol.replace("USDT", ""), (r.spread_bp, r.pnl_bps_of_volume), fontsize=7,
                           xytext=(4, 2), textcoords="offset points")
    ax[0].axhline(0, color="#999", lw=0.8)
    ax[0].set_xscale("log")
    ax[0].set(title="Join-touch quoter, day 2: P&L per $ traded vs spread\n● strict fills  ▲ optimistic fills",
              xlabel="typical spread (bp, log scale)", ylabel="P&L (bp of volume)")
    best = bt[bt.fill_rule == "through"].sort_values("pnl").groupby("symbol").tail(1)
    best = best.assign(o=best.tier.map(TIER_ORDER)).sort_values(["o", "symbol"])
    ax[1].barh(best.symbol + " · " + best.strategy, best.pnl_per_1k_capital, color=[colors[t] for t in best.tier])
    ax[1].axvline(0, color="#999", lw=0.8)
    ax[1].invert_yaxis()
    ax[1].set(title="Best strategy per coin, strict fills, no fees\nUSD P&L per day per $1,000 inventory limit",
              xlabel="USD per day")
    fig.tight_layout()
    fig.savefig("results/day8_universe.png", dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    main()
