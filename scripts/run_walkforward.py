"""Day 9: walk-forward test of calibration and defences against informed traders.

For every coin and every test day D (from the 4th available day on):
  calibrate on the 3 days before D   tick, spread, sigma, k (one exponential), k_core (two-part
                                     fill curve), and the flow alpha model (imbalance/momentum ->
                                     next 10 s move)
  test on day D, never seen before   strict fills, 50 ms latency, $100 per fill, $1,000 cap

Strategies (all quote through mm.protect.ProtectedAS, which matches mm.strategy.quote):
  A-S (tail k)       single-exponential k, the Day 8 calibration
  A-S (core k)       k from the core of the two-part fill curve
  + lean             core k, quotes shifted by the predicted 10 s move
  + kill switch      core k, no quotes while vol ratio > 3 or for 5 s after a sweep
  + lean + kill      both defences (core k)
  Tail k + lean + kill   both defences on the wider Day 8 quotes
  Join touch         fixed quotes at the typical spread; also with both defences.
                     The two join variants are also run with "touch" fills (first in queue).

Run from the repo root (about 10 minutes on 2 cores):
    python -m scripts.run_walkforward
Writes results/walkforward.csv, results/walkforward_alpha.csv, results/walkforward_runs.json,
results/day9_walkforward.png.
"""
from __future__ import annotations

import json
import time
from dataclasses import replace
from multiprocessing import Pool
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from mm.backtest import BTConfig, prepare_bars, run_backtest
from mm.calibrate import calibrate, gamma_from_skew
from mm.data import load_trades
from mm.flow import fit_alpha, flow_features, forward_return_bp, out_of_sample_r2, predict_alpha
from mm.metrics import summarize
from mm.protect import ProtectedAS

LOT_USD, Q_MAX, HORIZON, CAL_DAYS = 100.0, 10, 3600.0, 3
TIER_ORDER = {"large": 0, "mid": 1, "small": 2, "micro": 3}
STRAT_ORDER = ["A-S (tail k)", "A-S (core k)", "+ lean", "+ kill switch", "+ lean + kill",
               "Tail k + lean + kill", "Join touch", "Join + lean + kill"]


def files_by_symbol() -> dict[str, list[Path]]:
    out: dict[str, list[Path]] = {}
    for p in sorted(Path("data").glob("*_trades.parquet")):
        out.setdefault(p.stem.split("_")[0], []).append(p)
    return out


def run_coin(args) -> dict:
    sym, paths = args
    t0 = time.time()
    trades = {p.stem.split("_")[1]: load_trades(p) for p in paths}
    dates = sorted(trades)
    base = BTConfig()
    feats, fwds = {}, {}
    for d in dates:                                   # features per day (each day on its own grid)
        b = prepare_bars(trades[d], base)
        feats[d], fwds[d] = flow_features(b, base.bar_ms), forward_return_bp(b, 10, base.bar_ms)
    rows, alpha_rows, curves = [], [], {}
    for j in range(CAL_DAYS, len(dates)):
        test, cal_days = dates[j], dates[j - CAL_DAYS:j]
        cal = calibrate(pd.concat([trades[d] for d in cal_days], ignore_index=True), sym, test)
        model = fit_alpha([feats[d] for d in cal_days], [fwds[d] for d in cal_days])
        bars = prepare_bars(trades[test], base)
        f = feats[test]
        alpha = predict_alpha(model, f)
        oos = out_of_sample_r2(alpha, fwds[test])
        alpha_rows.append({"symbol": sym, "tier": cal["tier"], "test_date": test, **{f"in_{k}": v for k, v in model.as_dict()["coef"].items()},
                           **{f"t_{k}": v for k, v in model.as_dict()["tstat"].items()}, "r2_in": model.r2, "n_in": model.n, **oos})
        k_tail = cal["k"] if np.isfinite(cal["k"]) and cal["k"] > 0 else 2.0 / cal["spread"]
        k_core = cal["k_core"] if np.isfinite(cal["k_core"]) and cal["k_core"] > 0 else k_tail
        g = gamma_from_skew(max(10.0, 2 * cal["spread_bp"]), cal["price"], cal["sigma"], Q_MAX, HORIZON)
        common = dict(gamma=g, horizon_s=HORIZON, q_max=Q_MAX, tick=cal["tick"], bar_ms=base.bar_ms)
        defend = dict(vol_ratio=f["vol_ratio"].to_numpy(), sweep_z=f["sweep_z"].to_numpy())
        strategies = [
            ("A-S (tail k)", ProtectedAS(k=k_tail, **common), ("through",)),
            ("A-S (core k)", ProtectedAS(k=k_core, **common), ("through",)),
            ("+ lean", ProtectedAS(k=k_core, alpha_bp=alpha, **common), ("through",)),
            ("+ kill switch", ProtectedAS(k=k_core, **defend, **common), ("through",)),
            ("+ lean + kill", ProtectedAS(k=k_core, alpha_bp=alpha, **defend, **common), ("through",)),
            ("Tail k + lean + kill", ProtectedAS(k=k_tail, alpha_bp=alpha, **defend, **common), ("through", "touch")),
            ("Join touch", ProtectedAS(k=k_core, fixed_half=cal["spread"] / 2, **common), ("through", "touch")),
            ("Join + lean + kill", ProtectedAS(k=k_core, fixed_half=cal["spread"] / 2, alpha_bp=alpha, **defend, **common), ("through", "touch")),
        ]
        lot = LOT_USD / cal["price"]
        for name, q, rules in strategies:
            for rule in rules:
                res = run_backtest(bars, q, replace(base, lot=lot, fill_rule=rule))
                s = summarize(res)
                s["strategy"] = name
                rows.append({"symbol": sym, "tier": cal["tier"], "test_date": test, "fill_rule": rule,
                             "paused_share": q.paused_share, "k_tail_bp": cal["k_bp"], "k_core_bp": cal["k_core_bp"],
                             "spread_bp": cal["spread_bp"], "tick_bp": cal["tick_bp"], **s})
                m = res.minute
                idx = list(range(0, len(m), 30)) + [len(m) - 1]
                curves.setdefault(f"{name}|{rule}", []).append(
                    {"date": test, "t_s": [float(m["t_s"].iloc[i]) for i in idx], "pnl": [round(float(m["pnl"].iloc[i]), 3) for i in idx]})
    print(f"{sym:9s} done in {time.time() - t0:.0f}s", flush=True)
    return {"symbol": sym, "rows": rows, "alpha": alpha_rows, "curves": curves}


def main() -> None:
    by_sym = {s: p for s, p in files_by_symbol().items() if len(p) > CAL_DAYS}
    jobs = sorted(by_sym.items(), key=lambda kv: -sum(p.stat().st_size for p in kv[1]))   # big first
    with Pool(2) as pool:
        out = pool.map(run_coin, jobs, chunksize=1)
    df = pd.DataFrame([r for o in out for r in o["rows"]])
    al = pd.DataFrame([r for o in out for r in o["alpha"]])
    df.to_csv("results/walkforward.csv", index=False)
    al.to_csv("results/walkforward_alpha.csv", index=False)
    agg = aggregate(df)
    coins = []
    for o in out:
        tier = df.loc[df.symbol == o["symbol"], "tier"].iloc[0]
        coins.append({"symbol": o["symbol"], "tier": tier, "curves": o["curves"],
                      "alpha": al[al.symbol == o["symbol"]].round(5).to_dict("records")})
    coins.sort(key=lambda c: (TIER_ORDER[c["tier"]], c["symbol"]))
    Path("results/walkforward_runs.json").write_text(json.dumps({
        "meta": {"cal_days": CAL_DAYS, "lot_usd": LOT_USD, "q_max_lots": Q_MAX, "test_dates": sorted(df.test_date.unique().tolist()),
                 "strategies": STRAT_ORDER},
        "aggregate": agg.round(4).to_dict("records"), "coins": coins}, separators=(",", ":")))
    plot(agg, al)
    pd.set_option("display.width", 250)
    print(agg[agg.fill_rule == "through"].pivot(index="symbol", columns="strategy", values="pnl_total")[STRAT_ORDER].round(1).to_string())


def aggregate(df: pd.DataFrame) -> pd.DataFrame:
    """Per coin x strategy x fill rule, over all test days."""
    g = df.groupby(["symbol", "tier", "strategy", "fill_rule"])
    a = g.agg(pnl_total=("pnl", "sum"), pnl_days_positive=("pnl", lambda x: int((x > 0).sum())), days=("pnl", "size"),
              notional=("notional_usdt", "sum"), fills=("fills", "sum"), markout_60s_bp=("markout_60s_bp", "mean"),
              q_std=("q_std", "mean"), paused_share=("paused_share", "mean"), net_2bp=("net_2bp", "sum"),
              net_10bp=("net_10bp", "sum"), worst_day=("pnl", "min")).reset_index()
    a["bp_of_volume"] = a["pnl_total"] / a["notional"].replace(0, np.nan) * 1e4
    a["tier_o"] = a["tier"].map(TIER_ORDER)
    return a.sort_values(["tier_o", "symbol", "strategy"]).drop(columns="tier_o")


def plot(agg: pd.DataFrame, al: pd.DataFrame) -> None:
    fig, ax = plt.subplots(1, 2, figsize=(15, 6))
    a = agg[agg.fill_rule == "through"]
    syms = a.drop_duplicates("symbol").symbol.tolist()
    show = [("A-S (tail k)", "#94a3b8"), ("Tail k + lean + kill", "#34d399"), ("Join touch", "#f5a524"), ("Join + lean + kill", "#38bdf8")]
    y = np.arange(len(syms))
    w = 0.8 / len(show)
    for i, (sname, c) in enumerate(show):
        v = a[a.strategy == sname].set_index("symbol")["pnl_total"]
        ax[0].barh(y - 0.4 + (i + 0.5) * w, [v.get(x, np.nan) for x in syms], w, color=c, label=sname)
    ax[0].set_xscale("symlog", linthresh=50)
    ax[0].set_yticks(y, [x.replace("USDT", "") for x in syms])
    ax[0].invert_yaxis()
    ax[0].axvline(0, color="#333", lw=0.8)
    ax[0].set(title="P&L over 4 out-of-sample days, strict fills, no fees (USD, symlog)", xlabel="USD")
    ax[0].legend(fontsize=8, loc="lower left")
    s = al.groupby("symbol").agg(t=("t_imb_5s", "mean"), corr=("corr", "mean"), hit=("hit_rate", "mean"), tier=("tier", "first"))
    s = s.loc[[x for x in syms if x in s.index]]
    ax[1].bar(range(len(s)), s["corr"], color=["#111" if t == "large" else "#2563eb" if t == "mid" else "#16a34a" if t == "small" else "#dc2626" for t in s.tier])
    ax[1].set_xticks(range(len(s)), [x.replace("USDT", "") for x in s.index], rotation=45)
    ax[1].axhline(0, color="#999", lw=0.8)
    ax[1].set(title="Out-of-sample correlation: predicted vs actual next-10s move\n(flow model fitted on the 3 previous days)", ylabel="correlation")
    fig.tight_layout()
    fig.savefig("results/day9_walkforward.png", dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    main()
