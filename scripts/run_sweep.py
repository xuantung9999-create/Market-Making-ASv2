"""Day 9 (plan): parameter sweep, A-S vs GLFT, tuned only on the past.

Same walk-forward set-up as scripts/run_walkforward.py: for each coin and test day, tick,
spread, sigma, k, A and the flow model come from the 3 previous days. Every configuration
leans on the flow prediction.

Grid (32 configurations per coin-day):
  model       A-S (horizon resets hourly) or GLFT (infinite horizon)
  skew        reservation shift at full inventory = 0.5, 1, 2 or 4 x max(10 bp, 2 spreads)
  kill switch off | loose (vol 4x, sweep 12, 3 s) | medium (3x, 8, 5 s) | tight (2x, 6, 10 s)
Extra: requote interval 250 ms to 2 s and latency 50 to 500 ms for the default configuration.

Tuning is causal: the configuration used on test day n is the one with the best total P&L
on test days 1..n-1 (per coin, and pooled over all coins). Day 1 uses the default.
Run from the repo root (about 20 minutes on 2 cores):
    python -m scripts.run_sweep
Writes results/sweep.csv, results/sweep_runs.json, results/day9_sweep.png.
"""
from __future__ import annotations

import itertools
import json
import time
from dataclasses import replace
from multiprocessing import Pool
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from mm.backtest import BTConfig, prepare_bars, run_backtest
from mm.calibrate import calibrate, gamma_for_glft_skew, gamma_from_skew
from mm.data import load_trades
from mm.flow import fit_alpha, flow_features, forward_return_bp, predict_alpha
from mm.metrics import summarize
from mm.protect import ProtectedAS

LOT_USD, Q_MAX, HORIZON, CAL_DAYS = 100.0, 10, 3600.0, 3
MODELS = ("as", "glft")
SKEW_MULT = (0.5, 1.0, 2.0, 4.0)
KILLS = {"off": None, "loose": (4.0, 12.0, 3.0), "medium": (3.0, 8.0, 5.0), "tight": (2.0, 6.0, 10.0)}
DEFAULT = ("as", 1.0, "medium")
REQUOTE_MS = (250, 500, 1000, 2000)
LATENCY_MS = (50, 200, 500)
TIER_ORDER = {"large": 0, "mid": 1, "small": 2, "micro": 3}


def run_coin(args) -> list[dict]:
    sym, paths = args
    t0 = time.time()
    trades = {p.stem.split("_")[1]: load_trades(p) for p in paths}
    dates = sorted(trades)
    base = BTConfig()
    bars_d, feats, fwds = {}, {}, {}
    for d in dates:
        b = prepare_bars(trades[d], base)
        bars_d[d], feats[d], fwds[d] = b, flow_features(b, base.bar_ms), forward_return_bp(b, 10, base.bar_ms)
    rows = []
    for j in range(CAL_DAYS, len(dates)):
        test, cal_days = dates[j], dates[j - CAL_DAYS:j]
        cal = calibrate(pd.concat([trades[d] for d in cal_days], ignore_index=True), sym, test)
        alpha = predict_alpha(fit_alpha([feats[d] for d in cal_days], [fwds[d] for d in cal_days]), feats[test])
        k = cal["k"] if np.isfinite(cal["k"]) and cal["k"] > 0 else 2.0 / cal["spread"]
        A = cal["A"] if np.isfinite(cal["A"]) and cal["A"] > 0 else 1.0
        base_skew = max(10.0, 2 * cal["spread_bp"])
        f, bars = feats[test], bars_d[test]
        cfg0 = replace(base, lot=LOT_USD / cal["price"])

        def make(model, mult, kill):
            skew = base_skew * mult
            if model == "glft":
                g = gamma_for_glft_skew(skew, cal["price"], cal["sigma"], Q_MAX, k, A)
            else:
                g = gamma_from_skew(skew, cal["price"], cal["sigma"], Q_MAX, HORIZON)
            kw = dict(gamma=g, k=k, A=A, model=model, horizon_s=HORIZON, q_max=Q_MAX, tick=cal["tick"],
                      alpha_bp=alpha, bar_ms=base.bar_ms)
            if KILLS[kill]:
                v, sw, cd = KILLS[kill]
                kw.update(vol_ratio=f["vol_ratio"].to_numpy(), sweep_z=f["sweep_z"].to_numpy(),
                          vol_cap=v, sweep_cap=sw, cooldown_s=cd)
            return ProtectedAS(**kw)

        def record(q, cfg, **tags):
            s = summarize(run_backtest(bars, q, cfg))
            rows.append({"symbol": sym, "tier": cal["tier"], "test_date": test, **tags,
                         "pnl": s["pnl"], "notional": s["notional_usdt"], "fills": s["fills"],
                         "sharpe_ann": s["sharpe_ann"], "markout_60s_bp": s["markout_60s_bp"], "q_std": s["q_std"],
                         "max_drawdown": s["max_drawdown"], "paused_share": q.paused_share})

        for model, mult, kill in itertools.product(MODELS, SKEW_MULT, KILLS):
            record(make(model, mult, kill), cfg0, sweep="grid", model=model, skew_mult=mult, kill=kill,
                   requote_ms=base.requote_ms, latency_ms=base.latency_ms)
        for rq in REQUOTE_MS:
            if rq != base.requote_ms:
                record(make(*DEFAULT), replace(cfg0, requote_ms=rq), sweep="requote", model=DEFAULT[0],
                       skew_mult=DEFAULT[1], kill=DEFAULT[2], requote_ms=rq, latency_ms=base.latency_ms)
        for lat in LATENCY_MS:
            if lat != base.latency_ms:
                record(make(*DEFAULT), replace(cfg0, latency_ms=lat), sweep="latency", model=DEFAULT[0],
                       skew_mult=DEFAULT[1], kill=DEFAULT[2], requote_ms=base.requote_ms, latency_ms=lat)
    print(f"{sym:9s} done in {time.time() - t0:.0f}s", flush=True)
    return rows


def causal_tuning(grid: pd.DataFrame) -> pd.DataFrame:
    """P&L on each test day of: the default config, the per-coin config chosen on earlier days,
    the pooled config chosen on earlier days (all coins), and the hindsight-best config."""
    grid = grid.assign(cfg=grid.model + "|" + grid.skew_mult.astype(str) + "|" + grid.kill)
    dflt = "|".join(map(str, DEFAULT))
    dates = sorted(grid.test_date.unique())
    out = []
    pooled_hist = grid.groupby(["test_date", "cfg"]).pnl.sum().unstack()
    for sym, g in grid.groupby("symbol"):
        tab = g.pivot_table(index="test_date", columns="cfg", values="pnl")
        hindsight = tab.sum().idxmax()
        for n, d in enumerate(dates):
            past = dates[:n]
            coin_cfg = tab.loc[past].sum().idxmax() if past else dflt
            pool_cfg = pooled_hist.loc[past].sum().idxmax() if past else dflt
            out.append({"symbol": sym, "tier": g.tier.iloc[0], "test_date": d,
                        "default": tab.loc[d, dflt], "tuned_per_coin": tab.loc[d, coin_cfg], "cfg_per_coin": coin_cfg,
                        "tuned_pooled": tab.loc[d, pool_cfg], "cfg_pooled": pool_cfg,
                        "hindsight_best": tab.loc[d, hindsight], "cfg_hindsight": hindsight})
    return pd.DataFrame(out)


def main() -> None:
    by_sym: dict[str, list[Path]] = {}
    for p in sorted(Path("data").glob("*_trades.parquet")):
        by_sym.setdefault(p.stem.split("_")[0], []).append(p)
    jobs = sorted([(s, p) for s, p in by_sym.items() if len(p) > CAL_DAYS], key=lambda kv: -sum(x.stat().st_size for x in kv[1]))
    with Pool(2) as pool:
        rows = [r for part in pool.map(run_coin, jobs, chunksize=1) for r in part]
    df = pd.DataFrame(rows)
    df.to_csv("results/sweep.csv", index=False)
    grid = df[df.sweep == "grid"]
    tune = causal_tuning(grid)
    heat = (grid.groupby(["model", "skew_mult", "kill"])
            .agg(pnl=("pnl", "sum"), notional=("notional", "sum"), sharpe=("sharpe_ann", "mean"),
                 paused=("paused_share", "mean"), q_std=("q_std", "mean")).reset_index())
    heat["bp"] = heat.pnl / heat.notional * 1e4
    sens = (df[df.sweep.isin(["requote", "latency"]) | ((df.sweep == "grid") & (df.model == DEFAULT[0]) &
            (df.skew_mult == DEFAULT[1]) & (df.kill == DEFAULT[2]))]
            .groupby(["requote_ms", "latency_ms"]).agg(pnl=("pnl", "sum"), notional=("notional", "sum"), fills=("fills", "sum")).reset_index())
    sens["bp"] = sens.pnl / sens.notional * 1e4
    per_coin = (grid.groupby(["symbol", "tier", "model", "skew_mult", "kill"]).agg(pnl=("pnl", "sum"), notional=("notional", "sum")).reset_index())
    per_coin["bp"] = per_coin.pnl / per_coin.notional * 1e4
    tsum = tune[tune.test_date > tune.test_date.min()][["default", "tuned_per_coin", "tuned_pooled", "hindsight_best"]].sum()
    Path("results/sweep_runs.json").write_text(json.dumps({
        "meta": {"models": MODELS, "skew_mult": SKEW_MULT, "kills": {k: v for k, v in KILLS.items()}, "default": DEFAULT,
                 "requote_ms": REQUOTE_MS, "latency_ms": LATENCY_MS},
        "heat": heat.round(4).to_dict("records"), "per_coin": per_coin.round(3).to_dict("records"),
        "tuning": tune.round(3).to_dict("records"), "tuning_totals_days_2_4": tsum.round(2).to_dict(),
        "sensitivity": sens.round(4).to_dict("records")}, separators=(",", ":")))
    plot(heat, sens)
    pd.set_option("display.width", 250)
    print(heat.pivot_table(index=["model", "skew_mult"], columns="kill", values="pnl").round(0))
    print(heat.pivot_table(index=["model", "skew_mult"], columns="kill", values="bp").round(2))
    print("tuning totals (test days 2-4):", tsum.round(1).to_dict())
    print(sens.round(2))


def plot(heat: pd.DataFrame, sens: pd.DataFrame) -> None:
    kills = list(KILLS)
    fig, ax = plt.subplots(1, 3, figsize=(17, 5), gridspec_kw={"width_ratios": [1, 1, 0.9]})
    for a, model in zip(ax[:2], MODELS):
        h = heat[heat.model == model].pivot(index="skew_mult", columns="kill", values="pnl")[kills]
        im = a.imshow(h.values, cmap="RdYlGn", vmin=-heat.pnl.abs().max(), vmax=heat.pnl.abs().max(), aspect="auto")
        for (i, j), v in np.ndenumerate(h.values):
            a.text(j, i, f"{v:,.0f}", ha="center", va="center", fontsize=9)
        a.set_xticks(range(len(kills)), kills)
        a.set_yticks(range(len(h.index)), [f"{m:g}x" for m in h.index])
        a.set(title=f"{'A-S' if model == 'as' else 'GLFT'}: total P&L, 48 coin-days (USD)", xlabel="kill switch", ylabel="inventory skew")
    s = sens.sort_values(["latency_ms", "requote_ms"])
    for lat, g in s.groupby("latency_ms"):
        ax[2].plot(g.requote_ms, g.bp, "o-", label=f"latency {lat} ms")
    ax[2].set_xscale("log")
    ax[2].set(title="Default config: P&L per $ vs requote interval", xlabel="requote interval (ms)", ylabel="bp of volume")
    ax[2].legend(fontsize=8)
    fig.tight_layout()
    fig.savefig("results/day9_sweep.png", dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    main()
