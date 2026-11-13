"""Queue chain (v2.1 Task 14).

On a one-tick spread most of what moves a queue is other traders adding and cancelling, which
``QueueSim`` ignores by default. This module (a) classifies every change of the displayed size at the
best price as add / trade / cancel / move, (b) estimates the four event rates per (own size, opposite
size) bucket pair, (c) simulates the chain to get p_fill(x, n, m): the chance an order with ``x`` ahead
fills before the price moves away, under three assumptions about where cancels land, and (d) supplies
``CancelModel``, the hook ``QueueSim(cancel_model=...)`` uses to shrink ``queue_ahead`` on cancels.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

TRADE_WINDOW_US = 50_000
MAX_DT_S = 10.0                    # gaps longer than this are data gaps, not exposure
ASSUMPTIONS = ("front", "proportional", "back")
KINDS = ("add", "trade", "cancel", "move")
N_SIMS = 10_000
HORIZON_S = 30.0
X_MULTS = (0.0, 0.25, 0.5, 1.0, 2.0, 4.0, 8.0)


def classify(ts_us, k_prev, size_prev, k_new, size_new, trade_ts_us) -> str | None:
    """Kind of one change at the best price. ``trade_ts_us``: times of trades at the previous price."""
    if k_new != k_prev:
        return "move"
    if size_new > size_prev:
        return "add"
    if size_new < size_prev:
        t = np.asarray(trade_ts_us)
        return "trade" if len(t) and ((t <= ts_us) & (t >= ts_us - TRADE_WINDOW_US)).any() else "cancel"
    return None


def _recv(df: pd.DataFrame) -> pd.DataFrame:
    """The pipeline's frames call the time column ts_us, the recorder's recv_us; accept both."""
    return df if "recv_us" in df.columns or "ts_us" not in df.columns else df.rename(columns={"ts_us": "recv_us"})


def _rows(book: pd.DataFrame, trades: pd.DataFrame, tick: float, side: int) -> pd.DataFrame:
    """One row per consecutive pair of book updates: state before, kind of the change, event size, dt."""
    book, trades = _recv(book), _recv(trades)
    px, qty = (book["bid"], book["bid_qty"]) if side > 0 else (book["ask"], book["ask_qty"])
    opp = book["ask_qty"] if side > 0 else book["bid_qty"]
    ts = book["recv_us"].to_numpy(np.int64)
    k = np.round(px.to_numpy(float) / tick).astype(np.int64)
    n, m = qty.to_numpy(float), opp.to_numpy(float)
    tr = trades[trades["side"] < 0] if side > 0 else trades[trades["side"] > 0]
    tts, tk, tq = tr["recv_us"].to_numpy(np.int64), np.round(tr["price"].to_numpy(float) / tick).astype(np.int64), tr["qty"].to_numpy(float)
    order = np.argsort(tts, kind="stable")
    tts, tk, tq = tts[order], tk[order], tq[order]
    out = []
    for i in range(1, len(ts)):
        lo, hi = np.searchsorted(tts, ts[i] - TRADE_WINDOW_US, "left"), np.searchsorted(tts, ts[i], "right")
        sel = tk[lo:hi] == k[i - 1]
        kind = classify(ts[i], k[i - 1], n[i - 1], k[i], n[i], tts[lo:hi][sel])
        if kind == "add":
            size = n[i] - n[i - 1]
        elif kind == "cancel":
            size = n[i - 1] - n[i]
        elif kind == "trade":
            size = float(tq[lo:hi][sel].sum()) or n[i - 1] - n[i]
        else:
            size = 0.0
        out.append((ts[i], kind, size, n[i - 1], m[i - 1], min((ts[i] - ts[i - 1]) / 1e6, MAX_DT_S)))
    return pd.DataFrame(out, columns=["ts_us", "kind", "size", "n", "m", "dt"])


def events(book: pd.DataFrame, trades: pd.DataFrame, tick: float, side: int = 1) -> pd.DataFrame:
    r = _rows(book, trades, tick, side)
    return r[r["kind"].notna()].reset_index(drop=True)


def bucket_edges(sizes) -> np.ndarray:
    return np.quantile(np.asarray(sizes, float), [0.25, 0.5, 0.75])


def bucket(x: float, edges) -> int:
    return int(np.searchsorted(edges, x, side="right"))


@dataclass
class Cell:
    seconds: float
    rates: dict                 # events per second by kind
    mean_size: dict             # mean event size by kind
    n_rep: float                # representative own size (median of the bucket)


@dataclass
class QueueChain:
    edges_n: np.ndarray
    edges_m: np.ndarray
    cells: dict
    _table: dict = field(default_factory=dict)

    def cell(self, n: float, m: float) -> Cell:
        return self.cells[(bucket(n, self.edges_n), bucket(m, self.edges_m))]

    def _simulate(self, key, c: Cell, assumption: str) -> np.ndarray:
        """p_fill on the X_MULTS grid (x = mult * n_rep). Common random numbers across x and across the
        three assumptions, so the table is monotone in x and ordered front >= proportional >= back."""
        rng = np.random.default_rng(12345 + 4 * key[0] + key[1])
        r = np.array([c.rates[k] for k in KINDS])
        R = r.sum()
        grid = np.array(X_MULTS) * c.n_rep
        if R <= 0:
            return np.zeros(len(grid))
        cum = np.cumsum(r) / R
        steps = 400
        U_t = rng.random((steps, N_SIMS))
        U_k = rng.random((steps, N_SIMS))
        out = np.zeros(len(grid))
        for gi, x0 in enumerate(grid):
            x = np.full(N_SIMS, float(x0))
            n = np.full(N_SIMS, c.n_rep)
            t = np.zeros(N_SIMS)
            alive = np.ones(N_SIMS, bool)
            filled = np.zeros(N_SIMS, bool)
            for s in range(steps):
                if not alive.any():
                    break
                t = t + np.where(alive, -np.log(1 - U_t[s]) / R, 0.0)
                alive &= t <= HORIZON_S
                kind = np.searchsorted(cum, U_k[s], side="right").clip(max=3)
                add, trade, cancel, move = (alive & (kind == i) for i in range(4))
                alive &= ~move
                n = np.where(add, n + c.mean_size["add"], n)
                eat = np.where(trade, c.mean_size["trade"], 0.0)
                x = x - eat
                n = np.maximum(n - eat, 1.0)
                hit = trade & (x <= 0)
                filled |= hit
                alive &= ~hit
                cs = np.where(cancel, c.mean_size["cancel"], 0.0)
                if assumption == "front":
                    x = np.maximum(x - cs, 0.0)
                elif assumption == "proportional":
                    x = np.maximum(x - cs * np.clip(x / n, 0.0, 1.0), 0.0)
                n = np.maximum(n - cs, 1.0)
            out[gi] = filled.mean()
        return out

    def _grid(self, nb: int, mb: int, assumption: str):
        key = (nb, mb, assumption)
        if key not in self._table:
            c = self.cells[(nb, mb)]
            self._table[key] = (np.array(X_MULTS) * c.n_rep, self._simulate((nb, mb), c, assumption))
        return self._table[key]

    def p_fill(self, x: float, n: float, m: float, assumption: str = "proportional") -> float:
        grid, p = self._grid(bucket(n, self.edges_n), bucket(m, self.edges_m), assumption)
        return float(np.interp(x, grid, p))

    def table(self) -> dict:
        """The stored p_fill table: {(n_bucket, m_bucket, assumption): (x grid, p_fill)} for every cell."""
        for nb, mb in self.cells:
            for a in ASSUMPTIONS:
                self._grid(nb, mb, a)
        return dict(self._table)


def fit(book: pd.DataFrame, trades: pd.DataFrame, tick: float, side: int = 1) -> QueueChain:
    r = _rows(book, trades, tick, side)
    en, em = bucket_edges(r["n"]), bucket_edges(r["m"])
    r["nb"] = np.searchsorted(en, r["n"], side="right")
    r["mb"] = np.searchsorted(em, r["m"], side="right")
    pooled_size = {k: float(r.loc[r["kind"] == k, "size"].mean()) if (r["kind"] == k).any() else 1.0 for k in KINDS}
    pooled_rate = {k: float((r["kind"] == k).sum() / max(r["dt"].sum(), 1e-9)) for k in KINDS}
    cells = {}
    for nb in range(4):
        for mb in range(4):
            g = r[(r["nb"] == nb) & (r["mb"] == mb)]
            sec = float(g["dt"].sum())
            n_rep = float(g["n"].median()) if len(g) else float(np.median(r["n"]))
            if sec <= 0:
                cells[(nb, mb)] = Cell(0.0, dict(pooled_rate), dict(pooled_size), n_rep)
                continue
            rates = {k: float((g["kind"] == k).sum() / sec) for k in KINDS}
            sizes = {k: float(g.loc[g["kind"] == k, "size"].mean()) if (g["kind"] == k).any() else pooled_size[k] for k in KINDS}
            cells[(nb, mb)] = Cell(sec, rates, sizes, n_rep)
    return QueueChain(en, em, cells)


@dataclass(frozen=True)
class CancelModel:
    """Where a cancelled quantity sat relative to our order. ``QueueSim`` calls ``shrink`` when the
    displayed size at our price falls and no trade explains it."""
    assumption: str = "proportional"

    def __post_init__(self):
        if self.assumption not in ASSUMPTIONS:
            raise ValueError(f"assumption must be one of {ASSUMPTIONS}")

    def shrink(self, queue_ahead: float, size_before: float, size_after: float) -> float:
        cancelled = max(size_before - size_after, 0.0)
        if self.assumption == "front":
            return max(queue_ahead - cancelled, 0.0)
        if self.assumption == "proportional":
            return max(queue_ahead - cancelled * queue_ahead / size_before, 0.0) if size_before > 0 else queue_ahead
        return queue_ahead


def calibration(pred, filled, tol: float = 0.05) -> dict:
    """Task 14 pass rule: deciles of predicted p_fill; realised fill frequency within ``tol`` of the mean
    prediction in at least 8 of 10 deciles."""
    pred, filled = np.asarray(pred, float), np.asarray(filled, float)
    order = np.argsort(pred, kind="stable")
    rows = []
    for g in np.array_split(order, 10):
        rows.append({"pred": float(pred[g].mean()), "real": float(filled[g].mean()), "n": int(len(g))})
    within = sum(abs(r["pred"] - r["real"]) <= tol for r in rows)
    return {"deciles": rows, "n_within": int(within), "pass": bool(within >= 8)}
