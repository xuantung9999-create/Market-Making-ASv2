"""v2.1 Task 14: queue chain (mm/queue_model.py) and QueueSim(cancel_model=...)."""
import numpy as np
import pandas as pd
import pytest

from mm import queue_model as qm
from mm.queue_sim import Action, JoinTouch, QSConfig, QueueSim

S = 1_000_000
MS = 1_000


def test_classify_size_changes_at_the_best_price():
    t = 10 * S
    none = np.array([], dtype=np.int64)
    assert qm.classify(t, 5, 100.0, 5, 130.0, none) == "add"
    assert qm.classify(t, 5, 100.0, 5, 70.0, none) == "cancel"
    assert qm.classify(t, 5, 100.0, 5, 70.0, np.array([t - 30 * MS])) == "trade"
    assert qm.classify(t, 5, 100.0, 5, 70.0, np.array([t - 80 * MS])) == "cancel"
    assert qm.classify(t, 5, 100.0, 6, 70.0, none) == "move"
    assert qm.classify(t, 5, 100.0, 5, 100.0, none) is None


def test_events_from_a_book_and_trade_stream():
    book = pd.DataFrame({"recv_us": [0, 1 * S, 2 * S, 3 * S, 4 * S], "bid": [99, 99, 99, 99, 98],
                         "bid_qty": [100.0, 150.0, 90.0, 60.0, 50.0], "ask": [100] * 5, "ask_qty": [100.0] * 5})
    trades = pd.DataFrame({"recv_us": [3 * S - 10 * MS], "price": [99.0], "qty": [30.0], "side": [-1]})
    ev = qm.events(book, trades, tick=1.0, side=1)
    assert list(ev["kind"]) == ["add", "cancel", "trade", "move"]
    assert list(ev["size"])[:3] == [50.0, 60.0, 30.0]


def test_buckets_are_quantiles_and_four_wide():
    sizes = np.arange(1, 1001, dtype=float)
    edges = qm.bucket_edges(sizes)
    assert len(edges) == 3 and list(edges) == sorted(edges)
    assert [qm.bucket(x, edges) for x in (1, 300, 600, 999)] == [0, 1, 2, 3]


def synthetic_chain(seed=0, hours=6):
    """Size at the best bid moves by adds / cancels / trades of 40, with reflecting bounds and rare moves.
    Returns the book, the trades and the true kind counts the generator produced."""
    rng = np.random.default_rng(seed)
    t, size, rows, trs = 0, 200.0, [], []
    truth = {"add": 0, "cancel": 0, "trade": 0}
    while t < hours * 3600 * S:
        t += int(rng.exponential(0.5 * S))
        u = rng.random()
        if rng.random() < 0.005:                                   # the bid steps down for one row and returns
            rows.append((t, 98.0, 200.0, 100.0, 200.0))
            t += int(0.5 * S)
            rows.append((t, 99.0, 200.0, 100.0, 200.0))
            size = 200.0
            continue
        kind = "add" if size <= 60 else ("cancel" if u < 0.5 else "trade") if size >= 500 else \
            "add" if u < 0.35 else "cancel" if u < 0.65 else "trade"
        truth[kind] += 1
        if kind == "add":
            size += 40
        elif kind == "cancel":
            size -= 40
        else:
            trs.append((t - 5 * MS, 99.0, 40.0, -1))
            size -= 40
        rows.append((t, 99.0, size, 100.0, 200.0))
    book = pd.DataFrame(rows, columns=["recv_us", "bid", "bid_qty", "ask", "ask_qty"])
    trades = pd.DataFrame(trs, columns=["recv_us", "price", "qty", "side"])
    return book, trades, truth


def test_estimated_rates_recover_the_generating_process():
    book, trades, truth = synthetic_chain()
    chain = qm.fit(book, trades, tick=1.0, side=1)
    tot = {k: sum(c.rates[k] * c.seconds for c in chain.cells.values()) for k in truth}
    n, nt = sum(tot.values()), sum(truth.values())
    for k in truth:
        assert tot[k] / n == pytest.approx(truth[k] / nt, abs=0.03)


@pytest.fixture(scope="module")
def chain():
    book, trades, _ = synthetic_chain()
    return qm.fit(book, trades, tick=1.0, side=1)


def test_p_fill_falls_as_x_rises(chain):
    p = [chain.p_fill(x, 200.0, 200.0, "proportional") for x in (0.0, 50.0, 150.0, 400.0, 900.0)]
    assert all(a >= b - 1e-9 for a, b in zip(p, p[1:])) and p[0] > p[-1]
    assert p[0] > 0.9


def test_front_ge_proportional_ge_back(chain):
    for x in (50.0, 150.0, 400.0):
        f, pr, b = (chain.p_fill(x, 300.0, 200.0, a) for a in ("front", "proportional", "back"))
        assert f >= pr - 0.02 and pr >= b - 0.02 and f > b


def test_p_fill_is_deterministic(chain):
    assert chain.p_fill(120.0, 250.0, 200.0, "proportional") == chain.p_fill(120.0, 250.0, 200.0, "proportional")
    book, trades, _ = synthetic_chain()
    other = qm.fit(book, trades, tick=1.0, side=1)
    assert other.p_fill(120.0, 250.0, 200.0, "back") == chain.p_fill(120.0, 250.0, 200.0, "back")


def stream(sim, steps):
    return [getattr(sim, "on_" + k)(*a) for k, *a in steps]


def cfg():
    return QSConfig(lot_usd=99.0, latency_ms=0, decision_ms=1000, warmup_s=0, maker_fee_bps=0, q_max=None)


def sim_with(**kw):
    s = QueueSim(JoinTouch(), cfg(), tick=1.0, **kw)
    s.on_book(0, 99.0, 100.0, 100.0, 100.0)
    s.on_timer(0)
    return s


STEPS = [("book", 1 * S, 99.0, 100.0, 180.0, 100.0), ("book", 2 * S, 99.0, 100.0, 120.0, 100.0),
         ("trade", 2 * S + 5 * MS, 99.0, 30.0, -1), ("book", 2 * S + 10 * MS, 99.0, 100.0, 90.0, 100.0),
         ("trade", 3 * S, 99.0, 50.0, -1), ("trade", 4 * S, 99.0, 50.0, -1), ("trade", 5 * S, 99.0, 50.0, -1)]


def test_no_cancel_model_is_identical_to_the_current_engine():
    base = QueueSim(JoinTouch(), cfg(), tick=1.0)          # constructed without the keyword at all
    base.on_book(0, 99.0, 100.0, 100.0, 100.0); base.on_timer(0)
    explicit = sim_with(cancel_model=None)
    assert stream(base, STEPS) == stream(explicit, STEPS)


def test_cancel_models_move_the_queue_as_assumed():
    out = {}
    for a in ("front", "proportional", "back"):
        s = sim_with(cancel_model=qm.CancelModel(a))
        stream(s, STEPS[:2])                               # 100 -> 180 (add), 180 -> 120 (cancel of 60)
        out[a] = s.orders[1].queue_ahead
    assert out["front"] == pytest.approx(40.0)
    assert out["proportional"] == pytest.approx(100 - 60 * 100 / 180)
    assert out["back"] == pytest.approx(100.0)


def test_a_trade_driven_size_drop_is_not_treated_as_a_cancel():
    s = sim_with(cancel_model=qm.CancelModel("front"))
    stream(s, STEPS[:2])
    before = s.orders[1].queue_ahead
    s.on_trade(2 * S + 5 * MS, 99.0, 30.0, -1)
    s.on_book(2 * S + 10 * MS, 99.0, 100.0, 90.0, 100.0)
    assert s.orders[1].queue_ahead == pytest.approx(before - 30.0)


def test_calibration_deciles_and_the_pass_rule():
    rng = np.random.default_rng(0)
    pred = rng.random(5000)
    ok = qm.calibration(pred, rng.random(5000) < pred)
    assert len(ok["deciles"]) == 10 and ok["n_within"] >= 8 and ok["pass"]
    bad = qm.calibration(pred, rng.random(5000) < 0.5 * pred)
    assert not bad["pass"]
