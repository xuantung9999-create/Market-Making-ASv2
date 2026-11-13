# v2.1 research spec: book-state Markov layer and hedge study

**Status (13 Nov 2026): design only. Nothing in this file is implemented yet.**
It continues `docs/BUILD_GUIDE.md` (Tasks 0-11, all built) with Tasks 12-18.

> **For the model doing the work (Sonnet / Opus):** read sections 1-2, then only the task you were
> given. `docs/BUILD_GUIDE.md` sections 2, 3 and 5 still apply, word for word.

## 1. Why this exists

v2 answered its own question with a pre-registered test, and the answer was no.

| 60 days, 13 Sep - 11 Nov 2026, COTI / ANKR / SKL, always join the best price | Before fees | After 10 bp maker fee | t (daily P&L) | Days positive |
| --- | ---: | ---: | ---: | ---: |
| Queue 0.5x displayed size (optimistic) | -7.0 bp | -17.0 bp | -8.6 | 2% |
| Queue 1.0x (headline) | -8.2 bp | -18.2 bp | -8.4 | 2% |
| Queue 2.0x (stress) | -9.0 bp | -19.0 bp | -8.1 | 2% |
| Front of queue, 100 ms latency (v1's assumption) | -1.3 bp | -11.3 bp | -8.5 | 4% |

Basis points per dollar traded, pooled over 180 coin-days (`results/queue_baseline.csv`). The +16 bp
ANKR result from Day 8 was one day with no queue model; it does not survive.

**Gate A: fail.** After a 7-day warm-up the self-calibrating agent learned that every market state it
could see loses money, and stayed out on all 159 counted coin-days at the headline and stress queue
(`results/gate_a.json`). It refused a strategy that would have lost about 27,000 USD on paper.

**The one thing v2 could not test.** The Binance archive has trades but no order book, so v2 ran on a
book *inferred* from trades, with the same size on every level. Book imbalance was therefore always
zero, and the agent's edge table only ever saw the volatility bucket. Day 10 showed on live data that
book imbalance predicts the next 5 s about twice as well as trade flow. v2.1 asks one question:

> **H.** On the recorded book, are there states (imbalance, queue size, regime) in which a fill at or
> one tick behind the best price has positive net edge?

**Prior, stated before the data:** probably not after a 10 bp fee. Selection alone would have to
recover 17-19 bp per dollar. It is more plausible before fees and at 7.5 bp, so all three are reported.
If H fails, the project's conclusion stands as it is: no retail edge on these coins at this fee.

## 2. Rules

Everything in `docs/BUILD_GUIDE.md` sections 2 and 3 applies. The ones that bite here:

- No new dependencies. The hidden Markov model in Task 15 is written in numpy.
- Existing public functions and all 194 tests stay as they are and stay green.
- Past-only: anything used at time t comes from events with `ts_us <= t`. Each task has a test for it.
- Fixed constants stay fixed: `maker_fee_bps = 10.0` (also 7.5 and 0), `latency_ms = 300`,
  `lot_usd = 100`, `q_max = 10`, `queue_mult` 1.0 / 0.5 / 2.0, markout horizon 60 s.
- Pass rules below are fixed before the data exists. A fail is reported as a fail, with its numbers.
- No orders, no keys. Every script the user runs gets a `.bat` launcher that logs to `results\`.

New in v2.1:

- **`QueueSim` is never forked.** Changes go in as keyword arguments whose default reproduces today's
  results exactly; a test asserts identical fills and P&L on a fixed tape.
- **Recorded tape only.** Tasks 13-16 fit and test on `data/live` (real sizes). The inferred tape is
  not used, because the variables under study do not exist on it.

## 3. Task 12: recorder audit (Sonnet)

Known today: `results/recorder_multi_log.txt` shows one 91-minute session on 12 Nov (18:23-19:54,
12 symbols, best bid/ask and trades), stopped by hand. Whether it has run since is unverified.

`scripts/audit_recorder.py` + `run_audit_recorder.bat`, reading with `mm.recorder.load_live`.
Per symbol and UTC day it prints:

- hours covered, after dropping any hour with a gap over 120 s (the guide's rule)
- book updates, trades, and gaps over 5 s
- crossed or locked books, non-positive sizes, `update_id` going backwards
- share of trades priced outside the best bid/ask seen just before them
- median spread in ticks; median size at the best price, in multiples of the median trade size
  (`mm/tape.py` currently guesses 20)

Also: the recorder writes `data/live/heartbeat.json` every 10 s (per symbol: last message time,
messages in the last minute), and the dashboard gets a Recorder Health card that reads it.

**Pass:** COTIUSDT, ANKRUSDT, SKLUSDT and BTCUSDT each have at least 7 days with 20+ clean hours, zero
crossed books and under 2% out-of-book trades. Tasks 13-16 do not start before this passes.

## 4. Task 13: Markov microprice (Sonnet) - `mm/markov.py`

State `s` = (imbalance quintile 1-5, spread = 1 tick or 2+ ticks), sampled at every book update.
Count transitions between consecutive updates: `Q` when the mid does not move, `R` into a mid move of
`k` half-ticks, `T` to the state right after a move. Add the mirrored book (swap sides, flip signs)
before counting, so the estimate is symmetric.

    G1 = (I - Q)^-1 R K        B = (I - Q)^-1 T        G* = sum_{i=0..5} B^i G1

`G*(s)` is the expected mid change in bp given the state: a 10-entry table, refitted each day on the
previous 3 days. It becomes a seventh feature, `markov_bp`, in `mm/features.py`.

- Tests: `G*` is antisymmetric across imbalance buckets; a synthetic book with no imbalance effect
  gives zeros within noise; each row of `Q + R + T` sums to 1; future rows do not change past values.
- **Pass:** out of sample, `markov_bp` predicts the mid change at 1 s, 5 s and 30 s with higher R2 than
  the existing `micro_bp` on at least 2 of the 3 coins. Otherwise keep `micro_bp` and delete the module.

## 5. Task 14: queue chain (Opus) - `mm/queue_model.py`

Today `QueueSim` does not model other traders' cancels. On a one-tick spread that is most of what
moves a queue. Classify every change in size at the best price as `add` (size up), `trade` (size down
with a trade at that price within 50 ms), `cancel` (size down, no trade) or `move` (price changed).
Bucket our side's size `n` and the opposite side's `m` into 4 buckets each and estimate the four event
rates per `(n, m)`.

- `p_fill(x, n, m)`: probability an order with `x` ahead of it trades before the price moves away.
  Simulate the chain 10,000 times per cell, fixed seed, and store the table.
- Cancels ahead of us are drawn three ways, all reported: all in front, proportional, all behind.
- `QueueSim(..., cancel_model=None)`: `None` is today's behaviour; a model shrinks `queue_ahead` on
  cancel events.
- Tests: `p_fill` falls as `x` rises; front >= proportional >= back; `cancel_model=None` is identical
  to the current engine.
- **Pass:** group test-day shadow orders into deciles of predicted `p_fill`; realised fill frequency is
  within 5 percentage points of predicted in at least 8 of 10 deciles (proportional cancels).

## 6. Task 15: regime (Opus) - `mm/regime.py`

Two-state Gaussian hidden Markov model on one-minute features: realised volatility, absolute trade
imbalance, trade count, mean 10 s markout of shadow fills. Fit by EM on the previous 7 days; the state
with worse markouts is `toxic`. Online, only the forward filter is used, so `p_toxic` at minute t
depends on minutes up to t. The smoothed path is never used in a test.

**Pass:** on test days, shadow fills in minutes with `p_toxic > 0.7` have 60 s markouts at least 3 bp
worse than the rest, t above 3. Otherwise delete the module; the existing volatility bucket stays.

## 7. Task 16: edge table on book state, and Gate A' (Opus)

`EdgeTable` gets a `state_fn` argument. Default: today's 3 x 3 grid (imbalance x volatility). v2.1:
imbalance from the real book (3 buckets) x queue ahead when joining (3 buckets) x regime (2), which is
18 cells per action, with the same forgetting and shrinkage. `EdgePolicy` and the 12-entry menu are
unchanged.

Rerun `scripts/run_agent_walkforward.py` on recorded days only.

**Gate A':** the same five checks as Gate A with the same thresholds, on at least 21 counted days per
coin. Report at 10, 7.5 and 0 bp. A pass at 0 bp only is written up as "edge before fees, not tradable
at the base tier".

## 8. Hedging: Tasks 17-18

The agent holds no inventory when it declines to trade, so today there is nothing to hedge. This is a
risk study on the join-the-best-price fills, and it matters for P&L only if Gate A' passes.

**A. Baseline.** Inventory skew and `q_max`, plus a cap on the sum of absolute dollar positions.

**Task 17, pre-check (Sonnet)** - `scripts/hedge_precheck.py`. Per coin, from the queue-baseline
fills: (1) inventory half-life, the time for a position to halve; (2) R2 of the coin's returns on BTC
perpetual returns at that horizon. **If the half-life is under 5 minutes or R2 is under 0.15, stop:** a
BTC hedge cannot help that coin. Expected outcome for micro caps in calm markets: stop.

**Task 18, simulation (Opus, only if Task 17 says go)** - `mm/hedge.py`.

    D_t = sum_i beta_i * q_i * P_i        if |D_t| > H_enter: trade BTC perp until |D_t + h_t| = H_target

- `beta_i`: slope of 5-minute returns on BTC perp over the previous 3 days, shrunk halfway to 1,
  clamped to [0, 2].
- `H_enter` = 50% and `H_target` = 25% of the total position limit. Fixed, not swept. Hedging to the
  inside of the band, not to zero, avoids paying the taker fee on every small move.
- Costs: taker fee (config value, 5 bp assumed until checked on the account's fee page), half the
  perp spread, 1 bp slippage, and the recorded 8-hourly funding rate on the open hedge.
- P&L in three lines: spot market making, hedge trading, funding.
- **Pass, against A on identical fills over 21+ days:** daily P&L standard deviation down at least 20%,
  worst day better, mean net P&L down no more than 10%.

Out of scope: a same-coin perpetual hedge on every fill. It costs about 5 bp per fill against a
strategy that is already negative.

## 9. Order of work

| Task | What | Needs | Done when |
| --- | --- | --- | --- |
| 12 | Recorder audit, heartbeat, health card | the recorder running | pass rule in section 3 |
| 13 | Markov microprice | 12 | tests + pass rule, or module deleted |
| 14 | Queue chain, `cancel_model` | 12 | tests + calibration pass rule |
| 15 | Regime | 12 | pass rule, or module deleted |
| 16 | Edge table on book state, Gate A' | 13-15 | `results/gate_a_prime.json` with five booleans |
| 17 | Hedge pre-check | BTC perp trades (`run_futures_download.bat`) | go / stop per coin |
| 18 | Hedge simulation | 17 = go | A vs B table |

Dashboard: each task writes a run bundle through `mm/report.py`, as in `docs/DASHBOARD_GUIDE.md`.

Two things the author derives by hand before the model codes them, because they are what an
interviewer asks: the `Q`, `R`, `T` counts for one hour of ANKR (before Task 13), and why the hedge
band targets 25% instead of zero (before Task 18).
