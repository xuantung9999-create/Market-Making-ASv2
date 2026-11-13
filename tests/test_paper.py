"""v2 Task 10: the paper trader (offline: scripted websocket messages, no network)."""
import json

import numpy as np
import pandas as pd
import pytest

from mm.agent import AgentConfig, CalibrationAgent, run_agent
from mm.paper import PaperSession, replay_day
from mm.queue_sim import QSConfig
from mm.tape import BOOK_TAPE_COLUMNS

S = 1_000_000
DAY0 = 1_762_732_800 * S          # 2025-11-10 00:00:00 UTC


def scripted(seed=1, n=1500, start=DAY0 + 3600 * S, sym="ankrusdt", tick=1e-5):
    rng = np.random.default_rng(seed)
    t, m = start, 375
    msgs = []
    for i in range(n):
        t += int(rng.integers(50_000, 2_500_000))
        m += int(rng.choice([-1, 0, 0, 0, 0, 0, 1]))
        if rng.random() < 0.35:
            d = {"u": i, "s": sym.upper(), "b": f"{(m - 1) * tick:.8f}", "B": f"{rng.uniform(1e5, 9e5):.0f}",
                 "a": f"{m * tick:.8f}", "A": f"{rng.uniform(1e5, 9e5):.0f}"}
            msgs.append((json.dumps({"stream": f"{sym}@bookTicker", "data": d}), t))
        else:
            side = int(rng.choice([-1, 1]))
            px = (m - 1 if side < 0 else m) + side * int(rng.random() < 0.15)
            d = {"p": f"{px * tick:.8f}", "q": f"{rng.uniform(1e3, 3e5):.0f}", "T": t // 1000, "m": side < 0}
            msgs.append((json.dumps({"stream": f"{sym}@aggTrade", "data": d}), t))
    return msgs


def tapes(msgs):
    book, trades = [], []
    for raw, t in msgs:
        m = json.loads(raw); d = m["data"]
        if m["stream"].endswith("bookTicker"):
            book.append((t, float(d["b"]), float(d["a"]), float(d["B"]), float(d["A"])))
        else:
            trades.append((t, float(d["p"]), float(d["q"]), -1 if d["m"] else 1))
    return (pd.DataFrame(book, columns=BOOK_TAPE_COLUMNS), pd.DataFrame(trades, columns=["ts_us", "price", "qty", "side"]))


def cfgs():
    return AgentConfig(interval_s=600.0, min_arm_fills=5.0), QSConfig(stale_s=120.0, warmup_s=60.0, queue_mult=0.5)


def session(tmp_path, **kw):
    acfg, qcfg = cfgs()
    return PaperSession(["ANKRUSDT"], state_dir=tmp_path / "state", out_dir=tmp_path / "paper",
                        agent_cfg=acfg, sim_cfg=qcfg, ticks={"ANKRUSDT": 1e-5}, **kw)


def trained():
    from mm.edge import EdgeTable
    from mm.queue_sim import Action
    t = EdgeTable()
    for i in range(3):
        for j in range(3):
            for _ in range(60):
                t.update(Action.JOIN, (i, j), 30.0)
                t.update(Action.BACK, (i, j), 10.0)
    return t


def test_same_live_fills_as_run_agent(tmp_path):
    msgs = scripted()
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "ANKRUSDT_table.json").write_text(json.dumps(trained().to_dict()))
    ps = session(tmp_path)
    for raw, t in msgs:
        ps.handle(raw, t)
    ps.tick(msgs[-1][1])
    acfg, qcfg = cfgs()
    ref = CalibrationAgent(acfg, qcfg, 1e-5, trained())
    book, trades = tapes(msgs)
    run_agent(book, trades, ref, qcfg.decision_ms)
    got, want = ps.agents["ANKRUSDT"].result().fills, ref.result().fills
    assert len(want) > 0
    pd.testing.assert_frame_equal(got.reset_index(drop=True), want.reset_index(drop=True))
    assert ps.agents["ANKRUSDT"].history == ref.history


def test_unknown_stream_ignored_and_feed_recorded(tmp_path):
    ps = session(tmp_path)
    ps.handle(json.dumps({"stream": "solusdt@bookTicker", "data": {"u": 1, "b": "1", "B": "1", "a": "2", "A": "1"}}), DAY0)
    ps.handle(json.dumps({"stream": "ankrusdt@depth5", "data": {}}), DAY0 + 1)
    ps.handle(json.dumps({"result": None, "id": 1}), DAY0 + 2)
    assert "ANKRUSDT" not in ps.agents or ps.agents["ANKRUSDT"].live._last_ts is None
    for raw, t in scripted(n=50):
        ps.handle(raw, t)
    ps.checkpoint()
    assert list((tmp_path / "paper" / "feed" / "ANKRUSDT" / "book").glob("*.parquet"))


def test_state_round_trip_and_restart_resumes_live_arm(tmp_path):
    msgs = scripted(n=800)
    ps = session(tmp_path)
    for raw, t in msgs:
        ps.handle(raw, t)
    ps.agents["ANKRUSDT"].live_arm = 3
    ps.checkpoint()
    table = json.loads((tmp_path / "state" / "ANKRUSDT_table.json").read_text())
    ps2 = session(tmp_path)
    a2 = ps2.agent_for("ANKRUSDT")
    assert a2.live_arm == 3
    assert a2.table.to_dict() == table
    assert a2.score_mean == ps.agents["ANKRUSDT"].score_mean


def test_midnight_rollover_writes_day_file_and_replay_matches(tmp_path):
    first = scripted(seed=2, n=1200, start=DAY0 + 22 * 3600 * S)
    last_t = first[-1][1]
    second = scripted(seed=3, n=300, start=DAY0 + 86_400 * S + 5 * S)
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "ANKRUSDT_table.json").write_text(json.dumps(trained().to_dict()))
    ps = session(tmp_path)
    for raw, t in first + second:
        ps.handle(raw, t)
    ps.tick(second[-1][1])
    ps.checkpoint()
    day = pd.Timestamp(last_t, unit="us", tz="UTC").strftime("%Y-%m-%d")
    info = json.loads((tmp_path / "paper" / "ANKRUSDT" / f"day_{day}.json").read_text())
    assert info["fills"] > 0
    assert info["fills"] == len(pd.read_parquet(tmp_path / "paper" / "ANKRUSDT" / f"fills_{day}.parquet"))
    start = json.loads((tmp_path / "state" / f"ANKRUSDT_start_{day}.json").read_text())
    book, trades = tapes(first)
    res = replay_day(start, book, trades, info, AgentConfig(interval_s=600.0, min_arm_fills=5.0))
    assert len(res.fills) == info["fills"]
    assert res.totals["pnl"] == pytest.approx(info["pnl"], abs=1e-9)


def test_coin_state_scales_lot_and_disables(tmp_path):
    (tmp_path / "paper").mkdir(parents=True)
    (tmp_path / "paper" / "coin_state.json").write_text(json.dumps({"ANKRUSDT": {"size_mult": 0.5, "enabled": False}}))
    ps = session(tmp_path)
    a = ps.agent_for("ANKRUSDT")
    assert a.sim_cfg.lot_usd == pytest.approx(50.0)
    assert a.stopped is True
