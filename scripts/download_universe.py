"""Download the same days for a range of coins, from BTC down to micro caps.

Run from the repo root:
    python -m scripts.download_universe                       # default list, 9-10 Nov 2026
    python -m scripts.download_universe --date 2026-11-09 --days 2 --symbols SOLUSDT ARBUSDT

Coins are NOT sorted into tiers by name: Binance listings change and "small cap" is about
liquidity, not market cap. After downloading, each coin is measured (USD volume per day,
trades per second, spread in bp, tick size relative to price) and the tier is assigned from
those numbers in results/universe.csv. Symbols that are not available for a date (delisted,
renamed, not yet listed) are skipped with a message.
"""
from __future__ import annotations

import argparse
import urllib.error
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from mm.data import download_day, load_trades

# A wide net on purpose: from the most liquid pairs to thin ones. Missing ones are skipped.
CANDIDATES = [
    "BTCUSDT", "SOLUSDT", "DOGEUSDT",                     # usually large
    "ARBUSDT", "NEARUSDT", "INJUSDT",                     # usually mid
    "ONEUSDT", "CELRUSDT", "IOTXUSDT", "ANKRUSDT",        # usually small
    "SKLUSDT", "COTIUSDT", "HOOKUSDT",
    "DATAUSDT", "HIGHUSDT", "PERPUSDT", "LOKAUSDT",       # usually thin / micro
]


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-11-09")
    ap.add_argument("--days", type=int, default=2)
    ap.add_argument("--symbols", nargs="*", default=CANDIDATES)
    args = ap.parse_args(argv)
    first = date.fromisoformat(args.date)
    ok, missing = [], []
    for sym in args.symbols:
        for n in range(args.days):
            day = str(first + timedelta(days=n))
            try:
                download_day(sym, day)
                ok.append((sym, day))
            except urllib.error.HTTPError as e:
                print(f"  skip {sym} {day}: HTTP {e.code} (not available)")
                missing.append((sym, day))
            except Exception as e:                     # network hiccup, bad zip, ...
                print(f"  skip {sym} {day}: {e!r}")
                missing.append((sym, day))
    print(f"\ndownloaded {len(ok)} symbol-days, skipped {len(missing)}")
    rows = []
    for sym, day in ok:
        t = load_trades(Path("data") / f"{sym}_{day}_trades.parquet")
        rows.append({"symbol": sym, "date": day, "trades": len(t),
                     "usd_volume": float((t.price * t.qty).sum()), "price": float(t.price.iloc[-1])})
    if rows:
        df = pd.DataFrame(rows)
        print(df.groupby("symbol")[["trades", "usd_volume", "price"]].mean()
              .sort_values("usd_volume", ascending=False).round(4).to_string())


if __name__ == "__main__":
    main()
