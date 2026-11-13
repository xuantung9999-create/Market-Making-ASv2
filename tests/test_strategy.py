import math

import numpy as np
import pytest

from mm.strategy import (
    PAPER_PARAMS, ASParams, fill_intensity, liquidity_term, optimal_spread,
    quote, reservation_price,
)

P = PAPER_PARAMS  # gamma=0.1, sigma=2, k=1.5, A=140, T=1


# --- Hand-worked example from notes/derivation.md, section 5 ---------------

def test_worked_example_matches_notes():
    qt = quote(s=100.0, q=2, t=0.5, p=P)
    assert qt.reservation == pytest.approx(99.6)
    assert qt.spread == pytest.approx(1.490770, abs=1e-6)
    assert qt.bid == pytest.approx(98.854615, abs=1e-6)
    assert qt.ask == pytest.approx(100.345385, abs=1e-6)


# --- Reservation price ------------------------------------------------------

def test_zero_inventory_quotes_symmetric_around_mid():
    qt = quote(100.0, 0, 0.3, P)
    assert qt.reservation == pytest.approx(100.0)
    assert 100.0 - qt.bid == pytest.approx(qt.ask - 100.0)


def test_long_inventory_shifts_reservation_down_short_shifts_up():
    assert reservation_price(100, 3, 0.2, P) < 100 < reservation_price(100, -3, 0.2, P)


def test_reservation_is_linear_in_inventory():
    r = reservation_price(100, np.arange(-5, 6), 0.4, P)
    assert np.allclose(np.diff(r), np.diff(r)[0])
    assert np.diff(r)[0] == pytest.approx(-P.gamma * P.sigma**2 * 0.6)


def test_skew_fades_at_horizon():
    assert reservation_price(100, 5, P.T, P) == pytest.approx(100.0)
    assert reservation_price(100, 5, P.T + 10, P) == pytest.approx(100.0)  # tau floored at 0


def test_higher_gamma_means_stronger_skew():
    lo = ASParams(gamma=0.01, sigma=2, k=1.5)
    hi = ASParams(gamma=0.5, sigma=2, k=1.5)
    assert abs(100 - reservation_price(100, 2, 0, hi)) > abs(100 - reservation_price(100, 2, 0, lo))


# --- Spread -------------------------------------------------------------------

def test_spread_widens_with_sigma():
    lo = ASParams(gamma=0.1, sigma=1, k=1.5)
    hi = ASParams(gamma=0.1, sigma=3, k=1.5)
    assert optimal_spread(0, hi) > optimal_spread(0, lo)


def test_spread_tightens_with_k():
    assert optimal_spread(0, ASParams(0.1, 2, k=3.0)) < optimal_spread(0, ASParams(0.1, 2, k=1.0))


def test_spread_shrinks_toward_liquidity_term_at_horizon():
    assert optimal_spread(0.0, P) > optimal_spread(0.9, P)
    assert optimal_spread(P.T, P) == pytest.approx(liquidity_term(P))


def test_liquidity_term_tends_to_2_over_k_as_gamma_vanishes():
    p = ASParams(gamma=1e-9, sigma=2, k=1.5)
    assert liquidity_term(p) == pytest.approx(2 / 1.5, rel=1e-6)


def test_spread_is_not_monotone_in_gamma():
    """Trap from the notes: with tiny sigma^2*tau, higher gamma TIGHTENS the spread;
    with large sigma^2*tau it widens it."""
    calm_lo, calm_hi = ASParams(0.1, sigma=0.1, k=1.5), ASParams(1.0, sigma=0.1, k=1.5)
    wild_lo, wild_hi = ASParams(0.1, sigma=3.0, k=1.5), ASParams(1.0, sigma=3.0, k=1.5)
    assert optimal_spread(0, calm_hi) < optimal_spread(0, calm_lo)
    assert optimal_spread(0, wild_hi) > optimal_spread(0, wild_lo)


def test_quotes_always_straddle_reservation():
    for q in (-4, 0, 4):
        qt = quote(100, q, 0.1, P)
        assert qt.bid < qt.reservation < qt.ask


# --- Fill intensity ------------------------------------------------------------

def test_fill_intensity_decays_exponentially():
    assert fill_intensity(0.0, P) == pytest.approx(140.0)
    assert fill_intensity(1.0, P) / fill_intensity(0.0, P) == pytest.approx(math.exp(-1.5))


# --- Tick rounding ---------------------------------------------------------------

def test_tick_rounding_is_conservative():
    p = ASParams(0.1, 2, 1.5, tick_size=0.01)
    raw = quote(100.0, 2, 0.5, P)
    qt = quote(100.0, 2, 0.5, p)
    assert qt.bid == pytest.approx(98.85) and qt.bid <= raw.bid
    assert qt.ask == pytest.approx(100.35) and qt.ask >= raw.ask


def test_tick_rounding_keeps_one_tick_minimum_spread():
    p = ASParams(gamma=0.1, sigma=0.0, k=1e6, tick_size=1.0)  # model spread ~0
    qt = quote(100.5, 0, 0.0, p)            # mid between ticks, as in a real book
    assert (qt.bid, qt.ask) == (100.0, 101.0)
    # mid exactly on a tick: conservative rounding goes one tick out each side
    qt_on = quote(100.0, 0, 0.0, p)
    assert (qt_on.bid, qt_on.ask) == (99.0, 101.0)


# --- Inventory limits --------------------------------------------------------------

def test_inventory_limit_disables_risk_increasing_side():
    p = ASParams(0.1, 2, 1.5, q_max=5)
    assert quote(100, 5, 0, p).bid_active is False
    assert quote(100, 5, 0, p).ask_active is True
    assert quote(100, -5, 0, p).ask_active is False
    assert quote(100, -5, 0, p).bid_active is True
    assert quote(100, 0, 0, p).bid_active and quote(100, 0, 0, p).ask_active


# --- Validation ----------------------------------------------------------------------

@pytest.mark.parametrize("kwargs", [
    dict(gamma=0, sigma=2, k=1.5),
    dict(gamma=0.1, sigma=-1, k=1.5),
    dict(gamma=0.1, sigma=2, k=0),
    dict(gamma=0.1, sigma=2, k=1.5, T=0),
    dict(gamma=0.1, sigma=2, k=1.5, tick_size=0),
    dict(gamma=0.1, sigma=2, k=1.5, q_max=-1),
])
def test_invalid_params_raise(kwargs):
    with pytest.raises(ValueError):
        ASParams(**kwargs)
