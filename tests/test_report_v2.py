"""Dashboard D12 helpers that turn v2 objects into bundle sections."""
import numpy as np
import pandas as pd
import pytest

from mm.edge import EdgeTable
from mm.queue_sim import Action
from mm.report import (agent_rows, build_bundle, calib_rows, edge_rows, markout_rows, screen_rows,
                       validate_bundle, wait_hist_of)


def test_edge_rows_cover_both_actions_and_skip_unlearned():
    t = EdgeTable()
    for i in range(40):
        t.update(Action.JOIN, (1, i % 3), -10.0 + i % 4)
    rows = edge_rows(t, "ANKRUSDT")
    assert {r["action"] for r in rows} == {"JOIN"}                 # BACK has no pooled data yet
    assert len(rows) == 9 and all(set(r) == {"symbol", "action", "imb", "vol", "n", "mean", "se"} for r in rows)
    r = next(r for r in rows if (r["imb"], r["vol"]) == (1, 0))
    assert r["mean"] == pytest.approx(t.estimate(Action.JOIN, (1, 0))[0])


def test_agent_rows():
    hist = [{"ts_us": 1_762_732_800_000_000, "live_arm": 11, "switched": False, "scores": [0.123456] * 12, "fills": [0] * 12}]
    rows = agent_rows(hist, "SKLUSDT")
    assert rows[0]["ts"].endswith("Z") and rows[0]["live_arm"] == 11 and len(rows[0]["scores"]) == 12


def test_calib_rows_equal_count_bins():
    f = pd.DataFrame({"pred_edge_bp": np.arange(50, dtype=float), "net_edge_bp": np.arange(50, dtype=float) * 0.5})
    rows = calib_rows(f, "X")
    assert len(rows) == 5 and [r["n"] for r in rows] == [10] * 5
    assert rows[0]["pred_mean"] == pytest.approx(4.5) and rows[0]["real_mean"] == pytest.approx(2.25)
    assert calib_rows(f.head(5), "X") == []
    assert calib_rows(pd.DataFrame({"side": [1]}), "X") == []


def test_wait_hist_and_markout_action_names():
    f = pd.DataFrame({"wait_s": [0.5, 3.0, 3.5, 1000.0], "action": [1, 1, 2, 1], "side": [1, -1, 1, -1],
                      **{f"mk_{h}": [1.0, 2.0, 3.0, 4.0] for h in (1, 10, 60, 300)}})
    w = wait_hist_of(f)
    assert len(w["count"]) == len(w["edges"]) - 1 and sum(w["count"]) == 4
    class R: fills = f; markouts = None
    acts = {r["action"] for r in markout_rows(R, "X", "agent")}
    assert acts <= {"JOIN", "BACK"}


def test_screen_rows_and_bundle_valid():
    df = pd.DataFrame([{"symbol": "ANKRUSDT", "days": 7, "tick_bp_med": 25.6, "spread_ticks_med": 1.0,
                        "usd_volume_med": 2.2e5, "trades_per_sec_med": 0.03, "constrained": True}])
    rows = screen_rows(df)
    assert rows[0]["tick_bp"] == 25.6 and rows[0]["constrained"] is True and rows[0]["trades_per_s"] == 0.03
    b = build_bundle("qb-test", "backtest", "t", {"q_max": 10, "lot_usd": 100.0},
                     [{"symbol": "ANKRUSDT", "date": "2026-11-10", "variant": "q1.0", "pnl": -1.0, "fills": 30,
                       "notional": 3000.0}], screen=rows)
    assert validate_bundle(b) == []


def test_public_bundle_thins_and_refuses_demo():
    from mm.report import demo_bundle, public_bundle
    import pytest as _pt
    with _pt.raises(ValueError):
        public_bundle(demo_bundle())
    b = demo_bundle()
    b["kind"] = "walkforward"; b["run_id"] = "wf-x"
    key = next(iter(b["curves"]))
    n_before = len(b["curves"][key]["t"])
    p = public_bundle(b, every_min=60, agent_every=4)
    assert p["run_id"] == "pub-wf-x" and p["kind"] == "walkforward"
    assert 0 < len(p["curves"][key]["t"]) < n_before
    assert all(len(v) == len(p["curves"][key]["t"]) for v in p["curves"][key].values())
    assert len(p["agent"]) < len(b["agent"]) and all(r in p["agent"] for r in b["agent"] if r["switched"])
    assert validate_bundle(p) == []
