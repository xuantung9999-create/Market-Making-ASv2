"""Day 5: first look at one day of real trades.

Run from the repo root after downloading:
    python -m scripts.explore_day data/BTCUSDT_2026-11-10_trades.parquet

Writes results/day5_<SYMBOL>_<date>_overview.png with four panels:
  1. price over the day (1-minute mid)
  2. trades per minute (when is the market busy?)
  3. sigma in USDT per sqrt(second), rolling 1 hour: the sigma A-S uses, and how much it moves
  4. P(a quote delta USDT from mid gets traded through within 1 s), log scale:
     a preview of lambda(delta) = A e^{-k delta}. A straight line here means the
     exponential fill model is reasonable; its slope is about -k (Day 8 fits it properly).
"""
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from mm.data import load_trades, summarize, trades_to_bars

path = Path(sys.argv[1]) if len(sys.argv) > 1 else sys.exit(__doc__)
trades = load_trades(path)
info = summarize(trades)
for k, v in info.items():
    print(f"  {k:24s} {v}")

sec = trades_to_bars(trades, freq_ms=1000)
sec["time"] = pd.to_datetime(sec["ts_us"], unit="us", utc=True)
sec = sec.set_index("time")

# Panel 4: how far beyond the previous second's mid did aggressive trades reach?
prev_mid = sec["mid"].shift(1)
up = (sec["buy_max"] - prev_mid).to_numpy()      # would fill an ask at prev_mid + delta
dn = (prev_mid - sec["sell_min"]).to_numpy()     # would fill a bid at prev_mid - delta
reach = np.concatenate([up, dn])
reach = np.where(np.isnan(reach), -np.inf, reach)[1:]   # no trade on that side: no fill
tick = info["tick_size_guess"]
d_max = max(np.nanpercentile(reach[np.isfinite(reach)], 99.5), 10 * tick)
deltas = np.linspace(0, d_max, 40)
p_fill = np.array([(reach >= d).mean() for d in deltas])

fig, ax = plt.subplots(2, 2, figsize=(13, 8))
sec["mid"].resample("1min").last().plot(ax=ax[0, 0], color="#222", lw=1)
ax[0, 0].set(title="Mid (1-minute)", ylabel="USDT", xlabel="")
sec["n_trades"].resample("1min").sum().plot(ax=ax[0, 1], color="#2471a3", lw=0.8)
ax[0, 1].set(title="Trades per minute", xlabel="")
sigma_roll = sec["mid"].diff().rolling(3600, min_periods=600).std()
sigma_roll.plot(ax=ax[1, 0], color="#8e44ad", lw=1, label="rolling 1 h")
ax[1, 0].axhline(info["sigma_usdt_per_sqrt_s"], color="#999", ls="--",
                 label=f"whole day: {info['sigma_usdt_per_sqrt_s']:.2f}")
ax[1, 0].set(title="sigma, rolling 1 h (USDT per sqrt second)", xlabel="UTC")
ax[1, 0].legend()
ok = p_fill > 0
ax[1, 1].semilogy(deltas[ok], p_fill[ok], "o-", color="#c0392b", ms=3)
ax[1, 1].set(title="P(quote at mid ± delta is traded through within 1 s)",
             xlabel="delta (USDT from previous mid)", ylabel="probability per second (log)")

day = info["start_utc"].date()
fig.suptitle(f"{path.stem.split('_')[0]} {day}: {info['n_trades']:,} trades, "
             f"daily vol {info['daily_vol_pct']:.2f}%, tick {tick:g}")
fig.tight_layout()
out = Path("results") / f"day5_{path.stem.split('_')[0]}_{day}_overview.png"
out.parent.mkdir(exist_ok=True)
fig.savefig(out, dpi=130)
print(f"saved {out}")
