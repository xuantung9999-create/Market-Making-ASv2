import numpy as np
import pandas as pd
import pytest

from mm.backtest import ASQuoter, BTConfig, FixedSpread, prepare_bars, run_backtest
from mm.metrics import max_drawdown, summarize

CFG = BTConfig(bar_ms=100, requote_ms=100, latency_ms=50, lot=0.001, warmup_s=0.0, sigma_halflife_s=5)


def make_bars(mid, buy_max=None, sell_min=None, sigma=1.0):
    n = len(mid)
    return pd.DataFrame({
        "ts_us": np.arange(n) * 100_000, "mid": np.asarray(mid, float),
        "buy_max": np.full(n, np.nan) if buy_max is None else np.asarray(buy_max, float),
        "sell_min": np.full(n, np.nan) if sell_min is None else np.asarray(sell_min, float),
        "sigma": np.full(n, sigma), "t_s": np.arange(n) * 0.1,
    })


def random_bars(n=6000, seed=0):
    rng = np.random.default_rng(seed)
    mid = 100_000 + np.cumsum(rng.standard_normal(n) * 0.8)
    reach = rng.exponential(3.0, n)
    has_b, has_s = rng.random(n) < 0.6, rng.random(n) < 0.6
    return make_bars(mid, np.where(has_b, mid + reach, np.nan), np.where(has_s, mid - rng.exponential(3.0, n), np.nan), 2.0)


def test_strictly_through_rule_and_fill_price():
    # quote at 100 +/- 1 computed at bar 0, live from bar 1.
    bars = make_bars([100] * 5, buy_max=[np.nan, 101.0, 101.01, np.nan, np.nan],
                     sell_min=[np.nan, 99.0, np.nan, 98.99, np.nan])
    res = run_backtest(bars, FixedSpread(1.0, q_max=None), CFG)
    f = res.fills
    assert list(f["bar"]) == [2, 3]                  # touches at bar 1 do not fill
    assert list(f["side"]) == [-1, 1] and list(f["price"]) == [101.0, 99.0]


def test_quote_never_fills_in_the_bar_it_was_computed():
    bars = make_bars([100, 100], buy_max=[200, np.nan], sell_min=[1, np.nan])
    assert run_backtest(bars, FixedSpread(1.0), CFG).fills.empty


def test_latency_delays_activation():
    bars = make_bars([100] * 6, buy_max=[np.nan, 105, 105, 105, 105, 105])
    slow = BTConfig(**{**CFG.__dict__, "latency_ms": 300, "requote_ms": 10_000})
    assert run_backtest(bars, FixedSpread(1.0), slow).fills["bar"].iloc[0] == 3


def test_pnl_identity_exact():
    bars = random_bars()
    for quoter in (FixedSpread(2.0, q_max=5), ASQuoter(gamma=0.01, k=0.3, horizon_s=60, q_max=5)):
        res = run_backtest(bars, quoter, BTConfig(**{**CFG.__dict__, "maker_fee_bps": 1.0}))
        t = res.totals
        assert len(res.fills) > 50
        assert t["pnl"] == pytest.approx(t["spread_capture"] + t["inventory_pnl"] - t["fees"], abs=1e-6)
        assert t["fees"] == pytest.approx(t["notional"] * 1e-4)
        assert res.minute["pnl"].iloc[-1] == pytest.approx(t["pnl"])


def test_inventory_cap_is_respected():
    bars = random_bars(seed=1)
    res = run_backtest(bars, FixedSpread(0.5, q_max=3), CFG)
    q = np.cumsum(res.fills["side"].to_numpy())
    assert np.abs(q).max() <= 3


def test_no_look_ahead():
    """Changing the future must not change any fill that happened before it."""
    bars = random_bars(seed=2)
    cut = 3000
    alt = bars.copy()
    alt.loc[cut:, ["mid", "buy_max", "sell_min"]] += 500.0
    q = ASQuoter(gamma=0.01, k=0.3, horizon_s=60, q_max=5)
    a, b = run_backtest(bars, q, CFG).fills, run_backtest(alt, q, CFG).fills
    pd.testing.assert_frame_equal(a[a.bar < cut].reset_index(drop=True), b[b.bar < cut].reset_index(drop=True))


def test_as_quoter_skews_with_inventory():
    q = ASQuoter(gamma=0.01, k=0.3, horizon_s=3600)
    flat, long_ = q.quote(100_000, 0, 0, 3.0), q.quote(100_000, 5, 0, 3.0)
    assert long_[0] < flat[0] and long_[1] < flat[1]


def test_prepare_bars_sigma_is_past_only_and_in_per_second_units():
    rng = np.random.default_rng(3)
    n = 20_000
    ts = np.arange(n) * 100_000
    mid = 100 + np.cumsum(rng.choice([-1, 1], n) * 0.5)          # 0.5 per 0.1 s -> sigma = 0.5/sqrt(0.1)
    trades = pd.DataFrame({"ts_us": np.repeat(ts, 2) + np.tile([0, 1], n),
                           "price": np.ravel(np.column_stack([mid + 0.005, mid - 0.005])),
                           "qty": 0.01, "side": np.tile(np.array([1, -1], dtype="int8"), n)})
    bars = prepare_bars(trades, BTConfig(warmup_s=60, sigma_halflife_s=120))
    assert bars["sigma"].iloc[:600].isna().all()
    assert bars["sigma"].iloc[-1] == pytest.approx(0.5 / np.sqrt(0.1), rel=0.1)


def test_summary_and_drawdown():
    assert max_drawdown(np.array([1.0, 3.0, 2.0, 5.0, 1.0])) == -4.0
    res = run_backtest(random_bars(seed=4), FixedSpread(2.0, q_max=5), CFG)
    s = summarize(res)
    assert s["fills"] == len(res.fills)
    assert s["net_0bp"] == pytest.approx(s["pnl"])
    assert s["net_2bp"] == pytest.approx(s["pnl"] - 2e-4 * s["notional_usdt"])


def test_touch_rule_fills_on_equal_price():
    bars = make_bars([100] * 3, buy_max=[np.nan, 101.0, np.nan], sell_min=[np.nan, 99.0, np.nan])
    touch = BTConfig(**{**CFG.__dict__, "fill_rule": "touch"})
    assert len(run_backtest(bars, FixedSpread(1.0), touch).fills) == 2
    assert run_backtest(bars, FixedSpread(1.0), CFG).fills.empty
