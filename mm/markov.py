"""Markov microprice (v2.1 Task 13), after Stoikov (2018): the expected mid change given the book state.

State of the book at every update: (imbalance bucket 0..4, spread class), ten states.
    imbalance = (bid_qty - ask_qty) / (bid_qty + ask_qty), cut at -0.6, -0.2, 0.2, 0.6 (five equal-count-ish
    buckets of a fixed, symmetric width; fixed edges keep the table symmetric and comparable across days)
    spread class 0 = one tick, 1 = two ticks or more. State index = 5 * spread_class + bucket.

Between consecutive updates, count
    Q[s, s']  the mid does not move and the state goes s -> s'
    R[s, k]   the mid moves by k half-ticks
    T[s, s']  the mid moves and the state after the move is s'
The mirrored book (swap bid and ask sides, so bucket b -> 4 - b, and flip the sign of every move) is
added before normalising, so the table is symmetric by construction: G*(s) = -G*(mirror(s)).

    G1 = (I - Q)^-1 R K        B = (I - Q)^-1 T        G* = sum_{i=0..5} B^i G1

G* is in ticks; ``markov_bp`` converts to basis points of the mid. Past-only: the value at an update
uses that update's state alone, and ``fit_daily`` fits each UTC day on the previous days only.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

N_BUCKETS = 5
N_STATES = 10
EDGES = np.array([-0.6, -0.2, 0.2, 0.6])
K_MAX = 6                                   # moves beyond 6 half-ticks are clipped
SEC = 1_000_000
DAY = 86_400 * SEC
TERMS = 5                                   # i = 0..5 in the series for G*


def state_index(imb: np.ndarray, spread_ticks: np.ndarray) -> np.ndarray:
    bucket = np.searchsorted(EDGES, np.asarray(imb, float), side="right")
    wide = (np.asarray(spread_ticks, float) > 1.5).astype(int)
    return 5 * wide + bucket


def mirror_state(s):
    s = np.asarray(s)
    return 5 * (s // 5) + (4 - s % 5) if s.ndim else int(5 * (s // 5) + (4 - s % 5))


def _arrays(book: pd.DataFrame, tick: float):
    bid, ask = book["bid"].to_numpy(float), book["ask"].to_numpy(float)
    bq, aq = book["bid_qty"].to_numpy(float), book["ask_qty"].to_numpy(float)
    tot = bq + aq
    imb = np.divide(bq - aq, tot, out=np.zeros_like(tot), where=tot > 0)
    return state_index(imb, (ask - bid) / tick), (bid + ask) / 2


def fit(book: pd.DataFrame, tick: float) -> dict:
    """Estimate Q, R, T and G* from a recorded book (rows in time order)."""
    s, mid = _arrays(book, tick)
    if len(s) < 3:
        raise ValueError("need at least 3 book updates")
    k = np.clip(np.rint((mid[1:] - mid[:-1]) / tick * 2).astype(int), -K_MAX, K_MAX)
    a, b = s[:-1], s[1:]
    n = np.zeros(N_STATES)
    stay = np.zeros((N_STATES, N_STATES))
    move_to = np.zeros((N_STATES, N_STATES))
    rk = np.zeros((N_STATES, 2 * K_MAX + 1))
    for aa, bb, kk in ((a, b, k), (mirror_state(a), mirror_state(b), -k)):          # the book and its mirror image
        np.add.at(n, aa, 1.0)
        still = kk == 0
        np.add.at(stay, (aa[still], bb[still]), 1.0)
        np.add.at(move_to, (aa[~still], bb[~still]), 1.0)
        np.add.at(rk, (aa[~still], kk[~still] + K_MAX), 1.0)
    seen = n > 0
    div = np.where(seen, n, 1.0)[:, None]
    Q, T, R = stay / div, move_to / div, rk / div
    ks = (np.arange(-K_MAX, K_MAX + 1) / 2.0)                                        # half-ticks -> ticks
    RK = R @ ks
    Qs = Q * (1 - 1e-9)                                                              # keeps I - Q invertible if a row never moves
    inv_g1 = np.linalg.solve(np.eye(N_STATES) - Qs, RK)
    B = np.linalg.solve(np.eye(N_STATES) - Qs, T)
    G, Bi = inv_g1.copy(), np.eye(N_STATES)
    for _ in range(TERMS):
        Bi = Bi @ B
        G = G + Bi @ inv_g1
    G = np.where(seen, G, 0.0)
    return {"G": G, "Q": Q, "R": R, "T": T, "count": n, "RK": RK, "tick": float(tick)}


def markov_bp(book: pd.DataFrame, table: dict, tick: float) -> np.ndarray:
    """G* of each update's state, in basis points of the mid. One value per row; no look-ahead."""
    s, mid = _arrays(book, tick)
    return table["G"][s] * tick / mid * 1e4


def micro_bp(book: pd.DataFrame) -> np.ndarray:
    """The existing size-weighted microprice minus the mid, in basis points."""
    bid, ask = book["bid"].to_numpy(float), book["ask"].to_numpy(float)
    bq, aq = book["bid_qty"].to_numpy(float), book["ask_qty"].to_numpy(float)
    mid, tot = (bid + ask) / 2, bq + aq
    micro = np.divide(bid * aq + ask * bq, tot, out=mid.copy(), where=tot > 0)
    return (micro - mid) / mid * 1e4


def fit_daily(book: pd.DataFrame, tick: float, train_days: int = 3) -> dict[int, dict]:
    """``{utc_day_index: table}``: each day's table is fitted on the ``train_days`` days before it.
    A day with fewer than ``train_days`` earlier days in the data gets no table."""
    day = (book["recv_us"].to_numpy(np.int64) // DAY)
    days = sorted(set(day.tolist()))
    out = {}
    for d in days:
        prev = [x for x in days if x < d][-train_days:]
        if len(prev) < train_days:
            continue
        out[d] = fit(book[np.isin(day, prev)], tick)
    return out


def r2_report(book: pd.DataFrame, table: dict, tick: float, horizons=(1, 5, 30)) -> dict:
    """Out-of-sample R2 of ``markov_bp`` and ``micro_bp`` against the mid change over each horizon (seconds).
    The target uses the book at or before t + h; rows without one inside the data are dropped."""
    ts = book["recv_us"].to_numpy(np.int64)
    mid = (book["bid"].to_numpy(float) + book["ask"].to_numpy(float)) / 2
    xs = {"markov": markov_bp(book, table, tick), "micro": micro_bp(book)}
    out = {}
    for h in horizons:
        j = np.searchsorted(ts, ts + h * SEC, side="right") - 1
        ok = ts + h * SEC <= ts[-1]
        y = (mid[j] - mid)[ok] / mid[ok] * 1e4
        r = {}
        for name, x in xs.items():
            xv = x[ok]
            r[name] = float(np.corrcoef(xv, y)[0, 1] ** 2) if xv.std() > 0 and y.std() > 0 else 0.0
        r["n"] = int(ok.sum())
        out[h] = r
    return out
