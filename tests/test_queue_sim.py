"""v2 Task 3: the queue engine (BUILD_GUIDE section 5)."""
from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

from mm.metrics import summarize
from mm.queue_sim import Action, Fixed, JoinTouch, QSConfig, QueueSim, _drive, run_queue_sim
from mm.tape import BOOK_TAPE_COLUMNS

S = 1_000_000          # one second in microseconds
MS = 1_000


def base_cfg(**kw):
    d = dict(lot_usd=99.0, latency_ms=0, decision_ms=1000, warmup_s=0, maker_fee_bps=0, q_max=None)
    d.update(kw)
    return QSConfig(**d)


def make(policy=None, **kw):
    """Constant book bid 99 / ask 100, sizes 100, tick 1; first decision at t=0."""
    sim = QueueSim(policy or JoinTouch(), base_cfg(**kw), tick=1.0)
    sim.on_book(0, 99.0, 100.0, 100.0, 100.0)
    sim.on_timer(0)
    return sim


@dataclass
class Switch:
    bid: Action = Action.JOIN
    ask: Action = Action.JOIN
    name: str = "switch"

    def decide(self, st, q):
        return self.bid, self.ask


def buys(fills):
    return [f for f in fills if f["side"] == 1]


def test_queue_position():
    sim = make()
    assert sim.on_trade(1 * MS, 99.0, 60.0, -1) == []
    assert sim.on_trade(2 * MS, 99.0, 30.0, -1) == []
    f = sim.on_trade(3 * MS, 99.0, 20.0, -1)
    assert len(f) == 1 and f[0]["price"] == 99.0 and f[0]["side"] == 1


def test_through_trade_fills_whatever_the_queue():
    sim = make(queue_mult=1e12)
    f = sim.on_trade(1 * MS, 98.0, 0.001, -1)
    assert len(f) == 1 and f[0]["price"] == 99.0


def test_queue_mult_zero_and_huge():
    assert len(make(queue_mult=0.0).on_trade(1 * MS, 99.0, 0.001, -1)) == 1
    sim = make(queue_mult=1e12)
    for i in range(50):
        assert sim.on_trade((i + 1) * MS, 99.0, 1e6, -1) == []
    assert len(sim.on_trade(60 * MS, 98.0, 1.0, -1)) == 1


def test_latency_on_new_orders():
    sim = make(latency_ms=300)
    assert sim.on_trade(200 * MS, 98.0, 1.0, -1) == []
    assert len(sim.on_trade(400 * MS, 98.0, 1.0, -1)) == 1


@pytest.mark.parametrize("dt_ms, fills", [(200, 1), (400, 0)])
def test_cancel_latency(dt_ms, fills):
    pol = Switch()
    sim = make(pol, latency_ms=300)
    sim.on_book(500 * MS, 99.0, 100.0, 100.0, 100.0)        # an event, so the next timer is not skipped
    pol.bid = pol.ask = Action.OUT
    sim.on_timer(1 * S)
    assert len(sim.on_trade(1 * S + dt_ms * MS, 98.0, 1.0, -1)) == fills


def test_keep_queue_position_across_decisions():
    sim = make()
    sim.on_trade(1 * MS, 99.0, 60.0, -1)
    sim.on_timer(1 * S)
    assert sim.orders[1].queue_ahead == pytest.approx(40.0)
    assert len(sim.on_trade(1 * S + 1 * MS, 99.0, 50.0, -1)) == 1


def test_requeue_when_best_moves():
    sim = make()
    sim.on_trade(1 * MS, 99.0, 60.0, -1)
    sim.on_book(500 * MS, 100.0, 101.0, 100.0, 100.0)
    sim.on_timer(1 * S)
    o = sim.orders[1]
    assert o.price == 100.0 and o.queue_ahead == pytest.approx(100.0)


def test_back_rests_one_tick_behind():
    sim = make(Fixed(Action.BACK, Action.OUT))
    assert sim.orders[1].price == 98.0 and sim.orders[-1] is None
    assert sim.on_trade(1 * MS, 99.0, 1e6, -1) == []
    assert sim.on_trade(2 * MS, 98.0, 60.0, -1) == []
    assert len(sim.on_trade(3 * MS, 98.0, 50.0, -1)) == 1
    sim2 = make(Fixed(Action.BACK, Action.OUT))
    assert len(sim2.on_trade(1 * MS, 97.0, 0.1, -1)) == 1


def test_back_queue_mult():
    sim = make(Fixed(Action.BACK, Action.OUT), back_queue_mult=0.5)
    assert sim.orders[1].queue_ahead == pytest.approx(50.0)


def test_post_only_rejection():
    sim = QueueSim(JoinTouch(), base_cfg(latency_ms=300), tick=1.0)
    sim.on_book(0, 99.0, 100.0, 100.0, 100.0)
    sim.on_timer(0)                                      # targets bid 99 / ask 100, live at 300 ms
    sim.on_book(100 * MS, 98.0, 99.0, 100.0, 100.0)      # book drops: our bid 99 would cross the ask
    sim.on_book(350 * MS, 98.0, 99.0, 100.0, 100.0)
    assert sim.orders[1] is None
    assert buys(sim.on_trade(400 * MS, 97.0, 1.0, -1)) == []


def test_book_shrink_caps_queue():
    sim = make()
    sim.on_book(1 * MS, 99.0, 100.0, 30.0, 100.0)
    assert sim.orders[1].queue_ahead == pytest.approx(30.0)


def test_inventory_cap():
    sim = make(q_max=1, queue_mult=0.0)
    assert len(sim.on_trade(1 * MS, 99.0, 1.0, -1)) == 1
    assert sim.q == 1 and sim.orders[1] is None
    sim.on_timer(1 * S)
    assert sim.orders[1] is None
    assert sim.on_trade(1 * S + 1 * MS, 98.0, 1.0, -1) == []
    f = sim.on_trade(1 * S + 2 * MS, 100.0, 1.0, 1)
    assert len(f) == 1 and f[0]["side"] == -1 and sim.q == 0


def test_cap_cancels_resting_bid_immediately():
    sim = make(q_max=1, queue_mult=0.0)
    sim.on_trade(1 * MS, 99.0, 1.0, -1)             # buy fill -> q = 1
    sim.on_timer(1 * S)                             # sell side requotes; bid stays OUT
    assert sim.orders[1] is None and sim.orders[-1] is not None


def test_stale_data_forces_out_and_recovers():
    sim = make(stale_s=120.0)
    assert sim.orders[1] is not None
    for t in range(1, 122):
        sim.on_timer(t * S)
    assert sim.orders[1] is None and sim.orders[-1] is None
    sim.on_book(125 * S, 99.0, 100.0, 100.0, 100.0)
    assert sim.orders[1] is None
    sim.on_timer(126 * S)
    assert sim.orders[1] is not None and sim.orders[-1] is not None


def random_day(seed=7, n=5000, tick=0.01):
    rng = np.random.default_rng(seed)
    ts = np.cumsum(rng.integers(1_000, 400_000, n))
    mid_ticks = 10_000 + np.cumsum(rng.choice([-1, 0, 0, 0, 1], n))
    is_book = rng.random(n) < 0.4
    book_rows, trade_rows = [], []
    for t, m, b in zip(ts, mid_ticks, is_book):
        bid, ask = (m - 1) * tick, m * tick
        if b:
            book_rows.append((int(t), bid, ask, float(rng.uniform(1, 50)), float(rng.uniform(1, 50))))
        else:
            side = int(rng.choice([-1, 1]))
            px = (bid if side < 0 else ask) + side * tick * int(rng.random() < 0.2)
            trade_rows.append((int(t), px, float(rng.uniform(0.1, 30)), side))
    tape = pd.DataFrame(book_rows, columns=BOOK_TAPE_COLUMNS)
    trades = pd.DataFrame(trade_rows, columns=["ts_us", "price", "qty", "side"])
    return tape, trades, tick


def test_pnl_identity_on_random_tape():
    tape, trades, tick = random_day()
    cfg = QSConfig(maker_fee_bps=10.0, warmup_s=0, q_max=None, queue_mult=0.2)
    res = run_queue_sim(tape, trades, JoinTouch(), cfg, tick)
    tot = res.totals
    assert len(res.fills) > 50
    assert abs(tot["pnl"] - (tot["spread_capture"] + tot["inventory_pnl"] - tot["fees"])) < 1e-9
    m = res.minute
    assert np.allclose(m["pnl"], m["spread_capture"] + m["inventory_pnl"] - m["fees"], atol=1e-9)
    assert abs(m["pnl"].iloc[-1] - tot["pnl"]) < 1e-9
    assert tot["final_q"] == 0                                    # end of day resets inventory


def test_timer_skipping_does_not_change_results():
    tape, trades, tick = random_day(seed=3)
    cfg = QSConfig(maker_fee_bps=10.0, warmup_s=30, q_max=3, latency_ms=300)
    out = []
    for skip in (True, False):
        sim = QueueSim(JoinTouch(), cfg, tick)
        sim._skip_idle = skip
        _drive(sim, tape, trades, cfg.decision_ms)
        sim.end_day()
        out.append(sim.result().fills.drop(columns=["bar"]))
    pd.testing.assert_frame_equal(out[0], out[1])


def test_summarize_works_on_queue_results():
    tape, trades, tick = random_day(seed=5)
    res = run_queue_sim(tape, trades, JoinTouch(), QSConfig(warmup_s=0, queue_mult=0.2), tick)
    s = summarize(res)
    assert s["fills"] == len(res.fills) and "markout_60s_bp" in s and "net_10bp" in s
    for col in ("ts_us", "qty", "mid", "wait_s", "action", "side", "price", "t_s", "net_edge_bp"):
        assert col in res.fills.columns


def test_fill_columns_carry_decision_features():
    class Feat:
        def on_book(self, *a): pass
        def on_trade(self, *a): pass
        def snapshot(self, ts_us): return {"x": ts_us / S}
    sim = QueueSim(JoinTouch(), base_cfg(queue_mult=0.0), tick=1.0, features=Feat())
    sim.on_book(0, 99.0, 100.0, 100.0, 100.0)
    sim.on_timer(0)
    sim.on_book(500 * MS, 99.0, 100.0, 100.0, 100.0)
    sim.on_timer(1 * S)                                # keeps the order: features of the latest decision
    sim.on_trade(1 * S + 1, 99.0, 1.0, -1)
    sim.end_day()
    assert sim.result().fills["f_x"].tolist() == [1.0]


def test_markouts_exclude_fills_without_a_full_horizon():
    tape = pd.DataFrame([(0, 99.0, 100.0, 100.0, 100.0), (30 * S, 99.0, 100.0, 100.0, 100.0)],
                        columns=BOOK_TAPE_COLUMNS)
    trades = pd.DataFrame([(1 * S, 99.0, 1.0, -1)], columns=["ts_us", "price", "qty", "side"])
    res = run_queue_sim(tape, trades, JoinTouch(), base_cfg(queue_mult=0.0), 1.0)
    assert len(res.fills) == 1 and np.isnan(res.fills["net_edge_bp"].iloc[0])
    mk = res.markouts.set_index("h_s")
    assert mk.loc[0, "markout_bp"] == pytest.approx(0.5 / 99 * 1e4)
    assert np.isnan(mk.loc[60, "markout_bp"])


def test_empty_inputs():
    empty_tape = pd.DataFrame(columns=BOOK_TAPE_COLUMNS)
    empty_trades = pd.DataFrame(columns=["ts_us", "price", "qty", "side"])
    res = run_queue_sim(empty_tape, empty_trades, JoinTouch(), QSConfig(), 1.0)
    assert len(res.fills) == 0 and res.totals["pnl"] == 0
    tape = pd.DataFrame([(0, 99.0, 100.0, 1.0, 1.0)], columns=BOOK_TAPE_COLUMNS)
    res = run_queue_sim(tape, empty_trades, JoinTouch(), QSConfig(), 1.0)
    assert len(res.fills) == 0 and res.totals["pnl"] == 0
    summarize(res)


def test_out_of_order_event_is_clamped():
    sim = make(queue_mult=0.0)
    sim.on_book(5 * S, 99.0, 100.0, 100.0, 100.0)
    f = sim.on_trade(4 * S, 99.0, 1.0, -1)            # earlier than the last event
    assert len(f) == 1 and f[0]["ts_us"] == 5 * S


def test_per_day_results_add_up():
    sim = QueueSim(JoinTouch(), QSConfig(warmup_s=0, queue_mult=0.2, maker_fee_bps=10.0), 0.01)
    for seed in (1, 2):
        tape, trades, _ = random_day(seed=seed)
        off = (seed - 1) * 86_400 * S
        tape = tape.assign(ts_us=tape["ts_us"] + off)
        trades = trades.assign(ts_us=trades["ts_us"] + off)
        _drive(sim, tape, trades, 1000)
        sim.end_day()
    whole, d0, d1 = sim.result(), sim.result(day=0), sim.result(day=1)
    assert len(d0.fills) + len(d1.fills) == len(whole.fills) and len(d0.fills) > 0 and len(d1.fills) > 0
    for k in ("pnl", "spread_capture", "inventory_pnl", "fees", "notional"):
        assert d0.totals[k] + d1.totals[k] == pytest.approx(whole.totals[k], abs=1e-9)
    assert abs(d1.totals["pnl"] - (d1.totals["spread_capture"] + d1.totals["inventory_pnl"] - d1.totals["fees"])) < 1e-9
    assert d1.minute["pnl"].iloc[-1] == pytest.approx(d1.totals["pnl"], abs=1e-9)
    assert (d1.fills["ts_us"] >= 86_400 * S).all()
    summarize(d1)


def test_dashboard_fields_minute_ts_uptime_and_fill_markouts():
    tape, trades, tick = random_day(seed=9)
    res = run_queue_sim(tape, trades, JoinTouch(), QSConfig(warmup_s=0, queue_mult=0.2), tick)
    assert "ts_us" in res.minute.columns and res.minute["ts_us"].is_monotonic_increasing
    up = res.totals["uptime"]
    assert set(up) == {"bid", "ask"} and all(0.0 < v <= 1.0 for v in up.values())
    for h in (1, 10, 60, 300):
        assert f"mk_{h}" in res.fills.columns
    ok = res.fills["mk_60"].notna()
    assert np.allclose(res.fills.loc[ok, "net_edge_bp"], res.fills.loc[ok, "mk_60"] - 10.0)


def test_uptime_is_zero_when_never_quoting_and_counts_only_after_warmup():
    tape, trades, tick = random_day(seed=9)
    res = run_queue_sim(tape, trades, Fixed(Action.OUT, Action.OUT), QSConfig(warmup_s=0), tick)
    assert res.totals["uptime"] == {"bid": 0.0, "ask": 0.0}
    sim = make()                                   # quoting from t=0, warm-up 0
    sim.on_book(10 * S, 99.0, 100.0, 100.0, 100.0)
    sim.end_day()
    assert sim.result().totals["uptime"]["bid"] == pytest.approx(1.0)


def test_no_minute_rows_without_a_mid():
    trades = pd.DataFrame([(i * 30 * S, 99.0, 1.0, -1) for i in range(1, 6)], columns=["ts_us", "price", "qty", "side"])
    tape = pd.DataFrame([(200 * S, 99.0, 100.0, 1.0, 1.0)], columns=BOOK_TAPE_COLUMNS)
    res = run_queue_sim(tape, trades, JoinTouch(), base_cfg(), 1.0)
    assert len(res.minute) > 0 and res.minute["mid"].notna().all()
