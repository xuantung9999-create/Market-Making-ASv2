"""v2 Task 10: paper trader. Live public market data -> the same engine and agent as the
backtest -> fills and decisions logged to disk. It never sends an order anywhere.

    python -m mm.paper --symbols COTIUSDT,SKLUSDT,ANKRUSDT
    python -m mm.paper --symbols-file config/candidates.txt --state data/paper/state

How it stays identical to the backtest
- Every websocket message is fed to the symbol's ``CalibrationAgent`` at its receive time.
- Decision timers sit on the same 1-second grid as ``mm.tape.merge_events``: before an event at
  time t, every timer earlier than t fires; ``tick(now)`` fires timers up to now. So a scripted
  list of messages gives exactly the fills ``run_agent`` gives on the same tapes (tested).
- At UTC midnight the day is closed (``end_day``), and the agent's state at the start of the new
  day is saved. With the recorded feed, the day's first/last timer and that saved state, the
  daily supervisor (Task 11) replays the day and must get the same fills to the cent.

Files (``out`` = data/paper):
  out/feed/<SYM>/book|trades/*.parquet     the raw feed, same layout as mm.recorder
  out/<SYM>/fills_<date>.parquet           live-track fills of that day (rewritten every minute)
  out/<SYM>/history_<date>.jsonl           agent interval scores and switches
  out/<SYM>/day_<date>.json                closed day: fills, net P&L, first/last timer
  state/<SYM>_table.json, <SYM>_agent.json latest learned table and agent choices (every minute)
  state/<SYM>_start_<date>.json            state at the start of each UTC day (for replay)
  out/coin_state.json                      written by the supervisor: size_mult, enabled per coin
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from mm.agent import AgentConfig, CalibrationAgent
from mm.calibrate import infer_tick
from mm.edge import EdgeTable
from mm.queue_sim import Action, QSConfig, QSResult
from mm.recorder import MultiRecorder, combined_url, now_us, parse_book, parse_trade, read_symbols_file

DAY_US = 86_400_000_000


def day_str(day_no: int) -> str:
    return datetime.fromtimestamp(day_no * 86_400, tz=timezone.utc).strftime("%Y-%m-%d")


def _json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj))
    tmp.replace(path)


def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(Path(path).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def latest_tick(symbol: str, data_dir: str | Path = "data") -> Optional[float]:
    """Tick inferred from the most recent downloaded day of trades, if there is one."""
    files = sorted(Path(data_dir).glob(f"{symbol}_*_trades.parquet"))
    if not files:
        return None
    t = infer_tick(pd.read_parquet(files[-1], columns=["price"])["price"].to_numpy(float))
    return float(t) if np.isfinite(t) and t > 0 else None


def book_tick(symbol: str, data_dir: str | Path = "data") -> Optional[float]:
    """Tick inferred from the recorder's own book files (data/live/<SYM>/book), for coins whose history was
    never downloaded."""
    files = sorted((Path(data_dir) / "live" / symbol / "book").glob("*.parquet"))[-3:]
    if not files:
        return None
    px = np.concatenate([pd.read_parquet(f, columns=["bid", "ask"]).to_numpy(float).ravel() for f in files])
    t = infer_tick(px)
    return float(t) if np.isfinite(t) and t > 0 else None


class StateLogger:
    """Quote-state log (dashboard live spec 6.1): one ``state_<date>.jsonl`` line per side when its state
    changes, plus one per side every ``every_us``. ``cur[side]`` = {state, detail, since_us} (or None)."""

    def __init__(self, folder: str | Path, every_us: int = 60_000_000):
        self.folder, self.every_us = Path(folder), int(every_us)
        self.cur: dict = {1: None, -1: None}
        self._last = {1: None, -1: None}

    def update(self, side: int, state: str, detail, now: int) -> None:
        c = self.cur[side]
        changed = c is None or c["state"] != state
        if changed:
            self.cur[side] = {"state": state, "detail": detail, "since_us": int(now)}
        else:
            c["detail"] = detail
        last = self._last[side]
        if changed or last is None or now - last >= self.every_us:
            self._last[side] = int(now)
            self.folder.mkdir(parents=True, exist_ok=True)
            with open(self.folder / f"state_{day_str(int(now) // DAY_US)}.jsonl", "a") as fh:
                fh.write(json.dumps({"ts_us": int(now), "side": side, "state": state, "detail": detail}) + "\n")

    def snapshot(self) -> dict:
        return {"bid": self.cur[1], "ask": self.cur[-1]}


def sim_info(a, now: int) -> dict:
    """What the simulated live track knows about its own decision, for the quote-state and order logs."""
    live = a.live
    info: dict = {"live_arm": getattr(a, "live_arm", None)}
    if live._book is not None:
        bk, ak, bq, aq = live._book
        info["book"] = (bk * live.tick, ak * live.tick, bq, aq)
    cfg = live.cfg
    info["warmup"] = live._book is None or live._day_start is None or now - live._day_start < cfg.warmup_s * 1e6
    info["stale"] = (cfg.stale_s is not None and live._last_event is not None
                     and now - live._last_event > cfg.stale_s * 1e6)
    action, pred = {}, {}
    for side in (1, -1):
        o = live._pending[side] or live.orders[side]
        if o is not None:
            action[side] = Action(o.action).name
            feat = o.feat if isinstance(o.feat, dict) else {}
            pred[side] = feat.get("pred_bid" if side > 0 else "pred_ask")
    info["action"], info["pred_bp"] = action, pred
    try:
        info["score_bp"] = float(a.score_mean[a.live_arm])
    except (AttributeError, IndexError, TypeError):
        pass
    return info


class PaperSession:
    def __init__(self, symbols: list[str], state_dir: str | Path = "data/paper/state", out_dir: str | Path = "data/paper",
                 agent_cfg: AgentConfig = AgentConfig(), sim_cfg: QSConfig = QSConfig(stale_s=120.0),
                 ticks: Optional[dict] = None, data_dir: str | Path = "data"):
        self.symbols = [s.upper() for s in symbols]
        self.state_dir, self.out_dir = Path(state_dir), Path(out_dir)
        self.agent_cfg, self.sim_cfg = agent_cfg, sim_cfg
        self.ticks = {k.upper(): v for k, v in (ticks or {}).items()}
        self.data_dir = data_dir
        self.recorder = MultiRecorder(self.symbols, out=self.out_dir / "feed")
        self.agents: dict[str, CalibrationAgent] = {}
        self._st: dict[str, dict] = {}
        self._state_logs: dict[str, StateLogger] = {}
        self.step =int(sim_cfg.decision_ms) * 1000

    # ------------------------------------------------------------------ agents and state
    def _coin_state(self, sym: str) -> dict:
        cs = _read_json(self.out_dir / "coin_state.json") or {}
        c = cs.get(sym, {})
        return {"size_mult": float(c.get("size_mult", 1.0)), "enabled": bool(c.get("enabled", True))}

    def _tick(self, sym: str) -> float:
        if sym in self.ticks:
            return float(self.ticks[sym])
        st = _read_json(self.state_dir / f"{sym}_agent.json") or {}
        t = st.get("tick") or latest_tick(sym, self.data_dir) or book_tick(sym, self.data_dir)
        if not t:
            raise RuntimeError(f"{sym}: unknown tick size; download one day of trades first (run_download_history.bat)")
        return float(t)

    def _build(self, sym: str, table: Optional[EdgeTable], state: Optional[dict], tick: float) -> CalibrationAgent:
        coin = self._coin_state(sym)
        cfg = replace(self.sim_cfg, lot_usd=self.sim_cfg.lot_usd * coin["size_mult"])
        a = CalibrationAgent(self.agent_cfg, cfg, tick, table)
        if state:
            a.load_state(state)
        a.stopped = not coin["enabled"]
        a._enabled = coin["enabled"]
        return a

    def agent_for(self, sym: str) -> CalibrationAgent:
        if sym not in self.agents:
            tick = self._tick(sym)
            t = _read_json(self.state_dir / f"{sym}_table.json")
            table = EdgeTable.from_dict(t) if t else None
            self.agents[sym] = self._build(sym, table, _read_json(self.state_dir / f"{sym}_agent.json"), tick)
            self._st[sym] = {"day": None, "next": None, "first": None, "last": None, "hist": 0}
        return self.agents[sym]

    def _save_start(self, sym: str, day_no: int) -> None:
        a = self.agents[sym]
        _json(self.state_dir / f"{sym}_start_{day_str(day_no)}.json",
              {"table": a.table.to_dict(), "agent": a.state_dict(), "tick": a.tick, "sim_cfg": asdict(a.sim_cfg),
               "enabled": getattr(a, "_enabled", True)})

    # ------------------------------------------------------------------ events
    def handle(self, raw: str, recv_us: int) -> None:
        self.recorder.handle(raw, recv_us)
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        stream = msg.get("stream", "")
        if "@" not in stream:
            return
        s, kind = stream.split("@", 1)
        sym = s.upper()
        if sym not in self.symbols or kind not in ("bookTicker", "aggTrade"):
            return
        d = msg.get("data", {})
        a = self.agent_for(sym)
        st = self._st[sym]
        ts = int(recv_us)
        if st["next"] is None:
            st["next"] = -(-ts // self.step) * self.step
        if st["day"] is None:
            st["day"] = ts // DAY_US
            self._save_start(sym, st["day"])
        self._advance(sym, ts, inclusive=False)
        if ts // DAY_US != st["day"]:
            self._roll(sym, ts // DAY_US)
        a = self.agents[sym]
        if kind == "bookTicker":
            _, _, bid, bq, ask, aq = parse_book(d, ts)
            a.on_book(ts, bid, ask, bq, aq)
        else:
            _, _, px, qty, side = parse_trade(d, ts)
            a.on_trade(ts, px, qty, side)

    def tick(self, now: int) -> None:
        """Fire every decision timer up to ``now`` (call about once a second)."""
        for sym in list(self._st):
            if self._st[sym]["next"] is not None:
                self._advance(sym, int(now), inclusive=True)
                if self.log_sim_states:
                    self._log_sim_state(sym, int(now))

    # ------------------------------------------------------------------ quote state, snapshot (paper only)
    log_sim_states = True                 # the testnet session logs real order states itself

    def _state_logger(self, sym: str) -> StateLogger:
        if sym not in self._state_logs:
            self._state_logs[sym] = StateLogger(self.out_dir / sym)
        return self._state_logs[sym]

    def _log_sim_state(self, sym: str, now: int) -> None:
        a = self.agents[sym]
        info = sim_info(a, now)
        log = self._state_logger(sym)
        for side in (1, -1):
            live = a.live
            if info["warmup"]:
                st, detail = "WARMUP", None
            elif info["stale"]:
                st, detail = "STALE_FEED", None
            elif a.stopped:
                st, detail = "LOSS_STOP", {"enabled": getattr(a, "_enabled", True)}
            elif live._capped(side):
                st, detail = "INV_CAP", {"lots": live.q, "q_max": live.cfg.q_max}
            elif live._pending[side] is not None or live.orders[side] is not None:
                st, detail = "QUOTING", None
            else:
                st, detail = "POLICY_OUT", {"live_arm": info["live_arm"], "score_bp": info.get("score_bp")}
            log.update(side, st, detail, now)

    def log_session(self, op: str, args: dict) -> None:
        """``session.jsonl``: appended at every start and clean stop, one file per symbol."""
        for sym in self.symbols:
            folder = self.out_dir / sym
            folder.mkdir(parents=True, exist_ok=True)
            a = self.agents.get(sym)
            rec = {"ts_us": now_us(), "op": op, "pid": os.getpid(), "args": args}
            if op == "start":
                rec["pos_at_start"] = a.live.q if a is not None else 0
            with open(folder / "session.jsonl", "a") as fh:
                fh.write(json.dumps(rec, default=str) + "\n")

    def _write_snapshot(self) -> None:
        """``snapshot.json``: what the dashboard's Live tab polls for the paper trader."""
        syms = {}
        for sym, a in self.agents.items():
            live = a.live
            bk = live._book
            orders = {}
            for side, name in ((1, "bid"), (-1, "ask")):
                o = live.orders[side]
                if o is not None:
                    orders[name] = {"price": o.price, "queue_ahead": o.queue_ahead}
            syms[sym] = {"bid": bk[0] * live.tick if bk else None, "ask": bk[1] * live.tick if bk else None,
                         "q": live.q, "pnl_day": live.pnl - getattr(a, "_day_start_pnl", 0.0),
                         "fills_day": len(live._fills), "orders": orders, "live_arm": a.live_arm,
                         "loss_stop": bool(a.stopped), "state": self._state_logger(sym).snapshot()}
        _json(self.out_dir / "snapshot.json", {"kind": "paper", "ts_utc": datetime.now(timezone.utc).isoformat(),
                                               "symbols": syms})

    def _advance(self, sym: str, ts: int, inclusive: bool) -> None:
        st = self._st[sym]
        while st["next"] < ts or (inclusive and st["next"] == ts):
            T = st["next"]
            if T // DAY_US != st["day"]:
                self._roll(sym, T // DAY_US)
            self.agents[sym].on_timer(T)
            if st["first"] is None:
                st["first"] = T
            st["last"] = T
            st["next"] = T + self.step

    # ------------------------------------------------------------------ days and files
    def _write_day_files(self, sym: str, final: bool) -> None:
        a, st = self.agents[sym], self._st[sym]
        if st["day"] is None:
            return
        day = day_str(st["day"])
        folder = self.out_dir / sym
        folder.mkdir(parents=True, exist_ok=True)
        res = a.result(day=a.live._day)
        res.fills.to_parquet(folder / f"fills_{day}.parquet", index=False)
        new = a.history[st["hist"]:]
        if new:
            with open(folder / f"history_{day}.jsonl", "a") as fh:
                for h in new:
                    fh.write(json.dumps(h) + "\n")
            st["hist"] = len(a.history)
        if final:
            _json(folder / f"day_{day}.json", {"date": day, "fills": int(len(res.fills)), "pnl": float(res.totals["pnl"]),
                                               "first_timer": st["first"], "last_timer": st["last"],
                                               "decision_ms": int(a.sim_cfg.decision_ms), "live_arm": a.live_arm})

    def _roll(self, sym: str, new_day: int) -> None:
        """Close the day: write its files, end_day, pick up coin_state, save start-of-day state."""
        self._write_day_files(sym, final=True)
        a = self.agents[sym]
        a.end_day()
        coin = self._coin_state(sym)
        if abs(a.sim_cfg.lot_usd - self.sim_cfg.lot_usd * coin["size_mult"]) > 1e-12:
            a = self._build(sym, a.table, a.state_dict(), a.tick)       # new lot size: fresh sims, same learning
            self.agents[sym] = a
        a._enabled = coin["enabled"]
        a.stopped = not coin["enabled"]
        st = self._st[sym]
        st.update(day=new_day, first=None, last=None)
        self._save_start(sym, new_day)

    def checkpoint(self) -> None:
        """Every 60 s: save the feed, the learned state and today's fills and history."""
        self.recorder.flush()
        for sym, a in self.agents.items():
            _json(self.state_dir / f"{sym}_table.json", a.table.to_dict())
            _json(self.state_dir / f"{sym}_agent.json", {**a.state_dict(), "tick": a.tick})
            self._write_day_files(sym, final=False)
        if self.log_sim_states:
            self._write_snapshot()


def replay_day(start: dict, book: pd.DataFrame, trades: pd.DataFrame, info: dict,
               agent_cfg: AgentConfig = AgentConfig()) -> QSResult:
    """Re-run one paper day from its start-of-day state, recorded feed and timer schedule."""
    cfg = QSConfig(**{k: (tuple(v) if k == "markouts_s" else v) for k, v in start["sim_cfg"].items()})
    a = CalibrationAgent(agent_cfg, cfg, start["tick"], EdgeTable.from_dict(start["table"]))
    a.load_state(start["agent"])
    a.stopped = not start.get("enabled", True)
    step = int(info["decision_ms"]) * 1000
    timers = (np.arange(info["first_timer"], info["last_timer"] + 1, step, dtype=np.int64)
              if info.get("first_timer") is not None else np.empty(0, np.int64))
    bt = book["ts_us"].to_numpy(np.int64) if len(book) else np.empty(0, np.int64)
    tt = trades["ts_us"].to_numpy(np.int64) if len(trades) else np.empty(0, np.int64)
    ts = np.concatenate([bt, tt, timers])
    kind = np.concatenate([np.zeros(bt.size, np.int8), np.ones(tt.size, np.int8), np.full(timers.size, 2, np.int8)])
    idx = np.concatenate([np.arange(bt.size), np.arange(tt.size), np.arange(timers.size)])
    B = book[["bid", "ask", "bid_qty", "ask_qty"]].to_numpy(float) if len(book) else None
    if len(trades):
        P, Q, D = trades["price"].to_numpy(float), trades["qty"].to_numpy(float), trades["side"].to_numpy().astype(int)
    for o in np.lexsort((idx, kind, ts)):
        k, i, t = kind[o], idx[o], int(ts[o])
        if k == 0:
            a.on_book(t, *B[i])
        elif k == 1:
            a.on_trade(t, P[i], Q[i], D[i])
        else:
            a.on_timer(t)
    a.end_day()
    return a.result(day=0)


async def _run(session: PaperSession, hours: Optional[float]) -> None:
    import websockets

    url = combined_url(session.symbols)
    deadline = None if hours is None else time.monotonic() + hours * 3600
    last_ckpt = time.monotonic()

    async def ticker():
        nonlocal last_ckpt
        while True:
            await asyncio.sleep(1.0)
            session.tick(now_us())
            if time.monotonic() - last_ckpt >= 60:
                session.checkpoint()
                last_ckpt = time.monotonic()
                print(f"[{time.strftime('%H:%M:%S')}] checkpoint: " + ", ".join(
                    f"{s} q={a.live.q} pnl={a.live.pnl:.2f} arm={a.live_arm}{' STOP' if a.stopped else ''}"
                    for s, a in session.agents.items()), flush=True)

    tk = asyncio.create_task(ticker())
    backoff = 1.0
    try:
        while deadline is None or time.monotonic() < deadline:
            try:
                async with websockets.connect(url, ping_interval=20, max_queue=10_000) as ws:
                    print(f"paper trading (no orders are sent): {', '.join(session.symbols)}", flush=True)
                    backoff = 1.0
                    async for raw in ws:
                        session.handle(raw, now_us())
                        if deadline is not None and time.monotonic() >= deadline:
                            break
            except (OSError, asyncio.TimeoutError, websockets.ConnectionClosed) as e:
                print(f"connection lost ({e!r}); reconnecting in {backoff:.0f}s", flush=True)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
    finally:
        tk.cancel()
        session.checkpoint()


def _main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m mm.paper")
    ap.add_argument("--symbols", default=None)
    ap.add_argument("--symbols-file", default=None)
    ap.add_argument("--state", default="data/paper/state")
    ap.add_argument("--out", default="data/paper")
    ap.add_argument("--hours", type=float, default=None)
    args = ap.parse_args(argv)
    syms = read_symbols_file(args.symbols_file) if args.symbols_file else (args.symbols or "").split(",")
    syms = [s.strip().upper() for s in syms if s.strip()]
    if not syms:
        ap.error("give --symbols or --symbols-file")
    session = PaperSession(syms, args.state, args.out)
    for s in syms:
        session.agent_for(s)                 # fail early on an unknown tick
    session.log_session("start", vars(args))
    try:
        asyncio.run(_run(session, args.hours))
        session.log_session("stop", vars(args))
    except KeyboardInterrupt:
        session.log_session("stop", vars(args))
        print("stopped")


if __name__ == "__main__":
    _main()
