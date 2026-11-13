import numpy as np
import pandas as pd
import pytest

from mm.calibrate import (calibrate, fill_curve, gamma_from_skew, infer_tick, random_entry_markouts,
                          spread_estimate, tier_of, typical_spread)
from mm.data import trades_to_bars
from mm.strategy import reservation_price, ASParams


def synthetic_trades(n_sec=7200, price=0.05, tick=1e-5, spread_ticks=3, sigma_ticks=2.0, k_true=None, seed=0):
    """A coin quoted spread_ticks wide; each second one buy at the ask and one sell at the bid,
    plus occasional sweeps whose depth beyond the mid is exponential (so lambda(delta) is exponential)."""
    rng = np.random.default_rng(seed)
    mid = price + np.cumsum(rng.standard_normal(n_sec)) * sigma_ticks * tick
    mid = np.round(mid / tick) * tick + tick / 2 * (spread_ticks % 2)
    half = spread_ticks * tick / 2
    rows = []
    for s in range(n_sec):
        t = 1_700_000_000_000_000 + s * 1_000_000
        rows.append((t + 100_000, mid[s] + half, 1.0, 1))
        rows.append((t + 200_000, mid[s] - half, 1.0, -1))
        if k_true and rng.random() < 0.5:
            depth = rng.exponential(1 / k_true)
            side = rng.choice([1, -1])
            rows.append((t + 300_000, mid[s] + side * (half + depth), 1.0, side))
    df = pd.DataFrame(rows, columns=["ts_us", "price", "qty", "side"])
    df["price"] = np.round(df["price"] / tick) * tick
    df["side"] = df["side"].astype("int8")
    return df


def test_infer_tick():
    assert infer_tick(np.array([100.00, 100.01, 100.03, 100.07])) == pytest.approx(0.01)
    assert infer_tick(np.array([0.04512, 0.04513, 0.04515])) == pytest.approx(1e-5)


def test_spread_estimate_recovers_quoted_spread():
    t = synthetic_trades(n_sec=600, tick=1e-5, spread_ticks=3)
    s = spread_estimate(t)
    assert typical_spread(s, 1e-5) == pytest.approx(3e-5, rel=0.01)


def test_tiers():
    assert [tier_of(v) for v in (2e9, 1e8, 1e7, 1e6)] == ["large", "mid", "small", "micro"]


def test_gamma_from_skew_hits_target():
    g = gamma_from_skew(skew_bp=10, mid=0.05, sigma=2e-5, q_max=10, horizon_s=3600)
    r = reservation_price(0.05, 10, 0.0, ASParams(gamma=g, sigma=2e-5, k=1.0, T=3600))
    assert (0.05 - r) / 0.05 * 1e4 == pytest.approx(10)


def test_fill_curve_recovers_exponential_decay():
    tick, k_true = 1e-5, 1 / (8e-5)          # sweeps reach ~8 ticks beyond the touch on average
    t = synthetic_trades(n_sec=20_000, tick=tick, spread_ticks=2, sigma_ticks=0.3, k_true=k_true, seed=1)
    fc = fill_curve(trades_to_bars(t, 1000), tick, fit_from=6 * tick)
    assert fc["k"] == pytest.approx(k_true, rel=0.25)
    assert fc["r2"] > 0.9


def test_random_entry_markouts_are_near_zero():
    t = synthetic_trades(n_sec=20_000, seed=2)
    bars = trades_to_bars(t, 100)
    mk = random_entry_markouts(bars, 100, n=20_000)
    assert mk["markout_bp"].abs().max() < 0.5


def test_calibrate_units_are_consistent():
    t = synthetic_trades(n_sec=3600, price=0.05, tick=1e-5, spread_ticks=3, sigma_ticks=2.0, k_true=1 / 8e-5)
    c = calibrate(t, "TESTUSDT", "2026-01-01")
    assert c["tick"] == pytest.approx(1e-5)
    assert c["spread_ticks"] == pytest.approx(3, rel=0.05)
    assert c["spread_bp"] == pytest.approx(c["spread"] / c["price"] * 1e4)
    assert c["sigma_bp"] == pytest.approx(c["sigma"] / c["price"] * 1e4)
    assert c["tier"] == "micro"
