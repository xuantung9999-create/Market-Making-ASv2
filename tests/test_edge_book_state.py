"""v2.1 Task 16: EdgeTable state_fn, the 18-cell book state, and the causal regime feed."""
import numpy as np
import pandas as pd
import pytest

from mm import regime as rg
from mm.agent import AgentConfig, CalibrationAgent, run_agent
from mm.edge import EdgePolicy, EdgeTable, book_state, bucket_of
from mm.queue_sim import Action, JoinTouch, MarketState, QSConfig, QueueSim, run_queue_sim

S = 1_000_000


def test_book_state_is_imbalance_by_queue_ahead_by_regime():
    f = {"book_imb": 0.5, "qa_bid": 0.4, "qa_ask": 1.0, "p_toxic": 0.2}
    assert book_state(f, +1) == (2, 0, 0)               # imbalance with us, short queue, calm
    assert book_state(f, -1) == (0, 1, 0)               # imbalance against the ask side, normal queue
    assert book_state({**f, "qa_bid": 2.0, "p_toxic": 0.9}, +1) == (2, 2, 1)
    assert book_state({}, +1) == (1, 1, 0)              # neutral defaults when nothing is known
    cells = {book_state({"book_imb": i, "qa_bid": q, "p_toxic": p}, 1) for i in (-0.9, 0, 0.9) for q in (0.1, 1, 3) for p in (0, 1)}
    assert len(cells) == 18


def test_default_table_is_unchanged_and_state_fn_changes_the_key_width():
    d = EdgeTable()
    assert d.bucket({"book_imb": 0.5, "vol_ratio": 2.0}, +1) == bucket_of({"book_imb": 0.5, "vol_ratio": 2.0}, +1)
    t = EdgeTable(state_fn=book_state)
    b = t.bucket({"book_imb": 0.5, "qa_bid": 2.0, "p_toxic": 0.9}, +1)
    assert b == (2, 2, 1)
    for _ in range(40):
        t.update(Action.JOIN, b, 3.0)
    mean, se = t.estimate(Action.JOIN, b)
    assert mean > 2.0
    assert t.cell(Action.JOIN, (0, 0, 0))[0] == 0.0
    t2 = EdgeTable.from_dict(t.to_dict(), state_fn=book_state)
    assert t2.estimate(Action.JOIN, b) == t.estimate(Action.JOIN, b)


def test_edge_policy_reads_the_book_state_from_the_decision_state():
    t = EdgeTable(state_fn=book_state)
    good = (2, 0, 0)
    for _ in range(60):
        t.update(Action.JOIN, good, 4.0)
        t.update(Action.JOIN, (0, 2, 1), -4.0)
    pol = EdgePolicy(t, e_min_bp=0.0, z=0.0, gamma_bp=0.0)
    feat = {"book_imb": 0.6, "qa_bid": 0.3, "qa_ask": 0.3, "p_toxic": 0.0}
    st = MarketState(0, 99.0, 100.0, 100.0, 100.0, 1.0, feat)
    assert pol.decide(st, 0)[0] == Action.JOIN
    bad = MarketState(0, 99.0, 100.0, 100.0, 100.0, 1.0, {"book_imb": -0.6, "qa_bid": 3.0, "qa_ask": 3.0, "p_toxic": 1.0})
    assert pol.decide(bad, 0)[0] == Action.OUT


def day(seed=0, n=4000, t0=0):
    rng = np.random.default_rng(seed)
    t = t0 + np.cumsum(rng.integers(50_000, 400_000, n))
    mid = 100 + np.cumsum(rng.choice([-0.01, 0, 0.01], n))
    tape = pd.DataFrame({"ts_us": t, "bid": np.round(mid - 0.005, 2), "ask": np.round(mid + 0.005, 2),
                         "bid_qty": rng.uniform(50, 150, n), "ask_qty": rng.uniform(50, 150, n)})
    k = rng.random(n) < 0.5
    trades = pd.DataFrame({"ts_us": t[k] + 1000, "price": np.where(rng.random(k.sum()) < 0.5, tape["bid"][k], tape["ask"][k]),
                           "qty": rng.uniform(5, 40, k.sum()), "side": rng.choice([-1, 1], k.sum())})
    return tape, trades


def test_feat_extra_is_merged_into_decisions_and_default_changes_nothing():
    tape, trades = day()
    cfg = QSConfig(lot_usd=100, latency_ms=0, warmup_s=0, maker_fee_bps=0)
    from mm.features import FeatureEngine
    base = run_queue_sim(tape, trades, JoinTouch(), cfg, 0.01, features=FeatureEngine(0.01))
    seen = []

    class Spy:
        name = "spy"

        def decide(self, st, q):
            seen.append(dict(st.feat))
            return Action.JOIN, Action.JOIN

    from mm.queue_sim import _drive
    sim = QueueSim(Spy(), cfg, 0.01, FeatureEngine(0.01), feat_extra=lambda ts, bq, aq: {"qa_bid": bq, "p_toxic": 0.25})
    _drive(sim, tape, trades, cfg.decision_ms)
    assert seen and all(f["p_toxic"] == 0.25 and "qa_bid" in f for f in seen)
    assert "qa_bid" not in base.fills.columns and not any(c.startswith("f_qa") for c in base.fills.columns)


def test_agent_with_book_state_fills_18_cell_tables():
    tape, trades = day(seed=3, n=6000)
    cfg = QSConfig(lot_usd=100, latency_ms=0, warmup_s=0, maker_fee_bps=0)
    a = CalibrationAgent(AgentConfig(), cfg, 0.01, table=EdgeTable(state_fn=book_state), book_state=True)
    run_agent(tape, trades, a, cfg.decision_ms)
    a.end_day()
    keys = list(a.table._cells)
    assert keys and all(len(k) == 4 for k in keys)                     # (action, imbalance, queue, regime)
    assert a.table.pooled(Action.JOIN)[0] > 0


def test_causal_p_toxic_uses_only_past_minutes():
    train = [day(seed=s, t0=0)[1] for s in (1, 2)]
    for tr in train:
        tr["price"] = 100 + np.cumsum(np.random.default_rng(0).normal(0, 0.01, len(tr)))
    test = train[0].copy()
    f = rg.causal_p_toxic(train, test)
    assert isinstance(f, pd.Series) and ((0 <= f) & (f <= 1)).all()
    test2 = test.copy()
    cut = test2["ts_us"].iloc[len(test2) // 2]
    test2.loc[test2["ts_us"] > cut, "qty"] *= 50.0
    f2 = rg.causal_p_toxic(train, test2)
    early = f.index < (cut // rg.MIN_US) * rg.MIN_US
    assert np.array_equal(f[early].to_numpy(), f2[early].to_numpy())
    assert rg.lookup(f, int(f.index[3]) + 5 * S) == f.iloc[2]            # the value for minute 3 is minute 2's filter
