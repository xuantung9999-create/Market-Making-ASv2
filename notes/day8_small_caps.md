# Day 8: calibration across the market, from BTC to micro caps

Coins: 12 Binance spot USDT pairs, 9–10 Nov 2026. Tiers come from **measured** USD volume per day on Binance spot (large > $500M, mid $50–500M, small $5–50M, micro < $5M), not from market cap. Five of the 17 candidates (HOOK, DATA, HIGH, PERP, LOKA) were not in Binance's spot archive for these dates: delisted or renamed. That is itself a small-cap risk.

Method: `mm/calibrate.py` measures each coin on day 1; `scripts/run_universe.py` backtests on day 2 (out of sample) with $100 per fill and a $1,000 inventory cap. Files: `results/universe_calibration.csv`, `results/universe_backtest.csv`, `results/day8_fill_fits.png`, `results/day8_universe.png`.

## What the calibration shows (day 1)

| Coin | Tier | USD vol/day | Tick (bp) | Spread | σ (bp/√s) | k (per bp) | 1/k (bp) |
|---|---|---:|---:|---|---:|---:|---:|
| BTC | large | 1.17B | 0.001 | 1 tick = 0.001 bp | 0.61 | 1.20 | 0.8 |
| SOL | mid | 182M | 1.15 | 1 tick = 1.2 bp | 0.89 | 0.34 | 3.0 |
| NEAR | mid | 60M | 2.78 | 1 tick = 2.8 bp | 1.61 | 0.10 | 10.4 |
| DOGE | small | 35M | 1.44 | 1 tick = 1.4 bp | 0.88 | 0.22 | 4.5 |
| ARB | small | 31M | 5.64 | 1 tick = 5.6 bp | 1.85 | 0.18 | 5.6 |
| INJ | small | 15M | 1.23 | 1 tick = 1.2 bp | 1.61 | 0.28 | 3.5 |
| ONE | small | 7.6M | 6.52 | 1 tick = 6.5 bp | 3.21 | 0.05 | 19.0 |
| COTI | micro | 1.1M | 10.4 | 1 tick = 10.4 bp | 1.28 | 0.13 | 7.8 |
| ANKR | micro | 0.53M | 25.8 | 1 tick = 25.8 bp | 1.53 | 0.08 | 11.9 |
| CELR | micro | 0.35M | 4.56 | 3 ticks = 13.7 bp | 1.37 | 0.10 | 10.4 |
| SKL | micro | 0.35M | 27.4 | 1 tick = 27.4 bp | 1.21 | 0.04 | 27.2 |
| IOTX | micro | 0.09M | 3.42 | 4 ticks = 13.7 bp | 1.08 | 0.11 | 9.1 |

1. **Tick size relative to price is the biggest difference.** BTC's tick is 0.001 bp; ANKR's and SKL's are about 26 bp. Most liquid alts trade at a one-tick spread, so their spread *is* the tick. A coin like ANKR is **tick-constrained**: it cannot be quoted tighter than 26 bp, and the competition is about queue position, not price.
2. **The fill curve flattens as liquidity falls.** k drops from 1.2 per bp (BTC) to 0.04–0.1 (micro): fills decay over tens of bp instead of under one. A-S's 1/k half-spread goes from 0.8 bp to 10–27 bp, which is close to these coins' real spreads. Structurally, A-S fits small caps better than BTC, where its quotes sit about 600 ticks behind the market.
3. **The exponential is not always one exponential.** SOL, NEAR, DOGE and ONE show a steep core near the mid and a much flatter tail (big sweeps). A single k fitted on the tail underestimates how fast fills drop near the touch. D9: fit a core k for quoting and a tail k for risk.
4. **Volatility per √s is 2–5× BTC's**, and it can change regime overnight: ONE went from 3.2 to 6.9 bp/√s (daily vol 9% → 21%) with volume tripling. That is a pump, and every strategy lost on it.
5. **Activity is thin.** Micro caps trade 0.02–0.1 times per second, about one trade every 10–40 s. Mids built from trades go stale, and a day gives only a few hundred fills, too few for confident conclusions.

## What the backtest shows (day 2, out of sample)

- **Large and mid caps: almost everything loses**, as for BTC in week 1, about −1.5 to −7 bp per dollar traded with strict fills. The one exception, NEAR "Fixed 1/k" (+28 USD/day from 435 fills), turns into a loss with optimistic fills, which marks it as noise. Adverse selection grows in bp as liquidity falls (markouts −4 to −10 bp for NEAR, ONE, CELR), so wider spreads do not automatically pay.
- **Queue position barely matters for BTC but decides the result on tick-constrained coins.** Being first in the queue ("touch" fills) moves ANKR join-touch from +28 to +53 USD/day and SKL A-S from −10 to +19.
- **The only positive, statistically meaningful results are on tick-constrained micro caps**: ANKR join-touch +16 to +19 bp per dollar traded (60 s markout +3.8 bp, t = 2.2 with strict fills; +5.7 bp, t = 4.1 with optimistic fills), and SKL A-S with optimistic fills (+15 bp markout, t = 7). ANKR's result survives a 10 bp fee. But it is about $30–50 a day on a $1,000 limit, from 180–390 fills on one day. **Promising, not proven**: it needs more days and real queue data.
- **ARB** (small, 5.6 bp tick) breaks even to slightly positive with A-S and optimistic fills (+22 USD/day, t ≈ 2).
- **The faster σ (5-minute half-life) did not help** and was often worse: it widens quotes after a spike, when the damage is done, and adds noise the rest of the time.
- **Sanity check:** random entry times give markouts within ±0.2 bp at 60 s on every coin, so the −1.5 to −10 bp markouts of real fills are genuine adverse selection, not a measurement artefact.

## Advice: what to change for small and micro caps vs BTC

| Topic | BTC (large) | Small cap | Micro cap |
|---|---|---|---|
| Quote size | Base units (0.001 BTC) | **In USD**, and as a % of daily volume | Tiny: a $100 lot can be a visible share of an hour's volume |
| Inventory limit | Plenty of liquidity to exit | Set in USD **and** by time-to-liquidate | Limit by time-to-liquidate (hours, not seconds); assume you cannot exit fast |
| Hedging | Perpetual futures available | Sometimes a thin perp | Usually no hedge: carry inventory risk outright, so use a higher γ / larger skew |
| Pricing grid | Sub-bp tick: skew is continuous | Tick of 1–6 bp: skew moves in steps | Tick of 10–30 bp: **skew by withdrawing a side or by size**, not by price |
| What wins | Speed and fees; quoting formula matters little | Spread vs adverse selection; flow signals | **Queue priority** at a tick-constrained spread |
| Spread and k | Calibrate from 1 day | Calibrate over several days; single-exponential fit often fails (core vs tail) | Too few trades for a reliable k; use the tick/spread directly |
| Volatility | Smooth, intraday regimes | Jumps; pumps on news and listings | Regime changes and pumps; add a **kill switch** on volume or σ spikes |
| Adverse selection | Fast traders, cross-venue arbitrage | Price discovery often happens on perps or other venues first | Few large informed orders; one bad fill is a day's P&L |
| Fees | Maker fee wipes out the edge | Same; need VIP rates or rebates | A 10–25 bp spread can absorb fees, if fills are not toxic |
| Data | Trades are dense; trade-based mid is OK | Mid from trades sometimes stale | Need order-book data; a trade-based mid can be minutes old |
| Operational | Stable listing | Delistings happen | Delisting/renaming risk is real (5 of 17 candidates gone) |

Code changes already made for this: lot sized in USD, γ chosen from a target skew in bp (`gamma_from_skew`) so it scales with each coin's price and volatility, tick inferred per coin and used for quote rounding, spread estimated from adjacent trades, and a fallback k when there are too few sweeps.

## Next (D9)

1. Core vs tail k on the fill curve; quote from the core.
2. Several days per coin (calibrate on 3, test on the next 2) before trusting any micro-cap edge.
3. Queue model for tick-constrained coins using the live recorder's book data.
4. Volume/σ spike kill switch instead of a fast σ.
5. Parameter sweep (γ, quote width) per tier, with the same out-of-sample split.
