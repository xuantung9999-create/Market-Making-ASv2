"""Day 10: what the live order book adds (data from mm.recorder).

Questions:
  1. How wrong is the trade-based mid used in every backtest so far?
  2. Does the order book (best bid/ask sizes) predict the next move better than trades do?
  3. What latency does this machine see?

Run from the repo root after the recorder has collected some data:
    python -m scripts.book_study
Writes results/book_study.json and results/day10_book.png.
"""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from mm.data import trades_to_bars
from mm.recorder import load_live

ROOT = Path("data/live/BTCUSDT")
BAR_MS = 100
HORIZONS_S = (1, 5, 10, 30)


def grid_from_book(book: pd.DataFrame, bar_ms: int = BAR_MS) -> pd.DataFrame:
    """Last best bid/ask in each bar of receive time."""
    step = bar_ms * 1000
    b = book.assign(bar=(book["recv_us"] // step) * step).groupby("bar").last()
    idx = pd.RangeIndex(int(b.index.min()), int(b.index.max()) + step, step)
    g = b.reindex(idx).ffill()
    g["mid"] = (g["bid"] + g["ask"]) / 2
    g["spread"] = g["ask"] - g["bid"]
    tot = g["bid_qty"] + g["ask_qty"]
    g["book_imb"] = (g["bid_qty"] - g["ask_qty"]) / tot
    g["micro"] = (g["ask"] * g["bid_qty"] + g["bid"] * g["ask_qty"]) / tot      # size-weighted "fair" price
    return g


def main() -> None:
    book, trades = load_live(ROOT / "book"), load_live(ROOT / "trades")
    lat_ms = (trades["recv_us"] - trades["ts_us"]) / 1000
    g = grid_from_book(book)
    minutes = len(g) * BAR_MS / 60_000

    # 1. trade-based mid proxy (exchange time shifted onto this machine's receive clock)
    shift = int(np.median(trades["recv_us"] - trades["ts_us"]))
    tb = trades_to_bars(trades.assign(ts_us=trades["ts_us"] + shift)[["ts_us", "price", "qty", "side"]], BAR_MS).set_index("ts_us")
    proxy = tb["mid"].reindex(g.index).ffill()
    err_bp = ((proxy - g["mid"]) / g["mid"] * 1e4).dropna()
    err_usdt = (proxy - g["mid"]).dropna().abs()

    # 2. predictive power: book imbalance and microprice vs trade imbalance
    tf = tb[["buy_vol", "sell_vol"]].reindex(g.index).fillna(0.0)
    n5 = int(5000 / BAR_MS)
    bsum, ssum = tf["buy_vol"].rolling(n5, min_periods=1).sum(), tf["sell_vol"].rolling(n5, min_periods=1).sum()
    g["trade_imb_5s"] = ((bsum - ssum) / (bsum + ssum)).where(bsum + ssum > 0, 0.0)
    g["micro_dev_bp"] = (g["micro"] - g["mid"]) / g["mid"] * 1e4
    pred = {}
    step = int(1000 / BAR_MS)
    for h in HORIZONS_S:
        k = int(h * 1000 / BAR_MS)
        fwd = (g["mid"].shift(-k) - g["mid"]) / g["mid"] * 1e4
        samp = g.iloc[::step].assign(fwd=fwd.iloc[::step]).dropna(subset=["fwd", "book_imb", "trade_imb_5s"])
        pred[h] = {c: float(np.corrcoef(samp[c], samp["fwd"])[0, 1]) for c in ("book_imb", "trade_imb_5s", "micro_dev_bp")}
        pred[h]["n"] = int(len(samp))
    # imbalance deciles -> mean next-5s move (the classic microprice picture)
    k5 = int(5000 / BAR_MS)
    fwd5 = (g["mid"].shift(-k5) - g["mid"]) / g["mid"] * 1e4
    samp = g.iloc[::step].assign(fwd=fwd5.iloc[::step]).dropna(subset=["fwd", "book_imb"])
    samp["decile"] = pd.qcut(samp["book_imb"], 10, labels=False, duplicates="drop")
    dec = samp.groupby("decile").agg(imb=("book_imb", "mean"), fwd_bp=("fwd", "mean"), n=("fwd", "size")).reset_index()

    out = {
        "minutes": round(minutes, 1), "book_updates": int(len(book)), "trades": int(len(trades)),
        "latency_ms": {k: round(float(v), 1) for k, v in lat_ms.describe(percentiles=[0.5, 0.95, 0.99]).items() if k != "count"},
        "spread_share": {f"{s:.2f}": round(float(v), 5) for s, v in (g["spread"].round(2).value_counts(normalize=True).head(6)).items()},
        "mid_proxy_error": {
            "mean_bp": round(float(err_bp.mean()), 4), "mean_abs_bp": round(float(err_bp.abs().mean()), 4),
            "p95_abs_bp": round(float(err_bp.abs().quantile(0.95)), 4), "p99_abs_bp": round(float(err_bp.abs().quantile(0.99)), 4),
            "share_beyond_half_spread": round(float((err_usdt > 0.005 + 1e-9).mean()), 4),
            "share_beyond_1usdt": round(float((err_usdt > 1.0).mean()), 4)},
        "predictive_corr": {str(h): {k: round(v, 4) if isinstance(v, float) else v for k, v in d.items()} for h, d in pred.items()},
        "imbalance_deciles": dec.round(4).to_dict("records"),
    }
    Path("results/book_study.json").write_text(json.dumps(out, indent=1))
    print(json.dumps(out, indent=1))

    fig, ax = plt.subplots(1, 3, figsize=(16, 4.5))
    ax[0].hist(err_bp.clip(-1, 1), bins=80, color="#38bdf8")
    ax[0].set(title=f"Trade-based mid minus real mid ({minutes:.0f} min BTCUSDT)", xlabel="bp (clipped at ±1)", ylabel="100 ms bars")
    hs = list(pred)
    for c, col in (("book_imb", "#34d399"), ("micro_dev_bp", "#a78bfa"), ("trade_imb_5s", "#f5a524")):
        ax[1].plot(hs, [pred[h][c] for h in hs], "o-", color=col, label=c)
    ax[1].axhline(0, color="#999", lw=0.8)
    ax[1].set(title="Correlation with the next h-second move", xlabel="h (seconds)", ylabel="correlation")
    ax[1].legend(fontsize=8)
    ax[2].bar(dec["decile"], dec["fwd_bp"], color=["#f87171" if v < 0 else "#34d399" for v in dec["fwd_bp"]])
    ax[2].set(title="Next-5s move by book-imbalance decile", xlabel="decile (0 = ask side heavy, 9 = bid side heavy)", ylabel="mean move (bp)")
    fig.tight_layout()
    fig.savefig("results/day10_book.png", dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    main()
