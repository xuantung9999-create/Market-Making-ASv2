"""v2.1 Task 15: two-state regime model (mm/regime.py)."""
import numpy as np
import pandas as pd
import pytest

from mm import regime as rg

SEC = 1_000_000
MIN = 60 * SEC


def regime_series(n=2000, seed=0, p_stay=0.97):
    """Two regimes in blocks. calm: low vol, small |imbalance|, many trades, markout ~ +1 bp.
    toxic: high vol, large |imbalance|, few trades, markout ~ -6 bp."""
    rng = np.random.default_rng(seed)
    z = np.zeros(n, int)
    for i in range(1, n):
        z[i] = z[i - 1] if rng.random() < p_stay else 1 - z[i - 1]
    mu = np.array([[1.0, 0.2, 40.0, 1.0], [3.0, 0.7, 12.0, -6.0]])
    sd = np.array([[0.4, 0.1, 6.0, 1.5], [0.8, 0.12, 4.0, 2.0]])
    X = mu[z] + sd[z] * rng.standard_normal((n, 4))
    return X, z


def test_fit_finds_the_two_regimes_and_names_the_worse_markout_state_toxic():
    X, z = regime_series()
    m = rg.fit(X)
    p = m.p_toxic(X)
    assert p.shape == (len(X),) and ((0 <= p) & (p <= 1)).all()
    pred = p > 0.5
    assert (pred == (z == 1)).mean() > 0.93
    assert m.means[m.toxic][3] < m.means[1 - m.toxic][3]


def test_forward_filter_never_looks_ahead():
    X, _ = regime_series(n=800, seed=2)
    m = rg.fit(X)
    p1 = m.p_toxic(X)
    X2 = X.copy()
    X2[500:] = X2[500:][::-1]                         # scramble the future
    p2 = m.p_toxic(X2)
    assert np.array_equal(p1[:500], p2[:500]) and not np.array_equal(p1[500:], p2[500:])


def test_fit_is_deterministic_and_transition_rows_sum_to_one():
    X, _ = regime_series(seed=4)
    a, b = rg.fit(X), rg.fit(X)
    assert np.allclose(a.A, b.A) and np.allclose(a.means, b.means)
    assert np.allclose(a.A.sum(1), 1.0) and np.isclose(a.pi.sum(), 1.0)


def test_without_a_markout_column_the_volatile_state_is_toxic():
    X, z = regime_series(seed=5)
    m = rg.fit(X[:, :3], markout_col=None)
    assert m.means[m.toxic][0] > m.means[1 - m.toxic][0]


def test_minute_features_from_trades_and_fills():
    n = 36
    t = np.arange(n) * 10 * SEC                          # a trade every 10 s for 6 minutes
    px = 100 + 0.01 * np.sin(np.arange(n))
    trades = pd.DataFrame({"recv_us": t, "ts_us": t, "price": px, "qty": 1.0, "side": np.where(np.arange(n) % 3 == 0, -1, 1)})
    fills = pd.DataFrame({"ts_us": [30 * SEC, 90 * SEC], "mk10_bp": [-4.0, 2.0]})
    f = rg.minute_features(trades, fills)
    assert list(f.columns) == ["vol_bp", "abs_imb", "n_trades", "mk10_bp"] and len(f) == 6
    assert (f["n_trades"] == 6).all()
    assert f["abs_imb"].iloc[0] == pytest.approx(abs(4 - 2) / 6)       # 4 buys, 2 sells in the first minute
    assert f["mk10_bp"].iloc[0] == -4.0 and f["mk10_bp"].iloc[1] == 2.0 and f["mk10_bp"].iloc[2] == 0.0


def test_toxic_minutes_report_the_markout_gap_and_its_t_statistic():
    rng = np.random.default_rng(1)
    n = 4000
    p = np.where(rng.random(n) < 0.3, 0.9, 0.1)
    mk = np.where(p > 0.7, -5.0, 0.0) + rng.normal(0, 4, n)
    out = rg.markout_gap(p, mk, threshold=0.7)
    assert out["gap_bp"] == pytest.approx(-5.0, abs=0.7) and out["t"] < -8 and out["n_toxic"] > 1000
    assert rg.markout_gap(np.zeros(10), np.ones(10), 0.7)["n_toxic"] == 0
