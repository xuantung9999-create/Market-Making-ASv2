"""Shared helpers for the v2 history scripts (Tasks 7-8): universe, days, tapes."""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from mm.calibrate import infer_tick
from mm.data import load_trades
from mm.recorder import read_symbols_file
from mm.tape import book_from_trades, default_level_qty

DAY_RE = re.compile(r"^([A-Z0-9]+)_(\d{4}-\d{2}-\d{2})_trades\.parquet$")


def v2_universe(screen_csv: str = "results/screen.csv", fallback: str = "config/candidates.txt") -> list[str]:
    """Constrained coins from Task 2's screen (falls back to the whole candidate list)."""
    p = Path(screen_csv)
    if p.exists():
        df = pd.read_csv(p)
        syms = df.loc[df["constrained"].astype(bool), "symbol"].tolist()
        if syms:
            return syms
        print(f"note: no constrained coin in {screen_csv}; using every candidate")
    return read_symbols_file(fallback)


def symbol_days(symbol: str, data_dir: str = "data") -> list[str]:
    out = []
    for p in Path(data_dir).glob(f"{symbol}_*_trades.parquet"):
        m = DAY_RE.match(p.name)
        if m and m.group(1) == symbol:
            out.append(m.group(2))
    return sorted(out)


def load_day(symbol: str, day: str, data_dir: str = "data") -> Optional[tuple[pd.DataFrame, float, pd.DataFrame]]:
    """(trades, tick, inferred book tape), or None with a printed note when the day is unusable
    (no trades, trades on one side only -> empty tape). Such days are skipped, never counted as 0."""
    trades = load_trades(Path(data_dir) / f"{symbol}_{day}_trades.parquet")
    if len(trades) < 2:
        print(f"skip {symbol} {day}: fewer than 2 trades")
        return None
    tick = infer_tick(trades["price"].to_numpy(float))
    if not (np.isfinite(tick) and tick > 0):
        print(f"skip {symbol} {day}: cannot infer tick")
        return None
    tape = book_from_trades(trades, tick, default_level_qty(trades))
    if tape.empty:
        print(f"skip {symbol} {day}: trades on one side only, no book can be inferred")
        return None
    return trades, tick, tape


def t_stat(x) -> float:
    x = np.asarray(x, float)
    x = x[np.isfinite(x)]
    if x.size < 2 or x.std(ddof=1) == 0:
        return float("nan")
    return float(x.mean() / (x.std(ddof=1) / math.sqrt(x.size)))


def fee_note(fee_bps: float = 10.0, alt_bps: float = 7.5) -> str:
    return f"net P&L uses a {fee_bps:g} bp maker fee; net_{alt_bps:g}bp columns show the {alt_bps:g} bp case"
