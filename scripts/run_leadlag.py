"""Day 10: do other markets tell us where this coin is going next? (lead-lag)

Price discovery in crypto tends to happen first in BTC and in perpetual futures; altcoin and
spot quotes follow a moment later. A market maker who sees the leader move first can lean
away before the informed order arrives.

For every coin and test day (walk-forward, 3 calibration days -> 1 test day), the next-10s
move is predicted with four feature sets:
  own          the coin's own flow (Day 9 model)
  + BTC spot   adds BTCUSDT spot returns (1 s, 5 s) and trade imbalance (5 s)
  + BTC perp   adds the BTCUSDT perpetual future's
  + both
Then the Day-9 best strategy (tail k, kill switch, lean) is backtested with the own-flow
alpha and with the best cross-asset alpha.

Needs data/futures/BTCUSDT_<date>_trades.parquet (python -m mm.data download --market futures).
Run from the repo root (about 6 minutes):
    python -m scripts.run_leadlag
Writes results/leadlag.csv, results/leadlag_runs.json, results/day10_leadlag.png.
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
from mm.data import load_trades, trades_to_bars
from mm.flow import (FEATURES, fit_alpha, flow_features, forward_return_bp, leader_features,
                     out_of_sample_r2, predict_alpha)
from mm.metrics import summarize
from mm.protect import ProtectedAS

LOT_USD, Q_MAX, HORIZON, CAL_DAYS, BAR_MS = 100.0, 10, 3600.0, 3, 100
CACHE = Path("results/.leader_cache")
TIER_ORDER = {"large": 0, "mid": 1, "small": 2, "micro": 3}
SPOT = [f"S_{x}" for x in ("ret_1s", "ret_5s", "imb_5s")]
PERP = [f"P_{x}" for x in ("ret_1s", "ret_5s", "imb_5s")]


def leader_bars(kind: str, date: str) -> pd.DataFrame | None:
    path = Path("data/futures" if kind == "perp" else "data") / f"BTCUSDT_{date}_trades.parquet"
    if not path.exists():
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    c = CACHE / f"{kind}_{date}.parquet"
    if not c.exists():
        trades_to_bars(load_trades(path), BAR_MS)[["ts_us", "mid", "buy_vol", "sell_vol"]].to_parquet(c)
    return pd.read_parquet(c)


def run_coin(args) -> dict:
    sym, paths = args
    t0 = time.time()
    trades = {p.stem.split("_")[1]: load_trades(p) for p in paths}
    dates = sorted(trades)
    base = BTConfig()
    bars_d, feats, fwds = {}, {}, {}
    for d in dates:
        b = prepare_bars(trades[d], base)
        f = flow_features(b, BAR_MS)
        ts = b["ts_us"].to_numpy()
        for kind, prefix in (("spot", "S"), ("perp", "P")):
            lb = leader_bars(kind, d)
            if lb is not None and not (kind == "spot" and sym == "BTCUSDT"):
                f = pd.concat([f, leader_features(lb, ts, BAR_MS, prefix=prefix)], axis=1)
        bars_d[d], feats[d], fwds[d] = b, f, forward_return_bp(b, 10, BAR_MS)
    sets = {"own": FEATURES}
    have_spot = all(SPOT[0] in feats[d] for d in dates)
    have_perp = all(PERP[0] in feats[d] for d in dates)
    if have_spot:
        sets["+ BTC spot"] = FEATURES + SPOT
    if have_perp:
        sets["+ BTC perp"] = FEATURES + PERP
    if have_spot and have_perp:
        sets["+ both"] = FEATURES + SPOT + PERP
    pred_rows, bt_rows = [], []
    for j in range(CAL_DAYS, len(dates)):
        test, cal_days = dates[j], dates[j - CAL_DAYS:j]
        alphas = {}
        for name, cols in sets.items():
            m = fit_alpha([feats[d] for d in cal_days], [fwds[d] for d in cal_days], features=cols)
            a = predict_alpha(m, feats[test])
            alphas[name] = a
            oos = out_of_sample_r2(a, fwds[test])
            td = m.as_dict()["tstat"]
            pred_rows.append({"symbol": sym, "test_date": test, "features": name, "r2_in": m.r2, **oos,
                              "t_lead_ret_1s": td.get("P_ret_1s", td.get("S_ret_1s", np.nan))})
        cal = calibrate(pd.concat([trades[d] for d in cal_days], ignore_index=True), sym, test)
        k = cal["k"] if np.isfinite(cal["k"]) and cal["k"] > 0 else 2.0 / cal["spread"]
        g = gamma_from_skew(max(10.0, 2 * cal["spread_bp"]), cal["price"], cal["sigma"], Q_MAX, HORIZON)
        f = feats[test]
        cross = "+ both" if "+ both" in alphas else ("+ BTC perp" if "+ BTC perp" in alphas else "own")
        for label, key in (("lean on own flow", "own"), ("lean on own + BTC flow", cross)):
            q = ProtectedAS(gamma=g, k=k, horizon_s=HORIZON, q_max=Q_MAX, tick=cal["tick"], alpha_bp=alphas[key],
                            vol_ratio=f["vol_ratio"].to_numpy(), sweep_z=f["sweep_z"].to_numpy(), bar_ms=BAR_MS)
            s = summarize(run_backtest(bars_d[test], q, replace(base, lot=LOT_USD / cal["price"])))
            bt_rows.append({"symbol": sym, "tier": cal["tier"], "test_date": test, "strategy": label, "alpha": key,
                            "pnl": s["pnl"], "notional": s["notional_usdt"], "fills": s["fills"],
                            "markout_60s_bp": s["markout_60s_bp"], "net_2bp": s["net_2bp"]})
    print(f"{sym:9s} done in {time.time() - t0:.0f}s", flush=True)
    return {"pred": pred_rows, "bt": bt_rows}


def main() -> None:
    by_sym: dict[str, list[Path]] = {}
    for p in sorted(Path("data").glob("*_trades.parquet")):
        by_sym.setdefault(p.stem.split("_")[0], []).append(p)
    dates = sorted({p.stem.split("_")[1] for ps in by_sym.values() for p in ps})
    for d in dates:                                   # build the leader cache once, before forking
        leader_bars("spot", d), leader_bars("perp", d)
    jobs = sorted([(s, p) for s, p in by_sym.items() if len(p) > CAL_DAYS], key=lambda kv: -sum(x.stat().st_size for x in kv[1]))
    with Pool(2) as pool:
        out = pool.map(run_coin, jobs, chunksize=1)
    pred = pd.DataFrame([r for o in out for r in o["pred"]])
    bt = pd.DataFrame([r for o in out for r in o["bt"]])
    tiers = bt.drop_duplicates("symbol").set_index("symbol")["tier"]
    pred["tier"] = pred["symbol"].map(tiers)
    pred.to_csv("results/leadlag.csv", index=False)
    bt.to_csv("results/leadlag_backtest.csv", index=False)
    summ = pred.groupby(["symbol", "tier", "features"]).agg(corr=("corr", "mean"), hit=("hit_rate", "mean"),
                                                             r2_oos=("r2_oos", "mean"), t_lead=("t_lead_ret_1s", "mean")).reset_index()
    btsum = bt.groupby(["symbol", "tier", "strategy"]).agg(pnl=("pnl", "sum"), notional=("notional", "sum"),
                                                           net_2bp=("net_2bp", "sum"), markout_60s_bp=("markout_60s_bp", "mean")).reset_index()
    btsum["bp"] = btsum.pnl / btsum.notional * 1e4
    order = lambda df: df.assign(o=df.tier.map(TIER_ORDER)).sort_values(["o", "symbol"]).drop(columns="o")
    Path("results/leadlag_runs.json").write_text(json.dumps({
        "prediction": order(summ).round(4).to_dict("records"), "backtest": order(btsum).round(3).to_dict("records")},
        separators=(",", ":")))
    plot(order(summ), order(btsum))
    pd.set_option("display.width", 250)
    print(summ.pivot(index="symbol", columns="features", values="corr").round(3))
    print(btsum.pivot(index="symbol", columns="strategy", values="pnl").round(1))
    print(bt.groupby("strategy")[["pnl", "notional", "net_2bp"]].sum().round(0))


def plot(summ: pd.DataFrame, bt: pd.DataFrame) -> None:
    fig, ax = plt.subplots(1, 2, figsize=(15, 5))
    syms = summ.drop_duplicates("symbol").symbol.tolist()
    feats = [f for f in ("own", "+ BTC spot", "+ BTC perp", "+ both") if f in summ.features.unique()]
    cols = ["#94a3b8", "#38bdf8", "#f5a524", "#34d399"]
    w = 0.8 / len(feats)
    x = np.arange(len(syms))
    for i, (fname, c) in enumerate(zip(feats, cols)):
        v = summ[summ.features == fname].set_index("symbol")["corr"]
        ax[0].bar(x - 0.4 + (i + 0.5) * w, [v.get(s, np.nan) for s in syms], w, color=c, label=fname)
    ax[0].set_xticks(x, [s.replace("USDT", "") for s in syms], rotation=45)
    ax[0].set(title="Out-of-sample correlation with the next-10s move", ylabel="correlation")
    ax[0].legend(fontsize=8)
    for i, (sname, c) in enumerate((("lean on own flow", "#94a3b8"), ("lean on own + BTC flow", "#34d399"))):
        v = bt[bt.strategy == sname].set_index("symbol")["pnl"]
        ax[1].bar(x - 0.2 + i * 0.4, [v.get(s, np.nan) for s in syms], 0.4, color=c, label=sname)
    ax[1].set_yscale("symlog", linthresh=50)
    ax[1].axhline(0, color="#333", lw=0.8)
    ax[1].set_xticks(x, [s.replace("USDT", "") for s in syms], rotation=45)
    ax[1].set(title="Protected A-S, 4 out-of-sample days, no fees (USD, symlog)", ylabel="USD")
    ax[1].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig("results/day10_leadlag.png", dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    main()
