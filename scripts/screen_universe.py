"""v2 Task 2: screen every candidate coin for tick constraint (see mm/screen.py).

    python -m scripts.screen_universe            # up to the 7 most recent days per coin

Writes results/screen.csv (constrained coins first) and prints it.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

from mm.calibrate import calibrate
from mm.data import load_trades
from mm.recorder import read_symbols_file
from mm.screen import screen_row, screen_table

DAY_RE = re.compile(r"_(\d{4}-\d{2}-\d{2})_trades\.parquet$")


def recent_files(symbol: str, data_dir: Path, n: int) -> list[Path]:
    files = sorted(p for p in data_dir.glob(f"{symbol}_*_trades.parquet") if DAY_RE.search(p.name))
    return files[-n:]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m scripts.screen_universe")
    ap.add_argument("--symbols-file", default="config/candidates.txt")
    ap.add_argument("--data", default="data")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out", default="results/screen.csv")
    args = ap.parse_args(argv)

    rows = []
    for sym in read_symbols_file(args.symbols_file):
        cals = []
        for p in recent_files(sym, Path(args.data), args.days):
            day = DAY_RE.search(p.name).group(1)
            trades = load_trades(p)
            if len(trades) < 50 or trades["side"].nunique() < 2:
                print(f"skip {sym} {day}: too few trades or one-sided", flush=True)
                continue
            c = calibrate(trades, sym, day)
            c.pop("fill_curve", None)
            cals.append(c)
        if not cals:
            print(f"skip {sym}: no usable days", flush=True)
            continue
        rows.append(screen_row(cals))

    table = screen_table(rows)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.out, index=False)
    with pd.option_context("display.width", 140, "display.float_format", "{:,.2f}".format):
        print(table.to_string(index=False))
    print(f"\nv2 universe (constrained): {', '.join(table.loc[table['constrained'], 'symbol']) or 'none'}")
    print(f"saved -> {args.out}")


if __name__ == "__main__":
    main()
