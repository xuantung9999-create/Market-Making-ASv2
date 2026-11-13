"""v2.1 Task 13: Markov microprice (mm/markov.py)."""
import numpy as np
import pandas as pd
import pytest

from mm import markov as mk

SEC = 1_000_000
DAY = 86_400 * SEC
DAY0 = 20_000 * DAY
TICK = 0.01


def synth(n=40_000, effect=0.8, seed=1, start=DAY0, step_us=SEC // 2, spread_ticks=1, p_move=0.3):
    """Imbalance drawn fresh each update; the mid steps one tick up or down afterwards, more often up when imbalance is high."""
    rng = np.random.default_rng(seed)
    imb = rng.uniform(-1, 1, n)
    mid_k = np.zeros(n)
    for i in range(n - 1):
        u = rng.random()
        up = p_move * 0.5 * (1 + effect * imb[i])
        dn = p_move * 0.5 * (1 - effect * imb[i])
        mid_k[i + 1] = mid_k[i] + (1 if u < up else -1 if u < up + dn else 0)
    mid = 100.0 + mid_k * TICK
    q = 1000.0
    return pd.DataFrame({"recv_us": start + np.arange(n) * step_us, "update_id": np.arange(n),
                         "bid": mid - spread_ticks * TICK / 2, "bid_qty": q * (1 + imb) / 2,
                         "ask": mid + spread_ticks * TICK / 2, "ask_qty": q * (1 - imb) / 2})


@pytest.fixture(scope="module")
def table():
    return mk.fit(synth(), TICK)


def test_state_encoding_has_ten_states_and_mirrors():
    assert mk.N_STATES == 10
    assert sorted(mk.mirror_state(s) for s in range(10)) == list(range(10))
    assert all(mk.mirror_state(mk.mirror_state(s)) == s for s in range(10))
    s = mk.state_index(np.array([-0.9, 0.9, 0.0]), np.array([1.0, 1.0, 3.0]))
    assert list(s) == [0, 4, 7]                       # (bucket, spread class): 1 tick -> 0..4, 2+ ticks -> 5..9


def test_rows_of_q_plus_r_and_q_plus_t_sum_to_one(table):
    seen = table["count"] > 0
    assert np.allclose((table["Q"].sum(1) + table["R"].sum(1))[seen], 1.0)
    assert np.allclose((table["Q"].sum(1) + table["T"].sum(1))[seen], 1.0)
    assert np.allclose(table["R"].sum(1)[seen], table["T"].sum(1)[seen])


def test_gstar_is_antisymmetric_across_imbalance_buckets(table):
    g = table["G"]
    for s in range(10):
        assert g[s] == pytest.approx(-g[mk.mirror_state(s)], abs=1e-12)
    assert g[2 if False else 5 + 2] == pytest.approx(0.0, abs=1e-12)        # the balanced bucket is its own mirror


def test_gstar_rises_with_imbalance_when_the_book_predicts(table):
    g = table["G"][:5]
    assert all(b > a for a, b in zip(g, g[1:])) and g[0] < 0 < g[-1]


def test_no_imbalance_effect_gives_zeros_within_noise():
    t = mk.fit(synth(effect=0.0, seed=7), TICK)
    assert np.abs(t["G"]).max() < 0.05                  # ticks; the effect case is of order 0.3


def test_series_uses_only_the_current_state_so_future_rows_do_not_change_the_past(table):
    book = synth(n=2000, seed=3)
    a = mk.markov_bp(book, table, TICK)
    book2 = book.copy()
    book2.loc[1500:, ["bid_qty", "ask_qty"]] = book2.loc[1500:, ["ask_qty", "bid_qty"]].to_numpy()
    b = mk.markov_bp(book2, table, TICK)
    assert np.array_equal(a[:1500], b[:1500]) and not np.array_equal(a[1500:], b[1500:])


def test_daily_refit_uses_only_the_previous_three_days():
    days = [synth(n=6000, seed=10 + d, start=DAY0 + d * DAY, step_us=10 * SEC) for d in range(5)]
    book = pd.concat(days, ignore_index=True)
    t1 = mk.fit_daily(book, TICK, train_days=3)
    tampered = book.copy()
    last = tampered["recv_us"] >= DAY0 + 4 * DAY
    tampered.loc[last, ["bid_qty", "ask_qty"]] = tampered.loc[last, ["ask_qty", "bid_qty"]].to_numpy()
    t2 = mk.fit_daily(tampered, TICK, train_days=3)
    d4 = DAY0 // DAY + 4
    assert np.array_equal(t1[d4]["G"], t2[d4]["G"])      # day 4's table was fitted on days 1-3 only
    assert sorted(t1) == [DAY0 // DAY + k for k in (3, 4)]  # days with fewer than 3 days of history get no table


def test_r2_report_gives_both_predictors_at_every_horizon(table):
    test = synth(n=20_000, seed=99)
    r = mk.r2_report(test, table, TICK, horizons=(1, 5, 30))
    assert set(r) == {1, 5, 30}
    assert r[1]["markov"] > 0 and r[1]["micro"] > 0
    assert all(0.0 <= v["markov"] < 1.0 for v in r.values())


def test_eval_script_scores_coins_and_applies_the_two_of_three_rule():
    from scripts import eval_markov as ev
    days = [synth(n=8000, seed=20 + d, start=DAY0 + d * DAY, step_us=10 * SEC) for d in range(6)]
    book = pd.concat(days, ignore_index=True)
    row = ev.evaluate_coin(book, None, "SYNTH", tick=TICK)
    assert row["test_days"] == 3 and {"markov_1s", "micro_30s", "pass"} <= set(row)
    assert ev.verdict([{"pass": True}, {"pass": True}, {"pass": False}]) is True
    assert ev.verdict([{"pass": True}, {"pass": False}, {"pass": False}]) is False


def test_eval_script_fails_clearly_without_data(tmp_path):
    from scripts import eval_markov as ev
    assert ev.main(["--root", str(tmp_path)]) == 1
