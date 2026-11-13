"""Day 6: event-driven backtest of quoting strategies on real trade data.

Time runs on fixed bars (default 100 ms) built by ``mm.data.trades_to_bars``.

Each bar i:
  1. FILLS. The quotes that are live during bar i are checked against the trades
     printed inside bar i. Conservative rule: a bid fills only if a seller traded
     STRICTLY BELOW it (``sell_min < bid``); an ask only if a buyer traded strictly
     above it (``buy_max > ask``). Merely touching our price is not enough: there is
     usually a queue of other orders at that price ahead of us. ``fill_rule="touch"``
     also fills on an equal price: an optimistic bound, as if we were first in the queue.
     The truth lies between the two. One lot per side per bar,
     filled at our quoted price (we are the maker). A maker fee is charged on notional.
  2. QUOTE. Every ``requote_ms`` the strategy sees only what is known at the END of
     bar i (mid, its own inventory, the volatility estimate) and posts a new bid/ask.
     The new quote goes live after ``latency_ms`` (rounded up to whole bars, and never
     in the same bar it was computed in), so a quote can never react to the trades
     it is about to be filled by.

Units: price in USDT, time in seconds, inventory q in LOTS of ``lot`` BTC
(the strategy works in lots, like the paper's "one unit per fill").

Exact P&L identity, checked in tests, with everything marked to the end-of-bar mid:
    total = spread capture + inventory P&L - fees
    spread capture = sum over fills of side * lot * (mid_i - fill price)
    inventory P&L  = sum over bars of q_{i-1} * lot * (mid_i - mid_{i-1})
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional, Protocol

import numpy as np
import pandas as pd

from mm.data import trades_to_bars
from mm.strategy import ASParams, quote as as_quote


@dataclass(frozen=True)
class BTConfig:
    bar_ms: int = 100
    requote_ms: int = 500
    latency_ms: int = 50
    lot: float = 0.001                 # BTC per fill
    maker_fee_bps: float = 0.0         # charged on notional of every fill
    sigma_halflife_s: float = 1800.0   # EWMA of squared mid changes
    warmup_s: float = 600.0            # no quoting until sigma has settled
    markouts_s: tuple = (1, 5, 10, 30, 60, 120, 300)
    fill_rule: str = "through"         # "through" (pessimistic) or "touch" (optimistic)


# --------------------------------------------------------------------------- strategies
class Quoter(Protocol):
    name: str
    q_max: Optional[float]
    def quote(self, mid: float, q: float, t_s: float, sigma: float) -> tuple[float, float, bool, bool]: ...


@dataclass
class ASQuoter:
    """Avellaneda-Stoikov with a rolling horizon: T resets every ``horizon_s`` seconds
    (crypto trades 24/7, so there is no natural end of session)."""
    gamma: float
    k: float
    horizon_s: float = 3600.0
    q_max: Optional[float] = 10.0
    tick: Optional[float] = 0.01
    name: str = ""

    def __post_init__(self):
        if not self.name:
            self.name = f"A-S (γ={self.gamma:g}, k={self.k:g})"

    def quote(self, mid, q, t_s, sigma):
        t_in = t_s % self.horizon_s
        p = ASParams(gamma=self.gamma, sigma=sigma, k=self.k, T=self.horizon_s,
                     tick_size=self.tick, q_max=self.q_max)
        qt = as_quote(mid, q, t_in, p)
        return qt.bid, qt.ask, qt.bid_active, qt.ask_active


@dataclass
class FixedSpread:
    """Benchmark: symmetric quotes at mid +/- half, ignoring inventory except the hard cap."""
    half: float
    q_max: Optional[float] = 10.0
    tick: Optional[float] = 0.01
    name: str = ""

    def __post_init__(self):
        if not self.name:
            self.name = f"Fixed ±{self.half:g}"

    def quote(self, mid, q, t_s, sigma):
        bid, ask = mid - self.half, mid + self.half
        if self.tick:
            bid = math.floor(bid / self.tick + 1e-9) * self.tick
            ask = math.ceil(ask / self.tick - 1e-9) * self.tick
        cap = self.q_max
        return bid, ask, (cap is None or q < cap), (cap is None or q > -cap)


# --------------------------------------------------------------------------- data prep
def prepare_bars(trades: pd.DataFrame, cfg: BTConfig = BTConfig()) -> pd.DataFrame:
    """Bars + a past-only volatility estimate ``sigma`` in USDT per sqrt(second)."""
    bars = trades_to_bars(trades, cfg.bar_ms)
    dt_s = cfg.bar_ms / 1000.0
    d2 = bars["mid"].diff().fillna(0.0) ** 2
    hl_bars = max(cfg.sigma_halflife_s / dt_s, 1.0)
    var_bar = d2.ewm(halflife=hl_bars, adjust=True).mean()     # uses bars <= i only
    bars["sigma"] = np.sqrt(var_bar / dt_s)
    bars["t_s"] = (bars["ts_us"] - bars["ts_us"].iloc[0]) / 1e6
    bars.loc[bars["t_s"] < cfg.warmup_s, "sigma"] = np.nan
    return bars


# --------------------------------------------------------------------------- engine
@dataclass
class BTResult:
    name: str
    cfg: BTConfig
    minute: pd.DataFrame          # one row per minute: t_s, mid, pnl, q, spread, inventory, fees
    fills: pd.DataFrame           # bar, t_s, side (+1 buy, -1 sell), price
    totals: dict = field(default_factory=dict)


def run_backtest(bars: pd.DataFrame, quoter: Quoter, cfg: BTConfig = BTConfig()) -> BTResult:
    mid = bars["mid"].to_numpy(float)
    bmax = bars["buy_max"].to_numpy(float)
    smin = bars["sell_min"].to_numpy(float)
    sig = bars["sigma"].to_numpy(float)
    t_s = bars["t_s"].to_numpy(float)
    n = len(mid)

    requote_every = max(int(round(cfg.requote_ms / cfg.bar_ms)), 1)
    lat_bars = max(int(math.ceil(cfg.latency_ms / cfg.bar_ms)), 1)   # live from the NEXT bar at the earliest
    per_min = int(round(60_000 / cfg.bar_ms))
    lot, fee_rate, q_max = cfg.lot, cfg.maker_fee_bps / 1e4, quoter.q_max
    if cfg.fill_rule not in ("through", "touch"):
        raise ValueError("fill_rule must be 'through' or 'touch'")
    touch = cfg.fill_rule == "touch"

    if hasattr(quoter, "prepare"):          # quoters that precompute per-bar arrays
        quoter.prepare(bars)
    quote_at = getattr(quoter, "quote_at", None)

    q = 0.0
    cash = spread_cap = inv_pnl = fees = 0.0
    live = None          # (bid, ask, bid_on, ask_on)
    pending = None       # (activation bar, quote)
    f_bar, f_side, f_px = [], [], []
    rows = []

    for i in range(n):
        if pending is not None and i >= pending[0]:
            live, pending = pending[1], None
        m = mid[i]
        if i > 0:
            inv_pnl += q * lot * (m - mid[i - 1])

        # 1. fills against quotes live during this bar
        if live is not None:
            bid, ask, bid_on, ask_on = live
            if bid_on and (smin[i] <= bid if touch else smin[i] < bid) and (q_max is None or q < q_max):
                q += 1; cash -= bid * lot; fees += bid * lot * fee_rate
                spread_cap += lot * (m - bid)
                f_bar.append(i); f_side.append(1); f_px.append(bid)
            if ask_on and (bmax[i] >= ask if touch else bmax[i] > ask) and (q_max is None or q > -q_max):
                q -= 1; cash += ask * lot; fees += ask * lot * fee_rate
                spread_cap += lot * (ask - m)
                f_bar.append(i); f_side.append(-1); f_px.append(ask)

        # 2. requote using information up to the end of this bar
        if i % requote_every == 0 and np.isfinite(sig[i]):
            qt = quote_at(i, m, q, t_s[i], sig[i]) if quote_at else quoter.quote(m, q, t_s[i], sig[i])
            pending = (i + lat_bars, qt)
        elif not np.isfinite(sig[i]):
            live = pending = None

        if (i + 1) % per_min == 0 or i == n - 1:
            rows.append((t_s[i], m, cash + q * lot * m - fees, q, spread_cap, inv_pnl, fees))

    minute = pd.DataFrame(rows, columns=["t_s", "mid", "pnl", "q", "spread_capture", "inventory_pnl", "fees"])
    fills = pd.DataFrame({"bar": np.array(f_bar, dtype=np.int64), "side": np.array(f_side, dtype=np.int8),
                          "price": np.array(f_px, dtype=float)})
    fills["t_s"] = t_s[fills["bar"]] if len(fills) else []
    totals = {"pnl": cash + q * lot * mid[-1] - fees, "spread_capture": spread_cap,
              "inventory_pnl": inv_pnl, "fees": fees, "final_q": q,
              "notional": float((fills["price"] * lot).sum()) if len(fills) else 0.0}
    res = BTResult(quoter.name, cfg, minute, fills, totals)
    res.markouts = markouts(res, mid, cfg)
    return res


def markouts(res: BTResult, mid: np.ndarray, cfg: BTConfig) -> pd.DataFrame:
    """Per-horizon average of side * (mid at fill + h - fill price), in bp of price.
    h = 0 uses the mid at the end of the fill bar. Falling markouts = adverse selection."""
    f = res.fills
    if f.empty:
        return pd.DataFrame(columns=["h_s", "markout_bp", "se_bp"])
    hs = (0,) + tuple(cfg.markouts_s)
    out = []
    for h in hs:
        j = np.minimum(f["bar"].to_numpy() + int(round(h * 1000 / cfg.bar_ms)), len(mid) - 1)
        mk = f["side"].to_numpy() * (mid[j] - f["price"].to_numpy()) / f["price"].to_numpy() * 1e4
        se = float(mk.std(ddof=1) / np.sqrt(len(mk))) if len(mk) > 1 else float("nan")
        out.append((h, float(mk.mean()), se))
    return pd.DataFrame(out, columns=["h_s", "markout_bp", "se_bp"])
