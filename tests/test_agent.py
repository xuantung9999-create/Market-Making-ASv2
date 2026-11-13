"""v2 Task 6: the calibration agent."""
import numpy as np
import pandas as pd
import pytest

from mm.agent import MENU, START_ARM, AgentConfig, ArmSpec, CalibrationAgent, run_agent
from mm.edge import bucket_of, net_edge_bp
from mm.queue_sim import Action, QSConfig
from mm.tape import BOOK_TAPE_COLUMNS

S = 1_000_000


def sim_cfg(**kw):
    d = dict(lot_usd=99.0, latency_ms=0, decision_ms=1000, warmup_s=0, maker_fee_bps=10.0,
             q_max=10, queue_mult=0.0)
    d.update(kw)
    return QSConfig(**d)


def make_agent(**kw):
    a = CalibrationAgent(AgentConfig(**kw), sim_cfg(), tick=1.0)
    a.on_book(0, 99.0, 100.0, 100.0, 100.0)
    a.on_timer(0)
    return a


def test_menu():
    assert len(MENU) == 12
    assert MENU[START_ARM] == ArmSpec(5.0, 1.0, 2.0)
    assert MENU[0] == ArmSpec(0.0, 0.0, 0.5) and MENU[1] == ArmSpec(0.0, 0.0, 2.0)


def test_no_look_ahead_in_learning():
    a = make_agent()
    fills = a.on_trade(100 * S, 99.0, 1.0, -1)            # JOIN shadow buys at 99
    assert any(f["action"] == int(Action.JOIN) for f in fills)
    bucket = bucket_of({"book_imb": 0.0, "vol_ratio": 1.0}, +1)
    a.on_book(150 * S, 100.0, 101.0, 100.0, 100.0)         # mid 100.5 from 150 s on
    a.on_timer(159 * S)
    assert a.table.cell(Action.JOIN, bucket)[0] == 0.0
    a.on_timer(160 * S)
    n, mean, _ = a.table.cell(Action.JOIN, bucket)
    assert n == pytest.approx(1.0)
    assert mean == pytest.approx(net_edge_bp(+1, 99.0, 100.5, 10.0))
    a.on_book(161 * S, 90.0, 91.0, 100.0, 100.0)
    a.on_timer(161 * S)
    assert a.table.cell(Action.JOIN, bucket)[1] == pytest.approx(mean)


def test_shadows_have_no_inventory_cap():
    a = make_agent()
    for i in range(30):
        a.on_trade((i + 1) * S, 98.0, 1.0, -1)
        a.on_timer((i + 1) * S)
    join = a.shadows[0]
    assert join.q == 30
    assert (join.result().fills["side"] == 1).sum() == 30


def test_switching_rules():
    a = make_agent(min_arm_fills=50.0, switch_margin_bp=1.0)
    a.live_arm = 2
    a.score_mean = [0.0] * 12
    a.fill_n = [100.0] * 12
    a.score_mean[2], a.score_mean[3] = 2.0, 4.0
    assert a._maybe_switch() is True and a.live_arm == 3

    a.live_arm = 2
    a.score_mean[3] = 2.5
    assert a._maybe_switch() is False and a.live_arm == 2

    a.score_mean[3] = 4.0
    a.fill_n[3] = 49.0
    assert a._maybe_switch() is False and a.live_arm == 2


def test_interval_scoring_appends_history():
    a = CalibrationAgent(AgentConfig(interval_s=60.0), sim_cfg(), tick=1.0)
    a.on_book(0, 99.0, 100.0, 100.0, 100.0)
    for t in range(0, 181):
        a.on_timer(t * S)
    assert len(a.history) == 3
    h = a.history[0]
    assert set(h) >= {"ts_us", "live_arm", "switched", "scores", "fills"}
    assert len(h["scores"]) == 12


def trained_table(edge=8.0):
    from mm.edge import EdgeTable
    t = EdgeTable()
    for i in range(3):
        for j in range(3):
            for _ in range(100):
                t.update(Action.JOIN, (i, j), edge)
                t.update(Action.BACK, (i, j), edge - 5)
    return t


def test_loss_stop():
    a = CalibrationAgent(AgentConfig(), sim_cfg(queue_mult=1.0), tick=1.0, table=trained_table())
    a.live_arm = 0
    a.on_book(0, 99.0, 100.0, 100.0, 100.0)
    a.on_timer(0)
    live = a.live
    assert live.orders[1] is not None and live.orders[-1] is not None
    live._cash -= (live.pnl - a._day_start_pnl) + 20.01
    a.on_book(1 * S, 99.0, 100.0, 100.0, 100.0)
    a.on_timer(1 * S)
    assert a.stopped is True
    assert live.orders[1] is None and live.orders[-1] is None
    for t in range(2, 10):
        a.on_book(t * S, 99.0, 100.0, 100.0, 100.0)
        a.on_timer(t * S)
        assert live.orders[1] is None and live.orders[-1] is None
    assert a.arms[0].orders[1] is not None                 # arms keep running
    a.end_day()
    assert a.stopped is False
    a.on_book(100 * S, 99.0, 100.0, 100.0, 100.0)
    a.on_timer(100 * S)
    assert live.orders[1] is not None                      # quoting resumes the next day


def test_quotes_resume_after_end_day():
    a = CalibrationAgent(AgentConfig(), sim_cfg(), tick=1.0)
    a.live_arm = 0
    a.stopped = True
    a.end_day()
    assert a.stopped is False


def day_tape(seed, n=3000):
    rng = np.random.default_rng(seed)
    ts = np.cumsum(rng.integers(100_000, 3_000_000, n))
    mid = 1000 + np.cumsum(rng.choice([-1, 0, 0, 0, 0, 1], n))
    book, trades = [], []
    for t, m in zip(ts, mid):
        if rng.random() < 0.3:
            book.append((int(t), float(m - 1), float(m), float(rng.uniform(5, 50)), float(rng.uniform(5, 50))))
        else:
            s = int(rng.choice([-1, 1]))
            trades.append((int(t), float(m - 1 if s < 0 else m) + s * float(rng.random() < 0.15),
                           float(rng.uniform(1, 30)), s))
    return (pd.DataFrame(book, columns=BOOK_TAPE_COLUMNS),
            pd.DataFrame(trades, columns=["ts_us", "price", "qty", "side"]))


def run_days(seed):
    a = CalibrationAgent(AgentConfig(interval_s=600.0, min_arm_fills=5.0),
                         sim_cfg(queue_mult=0.5, warmup_s=60), tick=1.0)
    for d in range(2):
        tape, tr = day_tape(seed + d)
        run_agent(tape, tr, a, decision_ms=1000)
        a.end_day()
    return a


def test_determinism():
    a1, a2 = run_days(11), run_days(11)
    assert a1.history == a2.history
    pd.testing.assert_frame_equal(a1.result().fills, a2.result().fills)
    assert len(a1.history) > 0


def test_carry_over():
    a = CalibrationAgent(AgentConfig(interval_s=600.0), sim_cfg(queue_mult=0.5), tick=1.0)
    tape, tr = day_tape(5)
    run_agent(tape, tr, a, decision_ms=1000)
    table_before = a.table.to_dict()
    scores_before = (list(a.score_mean), list(a.score_n), list(a.fill_n))
    a.end_day()
    assert a.table.to_dict() == table_before
    assert (list(a.score_mean), list(a.score_n), list(a.fill_n)) == scores_before
    assert a.live.q == 0 and all(s.q == 0 for s in a.arms) and all(s.q == 0 for s in a.shadows)
    assert a.table.pooled(Action.JOIN)[0] > 0


def test_day_without_trades():
    a = CalibrationAgent(AgentConfig(interval_s=60.0), sim_cfg(), tick=1.0)
    tape = pd.DataFrame([(i * S, 99.0, 100.0, 10.0, 10.0) for i in range(0, 400, 7)], columns=BOOK_TAPE_COLUMNS)
    run_agent(tape, pd.DataFrame(columns=["ts_us", "price", "qty", "side"]), a, decision_ms=1000)
    a.end_day()
    assert a.live_arm == START_ARM
    empty = pd.DataFrame(columns=BOOK_TAPE_COLUMNS)
    run_agent(empty, pd.DataFrame(columns=["ts_us", "price", "qty", "side"]), a, decision_ms=1000)
    a.end_day()


def test_live_fills_carry_predicted_edge():
    a = CalibrationAgent(AgentConfig(), sim_cfg(queue_mult=0.0), tick=1.0, table=trained_table(edge=8.0))
    a.live_arm = 0
    a.on_book(0, 99.0, 100.0, 100.0, 100.0)
    a.on_timer(0)
    a.on_trade(1 * S, 99.0, 1.0, -1)
    a.end_day()
    f = a.result().fills
    assert len(f) == 1 and "pred_edge_bp" in f.columns
    est = a.table.estimate(Action.JOIN, bucket_of({"book_imb": 0.0, "vol_ratio": 1.0}, +1))[0]
    assert f["pred_edge_bp"].iloc[0] == pytest.approx(est)
