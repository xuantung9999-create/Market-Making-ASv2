"""Replay of the recorded testnet market with the agent, no daily loss stop (owner's request, 15 Nov 2026).

The testnet run of 12-15 Nov 2026 had two problems for showing inventory control: the 20 USDT daily loss stop held
for most of the time, and restarts lost the position before the L1b fix. This replays the same market instead: the
testnet order book and trades the trader recorded itself (``<archive>/feed``), one CalibrationAgent per coin started
from the earliest saved testnet agent state, running continuously across the whole recording. Same lot size, same
inventory cap (q_max), same 10 bp maker fee, same latency and queue model as the paper trader; only the loss stop is
off. Fills are simulated by the queue model: this is a replay, not a testnet result.

The testnet book is thin and sometimes prints a mid hundreds of bp away for a few seconds. Those book updates and
trades are dropped first (``clean_feed``, the same 100 bp size the live statistics use for an artifact jump), so the
replay never quotes into a glitched book; the counts are stored in the bundle's config.

Like every other replay in the project, inventory is closed at the last mid at each UTC midnight (``end_day``), so a
day's P&L is that day's alone. Hours without recorded data are not traded (the feed goes stale after 120 s).

    python -m scripts.replay_testnet
    python -m scripts.replay_testnet --archive data/testnet_archive/2026-11-15_before_fresh_run --symbols BTCUSDT

Writes dashboard/runs/replay-testnet-<first day>.js (a normal run: Risk tab = inventory, Overview = P&L).
"""
from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from mm import report
from mm.agent import AgentConfig, CalibrationAgent
from mm.edge import EdgeTable
from mm.paper import DAY_US
from mm.queue_sim import QSConfig
from mm.recorder import load_live
from mm.tape import book_from_recorder

ARCHIVE = Path("data/testnet_archive/2026-11-15_before_fresh_run")
SYMBOLS = ("BTCUSDT", "ETHUSDT")
VARIANT = "agent"
NO_LOSS_STOP = AgentConfig(max_daily_loss_usd=float("inf"))


class _Fills:
    def __init__(self, fills):
        self.fills, self.markouts = fills, None


def first_start_state(state_dir: Path, sym: str) -> tuple[str, dict]:
    files = sorted(state_dir.glob(f"{sym}_start_*.json"))
    if not files:
        raise FileNotFoundError(f"no {sym}_start_<day>.json in {state_dir}")
    return files[0].stem.rsplit("_", 1)[-1], json.loads(files[0].read_text())


def load_feed(feed_dir: Path, sym: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    book = book_from_recorder(load_live(feed_dir / sym / "book"))
    tr = load_live(feed_dir / sym / "trades")
    trades = tr.assign(ts_us=tr["recv_us"])[["ts_us", "price", "qty", "side"]].sort_values("ts_us", kind="stable")
    return book.reset_index(drop=True), trades.reset_index(drop=True)


GLITCH_BP = 100.0          # the live statistics' artifact-jump size (mm.livestats.Thresholds.jump_bp)
GLITCH_WINDOW_S = 300.0    # the reference mid: median of the per-second mid over the previous 5 minutes


def clean_feed(book: pd.DataFrame, trades: pd.DataFrame, glitch_bp: float = GLITCH_BP,
               window_s: float = GLITCH_WINDOW_S) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Drop the testnet book's glitches before the replay sees them (the live sessions flag the same thing as artifacts).

    A book update is a glitch when its mid is more than ``glitch_bp`` from the reference: the median, over the previous
    ``window_s`` whole seconds, of the last mid in each second. Weighting by time, not by update, matters: a glitch
    often prints dozens of updates in a few seconds, which would swamp a median over updates. Only past seconds are
    used, so nothing looks ahead. A trade is dropped when its price is more than ``glitch_bp`` from the last clean mid.
    Returns (book, trades, counts)."""
    counts = {"book_rows": int(len(book)), "book_dropped": 0, "trades": int(len(trades)), "trades_dropped": 0}
    if len(book) == 0:
        return book, trades, counts
    b = book.sort_values("ts_us", kind="stable").reset_index(drop=True)
    mid = (b["bid"].to_numpy(float) + b["ask"].to_numpy(float)) / 2.0
    ts = b["ts_us"].to_numpy(np.int64)
    sec = ts // 1_000_000
    per_sec = pd.Series(mid).groupby(sec).last()                 # last mid in each second that has an update
    grid = pd.Series(per_sec.values, index=per_sec.index).reindex(
        np.arange(per_sec.index.min(), per_sec.index.max() + 1)).ffill(limit=int(window_s))   # a long feed gap starts afresh
    w = int(window_s)
    med = grid.rolling(w, min_periods=1).median().shift(1)       # seconds before the current one only
    ref = med.reindex(sec).to_numpy()
    dev = np.abs(mid - ref) / np.where(ref > 0, ref, np.nan) * 1e4
    glitch = np.nan_to_num(dev, nan=0.0) > glitch_bp
    b = b[~glitch].reset_index(drop=True)
    counts["book_dropped"] = int(glitch.sum())
    if len(trades):
        t = trades.sort_values("ts_us", kind="stable").reset_index(drop=True)
        cm = pd.DataFrame({"ts_us": b["ts_us"].to_numpy(np.int64), "cmid": (b["bid"].to_numpy(float) + b["ask"].to_numpy(float)) / 2.0})
        m = pd.merge_asof(t[["ts_us"]].astype("int64"), cm, on="ts_us", direction="backward")["cmid"].to_numpy(float)
        tdev = np.abs(t["price"].to_numpy(float) - m) / np.where(m > 0, m, np.nan) * 1e4
        bad = np.nan_to_num(tdev, nan=0.0) > glitch_bp
        trades = t[~bad].reset_index(drop=True)
        counts["trades_dropped"] = int(bad.sum())
    return b, trades, counts


def make_agent(start: dict, agent_cfg: AgentConfig = NO_LOSS_STOP) -> CalibrationAgent:
    raw = dict(start["sim_cfg"])
    raw["markouts_s"] = tuple(report.MARKOUT_H)          # what the dashboard draws; does not change any decision
    cfg = QSConfig(**raw)
    a = CalibrationAgent(agent_cfg, cfg, start["tick"], EdgeTable.from_dict(start["table"]))
    a.load_state(start["agent"])
    a.stopped = False
    return a


def drive_day(a: CalibrationAgent, book: pd.DataFrame, trades: pd.DataFrame, decision_ms: int) -> None:
    """One UTC day of events, in the order replay_day uses (book, trade, timer at equal times), then end_day."""
    bt = book["ts_us"].to_numpy(np.int64)
    tt = trades["ts_us"].to_numpy(np.int64)
    if bt.size + tt.size == 0:
        return
    lo, hi = int(min(bt.min() if bt.size else tt.min(), tt.min() if tt.size else bt.min())), \
        int(max(bt.max() if bt.size else tt.max(), tt.max() if tt.size else bt.max()))
    step = int(decision_ms) * 1000
    timers = np.arange((lo // step + 1) * step, hi + 1, step, dtype=np.int64)
    ts = np.concatenate([bt, tt, timers])
    kind = np.concatenate([np.zeros(bt.size, np.int8), np.ones(tt.size, np.int8), np.full(timers.size, 2, np.int8)])
    idx = np.concatenate([np.arange(bt.size), np.arange(tt.size), np.arange(timers.size)])
    B = book[["bid", "ask", "bid_qty", "ask_qty"]].to_numpy(float)
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


def replay_symbol(archive: Path, sym: str, agent_cfg: AgentConfig = NO_LOSS_STOP,
                  log=print) -> tuple[CalibrationAgent, list[tuple[str, object]], dict]:
    """(agent, [(day, QSResult)], glitch counts) for every UTC day of the recorded feed, from the earliest saved start
    state on."""
    first_day, start = first_start_state(archive / "state", sym)
    a = make_agent(start, agent_cfg)
    book, trades = load_feed(archive / "feed", sym)
    d0 = pd.Timestamp(first_day, tz="UTC").value // 1000
    book, trades, counts = clean_feed(book[book["ts_us"] >= d0], trades[trades["ts_us"] >= d0])
    log(f"{sym}: dropped {counts['book_dropped']} of {counts['book_rows']} book updates and "
        f"{counts['trades_dropped']} of {counts['trades']} trades as testnet book glitches")
    days = sorted(set((book["ts_us"] // DAY_US).tolist()) | set((trades["ts_us"] // DAY_US).tolist()))
    out = []
    for n, d in enumerate(days):
        lo, hi = d * DAY_US, (d + 1) * DAY_US
        b = book[(book["ts_us"] >= lo) & (book["ts_us"] < hi)]
        t = trades[(trades["ts_us"] >= lo) & (trades["ts_us"] < hi)]
        drive_day(a, b, t, a.sim_cfg.decision_ms)
        date = pd.Timestamp(lo * 1000, tz="UTC").strftime("%Y-%m-%d")
        res = a.result(day=n)
        q = res.minute["q"].to_numpy(float) if len(res.minute) else np.array([0.0])
        log(f"{sym} {date}: {len(res.fills)} fills, net {res.totals.get('pnl', 0.0):+.2f} USDT, "
            f"inventory max |q| {np.abs(q).max():.0f} of {a.sim_cfg.q_max}, live arm {a.live_arm}")
        out.append((date, res))
    return a, out, counts


def build_run(archive: Path = ARCHIVE, symbols=SYMBOLS, agent_cfg: AgentConfig = NO_LOSS_STOP) -> dict:
    days, curves, hourly, markouts, wait, calib, edge, hist = [], {}, {}, [], {}, [], [], []
    cfg: Optional[QSConfig] = None
    first = None
    glitches = {}
    for sym in symbols:
        a, results, glitches[sym] = replay_symbol(archive, sym, agent_cfg)
        cfg = a.sim_cfg
        for date, res in results:
            days.append(report.day_row(res, sym, date, VARIANT, {"live_arm": a.live_arm}))
            first = date if first is None or date < first else first
        rs = [r for _, r in results]
        key = f"{sym}|{VARIANT}"
        curves[key] = report.curve(rs)
        hourly[key] = report.hourly(rs)
        nonempty = [r.fills for r in rs if len(r.fills)]
        if nonempty:
            fills = pd.concat(nonempty, ignore_index=True)
            markouts += report.markout_rows(_Fills(fills), sym, VARIANT)
            wait[sym] = report.wait_hist_of(fills)
            calib += report.calib_rows(fills, sym)
        edge += report.edge_rows(a.table, sym)
        hist += report.agent_rows(a.history, sym)
    if cfg is None or first is None:
        raise RuntimeError("nothing to replay")
    label = (f"Testnet replay: agent on the recorded testnet market, {', '.join(s[:-4] for s in symbols)}, "
             f"no loss stop, inventory cap {cfg.q_max} lots (simulated fills)")
    return report.build_bundle(f"replay-testnet-{first}", "backtest", label,
                               {"maker_fee_bps": cfg.maker_fee_bps, "latency_ms": cfg.latency_ms,
                                "queue_mult": cfg.queue_mult, "lot_usd": cfg.lot_usd, "q_max": cfg.q_max,
                                "decision_ms": cfg.decision_ms, "loss_stop": "off",
                                "source": "testnet order book and trades recorded by the testnet trader",
                                "glitch_rule": f"book updates more than {GLITCH_BP:g} bp from the previous "
                                               f"{GLITCH_WINDOW_S:g} s median mid, and trades more than {GLITCH_BP:g} bp "
                                               f"from the clean mid, are dropped",
                                "glitches_dropped": glitches},
                               days, curves=curves, hourly=hourly, markouts=markouts, wait_hist=wait or None,
                               calib=calib or None, edge=edge or None, agent=hist or None)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="python -m scripts.replay_testnet")
    ap.add_argument("--archive", default=str(ARCHIVE))
    ap.add_argument("--symbols", default=",".join(SYMBOLS))
    ap.add_argument("--out", default="dashboard/runs")
    args = ap.parse_args(argv)
    b = build_run(Path(args.archive), [s.strip().upper() for s in args.symbols.split(",") if s.strip()])
    print(f"dashboard bundle -> {report.write_bundle(b, args.out)}")


if __name__ == "__main__":
    main()
