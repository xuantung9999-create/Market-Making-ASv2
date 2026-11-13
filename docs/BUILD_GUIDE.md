# Market Maker v2 + Self-Calibrating Agent: Build Guide

> **For the model doing the work (Opus / Sonnet):** build this one task at a time, in order.
> Read sections 1-4 and then only the task you were given. Steps use `- [ ]` checkboxes: tick them as you go.
> You do not need to re-derive the design. Every decision is already made here. If something is not
> decided here, section 3 says when to stop and ask.

**Goal:** turn the existing Avellaneda-Stoikov research repo into a queue-aware, edge-aware quoter for
tick-constrained coins, with an online agent that recalibrates it, proven first on historical trades and
then in paper trading on a live feed. No real orders at any point in this guide.

**Architecture:** one event-driven engine (`QueueSim`) consumes a book tape and a trade tape and is used
unchanged by the backtest, the walk-forward test and the paper trader. Policies decide per side between
JOIN (rest at the best price), BACK (one tick behind) and OUT. An `EdgeTable` learns the average net
edge of a fill per market state from shadow orders; a `CalibrationAgent` updates the table online and
switches between a fixed menu of policy settings.

**Tech stack:** Python 3.11, numpy, pandas, pyarrow, scipy, matplotlib, pytest, websockets
(exactly what `requirements.txt` already lists).

**Design doc (human-readable background):** "Market Making Project - Review & Path to Production",
https://claude.ai/artifact/7sPg3pmLLpH4V9GvDCVSRa. This guide is self-contained; you do not need to open it.

---

## 1. Where the project stands (read once)

Repo root: `Desktop\voranoi\Market-Making-AS\Market-Making-AS`. Existing modules you will reuse:

| File | What it gives you |
| --- | --- |
| `mm/data.py` | `download_day(symbol, day, market, out_dir)`, `load_trades(path)` -> DataFrame `ts_us, price, qty, side` (side +1 = buyer aggressor, -1 = seller aggressor), `trades_to_bars` |
| `mm/calibrate.py` | `calibrate(trades, symbol, date)` -> dict with `tick`, `tick_bp`, `spread_ticks`, `usd_volume_day`, `sigma_bp`, ...; `infer_tick(prices)` |
| `mm/recorder.py` | live `bookTicker` + `aggTrade` recorder, one symbol; `load_live(folder)`; book columns `recv_us, update_id, bid, bid_qty, ask, ask_qty` |
| `mm/backtest.py` | v1 bar engine (`run_backtest`, `BTConfig`, `BTResult`). Do not modify. v2 is a new engine beside it |
| `mm/metrics.py` | `summarize(res)`. v2 results must work with it unchanged |
| `mm/flow.py`, `mm/protect.py`, `mm/strategy.py` | v1 signals and quoters. Do not modify |

What v1 found, and why v2 exists:

- Liquid coins lose 3-7 bp per dollar traded to adverse selection. v2 does not try to fix them.
- The only positive result is joining the best price on tick-constrained micro caps (tick about 26 bp of
  price, spread = 1 tick): ANKRUSDT, SKLUSDT, maybe ARBUSDT.
- v1 fills an order when a trade prints through (or touches) its price. On a tick-constrained coin the
  real question is queue position, which v1 does not model. That is the first thing v2 fixes.

Data available: Binance public archive has months of spot trades (`aggTrades`) per coin, free. It has
no spot order book. So historical tests use a book tape **inferred from trades**, and the live recorder
collects the real best bid/ask and sizes to check that inference (Task 9).

---

## 2. Global constraints (apply to every task)

- **No real orders, no API keys, no account endpoints.** Only public market-data endpoints
  (`data.binance.vision`, `wss://stream.binance.com:9443`). If a task seems to need a key, stop.
- **No new dependencies.** Only what `requirements.txt` lists.
- **Do not change existing public functions or the existing tests.** All existing tests must still pass
  after every task: `.venv\Scripts\python.exe -m pytest -q` (Windows) or `python -m pytest -q`.
- **Past-only rule.** Anything computed at time t may use only events with `ts_us <= t`. A fill's
  markout at horizon h may be used by a learner only at or after `fill time + h`. Each task that
  computes features or learns has a test for this.
- **Units.** Prices in USDT. Time in microseconds on tapes (`ts_us`), seconds in configs. Cross-coin
  numbers in basis points (bp) of price. Inventory `q` in whole lots; one lot = `lot_usd / price` base units.
- **Fixed scenario constants** (do not tune them to improve results):
  `maker_fee_bps = 10.0` (also report 7.5), `latency_ms = 300`, `lot_usd = 100.0`, `q_max = 10`,
  `queue_mult` headline 1.0 with stress 2.0 and optimistic 0.5, markout horizon 60 s.
- **Data is never committed.** `data/` is git-ignored; keep it that way.
- **Style.** Follow the existing files: module docstring that explains the idea in plain words, type
  hints, dataclasses for configs, no classes where a function will do.
- **Windows.** The user runs things by double-clicking `.bat` files in the repo root. Any script the
  user must run gets a `.bat` launcher modelled on `run_day5.bat`, logging to `results\<name>_log.txt`.

Deferred by the user until paper-trading results exist (do NOT build, do NOT ask about): legal route,
live risk budget, cloud server, exchange order placement.

---

## 3. How to work (rules for the executing model)

1. One task per session. Start by running the test suite; if it is not green, stop and report.
2. Test first. Write the task's tests, run them, see them fail, then implement.
3. Use the exact file names, function names, signatures and constants given. Other tasks depend on them.
4. Commit after each task: `git add -A && git commit -m "v2 task N: <title>"`.
5. **Stop and ask the user** (do not improvise) if: a signature here cannot work as written; an existing
   test would have to change; a result looks too good (any coin-day net edge above +30 bp per dollar
   traded, or zero losing days) since that usually means look-ahead; or you would need to change a
   constant in section 2.
6. End every task with this report: files changed, tests added and passing count, any deviation from
   this guide and why, and the numbers the task asked you to print.

Which model for which task: Sonnet is enough for Tasks 0, 1, 2, 4, 8, 11. Use Opus for Tasks 3, 5, 6,
7, 9, 10 (engine semantics, learning logic, evaluation). Gate verdicts (Tasks 7, 8, 10) should be reviewed
by the user with the strongest model available before anything further is built on them.

---

## 4. File map

| File | Status | Responsibility |
| --- | --- | --- |
| `mm/recorder.py` | modify | record several symbols at once |
| `mm/screen.py` | new | decide which coins are tick-constrained |
| `mm/tape.py` | new | book tapes (inferred from trades, or from the recorder) and the merged event stream |
| `mm/features.py` | new | incremental, past-only market features |
| `mm/queue_sim.py` | new | the v2 engine: orders, queue position, fills, P&L |
| `mm/edge.py` | new | net edge per fill, `EdgeTable`, `EdgePolicy` |
| `mm/agent.py` | new | `CalibrationAgent`: online table updates + menu switching + loss stop |
| `mm/paper.py` | new | live feed -> the same engine and agent, logged to disk |
| `scripts/download_history.py`, `screen_universe.py`, `run_queue_baseline.py`, `run_agent_walkforward.py`, `validate_tape.py`, `daily_supervisor.py` | new | runnable entry points |
| `config/candidates.txt` | new | one symbol per line |
| `tests/test_tape.py`, `test_features.py`, `test_queue_sim.py`, `test_edge.py`, `test_agent.py`, `test_screen.py`, `test_recorder_multi.py`, `test_paper.py` | new | tests |

---

## 5. Engine semantics (the spec every engine task implements)

**Tapes.** Book tape columns `ts_us, bid, ask, bid_qty, ask_qty`, sorted by `ts_us`. Trade tape =
`mm.data` format. Events are processed in time order; on equal timestamps book events come before
trades, and timer events come last.

**Orders.** At most one resting order per side. An order has `price, qty, queue_ahead, live_from_us`.
`qty = lot_usd / mid` at decision time.

**Decisions.** The policy is asked on a timer grid every `decision_ms`. A timer is skipped if no book or
trade event arrived since the previous decision and no order activation is pending. The policy returns
`(bid_action, ask_action)`.

- `JOIN`: target price = best price on that side at decision time.
- `BACK`: target price = best price one tick further from the mid.
- `OUT`: no order on that side.
- If the target price equals the resting order's price, the order is kept and keeps its queue position.
- Otherwise the resting order is cancelled and a new one is placed. Both take effect at
  `decision time + latency_ms`. Until then the old order can still fill.

**Activation** (at `live_from_us`, using the book at that moment):

- new bid price >= current ask (or new ask <= current bid): rejected (post-only), no order.
- price equals the current best on its side: `queue_ahead = queue_mult * displayed size at best`.
- price improves the best: `queue_ahead = 0`.
- price is behind the best: `queue_ahead = back_queue_mult * displayed size at best`.

**Fills** (bid shown; ask is the mirror image). For each seller-aggressor trade (`side == -1`):

- trade price < bid price: fill the whole order at our price.
- trade price == bid price: `queue_ahead -= trade qty`; if `queue_ahead <= 0`, fill the whole order.
- trade price > bid price: nothing.

No partial fills. Cancels by others are not modelled, except: on a book event where our price is the
best on its side, `queue_ahead = min(queue_ahead, queue_mult * displayed size)`.

**Inventory cap** (enforced by the engine, not the policy). If `q_max` is set and `q >= q_max`, the bid
is cancelled immediately and bid actions are treated as OUT; mirror for `q <= -q_max`.
`q_max = None` means no cap and is used for shadow orders.

**Stale data** (paper mode only). If `stale_s` is set and no event arrived for `stale_s` seconds, both
sides are forced OUT until the next event.

**P&L identity** (must hold to 1e-9 in tests), marked to the tape mid `(bid + ask) / 2`:
`total = spread_capture + inventory_pnl - fees`, with the same definitions as `mm/backtest.py`.

**Day boundaries.** Each UTC day is run separately: orders are cancelled and inventory is marked to the
last mid and reset to zero at the end of the day. Learned state (`EdgeTable`, agent scores) carries over.

**Net edge of a fill** (the quantity everything learns):
`net_edge_bp = side * (mid at fill time + 60 s - fill price) / fill price * 1e4 - maker_fee_bps`,
with `side = +1` for a buy. It already contains spread captured, adverse selection and the fee.

---

## Task 0: Baseline

**Files:** create `.git` (the folder is not a git repo yet), modify `docs/PROJECT_PLAN.md`, create `config/candidates.txt`.

- [ ] Run `python -m pytest -q`. Record the passing count in your report. If anything fails, stop.
- [ ] `git init`, check `.gitignore` already excludes `.venv/` and `data/*`, commit everything as "baseline before v2".
- [ ] Create `config/candidates.txt` with the 12 symbols that already have files in `data/` (list `data/*_trades.parquet`, take the part before the first `_`).
- [ ] Append to `docs/PROJECT_PLAN.md`: a line "v2 build guide: docs/BUILD_GUIDE.md" and an unticked checklist of Tasks 1-11 from this guide.
- [ ] Commit.

## Task 1: Multi-symbol recorder

**Files:** modify `mm/recorder.py`; create `tests/test_recorder_multi.py`, `run_recorder_multi.bat`.

**Produces:** `python -m mm.recorder --symbols ANKRUSDT,SKLUSDT,ARBUSDT,BTCUSDT`; files in the same
per-symbol layout as today (`data/live/<SYMBOL>/book|trades/...parquet`). `--symbol X` keeps working.

- [ ] Tests: `MultiRecorder(["ANKRUSDT","BTCUSDT"], out=tmp_path).handle(raw, recv_us)` with a combined-stream message `{"stream":"ankrusdt@bookTicker","data":{...}}` puts the row in ANKRUSDT's buffer only; an `aggTrade` for btcusdt goes to BTCUSDT; `flush()` writes one parquet per symbol per kind under the right folder; `load_live` reads them back with the existing column lists; an unknown stream is ignored without error.
- [ ] Implement `class MultiRecorder` (one websocket, combined streams URL with every `<sym>@bookTicker/<sym>@aggTrade`, one `Recorder`-style buffer per symbol, same reconnect loop). Reuse `parse_book` / `parse_trade`.
- [ ] `run_recorder_multi.bat`: starts it for every symbol in `config/candidates.txt` in its own window titled "v2 recorder - close this window to stop".
- [ ] Report to the user: they must start the .bat and set Windows to never sleep while plugged in. Everything in Tasks 2-8 works without it; Task 9 needs at least 3 days of it.

## Task 2: History download and tick-constraint screener

**Files:** create `mm/screen.py`, `scripts/download_history.py`, `scripts/screen_universe.py`, `tests/test_screen.py`, `run_download_history.bat`.

**Produces:**
- `screen_row(cals: list[dict]) -> dict` where `cals` are `mm.calibrate.calibrate` outputs for one symbol over several days. Returns `symbol, days, tick_bp_med, spread_ticks_med, usd_volume_med, trades_per_sec_med, constrained`.
- `constrained = tick_bp_med >= 10.0 and spread_ticks_med <= 1.5 and usd_volume_med >= 100_000`.
- `results/screen.csv`, sorted with constrained coins first, then by `usd_volume_med` descending.

- [ ] Tests for `screen_row`: medians are medians (3 days with tick_bp 25, 26, 100 -> 26); each of the three thresholds flips `constrained` on its own boundary (9.99 false, 10.0 true; 1.5 true, 1.51 false; 99_999 false, 100_000 true).
- [ ] `scripts/download_history.py --days 60 --end YYYY-MM-DD` (default end = yesterday UTC): for every symbol in `config/candidates.txt`, call `mm.data.download_day` for each day, skip files that exist, continue past a missing day with a printed warning, print a final table of days present per symbol.
- [ ] `scripts/screen_universe.py`: calibrate up to the 7 most recent days per symbol, write `results/screen.csv`, print it.
- [ ] `.bat` launcher runs download then screen. Ask the user to run it (downloads need their network).
- [ ] Report: the screen table. The constrained symbols are "the v2 universe" for all later tasks.

## Task 3: Book tape and the queue engine

**Files:** create `mm/tape.py`, `mm/queue_sim.py`, `tests/test_tape.py`, `tests/test_queue_sim.py`.

**Produces (exact):**

```python
# mm/tape.py
BOOK_TAPE_COLUMNS = ["ts_us", "bid", "ask", "bid_qty", "ask_qty"]
def book_from_trades(trades: pd.DataFrame, tick: float, level_qty: float) -> pd.DataFrame: ...
def book_from_recorder(book: pd.DataFrame) -> pd.DataFrame: ...      # recv_us -> ts_us, keeps the 5 columns
def typical_level_qty(tape: pd.DataFrame) -> float: ...               # median of bid_qty and ask_qty pooled
def default_level_qty(trades: pd.DataFrame) -> float: ...             # 20 * median trade qty (used until Task 9 measures it)
def merge_events(tape, trades, decision_ms: int): ...                 # yields ("book", row) / ("trade", row) / ("timer", ts_us)

# mm/queue_sim.py
class Action(IntEnum): OUT = 0; JOIN = 1; BACK = 2
@dataclass(frozen=True)
class MarketState: ts_us: int; bid: float; ask: float; bid_qty: float; ask_qty: float; tick: float; feat: Mapping[str, float]
class Policy(Protocol):
    name: str
    def decide(self, st: MarketState, q: int) -> tuple[Action, Action]: ...   # (bid, ask)
@dataclass(frozen=True)
class QSConfig:
    lot_usd: float = 100.0; q_max: Optional[int] = 10; maker_fee_bps: float = 10.0
    latency_ms: int = 300; decision_ms: int = 1000
    queue_mult: float = 1.0; back_queue_mult: float = 1.0
    warmup_s: float = 600.0; stale_s: Optional[float] = None
    markouts_s: tuple = (1, 10, 60, 300)
@dataclass
class JoinTouch: name: str = "Join touch"          # always (JOIN, JOIN)
@dataclass
class Fixed: bid: Action; ask: Action; name: str = "Fixed"   # always the same pair (used for shadows and tests)
class QueueSim:
    def __init__(self, policy: Policy, cfg: QSConfig, tick: float, features=None): ...
    def on_book(self, ts_us, bid, ask, bid_qty, ask_qty) -> None: ...
    def on_trade(self, ts_us, price, qty, side) -> list: ...     # returns the fills this trade caused
    def on_timer(self, ts_us) -> None: ...
    def end_day(self) -> None: ...
    def result(self) -> "QSResult": ...
    q: int; pnl: float                                        # live attributes, read by the agent
def run_queue_sim(tape, trades, policy, cfg, tick, features=None) -> "QSResult": ...
```

`QSResult` has `name, cfg, minute, fills, totals, markouts` with the same column names and `totals` keys
as `mm.backtest.BTResult`, plus fill columns `ts_us, qty, mid, wait_s, action` and one `f_<name>` column
per feature in the `MarketState.feat` of the decision that placed or last kept the order.
`features` is any object with `on_book`, `on_trade`, `snapshot(ts_us) -> dict`; `None` means `feat = {}`.

**`book_from_trades` rule:** bid = price of the last seller-aggressor trade, ask = price of the last
buyer-aggressor trade. Emit a row when either changes, once both exist. If a sell prints at or above the
current ask, set `ask = that price + tick`; if a buy prints at or below the current bid, set
`bid = that price - tick`. `bid_qty = ask_qty = level_qty`.

- [ ] **Tape tests** (`tick = 1`, `level_qty = 50`): trades `(t=1, 100, buy), (t=2, 99, sell)` -> one row at t=2 `bid 99, ask 100`; then `(t=3, 100, sell)` -> row `bid 100, ask 101`; then `(t=4, 100, buy)` -> row `bid 99, ask 100`; a tape with only buys is empty (0 rows, right columns); `merge_events` order at equal timestamps is book, trade, timer.
- [ ] **Engine tests.** Use a helper that builds a constant book `bid 99, ask 100, sizes 100`, `tick 1`, `QSConfig(lot_usd=99.0, latency_ms=0, decision_ms=1000, warmup_s=0, maker_fee_bps=0, q_max=None)` unless stated. Each bullet is one test:
  - Queue: sells at 99 of qty 60 then 30 cause no fill; a third of 20 fills the bid at 99 (`queue_mult=1`).
  - Through: one sell at 98 fills the bid at 99 immediately whatever the queue.
  - `queue_mult=0` fills on the first sell at 99 of any size; `queue_mult=1e12` never fills on trades at 99, only on a trade at 98.
  - Latency: with `latency_ms=300`, a sell at 98 arriving 200 ms after the first decision does not fill; one arriving 400 ms after does.
  - Cancel latency: policy switches to OUT at t; a through trade at t+200 ms still fills; one at t+400 ms does not.
  - Keep queue: two decisions in a row with the same target price do not reset `queue_ahead` (60 traded, decision, 50 traded -> filled).
  - Requeue: best bid moves 99 -> 100, JOIN replaces the order at 100 with a fresh queue.
  - BACK rests at 98; it fills only on a sell at 97, or after sells at 98 exceed `back_queue_mult * 100`.
  - Post-only: an activation whose bid price >= ask is rejected and nothing fills.
  - Book shrink: resting at best with `queue_ahead` 100, a book event with `bid_qty` 30 sets it to 30.
  - Cap: `q_max=1`; after one buy fill no second buy fill occurs, sells still fill.
  - Stale: `stale_s=120`; no events for 121 s -> no resting orders; next event restores quoting at the following timer.
  - Identity: random tape of 5,000 events (fixed seed) with `JoinTouch`, fee 10 bp: `abs(pnl - (spread_capture + inventory_pnl - fees)) < 1e-9` and minute rows sum consistently.
  - Timer skipping does not change results: same run with skipping disabled (a private flag) gives identical fills.
  - `mm.metrics.summarize(result)` runs and returns `fills`, `markout_60s_bp`, `net_10bp`.
  - Empty tape or zero trades: `run_queue_sim` returns zero fills and `pnl == 0`, no exception.
  - Out-of-order event (`ts_us` lower than the last one) is processed at the last timestamp, no exception.
- [ ] Implement `mm/tape.py`, then `mm/queue_sim.py` following section 5 line by line.
- [ ] Run the full suite, commit.

## Task 4: Incremental features

**Files:** create `mm/features.py`, `tests/test_features.py`.

**Produces:**

```python
FEATURE_NAMES = ("book_imb", "micro_bp", "flow_5s", "flow_60s", "vol_ratio", "spread_ticks")
class FeatureEngine:
    def __init__(self, tick: float): ...
    def on_book(self, ts_us, bid, ask, bid_qty, ask_qty) -> None: ...
    def on_trade(self, ts_us, price, qty, side) -> None: ...
    def snapshot(self, ts_us) -> dict[str, float]: ...
```

Definitions (all from events with `ts_us <=` the snapshot time):

- `book_imb = (bid_qty - ask_qty) / (bid_qty + ask_qty)`, 0 if the sum is 0.
- `micro_bp = (microprice - mid) / mid * 1e4`, `microprice = (ask_qty*bid + bid_qty*ask) / (bid_qty + ask_qty)`.
- `flow_h = (B - S) / (B + S)` where B and S are buy and sell volumes decayed with half-life h seconds (5 and 60); 0 if `B + S == 0`.
- `vol_ratio = sqrt(v_10 / v_1800)`, `v_h` = sum of squared mid changes decayed with half-life h, divided by `h / ln 2`. Return 1.0 during the first 600 s or if `v_1800 == 0`.
- `spread_ticks = (ask - bid) / tick`.

- [ ] Tests: sizes 300 / 100 -> `book_imb == 0.5` and microprice closer to the ask; 10 units bought at t=0 and nothing else -> `flow_5s == 1.0` at t=0 and still 1.0 at t=5 s (ratio is scale-free) while a 10-unit sell at t=5 s gives `flow_5s == (5-10)/(5+10)`; `vol_ratio == 1.0` before 600 s; zero sizes do not raise; **past-only test**: feed events 1..N and take snapshots at each; feed only events 1..k and the first k snapshots are identical.
- [ ] Implement, run suite, commit.

## Task 5: Edge table and edge policy

**Files:** create `mm/edge.py`, `tests/test_edge.py`.

**Produces:**

```python
IMB_EDGES = (-0.33, 0.33); VOL_EDGES = (1.5, 3.0); N_MIN_POOLED = 20.0
def net_edge_bp(side: int, fill_price: float, mid_later: float, fee_bps: float) -> float: ...
def bucket_of(feat: Mapping[str, float], side: int) -> tuple[int, int]: ...
class EdgeTable:
    def __init__(self, halflife_fills: float = 300.0, n0: float = 30.0): ...
    def update(self, action: Action, bucket: tuple[int, int], x: float) -> None: ...
    def estimate(self, action: Action, bucket: tuple[int, int]) -> tuple[float, float]: ...   # (mean, se)
    def to_dict(self) -> dict: ...
    @classmethod
    def from_dict(cls, d: dict) -> "EdgeTable": ...
@dataclass
class EdgePolicy:
    table: EdgeTable; e_min_bp: float = 0.0; z: float = 1.0; gamma_bp: float = 1.0; name: str = "Edge"
    def decide(self, st: MarketState, q: int) -> tuple[Action, Action]: ...
```

Rules:

- `bucket_of`: first index from `side * feat["book_imb"]` against `IMB_EDGES` (0 = book leaning against our order, 2 = leaning with it); second from `feat["vol_ratio"]` against `VOL_EDGES`. Missing features count as 0.0 and 1.0.
- Each cell `(action, bucket)` and one pooled cell per action keep a decayed count, mean and variance. On `update`, only that cell and its pooled cell decay by `0.5 ** (1 / halflife_fills)` before adding the observation.
- `estimate`: if the pooled count for that action is below `N_MIN_POOLED`, return `(-1e9, 0.0)`. Otherwise `mean = (n*cell_mean + n0*pooled_mean) / (n + n0)` and `se = sqrt(var / max(n, 1.0))` using the cell variance when `n >= 2`, else the pooled variance.
- `EdgePolicy.decide`, per side: `threshold = e_min_bp + gamma_bp * q` for the bid and `e_min_bp - gamma_bp * q` for the ask (being long makes buying harder and selling easier). For each of JOIN and BACK compute `score = mean - z * se - threshold`. Pick the action with the highest score if it is > 0, else OUT. Ties go to JOIN.

- [ ] Tests: `net_edge_bp(+1, 100.0, 100.05, 10.0) == -5.0` (within 1e-9) and `net_edge_bp(-1, 100.0, 99.8, 10.0) == 10.0`; `bucket_of({"book_imb": 0.5, "vol_ratio": 2.0}, +1) == (2, 1)` and with `side=-1` -> `(0, 1)`; fewer than 20 pooled updates -> `estimate` returns `(-1e9, 0.0)` and the policy returns `(OUT, OUT)`; a cell with 0 own observations returns the pooled mean; after 2,000 updates of +5 followed by 2,000 of -5 the mean is below -4.5 (forgetting works); shrinkage: after 1,000 updates of 0 spread over other cells and 30 updates of +10 in one cell, that cell's estimate equals `(n*10 + 30*P) / (n + 30)` where `n` is its decayed count and `P` the pooled mean read from the table, and lies strictly between `P` and 10; policy: table where JOIN is +8 bp and BACK is +3 bp in every bucket with tiny se -> `(JOIN, JOIN)` at `q = 0`; with `gamma_bp = 1`, `e_min = 0`, `q = 9` -> bid OUT (8 - 9 < 0) and ask JOIN; `to_dict` / `from_dict` round-trips estimates exactly.
- [ ] Implement, run suite, commit.

## Task 6: The calibration agent

**Files:** create `mm/agent.py`, `tests/test_agent.py`.

**Produces:**

```python
@dataclass(frozen=True)
class ArmSpec: e_min_bp: float; z: float; gamma_bp: float
MENU: tuple[ArmSpec, ...]     # e_min_bp in (0, 2, 5) x z in (0, 1) x gamma_bp in (0.5, 2.0), in that nesting order: 12 arms
START_ARM = MENU.index(ArmSpec(5.0, 1.0, 2.0))     # most conservative
@dataclass(frozen=True)
class AgentConfig:
    horizon_s: float = 60.0; interval_s: float = 1800.0
    score_halflife_intervals: float = 48.0; switch_margin_bp: float = 1.0; min_arm_fills: float = 50.0
    max_daily_loss_usd: float = 20.0
class CalibrationAgent:
    def __init__(self, cfg: AgentConfig, sim_cfg: QSConfig, tick: float, table: Optional[EdgeTable] = None): ...
    def on_book(self, ts_us, bid, ask, bid_qty, ask_qty) -> None: ...
    def on_trade(self, ts_us, price, qty, side) -> None: ...
    def on_timer(self, ts_us) -> None: ...
    def end_day(self) -> None: ...
    def result(self) -> QSResult: ...          # the live track
    live_arm: int; history: list[dict]; table: EdgeTable
def run_agent(tape, trades, agent: CalibrationAgent, decision_ms: int) -> None: ...   # feeds one day of events
```

How it works (three layers, in this order on every event):

1. **Shared features.** One `FeatureEngine`; every simulator below receives the same events.
2. **Shadow learners (layer 1).** Two simulators with `Fixed(JOIN, JOIN)` and `Fixed(BACK, BACK)` and `q_max=None`. Each of their fills goes into a pending queue with its action, side, price and the bucket from its `f_` features. When the clock reaches `fill time + horizon_s`, compute `net_edge_bp` with the current mid and call `table.update`. Fills still pending at `end_day` are dropped.
3. **Arms (layer 2).** One simulator per `MENU` entry, each with its own `EdgePolicy` on the shared table and its own inventory. At the end of every `interval_s`, each arm's score is its P&L change over the interval in bp of `q_max * lot_usd`; keep a decayed mean score and a decayed fill count per arm (half-life `score_halflife_intervals`).
4. **Live track.** One more simulator whose policy delegates to the current live arm's `EdgePolicy`. At the end of each interval: among arms with decayed fills >= `min_arm_fills`, take the best decayed mean; switch `live_arm` to it only if it beats the live arm's decayed mean by more than `switch_margin_bp`. Append to `history`: `ts_us, live_arm, switched, scores, fills`.
5. **Loss stop (layer 3 guardrail).** If the live track's P&L since the start of the UTC day is below `-max_daily_loss_usd`, the live policy returns `(OUT, OUT)` until `end_day`. Shadows and arms keep running.

The agent can change only: the table's numbers and which menu entry is live. It cannot change
`q_max`, `lot_usd`, the menu, the fee or the loss stop.

- [ ] Tests:
  - `len(MENU) == 12` and `MENU[START_ARM] == ArmSpec(5.0, 1.0, 2.0)`.
  - **No look-ahead:** shadow fill at t = 100 s; the table is unchanged at t = 159 s and updated at t = 160 s, and the value used is the mid at 160 s (move the mid at 161 s and check it has no effect).
  - Shadows have no inventory cap: 30 consecutive buy fills are all recorded.
  - Switching: stub scores so arm 3 has decayed mean 4.0 bp, the live arm 2.0 bp, both with enough fills -> switch; with arm 3 at 2.5 bp -> no switch (margin 1.0); with arm 3 below `min_arm_fills` -> no switch.
  - Loss stop: force live P&L to -20.01 -> live track places no orders for the rest of the day, quoting resumes after `end_day`.
  - Determinism: the same events twice give identical `history` and identical live fills.
  - Carry-over: `end_day` resets inventories to 0 but leaves `table` and arm scores unchanged.
  - A day with no trades runs without error and leaves `live_arm` unchanged.
- [ ] Implement. Reuse `QueueSim` unchanged; if you need a hook it lacks, stop and ask rather than fork it.
- [ ] Run suite, commit.

## Task 7: Queue baseline on history (does the micro-cap edge survive a queue?)

**Files:** create `scripts/run_queue_baseline.py`, `run_queue_baseline.bat`.

For every v2-universe symbol (Task 2) and every downloaded day: build `book_from_trades(trades, tick, default_level_qty(trades))`, run `JoinTouch` with `QSConfig()` defaults at `queue_mult` 0.5, 1.0, 2.0. Also run it with `queue_mult=0, latency_ms=100` as a bridge to v1's "touch" rule.

- [ ] Write `results/queue_baseline.csv`: one row per symbol, day, queue_mult with `mm.metrics.summarize` fields plus `net_edge_bp_mean` and `wait_s_median`.
- [ ] Print a table per symbol: days, fills per day, net P&L per day in USD, net bp per dollar traded, share of positive days, and t = mean daily net P&L / (std / sqrt(days)).
- [ ] Sanity check to print: on ANKRUSDT 2026-11-10 the `queue_mult=0` run should land near v1's join-touch "touch" result in `results/walkforward.csv` (same order of magnitude of fills and the same sign). If the sign differs, stop and report.
- [ ] Report the tables. **Do not tune anything.** This is the first honest look at the edge; the user decides what it means.

## Task 8: Agent walk-forward and Gate A

**Files:** create `scripts/run_agent_walkforward.py`, `run_agent_walkforward.bat`.

Per symbol: days in date order. Days 1-7 are warm-up (the agent runs and learns; results not counted).
From day 8 on, results count. One `CalibrationAgent` per symbol lives across all days (`end_day` between
days). Run the whole thing three times: `queue_mult` 1.0 (headline), 2.0 (stress), 0.5 (optimistic).
Baselines on the same days: `JoinTouch`, and `EdgePolicy` frozen at `START_ARM` with a table frozen after day 7.

- [ ] Write `results/agent_walkforward.csv` (symbol, day, variant, queue_mult, summarize fields), `results/agent_history.json` (switch history per symbol), and `results/gate_a.json`.
- [ ] **Gate A** (computed, not judged; write each number and a boolean): using agent rows, headline queue, counted days with >= 20 fills:
  1. mean daily net P&L > 0 and t > 3 across coin-days;
  2. at least 3 symbols with positive total net P&L;
  3. at least 60% of coin-days positive;
  4. mean daily net P&L still > 0 at `queue_mult = 2.0`;
  5. agent total net P&L >= `JoinTouch` total (otherwise the agent adds nothing).
  `pass = all five`.
- [ ] Print the gate table and a 5-line plain-language summary. If Gate A fails, say so plainly and stop: do not adjust the menu, buckets or thresholds to make it pass.

## Task 9: Check the inferred tape against the real book

Needs at least 3 days of Task 1's recorder for at least one v2-universe symbol.

**Files:** create `scripts/validate_tape.py`.

- [ ] For each recorded symbol-day: run `JoinTouch` (headline config) once on `book_from_recorder(load_live(.../book))` with the recorded trades, and once on `book_from_trades` of the same recorded trades with `default_level_qty`.
- [ ] Print and save `results/tape_validation.csv`: fills, net edge bp, median wait, for both; the ratio of fills; the difference in net edge; and `typical_level_qty(real tape) / default_level_qty(trades)`.
- [ ] Verdict rule to print: "inferred tape acceptable" if fills are within +/-30% and net edge within 2 bp on pooled days. If not, report the measured level-size ratio; the user will decide whether to re-run Tasks 7-8 with `level_qty` scaled by it.

## Task 10: Paper trader

**Files:** create `mm/paper.py`, `tests/test_paper.py`, `run_paper.bat`.

**Produces:** `python -m mm.paper --symbols <list> [--state data/paper/state]`. It opens the same public
websocket as the recorder, and for each symbol feeds `on_book` / `on_trade` / a 1-second timer into a
`CalibrationAgent` with `QSConfig(stale_s=120.0)`. It never sends an order anywhere.

- [ ] On start, load each symbol's `EdgeTable` from `<state>/<SYMBOL>_table.json` if present (Task 8 can export its final tables there with `--export-state`; add that flag to the Task 8 script).
- [ ] Every 60 s write `<state>/<SYMBOL>_table.json` and append live fills and `history` rows to `data/paper/<SYMBOL>/fills_<date>.parquet` and `history_<date>.jsonl`. At UTC midnight call `end_day`.
- [ ] Also record the raw feed exactly as the recorder does (reuse its buffers), so every paper day can be replayed.
- [ ] Tests (no network): a `PaperSession` fed a scripted list of raw websocket messages produces the same live fills as `run_agent` on the equivalent tapes; state files round-trip; a message with an unknown stream is ignored; a restart with saved state resumes with the same `live_arm`.
- [ ] `run_paper.bat` for the v2 universe. Report how to start and stop it.

## Task 11: Daily supervisor report

**Files:** create `scripts/daily_supervisor.py`, `run_supervisor.bat`.

For each paper symbol and the last completed UTC day:

- [ ] Replay the recorded feed of that day through a fresh agent started from the previous day's saved state; compare with the paper log: fills (count) and net P&L. They should match exactly; any difference is a bug to report, not to average away.
- [ ] Compute realised mean net edge of live fills versus the table's estimate at decision time; `z = (realised - predicted) / se`.
- [ ] Write `data/paper/coin_state.json`: `size_mult = 0.5` if `z < -2`, `enabled = false` after two such days in a row, back to `1.0` / `true` after three normal days. (The paper trader reads it at start and at midnight: `size_mult` scales `lot_usd`.)
- [ ] Write `results/paper_report_<date>.md`: per symbol fills, net P&L, net bp per dollar, live arm and switches, z, state change; and a running table of all paper days.
- [ ] **Gate B** numbers in the report once 14 paper days exist: mean daily net P&L and t across coin-days, share of positive days, replay-match rate. Only after the user has seen Gate B do the deferred items (legal route, risk budget, server, real orders) come back on the table.

---

## 6. Review focus (inputs the tests above might not make you think about)

1. **A day with trades on one side only** (thin coin): the inferred tape is empty. Every script must skip that day with a printed note, not crash and not count it as a zero-P&L day.
2. **Recorder gaps** (the PC slept): paper mode must go OUT via `stale_s`, and Task 9 / Task 11 must drop hours with gaps longer than 120 s from comparisons.
3. **Tick size changes** (Binance occasionally changes a pair's tick): compute `tick` per day with `infer_tick`; if it differs from the previous day, reset that symbol's `EdgeTable` and print a warning.
4. **Price near zero / huge lot counts**: `qty = lot_usd / mid` can be millions of units; nothing may assume small integers or use float equality on prices. Compare prices as integer tick counts `round(price / tick)`.
5. **Markouts at the end of a day**: fills in the last 60 s have no 60 s markout; they are excluded from learning and from `net_edge_bp_mean`, never filled with the last mid.

## 7. What "done" looks like

- Tasks 0-8 need only historical trades and can be finished without any live component.
- After Task 8 the user has a pre-registered pass/fail on whether the edge survives queues, fees and 300 ms latency, and whether the agent beats a static rule.
- Tasks 9-11 add the live feed: first to validate the inferred tape, then to paper trade.
- Nothing in this guide places an order. That decision comes after Gate B.
