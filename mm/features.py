"""v2 Task 4: market features computed one event at a time, from the past only.

These are the inputs the edge table (Task 5) conditions on. Each is updated in O(1) per
event and read with ``snapshot(ts_us)``; nothing ever looks at an event later than the
snapshot time, so the same code serves the backtest and the live paper trader.

  book_imb      (bid_qty - ask_qty) / (bid_qty + ask_qty): which side of the book is heavier
  micro_bp      microprice minus mid, in bp. The microprice weights each side's price by the
                OTHER side's size, so it leans toward the side that is about to be eaten
  flow_5s/60s   (buy volume - sell volume) / total, each volume decayed with a 5 s / 60 s
                half-life: who has been aggressive recently
  vol_ratio     sqrt(short-term variance / long-term variance) of mid changes (10 s vs 30 min
                half-lives): above 1 means the market is moving faster than usual
  spread_ticks  (ask - bid) / tick
"""
from __future__ import annotations

import math

FEATURE_NAMES = ("book_imb", "micro_bp", "flow_5s", "flow_60s", "vol_ratio", "spread_ticks")
_FLOW_HL = (5.0, 60.0)
_VOL_HL = (10.0, 1800.0)
_VOL_WARMUP_S = 600.0


class FeatureEngine:
    def __init__(self, tick: float):
        self.tick = float(tick)
        self._book = None                 # (bid, ask, bid_qty, ask_qty)
        self._mid = None
        self._t_first = None
        self._flow = {h: [0.0, 0.0, None] for h in _FLOW_HL}      # buy, sell, last ts
        self._var = {h: [0.0, None] for h in _VOL_HL}             # decayed sum of d^2, last ts

    def _start(self, ts_us: int) -> None:
        if self._t_first is None:
            self._t_first = ts_us

    def on_book(self, ts_us, bid, ask, bid_qty, ask_qty) -> None:
        self._start(ts_us)
        self._book = (float(bid), float(ask), float(bid_qty), float(ask_qty))
        mid = (bid + ask) / 2.0
        if self._mid is not None and mid != self._mid:
            d2 = ((mid - self._mid) / self._mid * 1e4) ** 2
            for h, acc in self._var.items():
                if acc[1] is not None:
                    acc[0] *= 0.5 ** ((ts_us - acc[1]) / 1e6 / h)
                acc[0] += d2
                acc[1] = ts_us
        self._mid = mid

    def on_trade(self, ts_us, price, qty, side) -> None:
        self._start(ts_us)
        for h, acc in self._flow.items():
            if acc[2] is not None:
                dec = 0.5 ** ((ts_us - acc[2]) / 1e6 / h)
                acc[0] *= dec
                acc[1] *= dec
            acc[0 if side > 0 else 1] += float(qty)
            acc[2] = ts_us

    def _v(self, h: float, ts_us: int) -> float:
        s, last = self._var[h]
        if last is None:
            return 0.0
        return s * 0.5 ** (max(ts_us - last, 0) / 1e6 / h) / (h / math.log(2))

    def snapshot(self, ts_us) -> dict:
        out = dict.fromkeys(FEATURE_NAMES, 0.0)
        if self._book is not None:
            bid, ask, bq, aq = self._book
            tot = bq + aq
            mid = (bid + ask) / 2.0
            if tot > 0:
                out["book_imb"] = (bq - aq) / tot
                out["micro_bp"] = ((aq * bid + bq * ask) / tot - mid) / mid * 1e4
            out["spread_ticks"] = (ask - bid) / self.tick
        for h, name in zip(_FLOW_HL, ("flow_5s", "flow_60s")):
            b, s, _ = self._flow[h]
            out[name] = (b - s) / (b + s) if b + s > 0 else 0.0     # decay cancels in the ratio
        v_long = self._v(_VOL_HL[1], ts_us)
        if self._t_first is None or (ts_us - self._t_first) / 1e6 < _VOL_WARMUP_S or v_long <= 0:
            out["vol_ratio"] = 1.0
        else:
            out["vol_ratio"] = math.sqrt(self._v(_VOL_HL[0], ts_us) / v_long)
        return out
