# Week 1 review (Day 7): first real-data backtest

Data: Binance spot BTCUSDT, every aggregated trade on 9 and 10 Nov 2026 (908,615 and 937,360 trades).
Backtest: `mm/backtest.py` on 100 ms bars, requote every 500 ms, 50 ms latency, 0.001 BTC per fill, cap ±10 lots.
Rough parameters: σ from a 30-minute EWMA of past mid changes; k = 0.15 per USDT from the 9 Nov fill-curve fit (so 10 Nov is out of sample); A-S horizon resets every hour.
Full table: `results/backtest_summary.csv`. Figures: `results/day7_<date>_backtest.png`.

## Result

Every strategy lost money on both days, before fees.

| Strategy | P&L 9 Nov | P&L 10 Nov | bp of volume | Markout 60 s | Inventory std (lots) |
|---|---:|---:|---:|---:|---:|
| Fixed ±0.5 USDT | −575 | −529 | −1.6 | −1.6 bp | 7.2 |
| Fixed ±2 | −463 | −433 | −1.6 | −1.6 bp | 7.0 |
| Fixed ±6.5 | −208 | −192 | −1.5 | −1.5 bp | 6.4 |
| A-S γ=1e-5, k=0.15 | −226 | −213 | −1.5 | −1.5 bp | 5.5 |
| **A-S γ=1e-4, k=0.15** | **−193** | −211 | −1.6 | −1.6 bp | **2.8** |
| A-S γ=1e-5, k=1.5 (tight) | −621 | −572 | −1.25 | −1.2 bp | 5.6 |

(USDT per day, no fees, strict fills. Volume traded: $1.3M–5.0M per strategy per day.)

## What the numbers say

1. **Adverse selection is the whole story.** At the moment of the fill the edge is about zero; 10 seconds later the average fill is worth −1.2 to −1.7 bp, and it stays there. Every strategy, at every spread, loses about the same 1.5 bp per dollar traded. Wider quotes lose less in total only because they trade less.
2. **A-S does its own job: it controls inventory.** With γ = 1e-4 inventory std falls from about 7 lots to under 3, and the strategy spends most of its time near zero while fixed-spread quoters sit at the ±10 cap. It had the smallest loss on 9 Nov. But inventory control cannot fix toxic fills.
3. **The fill rule barely matters (<1.5% difference between "through" and "touch").** All these quotes sit at least 50 ticks behind the best bid/ask, so they are only reached by sweeps that walk through several price levels. Sweeps are exactly the informed, one-sided flow that keeps going.
4. **Fees make it decisive.** A 2 bp maker fee more than doubles every loss; at 10 bp the losses are 7–9× the gross figure. Market making here is only viable with near-zero fees or rebates, plus an edge against adverse selection.
5. **The 10 Nov 13:30 UTC event is visible in every P&L curve** as a step loss: σ jumped ~5× and the 30-minute σ estimate reacted too slowly to widen the quotes.

## What broke, and what each item means for week 2

| Problem | Why it matters | Plan |
|---|---|---|
| Mid is a proxy from trades | Right after a sweep the proxy sits on the sweep side, which biases the "edge at fill" downward | Use the recorder's real best bid/ask for the mid (D12–13) |
| Quotes far behind the book | Only sweeps fill us | Test quoting at or near the touch, which needs a queue model from book data |
| k measures how far trades reach, not how often a resting order fills | The calibrated spread (≈ 2/k ≈ 13 USDT) is huge vs a 0.01 USDT market | D8: calibrate A, k properly; also sweep k as a tuning knob, not only a fitted value |
| σ reacts slowly | Losses concentrate in volatility spikes | D8–9: faster σ (5-minute EWMA or regime switch); widen after large sweeps |
| BTCUSDT is the tightest market there is | Little spread left to earn | Run the same pipeline on a less liquid pair (D9 or after) |
| No signal about flow direction | Fills are one-sided before moves | After week 2: order-flow-imbalance skew |

## Is it a bug?

Checks that argue it is real, not a coding error: the P&L identity (total = spread capture + inventory P&L − fees) holds exactly in tests; the no-look-ahead test passes (changing future data never changes past fills); the result is stable across two days, six strategies and two fill rules; and it matches the earlier simulation study, where naive quoting lost money once informed traders were added. A useful extra check for D8: random entry times should give markouts near zero.

## Interview version (30 seconds)

"I replicated Avellaneda–Stoikov, then backtested it on 1.8 million real BTCUSDT trades with conservative fills and latency. The model did what it promises, cutting inventory risk by more than half, but every passive strategy lost about 1.5 bp per dollar traded to adverse selection, because quotes behind the best price only get filled by sweeps that keep going. So the edge in market making isn't the quoting formula; it's fees, queue position and predicting short-term flow. That's what I'm working on next."
