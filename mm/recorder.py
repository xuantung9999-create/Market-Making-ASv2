"""Day 5: live Binance recorder for best bid/ask (bookTicker) and trades (aggTrade).

The public archive has trades but no spot order book, so start this early and let it
run: by Day 12-13 you will have real top-of-book data to check the backtest against.

Usage (from the repo root; leave the terminal open, Ctrl+C to stop):
    python -m mm.recorder --symbol BTCUSDT
    python -m mm.recorder --symbol BTCUSDT --hours 6
    python -m mm.recorder --symbols ANKRUSDT,SKLUSDT,ARBUSDT,BTCUSDT      (v2: one socket, many coins)
    python -m mm.recorder --symbols-file config/candidates.txt

Writes small parquet part files every --flush seconds:
    data/live/<SYMBOL>/book/<SYMBOL>_book_<unix_ms>.parquet
        recv_us, update_id, bid, bid_qty, ask, ask_qty
    data/live/<SYMBOL>/trades/<SYMBOL>_trades_<unix_ms>.parquet
        recv_us, ts_us, price, qty, side          (same columns as mm.data + recv_us)
Load a folder back with ``load_live(folder)``.

Notes
- Spot bookTicker messages carry no exchange timestamp, so recv_us (your clock) is the
  time axis for the book. Trades carry the exchange time (ts_us) too; ts_us - recv_us
  gives you a rough latency estimate for free.
- Binance closes connections after 24 h; the recorder reconnects automatically.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

WS_URL = "wss://stream.binance.com:9443/stream?streams={s}@bookTicker/{s}@aggTrade"
BOOK_COLUMNS = ["recv_us", "update_id", "bid", "bid_qty", "ask", "ask_qty"]
LIVE_TRADE_COLUMNS = ["recv_us", "ts_us", "price", "qty", "side"]


HEARTBEAT_TRADES = 30
HEARTBEAT_EVERY_S = 2.0


DEPTH_LEVELS = 10
DEPTH_COLUMNS = ["recv_us", "update_id"] + [f"{k}{i}" for i in range(DEPTH_LEVELS) for k in ("bp", "bq")] + \
                [f"{k}{i}" for i in range(DEPTH_LEVELS) for k in ("ap", "aq")]
DEPTH_STREAM = "depth10@1000ms"          # Binance partial book depth: 10 levels, 1 s snapshots


def parse_depth(d: dict, recv_us: int) -> tuple:
    """Partial-depth payload {"lastUpdateId", "bids": [[px, qty]...], "asks": [...]}. Ten levels per side,
    padded with NaN when the book is shallower. No exchange timestamp: recv_us is the clock."""
    def side(levels):
        out = []
        for i in range(DEPTH_LEVELS):
            if i < len(levels):
                out += [float(levels[i][0]), float(levels[i][1])]
            else:
                out += [float("nan"), float("nan")]
        return out
    return (recv_us, int(d.get("lastUpdateId", 0)), *side(d.get("bids", [])), *side(d.get("asks", [])))


def now_us() -> int:
    return time.time_ns() // 1000


def _iso(us: int, ms: bool = False) -> str:
    t = datetime.fromtimestamp(us / 1e6, tz=timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z" if ms else t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _note(q: deque, recv_us: int) -> None:
    """Remember a message time; forget anything more than a minute older than the newest."""
    q.append(recv_us)
    while q and q[0] < recv_us - 60_000_000:
        q.popleft()


def parse_book(d: dict, recv_us: int) -> tuple:
    """bookTicker payload: {"u": id, "s": sym, "b": bid, "B": bid_qty, "a": ask, "A": ask_qty}"""
    return (recv_us, int(d["u"]), float(d["b"]), float(d["B"]), float(d["a"]), float(d["A"]))


def parse_trade(d: dict, recv_us: int) -> tuple:
    """aggTrade payload: {"p": price, "q": qty, "T": trade time ms, "m": buyer is maker, ...}"""
    return (recv_us, int(d["T"]) * 1000, float(d["p"]), float(d["q"]), -1 if d["m"] else 1)


class Recorder:
    def __init__(self, symbol: str, out: str | Path = "data/live", flush_s: float = 60.0, depth: bool = False):
        self.symbol = symbol.upper()
        self.depth_on = depth
        self.depth: list[tuple] = []
        self.root = Path(out) / self.symbol
        self.flush_s = flush_s
        self.book: list[tuple] = []
        self.trades: list[tuple] = []
        self.n_book = self.n_trades = 0
        self._last_flush = time.monotonic()
        # kept for the heartbeat file only; nothing here changes what is written to disk
        self.last_book: tuple | None = None
        self.last_trades: deque = deque(maxlen=HEARTBEAT_TRADES)
        self._book_ts: deque = deque()
        self._trade_ts: deque = deque()

    def on_book(self, row: tuple) -> None:
        self.book.append(row)
        self.last_book = row
        _note(self._book_ts, row[0])

    def on_depth(self, row: tuple) -> None:
        self.depth.append(row)

    def on_trade(self, row: tuple) -> None:
        self.trades.append(row)
        self.last_trades.append(row)
        _note(self._trade_ts, row[0])

    def handle(self, raw: str, recv_us: int) -> None:
        msg = json.loads(raw)
        stream, d = msg.get("stream", ""), msg.get("data", {})
        if stream.endswith("@bookTicker"):
            self.on_book(parse_book(d, recv_us))
        elif stream.endswith("@aggTrade"):
            self.on_trade(parse_trade(d, recv_us))
        elif "@depth" in stream and self.depth_on:
            self.on_depth(parse_depth(d, recv_us))

    def heartbeat_entry(self, now_us: int) -> dict:
        lb = self.last_book
        lt = self.last_trades[-1] if self.last_trades else None
        cut = now_us - 60_000_000
        return {
            "bid": lb[2] if lb else None, "ask": lb[4] if lb else None,
            "bid_qty": lb[3] if lb else None, "ask_qty": lb[5] if lb else None,
            "last_book_utc": _iso(lb[0]) if lb else None,
            "last_trade_utc": _iso(lt[0]) if lt else None,
            "book_per_min": sum(1 for t in self._book_ts if t > cut),
            "trades_per_min": sum(1 for t in self._trade_ts if t > cut),
            "last_trades": [{"t": _iso(r[1], ms=True), "price": r[2], "qty": r[3], "side": int(r[4])}
                            for r in self.last_trades],
        }

    def flush(self) -> None:
        stamp = now_us() // 1000
        for name, rows, cols in (("book", self.book, BOOK_COLUMNS),
                                 ("trades", self.trades, LIVE_TRADE_COLUMNS),
                                 ("depth", self.depth, DEPTH_COLUMNS)):
            if not rows:
                continue
            folder = self.root / name
            folder.mkdir(parents=True, exist_ok=True)
            df = pd.DataFrame(rows, columns=cols)
            if name == "trades":
                df["side"] = df["side"].astype("int8")
            df.to_parquet(folder / f"{self.symbol}_{name}_{stamp}.parquet", index=False)
        self.n_book += len(self.book)
        self.n_trades += len(self.trades)
        self.book, self.trades, self.depth = [], [], []
        self._last_flush = time.monotonic()
        print(f"[{time.strftime('%H:%M:%S')}] saved: {self.n_book:,} book updates, "
              f"{self.n_trades:,} trades so far", flush=True)

    def maybe_flush(self) -> None:
        if time.monotonic() - self._last_flush >= self.flush_s:
            self.flush()

    async def run(self, hours: float | None = None) -> None:
        import websockets  # imported here so the parsers can be tested without it

        url = combined_url([self.symbol], self.depth_on)
        deadline = None if hours is None else time.monotonic() + hours * 3600
        backoff = 1.0
        try:
            while deadline is None or time.monotonic() < deadline:
                try:
                    async with websockets.connect(url, ping_interval=20, max_queue=10_000) as ws:
                        print(f"connected: {url}", flush=True)
                        backoff = 1.0
                        async for raw in ws:
                            self.handle(raw, now_us())
                            self.maybe_flush()
                            if deadline is not None and time.monotonic() >= deadline:
                                break
                except (OSError, asyncio.TimeoutError, websockets.ConnectionClosed) as e:
                    print(f"connection lost ({e!r}); reconnecting in {backoff:.0f}s", flush=True)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60.0)
        finally:
            self.flush()


def combined_url(symbols: list[str], depth: bool = False) -> str:
    """One combined-stream URL carrying bookTicker and aggTrade for every symbol (and, with ``depth``, the
    10-level partial book depth at 1 s)."""
    streams = "/".join(f"{s.lower()}@bookTicker/{s.lower()}@aggTrade" + (f"/{s.lower()}@{DEPTH_STREAM}" if depth else "") for s in symbols)
    return f"wss://stream.binance.com:9443/stream?streams={streams}"


class MultiRecorder:
    """v2: record several symbols over one websocket.

    Each symbol keeps its own ``Recorder`` buffer, so the files on disk are exactly the
    single-symbol layout (data/live/<SYMBOL>/book|trades/...). Messages for streams we did
    not subscribe to (or control messages) are ignored.
    """

    def __init__(self, symbols: list[str], out: str | Path = "data/live", flush_s: float = 60.0, depth: bool = False):
        self.symbols = [s.upper() for s in symbols]
        self.depth = depth
        self.recorders = {s: Recorder(s, out, flush_s, depth) for s in self.symbols}
        self.out = Path(out)
        self.flush_s = flush_s
        self._last_flush = time.monotonic()
        self._last_heartbeat = 0.0

    def handle(self, raw: str, recv_us: int) -> None:
        msg = json.loads(raw)
        stream = msg.get("stream", "")
        if "@" not in stream:
            return
        sym, kind = stream.split("@", 1)
        rec = self.recorders.get(sym.upper())
        if rec is None:
            return
        d = msg.get("data", {})
        if kind == "bookTicker":
            rec.on_book(parse_book(d, recv_us))
        elif kind == "aggTrade":
            rec.on_trade(parse_trade(d, recv_us))
        elif kind.startswith("depth") and self.depth:
            rec.on_depth(parse_depth(d, recv_us))

    def heartbeat(self, now_us: int | None = None) -> dict:
        """What the recorder sees right now, per symbol (docs/DASHBOARD_REDESIGN.md section 5)."""
        now = now_us if now_us is not None else globals()["now_us"]()
        return {"schema": 1, "ts_utc": _iso(now),
                "symbols": {s: r.heartbeat_entry(now) for s, r in self.recorders.items()}}

    def write_heartbeat(self, now_us: int | None = None) -> Path:
        """Atomic: write a temp file, then replace, so a reader never sees half a file."""
        self.out.mkdir(parents=True, exist_ok=True)
        path, tmp = self.out / "heartbeat.json", self.out / "heartbeat.json.tmp"
        tmp.write_text(json.dumps(self.heartbeat(now_us)), encoding="utf-8")
        os.replace(tmp, path)
        self._last_heartbeat = time.monotonic()
        return path

    def maybe_heartbeat(self) -> None:
        if time.monotonic() - self._last_heartbeat >= HEARTBEAT_EVERY_S:
            self.write_heartbeat()

    def flush(self) -> None:
        for rec in self.recorders.values():
            if rec.book or rec.trades or rec.depth:
                rec.flush()
        self._last_flush = time.monotonic()

    def maybe_flush(self) -> None:
        if time.monotonic() - self._last_flush >= self.flush_s:
            self.flush()

    async def run(self, hours: float | None = None) -> None:
        import websockets

        url = combined_url(self.symbols, self.depth)
        deadline = None if hours is None else time.monotonic() + hours * 3600
        backoff = 1.0
        try:
            while deadline is None or time.monotonic() < deadline:
                try:
                    async with websockets.connect(url, ping_interval=20, max_queue=10_000) as ws:
                        print(f"connected: {len(self.symbols)} symbols: {', '.join(self.symbols)}", flush=True)
                        backoff = 1.0
                        async for raw in ws:
                            self.handle(raw, now_us())
                            self.maybe_flush()
                            self.maybe_heartbeat()
                            if deadline is not None and time.monotonic() >= deadline:
                                break
                except (OSError, asyncio.TimeoutError, websockets.ConnectionClosed) as e:
                    print(f"connection lost ({e!r}); reconnecting in {backoff:.0f}s", flush=True)
                    await asyncio.sleep(backoff)
                    backoff = min(backoff * 2, 60.0)
        finally:
            self.flush()


def read_symbols_file(path: str | Path) -> list[str]:
    """One symbol per line; blank lines and # comments ignored."""
    out = []
    for line in Path(path).read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.append(line.upper())
    return out


def load_live(folder: str | Path) -> pd.DataFrame:
    """Concatenate all part files in a book/ or trades/ folder, sorted by receive time."""
    parts = sorted(Path(folder).glob("*.parquet"))
    if not parts:
        raise FileNotFoundError(f"no parquet files in {folder}")
    return pd.concat(map(pd.read_parquet, parts), ignore_index=True).sort_values(
        "recv_us", kind="stable").reset_index(drop=True)


def _main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m mm.recorder")
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--hours", type=float, default=None, help="stop after this long (default: run until Ctrl+C)")
    ap.add_argument("--out", default="data/live")
    ap.add_argument("--flush", type=float, default=60.0, help="seconds between saves")
    ap.add_argument("--symbols", default=None, help="comma-separated list (v2 multi-symbol mode)")
    ap.add_argument("--symbols-file", default=None, help="file with one symbol per line")
    ap.add_argument("--depth", action="store_true", help="also record the 10-level partial book depth (1 s snapshots) to <SYMBOL>/depth")
    args = ap.parse_args(argv)
    if args.symbols or args.symbols_file:
        syms = read_symbols_file(args.symbols_file) if args.symbols_file else args.symbols.split(",")
        rec = MultiRecorder([s.strip() for s in syms if s.strip()], args.out, args.flush, args.depth)
    else:
        rec = Recorder(args.symbol, args.out, args.flush, args.depth)
    try:
        asyncio.run(rec.run(args.hours))
    except KeyboardInterrupt:
        print("stopped")


if __name__ == "__main__":
    _main()
