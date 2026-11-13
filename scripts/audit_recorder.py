"""v2.1 Task 12: what did the recorder actually save?

    python -m scripts.audit_recorder                  # every coin in config/candidates.txt
    python -m scripts.audit_recorder --symbols ANKRUSDT,BTCUSDT

One row per coin per UTC day, read from data/live (``mm.recorder.load_live``). Everything is
timed by ``recv_us``, the one clock the book has (spot bookTicker carries no exchange time).

  clean_hours        hours of the day fully covered: the first and last book update within 120 s of
                     the hour's edges and no gap over 120 s inside it (the Build Guide's rule)
  gaps_over_5s       book gaps longer than 5 s; gap_seconds is their total, max_gap_s the longest
  crossed_or_locked  updates with bid >= ask (should be zero)
  bad_sizes          updates with a zero or negative size
  id_backwards       updates whose update_id is lower than the one before
  out_of_book_share  share of trades priced outside the best bid/ask recorded just before them
                     (judged in whole ticks; a clock or ordering fault if above 2%)
  spread_ticks_med   median spread in ticks
  touch_in_trades    median resting size at the best price, in median trade sizes (mm/tape.py
                     assumes 20 until this is measured)

Pass rule (docs/SPEC_V2_1.md section 3): each of COTIUSDT, ANKRUSDT, SKLUSDT and BTCUSDT has at
least 7 days with 20+ clean hours, zero crossed books and under 2% out-of-book trades.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from mm.calibrate import infer_tick
from mm.recorder import BOOK_COLUMNS, LIVE_TRADE_COLUMNS, load_live, read_symbols_file

HOUR_US = 3_600_000_000
DAY_US = 24 * HOUR_US
GAP_S = 5.0
CLEAN_GAP_US = 120_000_000
REQUIRED = ["COTIUSDT", "ANKRUSDT", "SKLUSDT", "BTCUSDT"]
MIN_GOOD_DAYS = 7
MIN_CLEAN_HOURS = 20
MAX_OUT_OF_BOOK = 0.02


def _clean_hours(ts: np.ndarray, day: int) -> int:
    n = 0
    for h in range(24):
        h0 = day * DAY_US + h * HOUR_US
        lo, hi = np.searchsorted(ts, [h0, h0 + HOUR_US])
        if hi == lo:
            continue
        seg = ts[lo:hi]
        if seg[0] - h0 > CLEAN_GAP_US or (h0 + HOUR_US) - seg[-1] > CLEAN_GAP_US:
            continue
        if len(seg) > 1 and np.diff(seg).max() > CLEAN_GAP_US:
            continue
        n += 1
    return n


def _out_of_book(book: pd.DataFrame, trades: pd.DataFrame, tick: float) -> pd.Series:
    """True/False per trade, NaN where no book update came before it. Index = trades' index."""
    if trades.empty:
        return pd.Series(dtype=float)
    m = pd.merge_asof(trades[["recv_us", "price"]], book[["recv_us", "bid", "ask"]], on="recv_us",
                      direction="backward")
    if np.isfinite(tick):
        px, bid, ask = (np.round(m[c] / tick) for c in ("price", "bid", "ask"))
        out = (px < bid) | (px > ask)
    else:
        eps = 1e-12 * m["price"]
        out = (m["price"] < m["bid"] - eps) | (m["price"] > m["ask"] + eps)
    return out.astype(float).where(m["bid"].notna())


def audit_symbol(symbol: str, book: pd.DataFrame, trades: pd.DataFrame, tick: float | None = None) -> list[dict]:
    book = book.sort_values("recv_us", kind="stable").reset_index(drop=True)
    trades = trades.sort_values("recv_us", kind="stable").reset_index(drop=True)
    if tick is None:
        prices = np.concatenate([book["bid"], book["ask"], trades["price"]]) if len(book) else trades["price"].to_numpy()
        tick = infer_tick(prices) if len(prices) else float("nan")
    book["day"] = book["recv_us"] // DAY_US
    trades["day"] = trades["recv_us"] // DAY_US
    trades["out"] = _out_of_book(book, trades, tick).to_numpy() if len(trades) else []
    rows = []
    for day in sorted(set(book["day"]) | set(trades["day"])):
        b, t = book[book["day"] == day], trades[trades["day"] == day]
        ts = b["recv_us"].to_numpy()
        d = np.diff(ts) / 1e6
        gaps = d[d > GAP_S]
        judged = t["out"].dropna() if len(t) else pd.Series(dtype=float)
        rows.append({
            "symbol": symbol,
            "date": pd.Timestamp(int(day) * DAY_US, unit="us").strftime("%Y-%m-%d"),
            "clean_hours": _clean_hours(ts, int(day)),
            "book_updates": len(b), "trades": len(t),
            "gaps_over_5s": int(len(gaps)), "gap_seconds": float(gaps.sum()),
            "max_gap_s": float(d.max()) if len(d) else 0.0,
            "crossed_or_locked": int((b["bid"] >= b["ask"]).sum()),
            "bad_sizes": int(((b["bid_qty"] <= 0) | (b["ask_qty"] <= 0)).sum()),
            "id_backwards": int((np.diff(b["update_id"].to_numpy()) < 0).sum()),
            "out_of_book_share": float(judged.mean()) if len(judged) else None,
            "spread_ticks_med": float(np.median((b["ask"] - b["bid"]) / tick)) if len(b) and np.isfinite(tick) else None,
            "touch_in_trades": (float(np.median((b["bid_qty"] + b["ask_qty"]) / 2) / np.median(t["qty"]))
                                if len(b) and len(t) else None),
            "tick": float(tick), "note": "",
        })
    return rows


def passes(rows: list[dict]) -> bool:
    """Seven good days: 20+ clean hours, no crossed book, out-of-book trades under 2%."""
    good = [r for r in rows
            if r["clean_hours"] >= MIN_CLEAN_HOURS and r["crossed_or_locked"] == 0
            and r["out_of_book_share"] is not None and r["out_of_book_share"] < MAX_OUT_OF_BOOK]
    return len(good) >= MIN_GOOD_DAYS


def audit_root(root: str | Path, symbols: list[str]) -> pd.DataFrame:
    root, rows = Path(root), []
    for sym in symbols:
        try:
            book = load_live(root / sym / "book")
        except FileNotFoundError:
            rows.append({"symbol": sym, "note": "no recorded files"})
            continue
        try:
            trades = load_live(root / sym / "trades")
        except FileNotFoundError:
            trades = pd.DataFrame({c: pd.Series(dtype="float64") for c in LIVE_TRADE_COLUMNS})
        rows += audit_symbol(sym, book[BOOK_COLUMNS], trades[LIVE_TRADE_COLUMNS])
    return pd.DataFrame(rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m scripts.audit_recorder")
    ap.add_argument("--root", default="data/live")
    ap.add_argument("--symbols", default=None, help="comma-separated; default: config/candidates.txt")
    ap.add_argument("--out", default="results/audit_recorder.csv")
    args = ap.parse_args(argv)
    syms = ([s.strip().upper() for s in args.symbols.split(",") if s.strip()] if args.symbols
            else read_symbols_file("config/candidates.txt"))
    table = audit_root(args.root, syms)
    if table.empty:
        print("nothing recorded")
        return 1
    show = ["symbol", "date", "clean_hours", "book_updates", "trades", "gaps_over_5s", "max_gap_s",
            "crossed_or_locked", "bad_sizes", "id_backwards", "out_of_book_share", "spread_ticks_med",
            "touch_in_trades", "note"]
    print(table[[c for c in show if c in table.columns]].to_string(index=False, float_format=lambda x: f"{x:.3g}"))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.out, index=False)
    print(f"\nsaved -> {args.out}\n")
    ok_all = True
    for sym in REQUIRED:
        rows = [r for r in table[table.symbol == sym].to_dict("records") if isinstance(r.get("date"), str)]
        ok = passes([{k: (None if pd.isna(v) else v) for k, v in r.items()} for r in rows]) if rows else False
        ok_all &= ok
        print(f"  {'PASS' if ok else 'FAIL'}  {sym}: {len(rows)} recorded days")
    print(f"\nTASK 12 {'PASS' if ok_all else 'FAIL'}: "
          + ("Tasks 13-16 may start." if ok_all else "fix the recorder or keep it running; Tasks 13-16 wait."))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
