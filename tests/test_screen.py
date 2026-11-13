"""v2 Task 2: the tick-constraint screen."""
import pandas as pd

from mm.screen import screen_row, screen_table


def cal(tick_bp=26.0, spread_ticks=1.0, usd=500_000.0, tps=0.05, sym="ANKRUSDT", date="2026-11-01"):
    return {"symbol": sym, "date": date, "tick_bp": tick_bp, "spread_ticks": spread_ticks,
            "usd_volume_day": usd, "trades_per_sec": tps}


def test_medians_are_medians():
    r = screen_row([cal(tick_bp=25), cal(tick_bp=26), cal(tick_bp=100)])
    assert r["tick_bp_med"] == 26
    assert r["days"] == 3 and r["symbol"] == "ANKRUSDT"
    assert set(r) >= {"symbol", "days", "tick_bp_med", "spread_ticks_med", "usd_volume_med",
                      "trades_per_sec_med", "constrained"}


def test_tick_threshold():
    assert screen_row([cal(tick_bp=9.99)])["constrained"] is False
    assert screen_row([cal(tick_bp=10.0)])["constrained"] is True


def test_spread_threshold():
    assert screen_row([cal(spread_ticks=1.5)])["constrained"] is True
    assert screen_row([cal(spread_ticks=1.51)])["constrained"] is False


def test_volume_threshold():
    assert screen_row([cal(usd=99_999)])["constrained"] is False
    assert screen_row([cal(usd=100_000)])["constrained"] is True


def test_table_sorts_constrained_first_then_volume():
    rows = [screen_row([cal(sym="A", tick_bp=1, usd=9e9)]),
            screen_row([cal(sym="B", usd=2e5)]),
            screen_row([cal(sym="C", usd=3e5)])]
    t = screen_table(rows)
    assert isinstance(t, pd.DataFrame)
    assert list(t["symbol"]) == ["C", "B", "A"]
