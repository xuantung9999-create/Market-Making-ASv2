"""Avellaneda-Stoikov (2008) quoting core.

One pure function, ``quote``, is shared by the simulator, the backtester and
the paper trader, so every part of the project uses identical strategy logic.

Units: choose them once and keep them consistent (see notes/derivation.md, s.7).
  time  -> seconds (or the paper's unit horizon, T = 1)
  price -> quote currency (USDT)
  q     -> base units (BTC)
  sigma -> price units per sqrt(time unit)
  k     -> 1 / price units
  gamma -> 1 / (price units * base units)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass(frozen=True)
class ASParams:
    gamma: float                      # risk aversion (> 0)
    sigma: float                      # volatility of mid (>= 0)
    k: float                          # fill-intensity decay with distance (> 0)
    A: float = 140.0                  # base fill intensity (fills per time unit)
    T: float = 1.0                    # horizon end, in time units
    tick_size: Optional[float] = None # round quotes to this grid if set
    q_max: Optional[float] = None     # stop quoting the side that increases |q| past this

    def __post_init__(self) -> None:
        if not self.gamma > 0:
            raise ValueError("gamma must be > 0")
        if not self.sigma >= 0:
            raise ValueError("sigma must be >= 0")
        if not self.k > 0:
            raise ValueError("k must be > 0")
        if not self.A >= 0:
            raise ValueError("A must be >= 0")
        if not self.T > 0:
            raise ValueError("T must be > 0")
        if self.tick_size is not None and not self.tick_size > 0:
            raise ValueError("tick_size must be > 0")
        if self.q_max is not None and not self.q_max > 0:
            raise ValueError("q_max must be > 0")


@dataclass(frozen=True)
class Quote:
    bid: float
    ask: float
    reservation: float
    spread: float          # theoretical (pre-rounding) total spread
    bid_active: bool = True
    ask_active: bool = True


def time_left(t, p: ASParams):
    """tau = T - t, floored at 0 so quotes stay defined after the horizon."""
    return np.maximum(p.T - np.asarray(t, dtype=float), 0.0)


def reservation_price(s, q, t, p: ASParams):
    """r = s - q * gamma * sigma^2 * (T - t). Works on scalars or numpy arrays."""
    tau = time_left(t, p)
    return np.asarray(s, dtype=float) - np.asarray(q, dtype=float) * p.gamma * p.sigma**2 * tau


def liquidity_term(p: ASParams) -> float:
    """(2/gamma) * ln(1 + gamma/k): the order-flow part of the spread."""
    # log1p keeps precision when gamma/k is tiny (limit -> 2/k as gamma -> 0)
    return (2.0 / p.gamma) * math.log1p(p.gamma / p.k)


def optimal_spread(t, p: ASParams):
    """delta_a + delta_b = gamma * sigma^2 * (T - t) + (2/gamma) ln(1 + gamma/k)."""
    tau = time_left(t, p)
    return p.gamma * p.sigma**2 * tau + liquidity_term(p)


def fill_intensity(delta, p: ASParams):
    """lambda(delta) = A * exp(-k * delta): fills per time unit at distance delta from mid."""
    return p.A * np.exp(-p.k * np.asarray(delta, dtype=float))


def _round_quotes(bid: float, ask: float, tick: float) -> tuple[float, float]:
    """Round bid down and ask up (never quote tighter than the model), keep >= 1 tick apart."""
    # small epsilon so values already on the grid are not pushed a full tick out
    eps = 1e-9
    bid_r = math.floor(bid / tick + eps) * tick
    ask_r = math.ceil(ask / tick - eps) * tick
    if ask_r - bid_r < tick - eps:
        ask_r = bid_r + tick
    # tidy float noise, e.g. 98.85000000000001 -> 98.85
    decimals = max(0, -int(math.floor(math.log10(tick))) + 2)
    return round(bid_r, decimals), round(ask_r, decimals)


def quote(s: float, q: float, t: float, p: ASParams) -> Quote:
    """Optimal A-S bid/ask for mid ``s``, inventory ``q`` at time ``t``."""
    r = float(reservation_price(s, q, t, p))
    spread = float(optimal_spread(t, p))
    bid, ask = r - spread / 2.0, r + spread / 2.0

    if p.tick_size is not None:
        bid, ask = _round_quotes(bid, ask, p.tick_size)

    bid_active = ask_active = True
    if p.q_max is not None:
        bid_active = q < p.q_max      # long at the limit: stop buying
        ask_active = q > -p.q_max     # short at the limit: stop selling

    return Quote(bid=bid, ask=ask, reservation=r, spread=spread,
                 bid_active=bid_active, ask_active=ask_active)


# Parameters used in the original paper's simulations (Avellaneda & Stoikov 2008, s.4)
PAPER_PARAMS = ASParams(gamma=0.1, sigma=2.0, k=1.5, A=140.0, T=1.0)
