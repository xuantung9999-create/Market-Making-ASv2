"""v2 Task 2: download N days of spot aggTrades for every coin in config/candidates.txt.

    python -m scripts.download_history --days 60                  # ends yesterday (UTC)
    python -m scripts.download_history --days 60 --end 2026-11-10

Files that already exist are skipped. A missing day (not yet published, delisted coin)
prints a warning and the download carries on. Ends with a table of days present per coin.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from mm.data import download_day, trades_path
from mm.recorder import read_symbols_file


def day_list(end: str, days: int) -> list[str]:
    e = date.fromisoformat(end)
    return [(e - timedelta(days=i)).isoformat() for i in range(days - 1, -1, -1)]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m scripts.download_history")
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--end", default=(datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat())
    ap.add_argument("--symbols-file", default="config/candidates.txt")
    ap.add_argument("--out", default="data")
    args = ap.parse_args(argv)

    symbols = read_symbols_file(args.symbols_file)
    days = day_list(args.end, args.days)
    print(f"{len(symbols)} symbols x {len(days)} days ({days[0]} .. {days[-1]})", flush=True)
    for sym in symbols:
        for d in days:
            if trades_path(sym, d, args.out).exists():
                continue
            try:
                download_day(sym, d, out_dir=args.out)
            except Exception as e:  # network error, 404 for a missing day, bad checksum
                print(f"WARNING {sym} {d}: {e!r} - skipped", flush=True)

    print("\ndays present per symbol")
    for sym in symbols:
        n = sum(trades_path(sym, d, args.out).exists() for d in days)
        print(f"  {sym:<12} {n:>3} / {len(days)}")


if __name__ == "__main__":
    main()
