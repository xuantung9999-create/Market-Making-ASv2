"""v2 Task 2: which coins are tick-constrained?

v1 found exactly one positive result: joining the best price on coins whose tick is large
relative to the price (about 26 bp) and whose spread is pinned at one tick. On such a coin
the spread is wider than the coin's natural volatility would make it, the queue at the best
price is the scarce resource, and a maker who is in the queue earns that wide spread.

``screen_row`` summarises several days of ``mm.calibrate.calibrate`` output for one coin
with medians (robust to one odd day) and applies three plain thresholds:

  tick_bp_med      >= 10      the tick is a meaningful share of the price
  spread_ticks_med <= 1.5     the spread is usually one tick (the book is "pinned")
  usd_volume_med   >= 100,000 enough trading that fills happen at all

The coins that pass are "the v2 universe" for every later task.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

TICK_BP_MIN = 10.0
SPREAD_TICKS_MAX = 1.5
USD_VOLUME_MIN = 100_000.0


def screen_row(cals: list[dict]) -> dict:
    """Medians over days for one symbol, plus the ``constrained`` verdict."""
    if not cals:
        raise ValueError("screen_row needs at least one calibrated day")

    def med(key: str) -> float:
        return float(np.median([float(c[key]) for c in cals]))

    tick_bp, spread_ticks, usd = med("tick_bp"), med("spread_ticks"), med("usd_volume_day")
    constrained = bool(tick_bp >= TICK_BP_MIN and spread_ticks <= SPREAD_TICKS_MAX and usd >= USD_VOLUME_MIN)
    return {
        "symbol": cals[0].get("symbol", ""),
        "days": len(cals),
        "tick_bp_med": tick_bp,
        "spread_ticks_med": spread_ticks,
        "usd_volume_med": usd,
        "trades_per_sec_med": med("trades_per_sec"),
        "constrained": constrained,
    }


def screen_table(rows: list[dict]) -> pd.DataFrame:
    """Constrained coins first, then by median USD volume, largest first."""
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values(["constrained", "usd_volume_med"], ascending=[False, False]).reset_index(drop=True)
