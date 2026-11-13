"""Day 9: Avellaneda-Stoikov with defences against informed traders.

``ProtectedAS`` quotes exactly like ``mm.strategy.quote`` (same reservation price, spread,
rounding and inventory cap; a test checks they agree) and adds two optional defences:

  lean        shift both quotes by the predicted short-term move (mm.flow alpha model).
              If buyers are pushing, the ask moves up (harder to be picked off) and the
              bid moves up too (we are happier to buy). This is the A-S model with a drift
              term: r = s + alpha - q * gamma * sigma^2 * (T - t).
  kill switch stop quoting while the market is in a burst (vol ratio above ``vol_cap``)
              and for ``cooldown_s`` seconds after a sweep (a trade reaching more than
              ``sweep_z`` normal bar-moves beyond the mid). Missing the next fill is cheaper
              than being on the wrong side of an informed order.

All A-S terms are precomputed as arrays in ``prepare`` (one pass over the day), which makes
walk-forward testing across many coins and days fast.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from mm.strategy import _round_quotes


@dataclass
class ProtectedAS:
    gamma: float
    k: float
    horizon_s: float = 3600.0
    q_max: Optional[float] = 10.0
    tick: Optional[float] = None
    alpha_bp: Optional[np.ndarray] = None      # per-bar predicted move (bp), past-only
    lean: float = 1.0
    vol_ratio: Optional[np.ndarray] = None     # per-bar, from mm.flow.flow_features
    sweep_z: Optional[np.ndarray] = None
    vol_cap: float = 3.0
    sweep_cap: float = 8.0
    cooldown_s: float = 5.0
    bar_ms: int = 100
    fixed_half: Optional[float] = None         # if set: fixed-spread quoter (no inventory skew) with the same defences
    name: str = "Protected A-S"
    _c: np.ndarray = field(default=None, repr=False)
    _half: np.ndarray = field(default=None, repr=False)
    _shift: np.ndarray = field(default=None, repr=False)
    _pause: np.ndarray = field(default=None, repr=False)

    def prepare(self, bars: pd.DataFrame) -> None:
        sig = bars["sigma"].to_numpy(float)
        t_in = bars["t_s"].to_numpy(float) % self.horizon_s
        tau = np.maximum(self.horizon_s - t_in, 0.0)
        if self.fixed_half is not None:
            self._c = np.zeros(len(sig))
            self._half = np.full(len(sig), float(self.fixed_half))
        else:
            self._c = self.gamma * sig ** 2 * tau                       # reservation shift per lot
            liq = (2.0 / self.gamma) * math.log1p(self.gamma / self.k)
            self._half = (self._c + liq) / 2.0
        mid = bars["mid"].to_numpy(float)
        self._shift = (self.lean * np.nan_to_num(self.alpha_bp) * mid * 1e-4
                       if self.alpha_bp is not None else np.zeros(len(mid)))
        pause = np.zeros(len(mid), dtype=bool)
        if self.vol_ratio is not None:
            pause |= np.asarray(self.vol_ratio) > self.vol_cap
        if self.sweep_z is not None:
            hit = (np.asarray(self.sweep_z) > self.sweep_cap).astype(float)
            w = max(int(self.cooldown_s * 1000 / self.bar_ms), 1)
            pause |= pd.Series(hit).rolling(w, min_periods=1).max().to_numpy() > 0
        self._pause = pause

    def quote_at(self, i: int, mid: float, q: float, t_s: float, sigma: float):
        if self._pause[i]:
            return (mid, mid, False, False)
        r = mid + self._shift[i] - q * self._c[i]
        bid, ask = r - self._half[i], r + self._half[i]
        if self.tick:
            bid, ask = _round_quotes(bid, ask, self.tick)
        cap = self.q_max
        return bid, ask, (cap is None or q < cap), (cap is None or q > -cap)

    def quote(self, mid, q, t_s, sigma):           # protocol fallback, used only without prepare()
        raise RuntimeError("ProtectedAS needs prepare(bars); run it through mm.backtest.run_backtest")

    @property
    def paused_share(self) -> float:
        return float(self._pause.mean()) if self._pause is not None else 0.0
