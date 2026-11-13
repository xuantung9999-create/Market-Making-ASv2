import numpy as np
import pytest

from mm.simulator import SimConfig, compare, simulate
from mm.strategy import PAPER_PARAMS as P, ASParams


def test_same_seed_same_result():
    a = simulate(P, SimConfig(n_paths=5, seed=7))
    b = simulate(P, SimConfig(n_paths=5, seed=7))
    assert np.array_equal(a.pnl, b.pnl)


def test_strategies_share_price_paths_under_same_seed():
    cfg = SimConfig(n_paths=20, seed=3)
    inv, sym = simulate(P, cfg, "inventory"), simulate(P, cfg, "symmetric")
    assert np.array_equal(inv.s, sym.s)


def test_binomial_mid_moves_exactly_sigma_sqrt_dt():
    res = simulate(P, SimConfig(n_paths=3, seed=1))
    steps = np.abs(np.diff(res.s, axis=1))
    assert np.allclose(steps, P.sigma * np.sqrt(0.005))
    assert res.t[-1] == pytest.approx(P.T) and res.s.shape[1] == 201


def test_no_order_flow_means_no_trades_and_zero_pnl():
    p = ASParams(gamma=0.1, sigma=2, k=1.5, A=0.0)
    res = simulate(p, SimConfig(n_paths=10, seed=0))
    assert not res.bid_fills.any() and not res.ask_fills.any()
    assert np.all(res.q == 0) and np.allclose(res.pnl, 0)


def test_cash_and_inventory_accounting():
    res = simulate(P, SimConfig(n_paths=50, seed=2))
    dq = res.bid_fills.astype(int) - res.ask_fills.astype(int)
    assert np.array_equal(res.q[:, -1], dq.sum(axis=1))
    cash = (res.ask_fills * res.ask - res.bid_fills * res.bid).sum(axis=1)
    assert np.allclose(res.x[:, -1], cash)
    assert np.allclose(res.final_pnl, res.x[:, -1] + res.q[:, -1] * res.s[:, -1])


def test_inventory_quotes_centre_on_r_symmetric_on_mid():
    cfg = SimConfig(n_paths=5, seed=4)
    inv, sym = simulate(P, cfg, "inventory"), simulate(P, cfg, "symmetric")
    assert np.allclose((inv.bid + inv.ask) / 2, inv.r)
    assert np.allclose((sym.bid + sym.ask) / 2, sym.s)
    assert np.allclose(inv.ask - inv.bid, sym.ask - sym.bid)  # same spread


def test_q_max_is_never_exceeded():
    p = ASParams(gamma=0.01, sigma=2, k=1.5, q_max=3)
    res = simulate(p, SimConfig(n_paths=200, seed=5), "symmetric")
    assert np.abs(res.q).max() <= 3


def test_paper_result_inventory_strategy_has_less_risk():
    """The headline of section 4: lower PnL variance and tighter inventory."""
    df = compare(P, SimConfig(n_paths=500, seed=0)).set_index("strategy")
    assert df.loc["inventory", "std_pnl"] < 0.7 * df.loc["symmetric", "std_pnl"]
    assert df.loc["inventory", "std_final_q"] < 0.5 * df.loc["symmetric", "std_final_q"]


def test_higher_gamma_trades_profit_for_lower_risk():
    cfg = SimConfig(n_paths=500, seed=0)
    lo = simulate(ASParams(gamma=0.01, sigma=2, k=1.5), cfg).summary()
    hi = simulate(ASParams(gamma=0.5, sigma=2, k=1.5), cfg).summary()
    assert hi["mean_pnl"] < lo["mean_pnl"]
    assert hi["std_pnl"] < lo["std_pnl"]
