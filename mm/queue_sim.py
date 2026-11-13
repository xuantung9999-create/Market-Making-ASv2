"""v2 Task 3: the queue-aware market-making engine (spec: docs/BUILD_GUIDE.md section 5).

v1 filled an order whenever a trade printed through (or touched) its price. On a
tick-constrained coin that misses the point: the spread is one tick, everybody quotes the
same two prices, and what decides whether you get filled is your PLACE IN THE QUEUE at that
price. This engine models exactly that, with one resting order per side:

  * Decisions on a timer grid (every ``decision_ms``). The policy says, per side, JOIN (rest
    at the best price), BACK (one tick behind) or OUT.
  * Every new order or cancel reaches the exchange ``latency_ms`` later; until then the old
    order can still be filled.
  * A new order at the best price joins the BACK of the displayed queue
    (``queue_ahead = queue_mult * displayed size``); one that improves the best is first;
    one behind the best waits behind ``back_queue_mult * displayed size``.
  * A trade at our price eats the queue ahead of us; when it reaches zero we are filled in
    full. A trade through our price fills us at once. No partial fills.
  * Other traders' cancels are not modelled, except that the queue ahead of us can never be
    longer than what the book displays at our price.

The same engine runs the historical backtest, the walk-forward agent and the paper trader,
so a result in one is a result in the others.

P&L identity (exact, checked in tests), everything marked to the tape mid (bid + ask) / 2:
    total = spread capture + inventory P&L - fees
    spread capture = sum over fills of side * qty * (mid at fill - fill price)
    inventory P&L  = sum over mid changes of position * (new mid - old mid)

Prices are compared as integer tick counts, never with float equality.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Mapping, Optional, Protocol

import numpy as np
import pandas as pd

from mm.tape import merge_events

MINUTE_US = 60_000_000


class Action(IntEnum):
    OUT = 0
    JOIN = 1
    BACK = 2


@dataclass(frozen=True)
class MarketState:
    ts_us: int
    bid: float
    ask: float
    bid_qty: float
    ask_qty: float
    tick: float
    feat: Mapping[str, float]


class Policy(Protocol):
    name: str
    def decide(self, st: MarketState, q: int) -> tuple[Action, Action]: ...   # (bid, ask)


@dataclass(frozen=True)
class QSConfig:
    lot_usd: float = 100.0
    q_max: Optional[int] = 10
    maker_fee_bps: float = 10.0
    latency_ms: int = 300
    decision_ms: int = 1000
    queue_mult: float = 1.0
    back_queue_mult: float = 1.0
    warmup_s: float = 600.0
    stale_s: Optional[float] = None
    markouts_s: tuple = (1, 10, 60, 300)


@dataclass
class JoinTouch:
    """Always rest at the best bid and the best ask."""
    name: str = "Join touch"

    def decide(self, st: MarketState, q: int) -> tuple[Action, Action]:
        return Action.JOIN, Action.JOIN


@dataclass
class Fixed:
    """Always the same pair of actions (shadow learners and tests)."""
    bid: Action
    ask: Action
    name: str = "Fixed"

    def decide(self, st: MarketState, q: int) -> tuple[Action, Action]:
        return self.bid, self.ask


@dataclass
class Order:
    side: int                 # +1 bid, -1 ask
    k: int                    # price in ticks
    price: float
    qty: float
    queue_ahead: float
    live_from_us: int
    action: Action
    feat: Mapping[str, float]
    last_disp: float = 0.0     # displayed size at our price at the last book update (cancel model)


@dataclass
class _Pending:
    at_us: int
    k: Optional[int]          # None = cancel only
    qty: float
    action: Action
    feat: Mapping[str, float]


@dataclass
class QSResult:
    name: str
    cfg: QSConfig
    minute: pd.DataFrame
    fills: pd.DataFrame
    totals: dict = field(default_factory=dict)
    markouts: pd.DataFrame = field(default_factory=pd.DataFrame)


MINUTE_COLUMNS = ["t_s", "mid", "pnl", "q", "spread_capture", "inventory_pnl", "fees", "ts_us"]
BASE_FILL_COLUMNS = ["bar", "t_s", "side", "price", "ts_us", "qty", "mid", "wait_s", "action", "net_edge_bp"]


class QueueSim:
    """Event-driven engine. Feed it ``on_book`` / ``on_trade`` / ``on_timer`` in time order,
    call ``end_day`` at each UTC day end, read ``result()``. ``q`` (lots) and ``pnl`` (USDT,
    marked to mid) are live attributes.

    ``features``: any object with on_book / on_trade / snapshot(ts_us). With
    ``feed_features=True`` (default) the engine forwards every event to it; set False when
    the caller feeds one shared feature engine to several simulators itself."""

    def __init__(self, policy: Policy, cfg: QSConfig, tick: float, features=None, feed_features: bool = True,
                 cancel_model=None, feat_extra=None):
        self.policy, self.cfg, self.tick = policy, cfg, float(tick)
        self.features, self._feed = features, bool(feed_features and features is not None)
        self._skip_idle = True                     # private: skip timers with nothing new (speed only)
        self.q = 0
        self.feat_extra = feat_extra               # optional callable(ts, bid_qty, ask_qty) -> dict merged into the decision features
        self.cancel_model = cancel_model           # None: today's behaviour (cancels only cap the queue)
        self._last_trade: dict[int, Optional[tuple]] = {1: None, -1: None}   # resting side -> (ts, price tick)
        self._pos = self._cash = self._spread = self._inv = self._fees = self._notional = 0.0
        self.orders: dict[int, Optional[Order]] = {1: None, -1: None}
        self._pending: dict[int, Optional[_Pending]] = {1: None, -1: None}
        self._book = None                          # (bid_k, ask_k, bid_qty, ask_qty)
        self._mid: Optional[float] = None
        self._t0: Optional[int] = None
        self._last_ts: Optional[int] = None
        self._next_min: Optional[int] = None
        self._day_start: Optional[int] = None
        self._last_event: Optional[int] = None
        self._event_since = False
        self._forced = True                        # last decision was not a normal policy call
        self._fills: list[dict] = []
        self._minute: list[tuple] = []
        self._mid_ts: list[int] = []
        self._mid_val: list[float] = []
        self._up = {1: 0.0, -1: 0.0}               # microseconds with a resting order, after warm-up
        self._elig = 0.0                           # microseconds after warm-up
        self._day = 0
        self._day_ends: list[int] = []
        self._day_marks: list[tuple[int, dict]] = [(0, self._cum())]   # (first minute row, totals at day start)

    # ------------------------------------------------------------------ live values
    @property
    def pnl(self) -> float:
        return self._cash + self._pos * (self._mid or 0.0) - self._fees

    def _cum(self) -> dict:
        return {"pnl": self.pnl, "spread_capture": self._spread, "inventory_pnl": self._inv,
                "fees": self._fees, "notional": self._notional,
                "_up_bid": self._up[1], "_up_ask": self._up[-1], "_elig": self._elig}

    def _row(self) -> tuple:
        t = 0.0 if self._t0 is None else (self._last_ts - self._t0) / 1e6
        return (t, self._mid if self._mid is not None else np.nan, self.pnl, self.q,
                self._spread, self._inv, self._fees, self._last_ts)

    # ------------------------------------------------------------------ event plumbing
    def _enter(self, ts_us: int) -> int:
        ts = int(ts_us)
        if self._last_ts is not None and ts < self._last_ts:
            ts = self._last_ts                     # out-of-order event: process at the last time
        if self._t0 is None:
            self._t0 = ts
        if self._day_start is None:
            self._day_start = ts
        elif self._last_ts is not None:
            start = max(self._last_ts, self._day_start + int(self.cfg.warmup_s * 1e6))
            if ts > start:                         # uptime: time after warm-up with a resting order
                self._elig += ts - start
                for side in (1, -1):
                    if self.orders[side] is not None:
                        self._up[side] += ts - start
        if self._next_min is None:
            self._next_min = (ts // MINUTE_US + 1) * MINUTE_US
        elif ts >= self._next_min:
            if self._mid is not None:              # no row before the day's first book update
                self._minute.append(self._row())
            self._next_min = (ts // MINUTE_US + 1) * MINUTE_US
        self._last_ts = ts
        self._activate_due(ts)
        return ts

    def _event(self, ts: int) -> None:
        self._last_event = ts
        self._event_since = True

    def on_book(self, ts_us, bid, ask, bid_qty, ask_qty) -> None:
        ts = self._enter(ts_us)
        self._event(ts)
        bk, ak = int(round(bid / self.tick)), int(round(ask / self.tick))
        self._book = (bk, ak, float(bid_qty), float(ask_qty))
        mid = (bid + ask) / 2.0
        if self._mid is not None and mid != self._mid:
            self._inv += self._pos * (mid - self._mid)
        if self._mid is None or mid != self._mid:
            self._mid_ts.append(ts); self._mid_val.append(mid)
        self._mid = mid
        if self._feed:
            self.features.on_book(ts, bid, ask, bid_qty, ask_qty)
        o = self.orders[1]
        if o is not None and o.k == bk:
            self._cancel_step(o, ts, float(bid_qty))
            o.queue_ahead = min(o.queue_ahead, self.cfg.queue_mult * float(bid_qty))
        o = self.orders[-1]
        if o is not None and o.k == ak:
            self._cancel_step(o, ts, float(ask_qty))
            o.queue_ahead = min(o.queue_ahead, self.cfg.queue_mult * float(ask_qty))

    def _cancel_step(self, o: Order, ts: int, new_disp: float) -> None:
        """A fall in the displayed size at our price with no trade at it in the last 50 ms is a cancel;
        the cancel model decides how much of it came out of the queue ahead of us."""
        prev = o.last_disp
        o.last_disp = new_disp
        if self.cancel_model is None or new_disp >= prev:
            return
        lt = self._last_trade[o.side]
        if lt is not None and lt[1] == o.k and ts - lt[0] <= 50_000:
            return                                                   # explained by a trade
        o.queue_ahead = self.cancel_model.shrink(o.queue_ahead, prev, new_disp)

    def on_trade(self, ts_us, price, qty, side) -> list:
        ts = self._enter(ts_us)
        self._event(ts)
        if self._feed:
            self.features.on_trade(ts, price, qty, side)
        k = int(round(price / self.tick))
        self._last_trade[1 if side < 0 else -1] = (ts, k)
        fills = []
        if side < 0:                              # seller aggressor hits bids
            o = self.orders[1]
            if o is not None:
                if k < o.k:
                    fills.append(self._fill(o, ts))
                elif k == o.k:
                    o.queue_ahead -= float(qty)
                    if o.queue_ahead <= 0:
                        fills.append(self._fill(o, ts))
        else:                                     # buyer aggressor lifts asks
            o = self.orders[-1]
            if o is not None:
                if k > o.k:
                    fills.append(self._fill(o, ts))
                elif k == o.k:
                    o.queue_ahead -= float(qty)
                    if o.queue_ahead <= 0:
                        fills.append(self._fill(o, ts))
        return fills

    def on_timer(self, ts_us) -> None:
        ts = self._enter(ts_us)
        cfg = self.cfg
        if cfg.stale_s is not None and self._last_event is not None and ts - self._last_event > cfg.stale_s * 1e6:
            self._apply(ts, Action.OUT, Action.OUT, {})
            self._forced, self._event_since = True, False
            self._activate_due(ts)
            return
        if (self._skip_idle and not self._event_since and not self._forced
                and self._pending[1] is None and self._pending[-1] is None):
            return
        self._event_since = False
        if self._book is None or ts - self._day_start < cfg.warmup_s * 1e6:
            self._apply(ts, Action.OUT, Action.OUT, {})
            self._forced = True
        else:
            bk, ak, bq, aq = self._book
            feat = dict(self.features.snapshot(ts)) if self.features is not None else {}
            if self.feat_extra is not None:
                feat.update(self.feat_extra(ts, bq, aq))
            st = MarketState(ts, bk * self.tick, ak * self.tick, bq, aq, self.tick, feat)
            a_bid, a_ask = self.policy.decide(st, self.q)
            self._apply(ts, Action(a_bid), Action(a_ask), feat)
            self._forced = False
        self._activate_due(ts)

    # ------------------------------------------------------------------ orders
    def _capped(self, side: int) -> bool:
        qm = self.cfg.q_max
        return qm is not None and (self.q >= qm if side > 0 else self.q <= -qm)

    def _apply(self, ts: int, a_bid: Action, a_ask: Action, feat) -> None:
        for side, a in ((1, a_bid), (-1, a_ask)):
            if self._capped(side):
                a = Action.OUT
            self._target(ts, side, a, feat)

    def _target(self, ts: int, side: int, action: Action, feat) -> None:
        if action == Action.OUT or self._book is None:
            k = None
        else:
            bk, ak = self._book[0], self._book[1]
            best = bk if side > 0 else ak
            k = best if action == Action.JOIN else best - side      # BACK: one tick further from mid
        o, p = self.orders[side], self._pending[side]
        if p is not None and p.k == k:
            p.feat, p.action = feat, action
            return
        if k == (o.k if o is not None else None):
            self._pending[side] = None
            if o is not None:
                o.feat, o.action = feat, action
            return
        qty = self.cfg.lot_usd / self._mid if self._mid else 0.0
        self._pending[side] = _Pending(ts + int(self.cfg.latency_ms) * 1000, k, qty, action, feat)

    def _activate_due(self, ts: int) -> None:
        for side in (1, -1):
            p = self._pending[side]
            if p is None or p.at_us > ts:
                continue
            self._pending[side] = None
            self.orders[side] = None
            if p.k is None or self._book is None:
                continue
            bk, ak, bq, aq = self._book
            if (side > 0 and p.k >= ak) or (side < 0 and p.k <= bk):
                continue                                         # post-only: would cross, rejected
            best, disp = (bk, bq) if side > 0 else (ak, aq)
            if p.k == best:
                qa = self.cfg.queue_mult * disp
            elif (p.k - best) * side > 0:
                qa = 0.0                                         # improves the best: first in line
            else:
                qa = self.cfg.back_queue_mult * disp
            self.orders[side] = Order(side, p.k, p.k * self.tick, p.qty, qa, p.at_us, p.action, p.feat,
                                      float(disp) if p.k == best else 0.0)

    def _fill(self, o: Order, ts: int) -> dict:
        side, px, qty, mid = o.side, o.price, o.qty, self._mid
        self.orders[side] = None
        self.q += side
        self._pos += side * qty
        self._cash -= side * px * qty
        fee = px * qty * self.cfg.maker_fee_bps / 1e4
        self._fees += fee
        self._notional += px * qty
        self._spread += side * qty * (mid - px)
        for s in (1, -1):                                        # inventory cap: cancel at once
            if self._capped(s):
                self.orders[s] = None
                self._pending[s] = None
        f = {"bar": len(self._fills), "t_s": (ts - self._t0) / 1e6, "side": side, "price": px,
             "ts_us": ts, "qty": qty, "mid": mid, "wait_s": (ts - o.live_from_us) / 1e6,
             "action": int(o.action), "_day": self._day, **{f"f_{k}": v for k, v in o.feat.items()}}
        self._fills.append(f)
        return f

    # ------------------------------------------------------------------ day / results
    def end_day(self) -> None:
        """Cancel everything, flatten inventory at the last mid, start a fresh day."""
        self.orders = {1: None, -1: None}
        self._pending = {1: None, -1: None}
        if self._last_ts is None:
            return
        if self._mid is not None:
            self._cash += self._pos * self._mid
        self._pos = 0.0
        self.q = 0
        if self._mid is not None:
            self._minute.append(self._row())
        self._day_ends.append(self._last_ts)
        self._day += 1
        self._day_marks.append((len(self._minute), self._cum()))
        self._book, self._mid = None, None
        self._day_start, self._last_event = None, None
        self._next_min = None
        self._event_since, self._forced = False, True

    def _mid_at(self, ts: int, mts: np.ndarray, mval: np.ndarray) -> float:
        j = np.searchsorted(mts, ts, side="right") - 1
        return float(mval[j]) if j >= 0 else float("nan")

    def result(self, day: Optional[int] = None) -> QSResult:
        """All days so far, or only day ``day`` (0 = first ``end_day`` period), with that day's
        P&L, fills, markouts and minute rows (P&L columns rebased to 0 at the day's start)."""
        cfg = self.cfg
        mts, mval = np.array(self._mid_ts, dtype=np.int64), np.array(self._mid_val, float)
        ends = list(self._day_ends) + ([self._last_ts] if self._last_ts is not None else [])
        src = self._fills if day is None else [f for f in self._fills if f["_day"] == day]
        fills = pd.DataFrame([{k: v for k, v in f.items() if not k.startswith("_")} for f in src])
        if fills.empty:
            fills = pd.DataFrame(columns=BASE_FILL_COLUMNS)
        hs = (0,) + tuple(cfg.markouts_s)
        mk_cols = {}
        for h in hs:
            vals = []
            for f in src:
                t = f["ts_us"] + int(h * 1e6)
                if t > ends[f["_day"]]:
                    vals.append(np.nan)
                else:
                    vals.append(f["side"] * (self._mid_at(t, mts, mval) - f["price"]) / f["price"] * 1e4)
            mk_cols[h] = np.array(vals, float)
        if len(src):
            mk60 = mk_cols[60] if 60 in mk_cols else np.array([np.nan] * len(src))
            fills["net_edge_bp"] = mk60 - cfg.maker_fee_bps
            for h in cfg.markouts_s:
                fills[f"mk_{h:g}"] = mk_cols[h]
        rows = []
        for h in hs:
            v = mk_cols[h][~np.isnan(mk_cols[h])] if len(src) else np.array([])
            mean = float(v.mean()) if v.size else float("nan")
            se = float(v.std(ddof=1) / math.sqrt(v.size)) if v.size > 1 else float("nan")
            rows.append((h, mean, se))
        markouts = pd.DataFrame(rows, columns=["h_s", "markout_bp", "se_bp"])
        minute = pd.DataFrame(self._minute, columns=MINUTE_COLUMNS)
        totals = {**self._cum(), "final_q": self.q}
        if day is not None:
            i0, c0 = self._day_marks[day] if day < len(self._day_marks) else (len(self._minute), self._cum())
            i1, c1 = self._day_marks[day + 1] if day + 1 < len(self._day_marks) else (len(self._minute), self._cum())
            minute = minute.iloc[i0:i1].reset_index(drop=True)
            for k in ("pnl", "spread_capture", "inventory_pnl", "fees"):
                minute[k] = minute[k] - c0[k]
            totals = {k: c1[k] - c0[k] for k in c0}
            totals["final_q"] = 0 if day + 1 < len(self._day_marks) else self.q
        el = totals.pop("_elig")
        ub, ua = totals.pop("_up_bid"), totals.pop("_up_ask")
        totals["uptime"] = {"bid": ub / el if el > 0 else 0.0, "ask": ua / el if el > 0 else 0.0}
        return QSResult(self.policy.name, cfg, minute, fills, totals, markouts)


def _drive(sim, tape: pd.DataFrame, trades: pd.DataFrame, decision_ms: int) -> None:
    """Feed one day of events to anything with on_book / on_trade / on_timer."""
    for kind, x in merge_events(tape, trades, decision_ms):
        if kind == "book":
            sim.on_book(*x)
        elif kind == "trade":
            sim.on_trade(*x)
        else:
            sim.on_timer(x)


def run_queue_sim(tape, trades, policy, cfg: QSConfig, tick: float, features=None) -> QSResult:
    """One UTC day through a fresh engine."""
    sim = QueueSim(policy, cfg, tick, features)
    _drive(sim, tape, trades, cfg.decision_ms)
    sim.end_day()
    return sim.result()
