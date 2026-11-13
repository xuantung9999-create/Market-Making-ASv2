"""v2.1 Task 17: hedge pre-check (inventory half-life and R2 against BTC perp returns)."""
import json

import numpy as np
import pandas as pd
import pytest

from scripts import hedge_precheck as hp

MIN = 60 * 1_000_000


def test_inventory_path_is_the_cumulative_signed_fills_sampled_each_minute():
    fills = pd.DataFrame({"ts_us": [10 * 1_000_000, 70 * 1_000_000, 80 * 1_000_000, 200 * 1_000_000], "side": [1, 1, -1, 1]})
    q = hp.inventory_path(fills, 0, 5 * MIN - 1)
    assert list(q) == [1, 1, 1, 2, 2]                         # minute-end values for minutes 0..4


def test_half_life_recovers_an_ar1_inventory():
    rng = np.random.default_rng(0)
    phi, n = 0.9, 20_000
    q = np.zeros(n)
    for i in range(1, n):
        q[i] = phi * q[i - 1] + rng.normal()
    hl = hp.half_life_minutes([q])
    assert hl == pytest.approx(np.log(0.5) / np.log(phi), rel=0.1)


def test_half_life_edge_cases():
    assert hp.half_life_minutes([np.tile([1.0, -1.0], 500)]) == 0.0                # flips every minute
    assert hp.half_life_minutes([np.cumsum(np.random.default_rng(1).normal(size=5000))]) > 100   # near unit root
    assert np.isnan(hp.half_life_minutes([np.zeros(100)]))                          # never held anything


def ticks(minutes, rng, vol=0.001, follow=None, beta=0.0):
    t = np.arange(minutes) * MIN + 1
    r = rng.normal(0, vol, minutes) + (beta * follow if follow is not None else 0.0)
    return pd.DataFrame({"ts_us": t, "price": 100 * np.exp(np.cumsum(r))}), r


def test_r2_and_beta_against_btc_at_a_horizon():
    rng = np.random.default_rng(2)
    btc, rb = ticks(6000, rng)
    coin, _ = ticks(6000, rng, follow=rb, beta=0.8)
    out = hp.r2_vs_btc(coin, btc, horizon_min=5)
    assert out["beta"] == pytest.approx(0.8, abs=0.1) and out["r2"] > 0.3
    indep, _ = ticks(6000, rng)
    assert hp.r2_vs_btc(indep, btc, 5)["r2"] < 0.02


def test_decision_rule_boundaries():
    assert hp.decide(4.9, 0.5)[0] == "stop" and "half-life" in hp.decide(4.9, 0.5)[1]
    assert hp.decide(30.0, 0.14)[0] == "stop" and "R2" in hp.decide(30.0, 0.14)[1]
    assert hp.decide(5.0, 0.15)[0] == "go"
    assert hp.decide(float("nan"), 0.5)[0] == "not evaluated"
    assert hp.decide(30.0, float("nan"))[0] == "not evaluated"


def write_days(tmp, sym, n_days=3, seed=0, follow_btc=False):
    rng = np.random.default_rng(seed)
    base = 1_700_000_000_000_000
    (tmp / "futures").mkdir(exist_ok=True)
    for d in range(n_days):
        n = 8000
        t = base + d * 86_400_000_000 + np.cumsum(rng.integers(20_000, 200_000, n))
        btc = np.round(30000 + np.cumsum(rng.normal(0, 3, n)), 1)
        pd.DataFrame({"ts_us": t, "price": btc, "qty": 0.01, "side": rng.choice([-1, 1], n)}) \
            .to_parquet(tmp / "futures" / f"BTCUSDT_2024-01-{d + 1:02d}_trades.parquet", index=False)
        px = np.round(1 + np.cumsum(rng.choice([-0.0001, 0.0, 0.0001], n)), 4)
        pd.DataFrame({"ts_us": t, "price": px, "qty": rng.uniform(100, 5000, n), "side": rng.choice([-1, 1], n)}) \
            .to_parquet(tmp / f"{sym}_2024-01-{d + 1:02d}_trades.parquet", index=False)


def test_precheck_stops_for_a_coin_that_does_not_follow_btc(tmp_path):
    write_days(tmp_path, "TESTUSDT")
    r = hp.precheck("TESTUSDT", str(tmp_path), str(tmp_path / "futures"))
    assert r["decision"] in ("stop", "not evaluated") and r["days"] == 3
    assert {"half_life_min", "r2", "beta", "horizon_min", "decision", "reason"} <= set(r)
    out = tmp_path / "hp.json"
    hp.main(["--symbols", "TESTUSDT", "--data", str(tmp_path), "--futures", str(tmp_path / "futures"), "--out", str(out)])
    assert json.loads(out.read_text())["TESTUSDT"]["decision"] == r["decision"]
