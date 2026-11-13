"""Testnet trader: the paper trader's agent, but its quotes become REAL post-only orders on the
Binance SPOT TESTNET (fake money). Use it to test execution, not to judge profit.

    python -m mm.testnet --symbols BTCUSDT --policy join --hours 1      # plumbing test: always quote
    python -m mm.testnet --symbols BTCUSDT,ETHUSDT                      # the self-calibrating agent
    python -m mm.testnet --symbols BTCUSDT --dry-run                    # log intended orders, send none

Keys: create them at https://testnet.binance.vision (log in with GitHub -> Generate HMAC key) and
put them in a file called .env in the repo root (it is git-ignored, never commit it):

    BINANCE_TESTNET_API_KEY=...
    BINANCE_TESTNET_API_SECRET=...

Why testnet P&L means little: the testnet book is thin and driven by other people's test bots,
so fills, spreads and adverse selection look nothing like the real market. The paper trader
(mm.paper: real mainnet data, simulated fills) is the place to judge the model. Testnet tells
you whether orders are placed, replaced, filled, counted and cancelled correctly.

How it works (every second, per symbol)
1. Market data comes from the TESTNET websocket, because orders must be priced off the book
   they rest in. Events feed the same ``CalibrationAgent`` used by the backtest and paper trader.
2. Before the decision timers fire, the simulated live track's inventory is set to the REAL
   inventory (in lots), so the policy reacts to what we actually hold.
3. The live track's target price per side (JOIN = best, BACK = one tick behind, OUT = none) is
   read and the real orders are reconciled: cancel an order whose price is wrong, place a
   LIMIT_MAKER (post-only) order where one is missing.
4. Fills are found by polling open orders: an order that grew its executedQty or disappeared
   without us cancelling it is queried and its fill recorded.
5. Guards on REAL numbers: inventory cap (q_max lots), spot balance check, daily loss stop
   (cancel all and stop quoting until the next UTC day). Ctrl+C cancels every open order.

Files (``out`` = data/testnet):
  out/<SYM>/orders_<date>.jsonl     every place / cancel / reject, with exchange responses
  out/<SYM>/fills_<date>.jsonl      every real fill (side, price, qty, mid at detection)
  out/<SYM>/status.json             latest position, P&L, open orders (every minute)
  out/feed/...                      recorded testnet feed (same layout as mm.recorder)
  out/state/...                     the agent's table and choices learned on testnet
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import math
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Optional

from mm.agent import AgentConfig
from mm.paper import DAY_US, PaperSession, day_str
from mm.queue_sim import Action, Fixed, QSConfig
from mm.recorder import now_us, read_symbols_file

TESTNET_REST = "https://testnet.binance.vision"
TESTNET_WS = "wss://stream.testnet.binance.vision/stream?streams="


def testnet_url(symbols: list[str]) -> str:
    return TESTNET_WS + "/".join(f"{s.lower()}@bookTicker/{s.lower()}@aggTrade" for s in symbols)


# ---------------------------------------------------------------------- keys
def load_env(path: str | Path = ".env") -> None:
    """Minimal .env reader (KEY=VALUE lines). Existing non-empty environment variables win; an empty one
    (e.g. read from a .env that had no keys yet) is filled in, so keys pasted later are picked up."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if not os.environ.get(k):
            os.environ[k] = v


# ---------------------------------------------------------------------- REST client
class BinanceError(Exception):
    def __init__(self, status: int, code: int, msg: str):
        super().__init__(f"HTTP {status} code {code}: {msg}")
        self.status, self.code, self.msg = status, code, msg


class TestnetClient:
    """Signed REST calls to the spot testnet. Refuses any non-testnet base URL."""
    __test__ = False                             # not a pytest class

    def __init__(self, key: str, secret: str, base: str = TESTNET_REST, recv_window: int = 5000):
        if "testnet" not in base:
            raise ValueError("this client only talks to the testnet")
        self.key, self.secret, self.base, self.recv_window = key, secret.encode(), base.rstrip("/"), recv_window
        self.offset_ms = 0
        self.weight = 0

    def _req(self, method: str, path: str, params: Optional[dict] = None, signed: bool = False):
        params = {k: v for k, v in (params or {}).items() if v is not None}
        if signed:
            params["timestamp"] = int(time.time() * 1000) + self.offset_ms
            params["recvWindow"] = self.recv_window
        qs = urllib.parse.urlencode(params)
        if signed:
            qs += "&signature=" + hmac.new(self.secret, qs.encode(), hashlib.sha256).hexdigest()
        url = f"{self.base}{path}" + (f"?{qs}" if qs else "")
        req = urllib.request.Request(url, method=method, headers={"X-MBX-APIKEY": self.key})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                self.weight = int(r.headers.get("X-MBX-USED-WEIGHT-1M", self.weight) or 0)
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            body = e.read()
            try:
                j = json.loads(body)
                raise BinanceError(e.code, int(j.get("code", 0)), str(j.get("msg", "")))
            except (json.JSONDecodeError, AttributeError):
                raise BinanceError(e.code, 0, body[:200].decode(errors="replace"))

    def sync_time(self) -> int:
        server = self._req("GET", "/api/v3/time")["serverTime"]
        self.offset_ms = int(server - time.time() * 1000)
        return self.offset_ms

    def exchange_info(self, symbol: str) -> dict:
        return self._req("GET", "/api/v3/exchangeInfo", {"symbol": symbol})["symbols"][0]

    def account(self) -> dict:
        return self._req("GET", "/api/v3/account", {"omitZeroBalances": "true"}, signed=True)

    def new_order(self, symbol: str, side: str, price: str, qty: str, client_id: str) -> dict:
        return self._req("POST", "/api/v3/order", {"symbol": symbol, "side": side, "type": "LIMIT_MAKER",
                                                    "price": price, "quantity": qty, "newClientOrderId": client_id,
                                                    "newOrderRespType": "RESULT"}, signed=True)

    def cancel(self, symbol: str, order_id: int) -> dict:
        return self._req("DELETE", "/api/v3/order", {"symbol": symbol, "orderId": order_id}, signed=True)

    def get_order(self, symbol: str, order_id: int) -> dict:
        return self._req("GET", "/api/v3/order", {"symbol": symbol, "orderId": order_id}, signed=True)

    def open_orders(self, symbol: str) -> list:
        return self._req("GET", "/api/v3/openOrders", {"symbol": symbol}, signed=True)

    def cancel_all(self, symbol: str) -> list:
        try:
            return self._req("DELETE", "/api/v3/openOrders", {"symbol": symbol}, signed=True)
        except BinanceError as e:
            if e.code == -2011:                  # no open orders
                return []
            raise


# ---------------------------------------------------------------------- symbol rules
@dataclass(frozen=True)
class Rules:
    tick: float
    step: float
    min_qty: float = 0.0
    min_notional: float = 0.0
    base: str = ""
    quote: str = ""

    @staticmethod
    def from_info(info: dict) -> "Rules":
        f = {x["filterType"]: x for x in info["filters"]}
        mn = f.get("NOTIONAL", f.get("MIN_NOTIONAL", {})).get("minNotional", 0)
        return Rules(tick=float(f["PRICE_FILTER"]["tickSize"]), step=float(f["LOT_SIZE"]["stepSize"]),
                     min_qty=float(f["LOT_SIZE"]["minQty"]), min_notional=float(mn),
                     base=info.get("baseAsset", ""), quote=info.get("quoteAsset", ""))

    @staticmethod
    def _decimals(x: float) -> int:
        return max(0, -Decimal(repr(x)).normalize().as_tuple().exponent)

    def price_str(self, k: int) -> str:
        return f"{k * self.tick:.{self._decimals(self.tick)}f}"

    def qty_floor(self, qty: float) -> float:
        n = math.floor(qty / self.step + 1e-9)
        return round(n * self.step, self._decimals(self.step))

    def qty_str(self, qty: float) -> str:
        return f"{self.qty_floor(qty):.{self._decimals(self.step)}f}"


# ---------------------------------------------------------------------- per-symbol executor
@dataclass
class LiveOrder:
    side: int            # +1 buy, -1 sell
    order_id: int
    k: int               # price in ticks
    price: float
    qty: float
    filled: float = 0.0  # executedQty already booked


@dataclass
class Executor:
    """Keeps the real orders of one symbol in line with the target prices. Pure logic plus
    calls to an injected client, so it can be tested with a fake exchange."""
    symbol: str
    rules: Rules
    client: object
    lot_usd: float
    q_max: int
    maker_fee_bps: float = 10.0
    max_daily_loss_usd: float = 20.0
    out_dir: Path = Path("data/testnet")
    dry_run: bool = False
    pos: float = 0.0                   # base units bought - sold since start
    cash: float = 0.0                  # quote spent/received since start
    fees: float = 0.0                  # estimated maker fees (quote)
    base_free: float = float("inf")    # spot balance limits: can't sell base we don't have
    quote_free: float = float("inf")
    orders: dict = field(default_factory=lambda: {1: None, -1: None})
    n_fills: int = 0
    n_rejects: int = 0
    stopped: bool = False
    day_start_pnl: float = 0.0
    day: Optional[int] = None
    _seq: int = 0

    # ---------------- accounting
    def pnl(self, mid: float) -> float:
        return self.cash + self.pos * mid - self.fees

    def lots(self, mid: float) -> int:
        """Real inventory in lots of ``lot_usd`` (rounded), what the policy sees as q."""
        return int(round(self.pos * mid / self.lot_usd)) if mid > 0 else 0

    def _log(self, kind: str, rec: dict) -> None:
        folder = self.out_dir / self.symbol
        folder.mkdir(parents=True, exist_ok=True)
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with open(folder / f"{kind}_{day}.jsonl", "a") as fh:
            fh.write(json.dumps({"ts_us": now_us(), **rec}) + "\n")

    def _book_fill(self, o: LiveOrder, executed: float, mid: float, how: str) -> None:
        d = executed - o.filled
        if d <= 1e-12:
            return
        o.filled = executed
        self.pos += o.side * d
        self.cash -= o.side * o.price * d
        self.fees += o.price * d * self.maker_fee_bps / 1e4
        if o.side > 0:
            self.base_free += d
        else:
            self.quote_free += o.price * d
        self.n_fills += 1
        self._log("fills", {"side": o.side, "price": o.price, "qty": d, "order_id": o.order_id,
                            "mid": mid, "pos": self.pos, "pnl": self.pnl(mid), "how": how})

    # ---------------- exchange sync
    def sync(self, mid: float) -> None:
        """Detect fills: compare our orders with the exchange's open orders."""
        if self.dry_run or not any(self.orders.values()):
            return
        open_ = {int(o["orderId"]): o for o in self.client.open_orders(self.symbol)}
        for side in (1, -1):
            o = self.orders[side]
            if o is None:
                continue
            if o.order_id in open_:
                self._book_fill(o, float(open_[o.order_id]["executedQty"]), mid, "partial")
            else:
                r = self.client.get_order(self.symbol, o.order_id)
                self._book_fill(o, float(r["executedQty"]), mid, "filled")
                self.orders[side] = None

    def _cancel(self, side: int, mid: float) -> None:
        o = self.orders[side]
        if o is None:
            return
        self.orders[side] = None
        if self.dry_run:
            self._log("orders", {"op": "cancel", "side": side, "dry_run": True})
            return
        try:
            r = self.client.cancel(self.symbol, o.order_id)
            self._book_fill(o, float(r.get("executedQty", 0)), mid, "before-cancel")
            self._log("orders", {"op": "cancel", "side": side, "order_id": o.order_id, "status": r.get("status")})
        except BinanceError as e:
            if e.code == -2011:                  # already gone: it filled
                r = self.client.get_order(self.symbol, o.order_id)
                self._book_fill(o, float(r["executedQty"]), mid, "filled-at-cancel")
                self._log("orders", {"op": "cancel-miss", "side": side, "order_id": o.order_id,
                                     "status": r.get("status")})
            else:
                self.orders[side] = o            # keep tracking; retry next second
                self._log("orders", {"op": "cancel-error", "side": side, "error": str(e)})

    def _place(self, side: int, k: int, mid: float) -> None:
        r_ = self.rules
        price = k * r_.tick
        qty = r_.qty_floor(self.lot_usd / mid)
        if qty < r_.min_qty or qty * price < r_.min_notional:
            self._log("orders", {"op": "skip", "side": side, "why": "below exchange minimum", "qty": qty})
            return
        if side < 0 and qty > self.base_free:
            return                               # spot: can't sell what we don't hold
        if side > 0 and qty * price > self.quote_free:
            return
        self._seq += 1
        cid = f"mmas-{self.symbol[:6]}-{int(time.time())}-{self._seq}"
        rec = {"op": "place", "side": side, "price": r_.price_str(k), "qty": r_.qty_str(qty), "cid": cid}
        if self.dry_run:
            self.orders[side] = LiveOrder(side, -self._seq, k, price, qty)
            self._log("orders", {**rec, "dry_run": True})
            return
        try:
            r = self.client.new_order(self.symbol, "BUY" if side > 0 else "SELL", r_.price_str(k), r_.qty_str(qty), cid)
        except BinanceError as e:
            self.n_rejects += 1
            self._log("orders", {**rec, "op": "reject", "error": str(e)})   # -2010: would cross (post-only)
            return
        o = LiveOrder(side, int(r["orderId"]), k, price, qty)
        self.orders[side] = o
        if side > 0:
            self.quote_free -= qty * price
        else:
            self.base_free -= qty
        self._log("orders", {**rec, "order_id": o.order_id, "status": r.get("status")})
        self._book_fill(o, float(r.get("executedQty", 0)), mid, "on-place")

    # ---------------- one decision
    def step(self, targets: dict, mid: float, now: int) -> None:
        """``targets`` = {+1: price in ticks or None, -1: ...}. Sync fills, guard, reconcile."""
        d = now // DAY_US
        if self.day is None:
            self.day = d
        elif d != self.day:                      # new UTC day: loss stop resets
            self.day, self.stopped, self.day_start_pnl = d, False, self.pnl(mid)
        self.sync(mid)
        if not self.stopped and self.pnl(mid) - self.day_start_pnl < -self.max_daily_loss_usd:
            self.stopped = True
            self._log("orders", {"op": "loss-stop", "pnl": self.pnl(mid)})
        q = self.lots(mid)
        for side in (1, -1):
            want = None if self.stopped else targets.get(side)
            if want is not None and (q >= self.q_max if side > 0 else q <= -self.q_max):
                want = None                      # real inventory cap
            cur = self.orders[side]
            if cur is not None and cur.k != want:
                self._cancel(side, mid)
                cur = None
            if cur is None and want is not None:
                self._place(side, want, mid)

    def cancel_all(self, mid: float = 0.0) -> None:
        for side in (1, -1):
            self._cancel(side, mid)
        if not self.dry_run:
            self.client.cancel_all(self.symbol)

    def status(self, mid: float) -> dict:
        return {"symbol": self.symbol, "pos": self.pos, "lots": self.lots(mid), "pnl": self.pnl(mid),
                "fees_est": self.fees, "fills": self.n_fills, "rejects": self.n_rejects, "stopped": self.stopped,
                "open": {("bid" if s > 0 else "ask"): (o.price if o else None) for s, o in self.orders.items()}}


def targets_from_sim(sim) -> dict:
    """Price (ticks) the simulated live track wants resting on each side, ignoring its latency."""
    out = {}
    for side in (1, -1):
        p = sim._pending[side]
        if p is not None:
            out[side] = p.k
        else:
            o = sim.orders[side]
            out[side] = o.k if o is not None else None
    return out


# ---------------------------------------------------------------------- session
class TestnetSession(PaperSession):
    __test__ = False
    def __init__(self, symbols, client, rules: dict, policy: str = "agent", dry_run: bool = False,
                 lot_usd: float = 100.0, q_max: int = 10, warmup_s: float = 120.0, max_loss: float = 20.0,
                 state_dir="data/testnet/state", out_dir="data/testnet"):
        sim = QSConfig(lot_usd=lot_usd, q_max=q_max, warmup_s=warmup_s, stale_s=120.0)
        super().__init__(symbols, state_dir, out_dir, AgentConfig(max_daily_loss_usd=max_loss), sim,
                         ticks={s: r.tick for s, r in rules.items()})
        self.policy = policy
        self.execs = {s: Executor(s, rules[s], client, lot_usd, q_max, sim.maker_fee_bps, max_loss,
                                  Path(out_dir), dry_run) for s in self.symbols}

    def agent_for(self, sym):
        new = sym not in self.agents
        a = super().agent_for(sym)
        if new and self.policy == "join":
            a.live.policy = Fixed(Action.JOIN, Action.JOIN, name="Always join (testnet plumbing)")
        return a

    def mid(self, sym) -> float:
        a = self.agents.get(sym)
        return float(a._mid) if a is not None and a._mid else 0.0

    def tick(self, now: int) -> None:
        for sym, a in self.agents.items():          # the policy sees the REAL inventory
            m = self.mid(sym)
            if m > 0:
                a.live.q = self.execs[sym].lots(m)
        super().tick(now)

    def execute(self, now: int) -> None:
        for sym, a in self.agents.items():
            m = self.mid(sym)
            if m <= 0:
                continue
            try:
                self.execs[sym].step(targets_from_sim(a.live), m, now)
            except (BinanceError, OSError) as e:
                print(f"{sym}: exchange error {e}; will retry", flush=True)

    def checkpoint(self) -> None:
        super().checkpoint()
        for sym, ex in self.execs.items():
            st = {**ex.status(self.mid(sym)), "live_arm": getattr(self.agents.get(sym), "live_arm", None),
                  "policy": self.policy, "ts": datetime.now(timezone.utc).isoformat()}
            p = self.out_dir / sym / "status.json"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(st, indent=1))

    def shutdown(self) -> None:
        for sym, ex in self.execs.items():
            try:
                ex.cancel_all(self.mid(sym))
                print(f"{sym}: all orders cancelled", flush=True)
            except Exception as e:                   # noqa: BLE001 - report and carry on
                print(f"{sym}: cancel-all failed ({e}); check the testnet UI", flush=True)


async def _run(session: TestnetSession, hours: Optional[float]) -> None:
    import websockets

    url = testnet_url(session.symbols)
    deadline = None if hours is None else time.monotonic() + hours * 3600
    last_ckpt = time.monotonic()
    lock = asyncio.Lock()

    async def ticker():
        nonlocal last_ckpt
        while True:
            await asyncio.sleep(1.0)
            async with lock:
                now = now_us()
                session.tick(now)
                await asyncio.to_thread(session.execute, now)
            if time.monotonic() - last_ckpt >= 60:
                session.checkpoint()
                last_ckpt = time.monotonic()
                print(f"[{time.strftime('%H:%M:%S')}] " + " | ".join(
                    f"{s} pos={e.pos:.6g} lots={e.lots(session.mid(s))} pnl={e.pnl(session.mid(s)):.2f} "
                    f"fills={e.n_fills} rej={e.n_rejects}{' STOP' if e.stopped else ''}"
                    for s, e in session.execs.items()), flush=True)

    tk = asyncio.create_task(ticker())
    backoff = 1.0
    try:
        while deadline is None or time.monotonic() < deadline:
            try:
                async with websockets.connect(url, ping_interval=20, max_queue=10_000) as ws:
                    print(f"TESTNET trading ({session.policy}{', DRY RUN' if session.execs[session.symbols[0]].dry_run else ''}): "
                          f"{', '.join(session.symbols)}  warm-up {session.sim_cfg.warmup_s:.0f}s before the first order",
                          flush=True)
                    backoff = 1.0
                    async for raw in ws:
                        async with lock:
                            session.handle(raw, now_us())
                        if deadline is not None and time.monotonic() >= deadline:
                            break
            except (OSError, asyncio.TimeoutError, websockets.ConnectionClosed) as e:
                print(f"connection lost ({e!r}); reconnecting in {backoff:.0f}s", flush=True)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
    finally:
        tk.cancel()
        async with lock:
            await asyncio.to_thread(session.shutdown)
        session.checkpoint()


def _main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m mm.testnet")
    ap.add_argument("--symbols", default="BTCUSDT")
    ap.add_argument("--symbols-file", default=None)
    ap.add_argument("--policy", choices=["agent", "join"], default="agent",
                    help="agent = self-calibrating agent; join = always rest at best bid/ask (plumbing test)")
    ap.add_argument("--lot-usd", type=float, default=100.0)
    ap.add_argument("--q-max", type=int, default=10, help="inventory cap in lots")
    ap.add_argument("--max-loss", type=float, default=20.0, help="daily loss stop, USDT")
    ap.add_argument("--warmup", type=float, default=120.0, help="seconds of data before the first order")
    ap.add_argument("--seed-state", default="data/paper/state",
                    help="copy the paper trader's learned tables into a fresh testnet state folder")
    ap.add_argument("--out", default="data/testnet")
    ap.add_argument("--hours", type=float, default=None)
    ap.add_argument("--dry-run", action="store_true", help="read testnet data and log orders, but send none")
    ap.add_argument("--env", default=".env")
    args = ap.parse_args(argv)

    syms = read_symbols_file(args.symbols_file) if args.symbols_file else args.symbols.split(",")
    syms = [s.strip().upper() for s in syms if s.strip()]
    load_env(args.env)
    key, secret = os.environ.get("BINANCE_TESTNET_API_KEY", ""), os.environ.get("BINANCE_TESTNET_API_SECRET", "")
    if not (key and secret):
        ap.error("missing BINANCE_TESTNET_API_KEY / BINANCE_TESTNET_API_SECRET (put them in .env, see .env.example)")
    client = TestnetClient(key, secret)
    print(f"clock offset to testnet: {client.sync_time()} ms")

    rules = {}
    for s in syms:
        rules[s] = Rules.from_info(client.exchange_info(s))
        print(f"{s}: tick {rules[s].tick:g}, step {rules[s].step:g}, min notional {rules[s].min_notional:g}")

    state = Path(args.out) / "state"
    seed = Path(args.seed_state)
    if seed.is_dir() and not state.exists():
        state.mkdir(parents=True)
        for s in syms:
            for f in seed.glob(f"{s}_*.json"):
                if "_start_" not in f.name:
                    shutil.copy2(f, state / f.name)

    session = TestnetSession(syms, client, rules, args.policy, args.dry_run, args.lot_usd, args.q_max,
                             args.warmup, args.max_loss, state, args.out)
    bal = {b["asset"]: float(b["free"]) for b in client.account()["balances"]}
    for s, ex in session.execs.items():
        ex.base_free, ex.quote_free = bal.get(rules[s].base, 0.0), bal.get(rules[s].quote, 0.0)
        print(f"{s}: free {ex.base_free:g} {rules[s].base}, {ex.quote_free:g} {rules[s].quote}")
        if not args.dry_run:
            left = client.cancel_all(s)
            if left:
                print(f"{s}: cancelled {len(left)} order(s) left over from a previous run")
        session.agent_for(s)
    try:
        asyncio.run(_run(session, args.hours))
    except KeyboardInterrupt:
        session.shutdown()                       # second safety net: never leave orders behind
        print("stopped")


if __name__ == "__main__":
    _main()
