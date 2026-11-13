"""v2 Task 4: incremental, past-only market features."""
import math

import numpy as np
import pytest

from mm.features import FEATURE_NAMES, FeatureEngine

S = 1_000_000


def test_book_features():
    fe = FeatureEngine(tick=1.0)
    fe.on_book(0, 99.0, 100.0, 300.0, 100.0)
    snap = fe.snapshot(0)
    assert set(snap) == set(FEATURE_NAMES)
    assert snap["book_imb"] == pytest.approx(0.5)
    assert snap["micro_bp"] > 0                       # microprice closer to the ask
    micro = (100 * 99 + 300 * 100) / 400
    assert snap["micro_bp"] == pytest.approx((micro - 99.5) / 99.5 * 1e4)
    assert snap["spread_ticks"] == pytest.approx(1.0)


def test_flow_is_scale_free_and_decays():
    fe = FeatureEngine(tick=1.0)
    fe.on_trade(0, 100.0, 10.0, 1)
    assert fe.snapshot(0)["flow_5s"] == pytest.approx(1.0)
    assert fe.snapshot(5 * S)["flow_5s"] == pytest.approx(1.0)
    fe.on_trade(5 * S, 100.0, 10.0, -1)
    assert fe.snapshot(5 * S)["flow_5s"] == pytest.approx((5 - 10) / (5 + 10))
    b60 = 10 * 0.5 ** (5 / 60)
    assert fe.snapshot(5 * S)["flow_60s"] == pytest.approx((b60 - 10) / (b60 + 10))


def test_vol_ratio_warmup_and_value():
    fe = FeatureEngine(tick=0.01)
    rng = np.random.default_rng(1)
    mid = 100.0
    for i in range(1200):
        mid += 0.01 * rng.choice([-1, 1])
        fe.on_book(i * S, mid - 0.005, mid + 0.005, 1.0, 1.0)
        if i < 600:
            assert fe.snapshot(i * S)["vol_ratio"] == 1.0
    v = fe.snapshot(1199 * S)["vol_ratio"]
    assert math.isfinite(v) and v > 0 and v != 1.0


def test_zero_sizes_and_empty_engine():
    fe = FeatureEngine(tick=1.0)
    snap = fe.snapshot(0)
    assert all(math.isfinite(v) for v in snap.values())
    fe.on_book(0, 99.0, 100.0, 0.0, 0.0)
    snap = fe.snapshot(0)
    assert snap["book_imb"] == 0.0 and snap["micro_bp"] == 0.0


def test_past_only():
    rng = np.random.default_rng(4)
    events = []
    t, mid = 0, 100.0
    for _ in range(400):
        t += int(rng.integers(1, 20)) * S // 10
        if rng.random() < 0.5:
            mid += float(rng.choice([-1, 0, 1]))
            events.append(("book", (t, mid - 0.5, mid + 0.5, float(rng.uniform(1, 9)), float(rng.uniform(1, 9)))))
        else:
            events.append(("trade", (t, mid, float(rng.uniform(1, 9)), int(rng.choice([-1, 1])))))

    def snaps(evs):
        fe, out = FeatureEngine(tick=1.0), []
        for kind, x in evs:
            (fe.on_book if kind == "book" else fe.on_trade)(*x)
            out.append(fe.snapshot(x[0]))
        return out

    full = snaps(events)
    k = 150
    assert snaps(events[:k]) == full[:k]
