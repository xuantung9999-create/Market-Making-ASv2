# Days 9–10: GLFT, parameter sweep, cross-asset signals and the live order book

All backtests are walk-forward on 12 Binance spot coins (BTC to micro caps): each test day uses parameters calibrated on the 3 days before it; 4 test days per coin (7–10 Nov 2026) = 48 out-of-sample coin-days. Strict fills, $100 per fill, $1,000 cap, no fees unless stated. Every strategy below leans on the flow prediction.

Code: `mm/protect.py` (GLFT quotes), `mm/calibrate.py` (`gamma_for_glft_skew`), `mm/flow.py` (`leader_features`), `scripts/run_sweep.py`, `scripts/run_leadlag.py`, `scripts/book_study.py`.
Results: `results/sweep.csv`, `results/leadlag.csv`, `results/book_study.json`, figures `results/day9_sweep.png`, `results/day10_leadlag.png`, `results/day10_book.png`.

## 1. GLFT vs A-S

GLFT (Guéant, Lehalle & Fernandez-Tapia, 2013) is the infinite-horizon version of A-S: the quotes do not depend on the time of day, which suits a market that never closes. Unlike A-S, the order-flow rate A enters the inventory skew: when fills are rare, inventory is slow to work off, so GLFT skews harder. To compare like with like, γ is chosen for each model so that both move the reservation price by the same number of bp at full inventory.

Result: **they end up close.** GLFT is slightly better per dollar traded at low skew (best cell −3.06 bp vs −3.36 bp for A-S); A-S is slightly better in total at high skew (−660 vs −676 USD). The hourly reset in our A-S was not a big handicap.

## 2. Parameter sweep (32 settings × 48 coin-days)

Total P&L, USD (A-S; GLFT is similar):

| Skew at full inventory | Kill off | Loose | Medium | Tight |
|---|---:|---:|---:|---:|
| 0.5× | −3,628 | −2,356 | −1,657 | −900 |
| 1× | −3,659 | −2,343 | −1,569 | −721 |
| 2× | −3,735 | −2,335 | −1,472 | −679 |
| 4× | −3,773 | −2,237 | −1,419 | **−660** |

(Skew 1× = max(10 bp, 2 spreads). Kill switch: loose pauses ~10% of the time, medium ~25%, tight ~45%.)

- **The kill switch dominates everything else.** Going from off to tight cuts losses by 75–80%. A tight switch pauses quoting almost half the time: the strategy makes most of its improvement by staying out of the market when flow is toxic.
- **More skew cuts total losses but worsens P&L per dollar traded.** It trades less, but on worse terms. The per-dollar figures are all between −3 and −7 bp: no setting has a positive edge.

### Tuning only on the past

Choosing each day's setting from the earlier test days only (no hindsight), over test days 2–4:

| Choice of setting | P&L (USD) |
|---|---:|
| Default (A-S, 1×, medium) | −1,096 |
| Tuned per coin on past days | −458 |
| Tuned on all coins pooled | −452 |
| Best setting in hindsight (not achievable) | −271 |

Tuning works out of sample (−58%), and the pooled choice (A-S, 4× skew, tight kill switch) is as good as per-coin tuning while being far less likely to be overfit. The gap to the hindsight figure is the usual price of not knowing the future.

### Speed matters

| Requote interval / latency | P&L per $ traded |
|---|---:|
| 250 ms / 50 ms | −3.40 bp |
| 500 ms / 50 ms | −3.67 bp |
| 1,000 ms / 50 ms | −4.62 bp |
| 2,000 ms / 50 ms | −7.57 bp |
| 500 ms / 200 ms | −3.99 bp |
| 500 ms / 500 ms | −4.89 bp |

Stale quotes are what informed traders pick off: slower requoting and higher latency both mean more fills at worse prices. **Measured latency from your PC to Binance is ~285 ms** (section 4), between the 200 and 500 ms rows, so a live run from Vietnam on a home connection would do noticeably worse than the 50 ms backtests. Professional market makers co-locate servers next to the exchange for exactly this reason.

## 3. Cross-asset signals (lead–lag)

Out-of-sample correlation between predicted and actual next-10-second moves:

| Coin | Own flow | + BTC spot | + BTC perpetual | + both |
|---|---:|---:|---:|---:|
| BTC (spot) | 0.103 | – | **0.180** | – |
| ARB | 0.164 | 0.223 | 0.226 | 0.229 |
| DOGE | 0.159 | 0.197 | 0.216 | 0.219 |
| SOL | 0.141 | 0.163 | 0.179 | 0.186 |
| NEAR | 0.196 | 0.217 | 0.222 | 0.222 |
| INJ | 0.239 | 0.254 | 0.258 | 0.259 |
| micro caps | 0.07–0.13 | +0.00–0.03 | similar | similar |

- **The perpetual future leads spot.** For BTC itself, adding perp flow raises the correlation by 75%. Price discovery happens on the futures market first.
- **BTC leads the alts.** Every coin except ONE improves; liquid alts the most, micro caps least.
- **But better prediction barely changed P&L:** −1,569 → −1,519 USD in total (BTC alone: −359 → −290, NEAR turns slightly more positive). Leaning by a few bp on a 10-second prediction is small next to a half-spread, and our 500 ms requote is slow relative to how fast BTC moves propagate. To turn this signal into money you would quote near the touch, requote much faster, and pull quotes the moment the leader jumps.

## 4. What the live order book adds (50 minutes of recorded BTCUSDT)

The recorder ran for 50 minutes before stopping (probably the laptop sleeping), giving 363,000 best bid/ask updates and 28,450 trades.

- **Spread:** one tick (0.01 USDT) 99.95% of the time.
- **Latency:** trades arrive ~285 ms after their exchange timestamp (median; 95% under 320 ms). This includes any offset in your PC's clock.
- **The trade-based mid used in all backtests is unbiased but noisy:** average error 0.002 bp, but off by more than half a spread 20% of the time and by up to 0.5 bp in the worst 5% of bars. So "edge at the moment of the fill" was measured noisily; markouts at 10–60 s, the main adverse-selection measure, are unaffected.
- **Order-book imbalance predicts better than trades.** (Bid size − ask size) / total correlates 0.24 with the next 5-second move, against 0.13 for 5-second trade imbalance. By decile it is cleanly monotone: −0.69 bp after the most ask-heavy books, +0.83 bp after the most bid-heavy. Fifty minutes is a small sample; this needs days of recording before going into a strategy.

## What it adds up to

Every tool that helps works the same way: it gets the strategy out of the way of informed flow (kill switch, faster requotes, lower latency, leaning on better predictions). Together they cut losses by up to ~80%, but the edge per dollar traded stays negative before fees on liquid coins. A real market maker closes that gap with structure we cannot simulate from trade data: co-location, queue priority, and maker rebates. Tick-constrained micro caps (ANKR, SKL) remain the only place with positive results.

## Next

1. Keep the recorder running for several days (stop the laptop from sleeping) and add book imbalance to the flow model.
2. Requote on events (leader jump, book change) instead of a fixed timer.
3. D12: paper trading on live data, with the tuned setting (A-S or GLFT, 4× skew, tight kill switch, lean on own + BTC flow).
4. D13–14: robustness tables and the final write-up.
