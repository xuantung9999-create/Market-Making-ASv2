import numpy as np
import pandas as pd
import pytest

from mm.backtest import ASQuoter, BTConfig, run_backtest
from mm.calibrate import fit_two_part
from mm.flow import FEATURES, fit_alpha, flow_features, forward_return_bp, out_of_sample_r2, predict_alpha
from mm.protect import ProtectedAS
from mm.strategy import ASParams, quote


def bars_with_flow(n=200_000, seed=0, informed=True):
    """Bars where buy/sell imbalance over 5 s predicts the next moves (if informed)."""
    rng = np.random.default_rng(seed)
    flow = pd.Series(rng.standard_normal(n)).rolling(50, min_periods=1).mean().to_numpy()
    buy = np.clip(1 + flow * 3, 0, None) * rng.random(n)
    sell = np.clip(1 - flow * 3, 0, None) * rng.random(n)
    drift = (0.05 * flow) if informed else 0.0
    mid = 100 + np.cumsum(drift + rng.standard_normal(n) * 0.01)
    return pd.DataFrame({"ts_us": np.arange(n) * 100_000, "mid": mid, "buy_vol": buy, "sell_vol": sell,
                         "buy_max": mid + rng.exponential(0.1, n), "sell_min": mid - rng.exponential(0.1, n),
                         "sigma": 0.05, "t_s": np.arange(n) * 0.1})


def test_features_are_past_only():
    b = bars_with_flow(n=20_000)
    f_all = flow_features(b)
    f_cut = flow_features(b.iloc[:12_000])
    pd.testing.assert_frame_equal(f_all.iloc[:12_000], f_cut)


def test_alpha_model_finds_planted_signal_and_not_a_fake_one():
    real = bars_with_flow(seed=1, informed=True)
    m = fit_alpha([flow_features(real)], [forward_return_bp(real)])
    assert m.tstat[1 + FEATURES.index("imb_5s")] > 2
    test = bars_with_flow(seed=2, informed=True)
    oos = out_of_sample_r2(predict_alpha(m, flow_features(test)), forward_return_bp(test))
    assert oos["corr"] > 0.1
    noise = bars_with_flow(seed=3, informed=False)
    m0 = fit_alpha([flow_features(noise)], [forward_return_bp(noise)])
    assert abs(m0.tstat[1 + FEATURES.index("imb_5s")]) < 2


def test_predict_alpha_is_capped():
    b = bars_with_flow(n=5000)
    m = fit_alpha([flow_features(b)], [forward_return_bp(b)], cap_bp=0.5)
    m.coef[:] = 100.0
    assert np.abs(predict_alpha(m, flow_features(b))).max() == pytest.approx(0.5)


def test_protected_as_without_defences_matches_shared_quote_function():
    b = bars_with_flow(n=3000)
    pq = ProtectedAS(gamma=0.01, k=5.0, horizon_s=60, q_max=5, tick=0.01)
    pq.prepare(b)
    for i in (0, 777, 2999):
        for q in (-5, -2, 0, 3, 5):
            t = b.t_s[i]
            ref = quote(b.mid[i], q, t % 60, ASParams(gamma=0.01, sigma=0.05, k=5.0, T=60, tick_size=0.01, q_max=5))
            got = pq.quote_at(i, b.mid[i], q, t, 0.05)
            assert got == pytest.approx((ref.bid, ref.ask, ref.bid_active, ref.ask_active))


def test_backtest_identical_for_fast_and_reference_quoter():
    b = bars_with_flow(n=6000)
    cfg = BTConfig(requote_ms=100, warmup_s=0)
    a = run_backtest(b, ASQuoter(gamma=0.01, k=30.0, horizon_s=60, q_max=5, tick=0.01), cfg)
    f = run_backtest(b, ProtectedAS(gamma=0.01, k=30.0, horizon_s=60, q_max=5, tick=0.01), cfg)
    assert len(a.fills) > 20
    pd.testing.assert_frame_equal(a.fills, f.fills)


def test_kill_switch_pauses_and_lean_shifts():
    b = bars_with_flow(n=3000)
    vr = np.ones(3000); vr[1000:1010] = 5.0
    sz = np.zeros(3000); sz[2000] = 20.0
    pq = ProtectedAS(gamma=0.01, k=5.0, horizon_s=60, vol_ratio=vr, sweep_z=sz, cooldown_s=2.0)
    pq.prepare(b)
    assert pq.quote_at(1005, 100, 0, 1, 0.05)[2:] == (False, False)
    assert pq.quote_at(2015, 100, 0, 1, 0.05)[2:] == (False, False)      # within 2 s cooldown
    assert pq.quote_at(2025, 100, 0, 1, 0.05)[2:] == (True, True)
    up = ProtectedAS(gamma=0.01, k=5.0, horizon_s=60, alpha_bp=np.full(3000, 10.0))
    up.prepare(b)
    flat = ProtectedAS(gamma=0.01, k=5.0, horizon_s=60)
    flat.prepare(b)
    assert up.quote_at(5, b.mid[5], 0, 0.5, 0.05)[0] == pytest.approx(flat.quote_at(5, b.mid[5], 0, 0.5, 0.05)[0] + b.mid[5] * 1e-3)


def test_two_part_fit_recovers_core_and_tail():
    d = np.linspace(0, 60, 61)
    lam = np.where(d < 20, 0.5 * np.exp(-0.3 * d), 0.5 * np.exp(-0.3 * 20) * np.exp(-0.05 * (d - 20)))
    out = fit_two_part({"delta": d, "lam": lam})
    assert out["k_core"] == pytest.approx(0.3, rel=0.05)
    assert out["k_tail"] == pytest.approx(0.05, rel=0.1)
    assert 17 <= out["break_delta"] <= 23
    assert out["r2_two"] > out["r2_one"]
