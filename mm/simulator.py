"""Day 3-4: synthetic market to replicate Avellaneda & Stoikov (2008), section 4.

The market is exactly the one the model assumes, so this is where the strategy
*should* work. If it doesn't work here, it won't work on real data.

Each time step of length dt:
  1. The market maker posts a bid and an ask (inventory or symmetric strategy).
  2. Each quote is filled with probability  lambda(delta) * dt = A e^{-k delta} dt,
     where delta is the quote's distance from mid. One unit per fill.
  3. The mid moves  s -> s +/- sigma * sqrt(dt)  (fair coin, as in the paper).

Profit is marked to market at the horizon:  PnL_T = cash_T + q_T * s_T.

Everything is vectorised over paths, so one call runs the whole Monte Carlo.
Both strategies can be run on the same random numbers (``seed``) so their
difference comes from the strategy, not from luck (common random numbers).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np
import pandas as pd

from mm.strategy import ASParams, optimal_spread, reservation_price

Strategy = Literal["inventory", "symmetric"]


@dataclass(frozen=True)
class SimConfig:
    s0: float = 100.0
    dt: float = 0.005                 # paper: 200 steps over T = 1
    n_paths: int = 1
    q0: float = 0.0
    x0: float = 0.0
    seed: int | None = 0
    price: Literal["binomial", "gaussian"] = "binomial"


@dataclass
class SimResult:
    """Arrays are shaped (n_paths, n_steps + 1); column i is time t[i]."""
    strategy: str
    t: np.ndarray
    s: np.ndarray            # mid
    r: np.ndarray            # reservation price (what the inventory strategy centres on)
    bid: np.ndarray
    ask: np.ndarray
    q: np.ndarray            # inventory
    x: np.ndarray            # cash
    bid_fills: np.ndarray    # bool, fill at step i (last column always False)
    ask_fills: np.ndarray

    @property
    def pnl(self) -> np.ndarray:
        """Mark-to-market wealth x + q*s at every step."""
        return self.x + self.q * self.s

    @property
    def final_pnl(self) -> np.ndarray:
        return self.pnl[:, -1]

    def summary(self) -> dict:
        """The columns of the paper's results tables."""
        spread = (self.ask - self.bid)[:, :-1]
        fp, fq = self.final_pnl, self.q[:, -1]
        return {
            "strategy": self.strategy,
            "avg_spread": spread.mean(),
            "mean_pnl": fp.mean(),
            "std_pnl": fp.std(ddof=1) if fp.size > 1 else 0.0,
            "mean_final_q": fq.mean(),
            "std_final_q": fq.std(ddof=1) if fq.size > 1 else 0.0,
            "fills_per_path": (self.bid_fills.sum() + self.ask_fills.sum()) / fp.size,
        }


def simulate(p: ASParams, cfg: SimConfig = SimConfig(), strategy: Strategy = "inventory") -> SimResult:
    """Run ``cfg.n_paths`` paths of the A-S market with the chosen quoting strategy.

    inventory : quotes centred on the reservation price r (the A-S optimum).
    symmetric : same spread, but centred on the mid. This is the paper's benchmark;
                it ignores inventory.
    """
    if strategy not in ("inventory", "symmetric"):
        raise ValueError(f"unknown strategy {strategy!r}")

    n_steps = int(round(p.T / cfg.dt))
    n = cfg.n_paths
    t = np.arange(n_steps + 1) * cfg.dt
    rng = np.random.default_rng(cfg.seed)

    # Draw every random number up front, in a fixed order. Same seed -> same
    # price path and same fill coins for both strategies.
    if cfg.price == "binomial":
        dS = cfg.dt ** 0.5 * p.sigma * rng.choice([-1.0, 1.0], size=(n, n_steps))
    else:
        dS = cfg.dt ** 0.5 * p.sigma * rng.standard_normal((n, n_steps))
    u_bid = rng.random((n, n_steps))
    u_ask = rng.random((n, n_steps))

    shape = (n, n_steps + 1)
    s, r, bid, ask, q, x = (np.empty(shape) for _ in range(6))
    bid_fills = np.zeros(shape, dtype=bool)
    ask_fills = np.zeros(shape, dtype=bool)
    s[:, 0], q[:, 0], x[:, 0] = cfg.s0, cfg.q0, cfg.x0

    for i in range(n_steps + 1):
        # 1. quote
        r[:, i] = reservation_price(s[:, i], q[:, i], t[i], p)
        half = optimal_spread(t[i], p) / 2.0
        centre = r[:, i] if strategy == "inventory" else s[:, i]
        bid[:, i], ask[:, i] = centre - half, centre + half
        if i == n_steps:
            break

        # 2. fills: P(fill in dt) = lambda(delta) * dt, capped at 1.
        #    delta can be negative when a big skew pushes a quote through the mid;
        #    then the quote fills almost surely, which is what you'd expect.
        d_bid = s[:, i] - bid[:, i]
        d_ask = ask[:, i] - s[:, i]
        p_bid = np.minimum(p.A * np.exp(-p.k * d_bid) * cfg.dt, 1.0)
        p_ask = np.minimum(p.A * np.exp(-p.k * d_ask) * cfg.dt, 1.0)
        hit_bid = u_bid[:, i] < p_bid
        lift_ask = u_ask[:, i] < p_ask
        if p.q_max is not None:                  # hard inventory limit
            hit_bid &= q[:, i] < p.q_max
            lift_ask &= q[:, i] > -p.q_max

        bid_fills[:, i], ask_fills[:, i] = hit_bid, lift_ask
        q[:, i + 1] = q[:, i] + hit_bid - lift_ask
        x[:, i + 1] = x[:, i] - hit_bid * bid[:, i] + lift_ask * ask[:, i]

        # 3. mid moves
        s[:, i + 1] = s[:, i] + dS[:, i]

    return SimResult(strategy, t, s, r, bid, ask, q, x, bid_fills, ask_fills)


def compare(p: ASParams, cfg: SimConfig) -> pd.DataFrame:
    """Inventory vs symmetric on identical random numbers: one row per strategy."""
    rows = [simulate(p, cfg, st).summary() for st in ("inventory", "symmetric")]
    df = pd.DataFrame(rows)
    df.insert(0, "gamma", p.gamma)
    return df


def paper_table(gammas=(0.01, 0.1, 0.5), n_paths: int = 1000, seed: int = 0,
                sigma: float = 2.0, k: float = 1.5, A: float = 140.0) -> pd.DataFrame:
    """The paper's Monte Carlo experiment: both strategies for each gamma."""
    cfg = SimConfig(n_paths=n_paths, seed=seed)
    frames = [compare(ASParams(gamma=g, sigma=sigma, k=k, A=A, T=1.0), cfg) for g in gammas]
    return pd.concat(frames, ignore_index=True)
