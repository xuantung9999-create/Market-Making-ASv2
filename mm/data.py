"""Day 5: historical Binance trade data.

Source: Binance's free public archive (data.binance.vision). No API key, no account.
One zip per symbol per UTC day, published the following day, with a SHA-256 checksum.

Saved format: data/<SYMBOL>_<YYYY-MM-DD>_trades.parquet, one row per aggregated trade

    ts_us   int64    trade time, microseconds since 1970 (UTC)
    price   float64  USDT
    qty     float64  base units (BTC)
    side    int8     +1 buyer was the aggressor (lifted the ask)
                     -1 seller was the aggressor (hit the bid)

The aggressor side is what matters for a market maker: a +1 trade at price p
would have filled a resting ASK at or below p; a -1 trade would have filled a
resting BID at or above p.

Usage (on your own machine, from the repo root):
    python -m mm.data download --symbol BTCUSDT --date 2026-11-10 --days 2
    python -m mm.data info data/BTCUSDT_2026-11-10_trades.parquet
"""
from __future__ import annotations

import argparse
import hashlib
import io
import urllib.request
import zipfile
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

BASE_URL = "https://data.binance.vision/data"
MARKETS = {"spot": "spot", "futures": "futures/um"}
TRADE_COLUMNS = ["ts_us", "price", "qty", "side"]


# --------------------------------------------------------------------------- download
def aggtrades_url(symbol: str, day: str, market: str = "spot") -> str:
    sym = symbol.upper()
    return f"{BASE_URL}/{MARKETS[market]}/daily/aggTrades/{sym}/{sym}-aggTrades-{day}.zip"


def _fetch(url: str, timeout: int = 300) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "as-market-maker/0.1"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _verify_checksum(raw: bytes, url: str) -> None:
    """Compare against the published <file>.CHECKSUM ("<sha256>  <name>")."""
    expected = _fetch(url + ".CHECKSUM", timeout=60).decode().split()[0].lower()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise IOError(f"checksum mismatch for {url}: got {actual}, expected {expected}")


def parse_aggtrades(fh) -> pd.DataFrame:
    """Parse a Binance aggTrades CSV into the TRADE_COLUMNS schema.

    Columns: agg_id, price, qty, first_id, last_id, time, is_buyer_maker[, is_best_match].
    Spot files have no header and (since 2025) microsecond timestamps.
    Futures files have a header and millisecond timestamps.
    """
    df = pd.read_csv(fh, header=None, dtype=str)
    if not df.iloc[0, 1].replace(".", "", 1).isdigit():   # header row present
        df = df.iloc[1:]
    df = df.iloc[:, :7]
    df.columns = ["agg_id", "price", "qty", "first_id", "last_id", "time", "is_buyer_maker"]

    t = df["time"].astype("int64").to_numpy()
    ts_us = np.where(t > 10**14, t, t * 1000)               # ms -> us when needed
    buyer_is_maker = df["is_buyer_maker"].str.strip().str.lower().isin(["true", "1"]).to_numpy()
    out = pd.DataFrame({
        "ts_us": ts_us.astype("int64"),
        "price": df["price"].astype("float64").to_numpy(),
        "qty": df["qty"].astype("float64").to_numpy(),
        # buyer is maker  <=>  seller crossed the spread  <=>  side = -1
        "side": np.where(buyer_is_maker, -1, 1).astype("int8"),
    })
    return out.sort_values("ts_us", kind="stable").reset_index(drop=True)


def trades_path(symbol: str, day: str, out_dir: str | Path = "data") -> Path:
    return Path(out_dir) / f"{symbol.upper()}_{day}_trades.parquet"


def download_day(symbol: str, day: str, market: str = "spot", out_dir: str | Path = "data",
                 overwrite: bool = False, verify: bool = True) -> Path:
    """Download, verify and save one UTC day of aggTrades. Returns the parquet path."""
    out = trades_path(symbol, day, out_dir)
    if out.exists() and not overwrite:
        print(f"exists, skipping: {out}")
        return out
    url = aggtrades_url(symbol, day, market)
    print(f"downloading {url}")
    raw = _fetch(url)
    if verify:
        _verify_checksum(raw, url)
    with zipfile.ZipFile(io.BytesIO(raw)) as zf, zf.open(zf.namelist()[0]) as fh:
        trades = parse_aggtrades(fh)
    out.parent.mkdir(parents=True, exist_ok=True)
    trades.to_parquet(out, index=False)
    print(f"saved {len(trades):,} trades ({len(raw) / 1e6:.0f} MB zip) -> {out}")
    return out


def load_trades(path: str | Path) -> pd.DataFrame:
    df = pd.read_parquet(path)
    missing = set(TRADE_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"{path} is missing columns {missing}")
    return df[TRADE_COLUMNS]


# --------------------------------------------------------------------------- bars
def trades_to_bars(trades: pd.DataFrame, freq_ms: int = 100) -> pd.DataFrame:
    """Aggregate trades into fixed time bars, the grid the backtester will requote on.

    One row per bar [t, t + freq). Bars with no trades are kept so time is regular.
      ts_us     bar start
      last_buy  last buyer-aggressor price seen up to the END of the bar (~ best ask)
      last_sell last seller-aggressor price seen up to the END of the bar (~ best bid)
      mid       (last_buy + last_sell) / 2: a mid proxy when there is no order book
      buy_max   highest buyer-aggressor price IN the bar (NaN if none): would lift asks up to here
      sell_min  lowest seller-aggressor price IN the bar (NaN if none): would hit bids down to here
      buy_vol, sell_vol, n_trades

    Only trades inside each bar feed that bar, so a strategy that quotes at the start of
    a bar using the PREVIOUS bar's row has no look-ahead.
    """
    if trades.empty:
        raise ValueError("no trades")
    step = freq_ms * 1000
    b = (trades["ts_us"].to_numpy() // step) * step
    df = trades.assign(bar=b)
    buys, sells = df[df.side > 0], df[df.side < 0]

    idx = pd.RangeIndex(int(b.min()), int(b.max()) + step, step, name="ts_us")
    out = pd.DataFrame(index=idx)
    out["last_buy"] = buys.groupby("bar")["price"].last().reindex(idx).ffill()
    out["last_sell"] = sells.groupby("bar")["price"].last().reindex(idx).ffill()
    out["mid"] = ((out["last_buy"] + out["last_sell"]) / 2).fillna(out["last_buy"]).fillna(out["last_sell"])
    out["buy_max"] = buys.groupby("bar")["price"].max()
    out["sell_min"] = sells.groupby("bar")["price"].min()
    out["buy_vol"] = buys.groupby("bar")["qty"].sum()
    out["sell_vol"] = sells.groupby("bar")["qty"].sum()
    out["n_trades"] = df.groupby("bar").size()
    out[["buy_vol", "sell_vol", "n_trades"]] = out[["buy_vol", "sell_vol", "n_trades"]].fillna(0)
    out["n_trades"] = out["n_trades"].astype("int64")
    return out.reset_index()


def summarize(trades: pd.DataFrame) -> dict:
    """Quick facts about a day, including sigma in the units A-S needs (USDT per sqrt(second))."""
    secs = trades_to_bars(trades, freq_ms=1000)
    dmid = secs["mid"].diff().dropna()
    t0, t1 = trades["ts_us"].iloc[[0, -1]]
    px = trades["price"]
    ticks = np.diff(np.unique(np.round(px.to_numpy(), 8)))
    return {
        "start_utc": pd.to_datetime(t0, unit="us", utc=True),
        "end_utc": pd.to_datetime(t1, unit="us", utc=True),
        "n_trades": len(trades),
        "buy_share": float((trades.side > 0).mean()),
        "volume_base": float(trades.qty.sum()),
        "price_min": float(px.min()), "price_max": float(px.max()),
        "price_last": float(px.iloc[-1]),
        "tick_size_guess": round(float(ticks[ticks > 0].min()), 8) if (ticks > 0).any() else float("nan"),
        "trades_per_sec": len(trades) / max((t1 - t0) / 1e6, 1.0),
        "sigma_usdt_per_sqrt_s": float(dmid.std()),
        "daily_vol_pct": float((np.log(secs["mid"]).diff().std()) * np.sqrt(86_400) * 100),
    }


# --------------------------------------------------------------------------- CLI
def _main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m mm.data")
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download", help="download daily aggTrades from data.binance.vision")
    d.add_argument("--symbol", default="BTCUSDT")
    d.add_argument("--date", default=str(date.today() - timedelta(days=2)),
                   help="first UTC day, YYYY-MM-DD (files appear the day after)")
    d.add_argument("--days", type=int, default=1, help="number of consecutive days")
    d.add_argument("--market", choices=list(MARKETS), default="spot")
    d.add_argument("--out", default="data")
    d.add_argument("--overwrite", action="store_true")
    i = sub.add_parser("info", help="print a summary of a saved trades file")
    i.add_argument("path")
    args = ap.parse_args(argv)

    if args.cmd == "download":
        first = date.fromisoformat(args.date)
        for n in range(args.days):
            day = str(first + timedelta(days=n))
            path = download_day(args.symbol, day, args.market, args.out, args.overwrite)
            for k, v in summarize(load_trades(path)).items():
                print(f"  {k:24s} {v}")
    else:
        for k, v in summarize(load_trades(args.path)).items():
            print(f"  {k:24s} {v}")


if __name__ == "__main__":
    _main()
