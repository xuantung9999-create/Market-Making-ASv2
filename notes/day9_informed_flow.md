# Day 9: calibrating further, and managing informed traders

Data: 12 Binance spot coins (BTC to micro caps), 7 days each, 4–10 Nov 2026.
Method: **walk-forward**. For each test day, everything (tick, spread, σ, k, the two-part fill curve, the flow model) is calibrated on the 3 previous days only, then the strategy trades the test day it has never seen. 12 coins × 4 test days = 48 out-of-sample coin-days. Strict fills, 50 ms latency, $100 per fill, $1,000 cap, no fees unless stated.
Code: `mm/flow.py` (flow features and alpha model), `mm/protect.py` (A-S with defences), `mm/calibrate.py` (`fit_two_part`), `scripts/run_walkforward.py`. Results: `results/walkforward.csv`, `results/walkforward_alpha.csv`, `results/day9_walkforward.png`.

## 1. Calibrating further: what changed

| Change | Result |
|---|---|
| Calibrate on 3 days instead of 1 | k varies less from window to window on 9 of 12 coins (BTC: 27% → 8%, SKL 25% → 6%); ANKR is worse, with too few sweeps to fit; DOGE and SOL unchanged |
| Two-part fill curve (steep core, flat tail) | R² rises from 0.85–0.90 to 0.98–0.99 on ARB, NEAR, DOGE, SOL (two lines always fit at least as well as one, so this alone proves little), **and quoting from the core k lost 2.4× more** (−9,638 vs −3,939 USD) |
| Faster σ (Day 8) | Did not help; replaced by a kill switch |

The core-k result is the most instructive one of the week. The core of the fill curve is steeper, so it implies tighter quotes and more fills, and in the backtest those extra fills are mostly toxic. **The A-S fill model measures how often you get filled, not whether the fill was a good one.** A better statistical fit to λ(δ) made the strategy worse, because the model has no term for adverse selection. Calibration has to be judged by out-of-sample P&L and markouts, not by R².

## 2. Is there information in the flow? Yes

Model: next-10-second mid move (bp) regressed on trade imbalance over 5 s and 60 s and momentum over 5 s and 60 s, fitted on 3 days, non-overlapping samples.

- In sample, 5-second imbalance is significant on every coin (t = 2.7 to 32).
- **Out of sample, on every coin and every test day, the prediction correlates with the real move (0.07 to 0.24) and gets the direction right 58–65% of the time.**
- Strongest on small and mid caps (INJ 0.24, NEAR 0.20, ARB 0.16, DOGE 0.16), weaker on BTC (0.10) and the thinnest coins (ANKR, SKL ~0.07).

R² is small (1–5%), which is normal: a few percent of predictability is a lot at 10-second horizons, and it is exactly what an informed trader leaves behind.

## 3. What the defences did (48 out-of-sample coin-days, no fees)

| Strategy | Total P&L | P&L per $ traded | Fills vs baseline |
|---|---:|---:|---:|
| A-S, Day 8 calibration (tail k) | −3,939 | −4.31 bp | 1.00 |
| A-S core k | −9,638 | −4.99 bp | 2.1× |
| core k + lean | −8,968 | −4.93 bp | |
| core k + kill switch | −4,211 | −4.61 bp | |
| core k + lean + kill | −3,990 | −4.57 bp | |
| **tail k + lean + kill** | **−1,569** | **−3.67 bp** | 0.48× |
| Join touch | −24,110 | −5.08 bp | |
| **Join + lean + kill** | −11,108 | **−2.71 bp** | |

- **The kill switch is the biggest lever.** It pauses quoting about 25% of the time (volatility bursts and 5 s after sweeps) and cuts losses by roughly half on every base strategy.
- **Leaning on the flow prediction adds 5–15%.** The signal is real, but at 10-second horizons it is small next to a half-spread.
- **Best combination: the wider Day-8 quotes + lean + kill switch.** Losses fall 60% (−3,939 → −1,569) and it improves on the baseline for 11 of 12 coins; NEAR turns positive (+39 USD, +19 bp per dollar traded).
- **Be honest about where the gain comes from.** It trades half as much, and per-dollar losses improve only 15% (−4.31 → −3.67 bp). Most of the gain is *not trading in the worst moments*, which is the point of a kill switch, but it means the defences reduce the damage rather than create an edge. For join-touch quoting the per-dollar improvement is larger (−5.08 → −2.71 bp).
- **Tick-constrained micro caps stay the only place with positive results**: ANKR join + defences +16 USD (+6 bp per dollar) with strict fills and +149 if first in the queue; SKL +3 strict, +74 first in queue. Small amounts, a few hundred fills per day: still "promising, not proven".
- **With a 2 bp maker fee everything is negative.** The best strategy goes from −1,569 to −2,424.

## 4. How to manage informed traders: the full toolkit

Theory first: a market maker's spread has three parts (Glosten–Milgrom; Huang–Stoll): order-processing cost, inventory risk (what A-S models), and **adverse selection**, the loss to traders who know more. A-S has no adverse-selection term, which is why it bleeds on real data. Managing informed flow means one of five things.

| Lever | What it means | Status in this project |
|---|---|---|
| **1. Measure it** | Markouts per fill (1 s, 10 s, 60 s), split by time of day, size, side, volatility; random-entry baseline to prove it is real | Done (Days 7–9): −1.5 to −10 bp at 60 s; random entries ~0 |
| **2. Avoid it** | Stop quoting when toxicity is high: vol bursts, right after sweeps, scheduled news (e.g. US data at 13:30 UTC), when correlated markets jump. Don't sit far behind the book, where only sweeps reach you | Kill switch done: −50% losses. Event calendar and cross-asset triggers: next |
| **3. Predict and lean** | Move quotes toward where the price is going: trade/order-book imbalance, micro-price, lead–lag (BTC leads alts; perpetual futures lead spot; other exchanges). In A-S terms, a drift term: r = s + α − qγσ²τ | Trade-imbalance lean done (+5–15%). Order-book imbalance and BTC/perp lead–lag: next |
| **4. Price it** | Add an adverse-selection term to the spread; widen asymmetrically on the side under pressure; widen after your own fills (fills cluster) | Partly implied by lean; explicit asymmetric widening: next |
| **5. Structure** | Quote smaller at the touch, cut inventory faster or hedge on the perp, cancel fast (latency), pay low or negative maker fees, choose flow that is less informed (tick-constrained coins, where queue priority protects you) | Fees modelled; latency fixed at 50 ms; queue modelling needs the recorder's book data |

## 5. Interview version

"Real fills lost 1.5–10 bp a minute later while random entries lost nothing, so I knew it was adverse selection. Trade imbalance predicts the next 10 seconds out of sample on all 12 coins I tested, with a 58–65% hit rate. Using it to lean quotes helped a little; switching quoting off during volatility bursts and after sweeps cut losses by more than half. Interestingly, a better-fitting fill model made things worse, because A-S counts fills but can't tell good fills from toxic ones. My conclusion is that the edge in crypto market making comes from avoiding informed flow and from structure (fees, queue priority, speed), not from the quoting formula."

## Next (D10 onward)

1. Cross-asset signals: BTC moves as a predictor for alts, and perpetual-futures flow as a predictor for spot.
2. Order-book imbalance and queue position from the live recorder.
3. Tune the kill switch thresholds walk-forward (they are fixed at vol ratio 3, sweep 8σ, 5 s cooldown, never tuned).
4. Asymmetric widening and an explicit adverse-selection spread term.
5. Paper trading on live data (D12).
