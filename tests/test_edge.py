"""v2 Task 5: net edge per fill, the edge table and the edge policy."""
import json

import pytest

from mm.edge import EdgePolicy, EdgeTable, bucket_of, net_edge_bp
from mm.queue_sim import Action, MarketState


def state(q_feat=None):
    return MarketState(0, 99.0, 100.0, 10.0, 10.0, 1.0, q_feat or {"book_imb": 0.0, "vol_ratio": 1.0})


def test_net_edge():
    assert net_edge_bp(+1, 100.0, 100.05, 10.0) == pytest.approx(-5.0, abs=1e-9)
    assert net_edge_bp(-1, 100.0, 99.8, 10.0) == pytest.approx(10.0, abs=1e-9)


def test_buckets():
    assert bucket_of({"book_imb": 0.5, "vol_ratio": 2.0}, +1) == (2, 1)
    assert bucket_of({"book_imb": 0.5, "vol_ratio": 2.0}, -1) == (0, 1)
    assert bucket_of({}, +1) == (1, 0)
    assert bucket_of({"book_imb": 0.0, "vol_ratio": 3.5}, +1) == (1, 2)


def test_too_few_pooled_updates():
    t = EdgeTable()
    for _ in range(19):
        t.update(Action.JOIN, (1, 0), 50.0)
        t.update(Action.BACK, (1, 0), 50.0)
    assert t.estimate(Action.JOIN, (1, 0)) == (-1e9, 0.0)
    assert EdgePolicy(t).decide(state(), 0) == (Action.OUT, Action.OUT)


def test_empty_cell_returns_pooled_mean():
    t = EdgeTable()
    for i in range(40):
        t.update(Action.JOIN, (0, 0), float(i % 5))
    mean, se = t.estimate(Action.JOIN, (2, 2))
    assert mean == pytest.approx(t.pooled(Action.JOIN)[1])
    assert se > 0


def test_forgetting():
    t = EdgeTable()
    for _ in range(2000):
        t.update(Action.JOIN, (1, 0), 5.0)
    for _ in range(2000):
        t.update(Action.JOIN, (1, 0), -5.0)
    assert t.estimate(Action.JOIN, (1, 0))[0] < -4.5


def test_shrinkage_toward_pooled():
    t = EdgeTable()
    others = [(0, 0), (0, 1), (2, 2), (1, 1)]
    for i in range(1000):
        t.update(Action.JOIN, others[i % 4], 0.0)
    for _ in range(30):
        t.update(Action.JOIN, (2, 0), 10.0)
    n, cell_mean, _ = t.cell(Action.JOIN, (2, 0))
    P = t.pooled(Action.JOIN)[1]
    assert cell_mean == pytest.approx(10.0)
    est = t.estimate(Action.JOIN, (2, 0))[0]
    assert est == pytest.approx((n * 10 + 30 * P) / (n + 30))
    assert P < est < 10


def table_with(join=8.0, back=3.0):
    t = EdgeTable()
    for i in range(3):
        for j in range(3):
            for _ in range(200):
                t.update(Action.JOIN, (i, j), join)
                t.update(Action.BACK, (i, j), back)
    return t


def test_policy_choices():
    t = table_with()
    assert EdgePolicy(t, e_min_bp=0.0, z=1.0, gamma_bp=1.0).decide(state(), 0) == (Action.JOIN, Action.JOIN)
    assert EdgePolicy(t, e_min_bp=0.0, z=1.0, gamma_bp=1.0).decide(state(), 9) == (Action.OUT, Action.JOIN)
    assert EdgePolicy(t, e_min_bp=0.0, gamma_bp=1.0).decide(state(), -9) == (Action.JOIN, Action.OUT)


def test_policy_prefers_back_when_better_and_ties_go_to_join():
    assert EdgePolicy(table_with(join=1.0, back=6.0)).decide(state(), 0) == (Action.BACK, Action.BACK)
    assert EdgePolicy(table_with(join=4.0, back=4.0)).decide(state(), 0) == (Action.JOIN, Action.JOIN)


def test_round_trip():
    t = EdgeTable(halflife_fills=123.0, n0=17.0)
    for i in range(300):
        t.update(Action.JOIN if i % 3 else Action.BACK, (i % 3, (i // 3) % 3), (i * 7 % 11) - 5.3)
    d = json.loads(json.dumps(t.to_dict()))
    t2 = EdgeTable.from_dict(d)
    for a in (Action.JOIN, Action.BACK):
        for i in range(3):
            for j in range(3):
                assert t2.estimate(a, (i, j)) == t.estimate(a, (i, j))
    t.update(Action.JOIN, (0, 0), 1.0)
    t2.update(Action.JOIN, (0, 0), 1.0)
    assert t2.estimate(Action.JOIN, (0, 0)) == t.estimate(Action.JOIN, (0, 0))
