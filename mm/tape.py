"""v2 Task 3: book tapes and the single time-ordered event stream the engine consumes.

The Binance archive has months of trades but no spot order book. So for history we INFER
the best bid and ask from the trades themselves: a seller-aggressor trade prints at the bid,
a buyer-aggressor trade prints at the ask. On a tick-constrained coin (spread = one tick)
this is close to exact; the live recorder collects the real top of book so Task 9 can check.

Displayed sizes are unknown on an inferred tape, so every level gets the same
``level_qty`` (by default 20 x the median trade size, until Task 9 measures it).

Event order (``merge_events``): by time; at equal timestamps book first, then trades, then
the decision timer. So a decision at time t has seen every event stamped t.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BOOK_TAPE_COLUMNS = ["ts_us", "bid", "ask", "bid_qty", "ask_qty"]


def _empty_tape() -> pd.DataFrame:
    return pd.DataFrame({c: pd.Series(dtype="int64" if c == "ts_us" else float) for c in BOOK_TAPE_COLUMNS})


def book_from_trades(trades: pd.DataFrame, tick: float, level_qty: float) -> pd.DataFrame:
    """Best bid = last seller-aggressor price, best ask = last buyer-aggressor price.

    A sell at or above the current ask means the ask moved up: ask = that price + tick.
    A buy at or below the current bid means the bid moved down: bid = that price - tick.
    A row is emitted whenever bid or ask changes, once both exist. Prices are compared as
    integer tick counts (no float equality on prices)."""
    if len(trades) == 0:
        return _empty_tape()
    ts = trades["ts_us"].to_numpy(np.int64)
    k = np.rint(trades["price"].to_numpy(float) / tick).astype(np.int64)
    side = trades["side"].to_numpy()
    bid = ask = None
    last = None
    out_ts, out_b, out_a = [], [], []
    for t, p, s in zip(ts, k, side):
        if s < 0:
            if ask is not None and p >= ask:
                ask = p + 1
            bid = p
        else:
            if bid is not None and p <= bid:
                bid = p - 1
            ask = p
        if bid is None or ask is None:
            continue
        if last != (bid, ask):
            last = (bid, ask)
            out_ts.append(int(t)); out_b.append(bid); out_a.append(ask)
    if not out_ts:
        return _empty_tape()
    n = len(out_ts)
    return pd.DataFrame({"ts_us": np.array(out_ts, dtype=np.int64),
                         "bid": np.array(out_b, float) * tick, "ask": np.array(out_a, float) * tick,
                         "bid_qty": np.full(n, float(level_qty)), "ask_qty": np.full(n, float(level_qty))})


def book_from_recorder(book: pd.DataFrame) -> pd.DataFrame:
    """Recorder bookTicker rows -> book tape (receive time is the time axis)."""
    if len(book) == 0:
        return _empty_tape()
    df = book.rename(columns={"recv_us": "ts_us"})[BOOK_TAPE_COLUMNS]
    return df.sort_values("ts_us", kind="stable").reset_index(drop=True)


def typical_level_qty(tape: pd.DataFrame) -> float:
    """Median displayed size at the best price, bid and ask pooled."""
    return float(np.median(np.concatenate([tape["bid_qty"].to_numpy(float), tape["ask_qty"].to_numpy(float)])))


def default_level_qty(trades: pd.DataFrame) -> float:
    """Stand-in queue size for inferred tapes: 20 x the median trade size."""
    return 20.0 * float(np.median(trades["qty"].to_numpy(float)))


def merge_events(tape: pd.DataFrame, trades: pd.DataFrame, decision_ms: int):
    """Yield ("book", (ts, bid, ask, bid_qty, ask_qty)), ("trade", (ts, price, qty, side)) and
    ("timer", ts) in time order; at equal times book < trade < timer. Timers sit on the absolute
    grid of multiples of ``decision_ms`` between the first and last book/trade event."""
    bt = tape["ts_us"].to_numpy(np.int64) if len(tape) else np.empty(0, np.int64)
    tt = trades["ts_us"].to_numpy(np.int64) if len(trades) else np.empty(0, np.int64)
    if bt.size + tt.size == 0:
        return
    step = int(decision_ms) * 1000
    lo = int(min(bt.min() if bt.size else tt.min(), tt.min() if tt.size else bt.min()))
    hi = int(max(bt.max() if bt.size else tt.max(), tt.max() if tt.size else bt.max()))
    first = -(-lo // step) * step
    timers = np.arange(first, hi + 1, step, dtype=np.int64)

    ts = np.concatenate([bt, tt, timers])
    kind = np.concatenate([np.zeros(bt.size, np.int8), np.ones(tt.size, np.int8), np.full(timers.size, 2, np.int8)])
    idx = np.concatenate([np.arange(bt.size), np.arange(tt.size), np.arange(timers.size)])
    order = np.lexsort((idx, kind, ts))

    if bt.size:
        B = tape[["bid", "ask", "bid_qty", "ask_qty"]].to_numpy(float)
    if tt.size:
        P = trades["price"].to_numpy(float); Q = trades["qty"].to_numpy(float)
        D = trades["side"].to_numpy().astype(int)
    for o in order:
        k, i, t = kind[o], idx[o], int(ts[o])
        if k == 0:
            r = B[i]
            yield "book", (t, float(r[0]), float(r[1]), float(r[2]), float(r[3]))
        elif k == 1:
            yield "trade", (t, float(P[i]), float(Q[i]), int(D[i]))
        else:
            yield "timer", t
