"""v2 Task 9 helpers: dropping hours with recorder gaps, and the verdict rule."""
import pandas as pd

from scripts.validate_tape import drop_gap_hours, verdict

S = 1_000_000
H = 3600 * S


def test_hours_with_long_gaps_are_dropped():
    ts = [i * 60 * S for i in range(0, 180)]                       # every minute for 3 hours
    ts = [t for t in ts if not (H + 10 * 60 * S < t < H + 20 * 60 * S)]   # 10-min gap inside hour 1
    book = pd.DataFrame({"ts_us": ts, "bid": 1.0, "ask": 1.1, "bid_qty": 1.0, "ask_qty": 1.0})
    trades = pd.DataFrame({"ts_us": [30 * S, H + 30 * S, 2 * H + 30 * S], "price": 1.0, "qty": 1.0, "side": 1})
    b, t, kept = drop_gap_hours(book, trades, max_gap_s=120)
    assert kept == 2
    assert not ((b["ts_us"] >= H) & (b["ts_us"] < 2 * H)).any()
    assert t["ts_us"].tolist() == [30 * S, 2 * H + 30 * S]


def test_verdict_rule():
    ok = pd.DataFrame([{"fills_real": 100, "fills_inf": 120, "net_edge_real": -5.0, "net_edge_inf": -6.5}])
    assert verdict(ok)[0] is True
    too_many = ok.assign(fills_inf=131)
    assert verdict(too_many)[0] is False
    edge_off = ok.assign(net_edge_inf=-7.1)
    assert verdict(edge_off)[0] is False
    v, nums = verdict(pd.concat([ok, ok.assign(fills_real=300, fills_inf=300, net_edge_real=1.0, net_edge_inf=1.0)]))
    assert nums["fill_ratio"] == (120 + 300) / (100 + 300)
