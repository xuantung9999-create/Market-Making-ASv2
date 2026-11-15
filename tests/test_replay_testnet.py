import json
import math
from dataclasses import asdict

import numpy as np
import pandas as pd

from mm import report
from mm.agent import START_ARM, AgentConfig, CalibrationAgent
from mm.edge import EdgeTable
from mm.paper import DAY_US
from mm.queue_sim import QSConfig
from scripts import replay_testnet as rt

DAY0 = pd.Timestamp("2026-11-12", tz="UTC").value // 1000


def _start(arm=3):
    a = CalibrationAgent(AgentConfig(), QSConfig(), 0.01)
    a.live_arm = arm
    cfg = asdict(QSConfig())
    cfg["markouts_s"] = list(cfg["markouts_s"])
    return {"table": EdgeTable().to_dict(), "agent": a.state_dict(), "tick": 0.01, "sim_cfg": cfg, "enabled": True}


def _feed(t0, hours=1.0, mid=100.0):
    """A quiet two-sided book every second with a trade on each side every 5 s."""
    n = int(hours * 3600)
    ts = t0 + np.arange(n, dtype=np.int64) * 1_000_000
    book = pd.DataFrame({"ts_us": ts, "bid": mid - 0.01, "ask": mid + 0.01, "bid_qty": 5.0, "ask_qty": 5.0})
    tt = ts[::5] + 500_000
    trades = pd.DataFrame({"ts_us": tt, "price": np.where(np.arange(tt.size) % 2, mid + 0.01, mid - 0.01),
                           "qty": 0.5, "side": np.where(np.arange(tt.size) % 2, 1, -1)})
    return book, trades


def test_the_replay_agent_has_no_loss_stop_and_keeps_the_saved_arm_and_cap():
    a = rt.make_agent(_start(arm=3))
    assert math.isinf(a.cfg.max_daily_loss_usd) and a.live_arm == 3 and not a.stopped
    assert a.sim_cfg.q_max == QSConfig().q_max
    assert tuple(a.sim_cfg.markouts_s) == tuple(report.MARKOUT_H)
    a.live._cash = -1e6                                      # a huge loss never stops it
    from mm.queue_sim import MarketState
    a.live.policy.decide(MarketState(0, 99.99, 100.01, 5, 5, 0.01, {}), 0)
    assert not a.stopped


def test_first_start_state_is_the_earliest_day(tmp_path):
    for d in ("2026-11-13", "2026-11-12", "2026-11-14"):
        (tmp_path / f"BTCUSDT_start_{d}.json").write_text(json.dumps({"day": d}))
    day, st = rt.first_start_state(tmp_path, "BTCUSDT")
    assert day == "2026-11-12" and st == {"day": "2026-11-12"}


def test_replay_runs_day_by_day_and_ends_each_day_flat(tmp_path, monkeypatch):
    (tmp_path / "state").mkdir()
    (tmp_path / "state" / "XUSDT_start_2026-11-12.json").write_text(json.dumps(_start()))
    b1, t1 = _feed(DAY0 + 23 * 3600 * 1_000_000)             # the last hour of day 1
    b2, t2 = _feed(DAY0 + DAY_US)                            # the first hour of day 2
    early_b, early_t = _feed(DAY0 - 3600 * 1_000_000, hours=0.5)   # before the start state: ignored
    monkeypatch.setattr(rt, "load_feed", lambda feed, sym: (pd.concat([early_b, b1, b2], ignore_index=True),
                                                            pd.concat([early_t, t1, t2], ignore_index=True)))
    a, results, counts = rt.replay_symbol(tmp_path, "XUSDT", log=lambda *_: None)
    assert counts["book_dropped"] == 0 and counts["trades_dropped"] == 0
    assert [d for d, _ in results] == ["2026-11-12", "2026-11-13"]
    assert a.live.q == 0                                     # end_day closed the inventory
    for _, res in results:
        q = res.minute["q"].to_numpy(float) if len(res.minute) else np.zeros(1)
        assert np.abs(q).max() <= a.sim_cfg.q_max


def test_clean_feed_drops_glitched_book_updates_and_far_trades_using_only_the_past():
    book, trades = _feed(DAY0, hours=0.2)
    g = book.index[300:304]                                  # four updates 300 bp up, then back to normal
    book.loc[g, ["bid", "ask"]] = book.loc[g, ["bid", "ask"]] * 1.03
    trades.loc[trades.index[70], "price"] = 97.0             # a print 300 bp away from the clean mid
    b, t, c = rt.clean_feed(book, trades)
    assert c["book_dropped"] == 4 and c["trades_dropped"] == 1
    assert len(b) == len(book) - 4 and len(t) == len(trades) - 1
    assert (b["bid"] < 103).all() and (t["price"] > 99).all()


def test_a_burst_of_glitch_updates_cannot_outvote_the_quiet_minutes_before_it():
    book, trades = _feed(DAY0, hours=0.2)
    t0 = int(book["ts_us"].iloc[400])
    burst = pd.DataFrame({"ts_us": t0 + 100_000 + np.arange(200) * 10_000, "bid": 106.0, "ask": 106.02,
                          "bid_qty": 1.0, "ask_qty": 1.0})       # 200 updates in 2 s, 6% away
    b, _, c = rt.clean_feed(pd.concat([book, burst], ignore_index=True), trades)
    assert c["book_dropped"] == 200 and (b["bid"] < 103).all()


def test_after_a_long_feed_gap_the_reference_starts_afresh():
    b1, t1 = _feed(DAY0, hours=0.1, mid=100.0)
    b2, t2 = _feed(DAY0 + 3 * 3600 * 1_000_000, hours=0.1, mid=103.0)   # 3 h later the market is 300 bp higher
    b, t, c = rt.clean_feed(pd.concat([b1, b2], ignore_index=True), pd.concat([t1, t2], ignore_index=True))
    assert c["book_dropped"] == 0 and c["trades_dropped"] == 0


def test_the_run_is_a_valid_bundle_that_says_it_is_a_replay_without_a_loss_stop(tmp_path, monkeypatch):
    (tmp_path / "state").mkdir()
    for s in ("AUSDT", "BUSDT"):
        (tmp_path / "state" / f"{s}_start_2026-11-12.json").write_text(json.dumps(_start()))
    monkeypatch.setattr(rt, "load_feed", lambda feed, sym: _feed(DAY0 + 3600 * 1_000_000))
    b = rt.build_run(tmp_path, ["AUSDT", "BUSDT"])
    assert b["run_id"] == "replay-testnet-2026-11-12" and b["kind"] == "backtest"
    assert b["config"]["loss_stop"] == "off" and b["config"]["q_max"] == QSConfig().q_max
    assert set(b["config"]["glitches_dropped"]) == {"AUSDT", "BUSDT"} and "100 bp" in b["config"]["glitch_rule"]
    assert "simulated fills" in b["label"] and "no loss stop" in b["label"]
    assert {d["symbol"] for d in b["days"]} == {"AUSDT", "BUSDT"} and all(d["variant"] == "agent" for d in b["days"])
    assert set(b["curves"]) >= {"AUSDT|agent", "BUSDT|agent"}
    out = report.write_bundle(b, tmp_path / "runs")
    assert out.exists() and report.validate_bundle(report.slim_bundle(b)) == []
