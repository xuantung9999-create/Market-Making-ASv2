"""Task L4: scripts/build_session.py builds bundles, the session list and tape files, under dashboard/live only."""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts import build_session as bs

S = 1_000_000
T0 = 1_794_600_000 * S
BUNDLE_KEYS = {"meta", "headline", "now", "curve", "markers", "states", "uptime", "attribution", "fills", "markout",
               "funnel", "incidents", "model", "takeaways"}


def write_jsonl(p: Path, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows))


def make_base(tmp_path, glitch=True):
    base = tmp_path
    (base / "config").mkdir()
    (base / "config" / "live.json").write_text(json.dumps({
        "testnet": [{"name": "testnet-join", "symbols": ["BTCUSDT"], "policy": "join", "lot_usd": 100, "q_max": 10, "max_loss": 20}],
        "paper": {"name": "paper", "symbols": ["ANKRUSDT"]}}))
    n = 3600
    rng = np.random.default_rng(1)
    t = T0 + np.arange(n) * S
    mid = 67_500 + np.cumsum(rng.integers(-1, 2, n)) * 0.01
    bid, ask = mid - 0.01, mid + 0.01
    if glitch:                                              # a book glitch: bid and ask collapse for 4 s
        bid[1000:1004], ask[1000:1004] = 55_000.0, 57_882.59
    feed = base / "data/testnet/feed/BTCUSDT"
    (feed / "book").mkdir(parents=True)
    (feed / "trades").mkdir(parents=True)
    pd.DataFrame({"recv_us": t, "update_id": np.arange(n), "bid": bid, "bid_qty": 1.0, "ask": ask, "ask_qty": 1.0}
                 ).to_parquet(feed / "book" / f"BTCUSDT_book_{T0 // 1000}.parquet")
    pd.DataFrame({"recv_us": t[::5], "ts_us": t[::5], "price": mid[::5], "qty": 0.01, "side": 1}
                 ).to_parquet(feed / "trades" / f"BTCUSDT_trades_{T0 // 1000}.parquet")
    d = base / "data/testnet/BTCUSDT"
    fills = []
    for k, s in enumerate(range(100, 3000, 60)):
        sd = 1 if k % 3 else -1
        m = float(mid[s])
        fills.append({"ts_us": T0 + s * S + 300_000, "side": sd, "price": m - sd * 0.01, "qty": 0.0015,
                      "order_id": 100 + k, "mid": m, "pos": 0.0, "pnl": 0.0, "how": "filled"})
    if glitch:
        fills.append({"ts_us": T0 + 1002 * S, "side": -1, "price": 57_882.59, "qty": 0.00177, "order_id": 999,
                      "mid": 56_000.0, "pos": 0.0, "pnl": 0.0, "how": "filled"})
    write_jsonl(d / "fills_2026-11-14.jsonl", fills)
    orders = [{"ts_us": f["ts_us"] - 5 * S, "op": "place", "side": f["side"], "price": str(f["price"]), "qty": "0.0015",
               "order_id": f["order_id"], "action": "JOIN", "pred_bp": 1.0} for f in fills]
    orders += [{"ts_us": T0 + 500 * S, "op": "reject", "side": 1, "price": "1", "error": "HTTP 400 code -2010: Order would immediately match"},
               {"ts_us": T0 + 2000 * S, "op": "loss-stop", "pnl": -20.5}]
    write_jsonl(d / "orders_2026-11-14.jsonl", orders)
    write_jsonl(d / "state_2026-11-14.jsonl", [
        {"ts_us": T0 + k * 60 * S, "side": sd, "state": "QUOTING", "detail": None} for k in range(0, 50) for sd in (1, -1)])
    write_jsonl(d / "session.jsonl", [{"ts_us": T0, "op": "start", "pid": 1, "args": {}, "pos_at_start": 0.0}])
    (d / "status.json").write_text(json.dumps({"symbol": "BTCUSDT", "pos": -0.001, "lots": -1, "pnl": 0.0, "stopped": False,
                                               "open": {"bid": 67_500.0, "ask": None}, "policy": "join"}))
    return base


def load_bundle(base, sid):
    txt = (base / "dashboard/live" / f"session-{sid}.js").read_text()
    return json.loads(txt[txt.index('"] = ') + 5: txt.rindex(";")])


def test_bundle_has_every_key_and_no_nan(tmp_path):
    base = make_base(tmp_path)
    sessions = bs.build(base, now_us=T0 + 3600 * S)
    ids = [s["id"] for s in sessions]
    assert ids == ["testnet-BTCUSDT-join", "paper-ANKRUSDT-agent"]
    b = load_bundle(base, "testnet-BTCUSDT-join")
    assert BUNDLE_KEYS <= set(b)
    for k in ("id", "source", "symbol", "policy", "lot_usd", "q_max", "max_loss", "fee_bps", "built_ms", "thresholds"):
        assert k in b["meta"]
    for k in ("state", "lots", "pos_usd", "open", "last_fill_ms", "process"):
        assert k in b["now"]
    assert set(b["curve"]) == {"t", "pnl", "pnl_ex_artifact", "lots"}
    assert set(b["attribution"]["total"]) >= {"edge", "adverse", "carry", "fees", "artifact", "net"}
    assert {"placed", "cancelled", "rejected", "filled", "partial", "by_hour", "reject_reasons"} <= set(b["funnel"])
    assert {"arm_strip", "arms", "history", "calibration"} <= set(b["model"])
    text = (base / "dashboard/live/session-testnet-BTCUSDT-join.js").read_text()
    assert "NaN" not in text and "Infinity" not in text
    assert all(isinstance(v, str) and v for v in b["takeaways"].values()) and b["headline"]
    e = load_bundle(base, "paper-ANKRUSDT-agent")                 # empty session: still a full bundle, with sentences
    assert BUNDLE_KEYS <= set(e) and "no fills" in e["headline"].lower()


def test_glitch_fill_is_an_artifact_and_net_is_the_sum_of_five_terms(tmp_path):
    base = make_base(tmp_path)
    bs.build(base, now_us=T0 + 3600 * S)
    b = load_bundle(base, "testnet-BTCUSDT-join")
    a = b["attribution"]["total"]
    assert abs(sum(a[k] for k in ("edge", "adverse", "carry", "fees", "artifact")) - a["net"]) < 1e-6
    arts = [f for f in b["fills"] if f["artifact"]]
    # the glitch fill, plus the ordinary fill that happens to land inside the glitch window (its price is far from that mid)
    assert any(f["price"] == pytest.approx(57_882.59) for f in arts) and len(arts) == 2
    kinds = [i["kind"] for i in b["incidents"]]
    assert "artifact_fill" in kinds and "loss_stop" in kinds and "reject_burst" not in kinds
    assert any(m["kind"] == "loss_stop" for m in b["markers"])
    assert b["attribution"]["by_day"][0]["loss_stop"] is True


def test_state_log_feeds_uptime_and_now(tmp_path):
    base = make_base(tmp_path)
    bs.build(base, now_us=T0 + 3000 * S)
    b = load_bundle(base, "testnet-BTCUSDT-join")
    up = {(u["side"], u["state"]): u["share"] for u in b["uptime"]}
    assert up[("bid", "QUOTING")] == pytest.approx(1.0) and up[("ask", "QUOTING")] == pytest.approx(1.0)
    assert b["states"]["bid"][0]["state"] == "QUOTING"
    assert b["now"]["state"]["bid"]["state"] == "QUOTING"        # inferred from the resting bid: quoting
    assert b["now"]["state"]["ask"]["state"] in ("UNKNOWN", "INV_CAP", "QUOTING")


def test_sizes_are_under_the_limits_and_files_are_inside_dashboard_live(tmp_path):
    base = make_base(tmp_path)
    before = {p for p in base.rglob("*") if p.is_file() and "dashboard" not in p.parts}
    bs.build(base, now_us=T0 + 3600 * S)
    after = {p for p in base.rglob("*") if p.is_file() and "dashboard" not in p.parts}
    assert before == after                                        # nothing written outside dashboard/live
    files = list((base / "dashboard/live").glob("*.js"))
    assert files and all(f.stat().st_size < bs.MAX_BYTES for f in files)
    assert any(f.name.startswith("tape-testnet-BTCUSDT-join-2026-11-14") or f.name.startswith("tape-testnet-BTCUSDT-join-")
               for f in files)


def test_tape_has_touch_trades_orders_around_the_glitch_fill(tmp_path):
    base = make_base(tmp_path)
    bs.build(base, now_us=T0 + 3600 * S)
    tapes = list((base / "dashboard/live").glob("tape-*.js"))
    txt = tapes[0].read_text()
    t = json.loads(txt[txt.index('"] = ') + 5: txt.rindex(";")])
    w = t["windows"][0]
    assert w["touch"] and w["trades"] and w["orders"]
    assert w["t0"] <= (T0 + 1002 * S) // 1000 - 59_000 and w["t1"] >= (T0 + 1002 * S) // 1000 + 299_000
    assert {"side", "price", "t_place", "t_end", "end"} <= set(w["orders"][0])


def test_refuses_to_write_outside_the_output_folder(tmp_path):
    out = tmp_path / "dashboard" / "live"
    with pytest.raises(ValueError):
        bs._write(tmp_path / "elsewhere.js", "x", out)


def test_stale_session_files_are_removed(tmp_path):
    base = make_base(tmp_path)
    live = base / "dashboard/live"
    live.mkdir(parents=True)
    (live / "session-old-thing.js").write_text("x")
    (live / "status.js").write_text("window.LIVE={}")
    bs.build(base, now_us=T0 + 3600 * S)
    assert not (live / "session-old-thing.js").exists() and (live / "status.js").exists()


def test_size_guard_thins_a_large_bundle(tmp_path, monkeypatch):
    base = make_base(tmp_path)
    monkeypatch.setattr(bs, "MAX_BYTES", 60_000)
    bs.build(base, now_us=T0 + 3600 * S)
    b = load_bundle(base, "testnet-BTCUSDT-join")
    assert len(b["curve"]["t"]) < 1500


# ---------------------------------------------------------------- showcase spec S1: numbers that agree (section 9)
DAY = 86_400


@pytest.fixture(scope="module")
def three_days(tmp_path_factory):
    base = make_three_days(tmp_path_factory.mktemp("three_days"))
    bs.build(base, now_us=T0 + 3 * DAY * S)
    return base


def make_three_days(tmp_path):
    """One testnet session over three days: a fill every 10 min on alternating sides, two loss stops (one old, one
    inside the last 24 h, with the trader's own LOSS_STOP state line), a paper session that only has a state log."""
    base = tmp_path
    (base / "config").mkdir()
    (base / "config" / "live.json").write_text(json.dumps({
        "testnet": [{"name": "testnet-join", "symbols": ["BTCUSDT"], "policy": "join", "lot_usd": 100, "q_max": 10, "max_loss": 20}],
        "paper": {"name": "paper", "symbols": ["ANKRUSDT"]}}))
    n = 3 * DAY // 10
    rng = np.random.default_rng(3)
    t = T0 + np.arange(n) * 10 * S
    mid = 67_500 + np.cumsum(rng.integers(-1, 2, n)) * 0.02
    feed = base / "data/testnet/feed/BTCUSDT"
    (feed / "book").mkdir(parents=True)
    (feed / "trades").mkdir(parents=True)
    pd.DataFrame({"recv_us": t, "update_id": np.arange(n), "bid": mid - 0.01, "bid_qty": 1.0, "ask": mid + 0.01, "ask_qty": 1.0}
                 ).to_parquet(feed / "book" / f"BTCUSDT_book_{T0 // 1000}.parquet")
    pd.DataFrame({"recv_us": t[::6], "ts_us": t[::6], "price": mid[::6], "qty": 0.01, "side": 1}
                 ).to_parquet(feed / "trades" / f"BTCUSDT_trades_{T0 // 1000}.parquet")
    d = base / "data/testnet/BTCUSDT"
    fills = []
    for k, s in enumerate(range(600, 3 * DAY - 600, 600)):
        sd = 1 if k % 2 else -1
        m = float(mid[s // 10])
        fills.append({"ts_us": T0 + s * S + 300_000, "side": sd, "price": m - sd * 0.01, "qty": 0.0015, "order_id": 100 + k,
                      "mid": m, "pos": 0.0, "pnl": 0.0, "how": "filled", "fill_ts_us": T0 + s * S + 200_000,
                      "place_ts_us": T0 + s * S + 300_000 - 16 * S})
    write_jsonl(d / "fills_2026-11-14.jsonl", fills)
    orders = [{"ts_us": T0 + 90_000 * S + j * 16 * S, "op": "place", "side": sd, "price": "67500", "qty": "0.0015", "order_id": 5000 + j * 2 + (sd > 0)}
              for j in range(40) for sd in (1, -1)]
    orders += [{"ts_us": f["ts_us"] - 16 * S, "op": "place", "side": f["side"], "price": str(f["price"]), "qty": "0.0015",
               "order_id": f["order_id"], "action": "JOIN"} for f in fills]
    old_stop, new_stop = T0 + 30_000 * S, T0 + 216_000 * S
    orders += [{"ts_us": old_stop, "op": "loss-stop", "pnl": -20.4}, {"ts_us": new_stop, "op": "loss-stop", "pnl": -118.49}]
    write_jsonl(d / "orders_2026-11-14.jsonl", orders)
    write_jsonl(d / "state_2026-11-14.jsonl", [
        {"ts_us": new_stop - S // 4, "side": sd, "state": "LOSS_STOP", "detail": {"pnl_day": -20.12, "max_loss": 20.0}}
        for sd in (1, -1)] + [
        {"ts_us": new_stop + 3600 * S, "side": sd, "state": "LOSS_STOP", "detail": {"pnl_day": -7.7, "max_loss": 20.0}}
        for sd in (1, -1)])
    write_jsonl(d / "session.jsonl", [{"ts_us": T0, "op": "start", "pid": 1, "args": {}, "pos_at_start": 0.0}])
    p = base / "data/paper/ANKRUSDT"
    write_jsonl(p / "state_2026-11-14.jsonl", [
        {"ts_us": T0 + k * 60 * S, "side": sd, "state": "POLICY_OUT", "detail": {"live_arm": 11, "score_bp": 0.0}}
        for k in range(0, 30) for sd in (1, -1)])
    return base


def test_range_numbers_agree_with_the_sentences_and_counts(three_days):
    base, b = three_days, load_bundle(three_days, "testnet-BTCUSDT-join")
    assert set(b["by_range"]) == {"6h", "24h", "3d", "all"}
    end = b["meta"]["last_ms"]
    by_hour = b["attribution"]["by_hour"]
    nets = {}
    for key, hours in (("6h", 6), ("24h", 24), ("3d", 72), ("all", None)):
        e = b["by_range"][key]
        t, tk, c = e["tiles"], e["takeaways"], e["counts"]
        nets[key] = t["net"]
        if hours:
            want = sum(r["net"] for r in by_hour if r["t"] + 3_600_000 > end - hours * 3_600_000 and r["t"] <= end)
            assert t["net"] == pytest.approx(want, abs=1e-4)
        assert f"{t['net']:+.2f}" in tk["cum_pnl"] and f"{t['net']:+.2f}" in tk["waterfall"] and f"{t['net_ex_artifacts']:+.2f}" in tk["cum_pnl"]
        assert f"{t['fills']} fills" in tk["cum_pnl"] and f"{t['fills']} fills" in e["headline"]
        assert e["label"] in tk["cum_pnl"] and e["label"] in e["headline"]          # every number names its window
        inc = [i for i in b["incidents"] if (not hours or i["t0"] >= end - hours * 3_600_000) and i["t0"] <= end]
        assert c["incidents"] == len(inc)
        assert c["open_incidents"] == sum(1 for i in inc if i["severity"] in ("high", "medium"))
        assert f"{c['open_incidents']} open incident" in e["headline"]
    assert b["by_range"]["24h"]["tiles"]["fills"] < b["by_range"]["all"]["tiles"]["fills"] and nets["24h"] != nets["all"]
    assert b["now"]["open_incidents"] == b["by_range"]["24h"]["counts"]["open_incidents"]
    assert b["headline"] == b["by_range"]["all"]["headline"]
    assert b["by_range"]["all"]["counts"]["open_incidents"] > b["by_range"]["24h"]["counts"]["open_incidents"] >= 1


def test_fills_on_a_side_logged_in_loss_stop_are_tagged_unwind(tmp_path):
    base = make_base(tmp_path, glitch=False)
    d = base / "data/testnet/BTCUSDT"                       # the ask side is in LOSS_STOP from T0 + 2000 s; the bid keeps quoting
    write_jsonl(d / "state_2026-11-14.jsonl", [
        {"ts_us": T0 + k * 60 * S, "side": sd, "state": "LOSS_STOP" if sd < 0 and k * 60 >= 2000 else "QUOTING", "detail": None}
        for k in range(0, 50) for sd in (1, -1)])
    bs.build(base, now_us=T0 + 3600 * S)
    b = load_bundle(base, "testnet-BTCUSDT-join")
    first_stop_ms = (T0 + 34 * 60 * S) // 1000             # first logged LOSS_STOP line at or after 2000 s
    assert b["fills"] and all(r["unwind"] == (r["side"] < 0 and r["t"] >= first_stop_ms) for r in b["fills"])
    n = sum(r["unwind"] for r in b["fills"])
    e = b["by_range"]["all"]
    assert e["counts"]["unwind_fills"] == n > 0
    s = e["takeaways"]["unwind"]
    assert s.startswith(f"{n} fills in {e['label']} (all sells)") and "loss-stop unwind" in s


def test_unwind_flags_follow_the_logged_state_not_the_stop_event():
    """A same-day restart that went back to QUOTING (older traders) must not tag the fills after it."""
    iv = {"bid": [{"t0": 0, "t1": 100, "state": "LOSS_STOP"}, {"t0": 100, "t1": 300, "state": "QUOTING"}],
          "ask": [{"t0": 0, "t1": 300, "state": "QUOTING"}]}
    t, side = pd.Series([50, 50, 200]), pd.Series([1, -1, 1])
    assert bs.unwind_flags(t, side, iv) == [True, False, False]
    assert bs.unwind_flags(t, side, {"bid": [], "ask": []}) == [False] * 3
    # a restart's warm-up that runs straight into LOSS_STOP is part of the stop; one that runs into QUOTING is not
    warm = {"bid": [], "ask": [{"t0": 0, "t1": 120, "state": "WARMUP"}, {"t0": 120, "t1": 300, "state": "LOSS_STOP"},
                               {"t0": 300, "t1": 420, "state": "WARMUP"}, {"t0": 420, "t1": 600, "state": "QUOTING"}]}
    assert bs.unwind_flags(pd.Series([60, 200, 360]), pd.Series([-1, -1, -1]), warm) == [True, True, False]


def test_worst_fills_is_about_fills_and_never_a_loss_stop(three_days):
    b = load_bundle(three_days, "testnet-BTCUSDT-join")
    assert any(i["kind"] == "loss_stop" for i in b["incidents"])
    for e in b["by_range"].values():
        s = e["takeaways"]["worst_fills"]
        assert "loss stop" not in s.lower() and ("worst fill" in s)
        assert e["label"] in s


def test_loss_stop_sentence_prints_the_day_figure_and_the_cumulative_one(three_days):
    b = load_bundle(three_days, "testnet-BTCUSDT-join")
    stops = sorted((i for i in b["incidents"] if i["kind"] == "loss_stop"), key=lambda i: i["t0"])
    old, new = stops
    assert "day's P&L was -20.12 USDT against a limit of -20 USDT" in new["sentence"]
    assert "cumulative P&L at that moment was -118.49 USDT" in new["sentence"] and "next UTC day" in new["sentence"]
    assert "day's loss passed the limit of 20 USDT" in old["sentence"]               # no state line logged: say only what is known
    reason = b["now"]["state"]["bid"]["reason"]                                      # the state card: inside the limit, still stopped
    assert "-7.70 USDT" in reason and "inside the limit" in reason and "holds until the next UTC day" in reason


def test_why_out_has_three_cases():
    arms = lambda *rows: [{"arm": i, "score_bp": s, "fills": n} for i, (s, n) in enumerate(rows)]
    base = {"min_arm_fills": 50.0, "start_arm": 2, "entry_threshold_bp": 0.0, "policy_out_share": None}
    none_eligible = bs.why_out_sentence({**base, "arms": arms((8.06, 8.6), (1.0, 3.0), (0.0, 0.0)), "eligible_arms": [], "live_arm": 2})
    assert "No setting has the 50 shadow fills needed to be chosen" in none_eligible
    assert "best so far: arm 0, +8.06 bp on 8.6 fills" in none_eligible and "most conservative setting, arm 2" in none_eligible
    below = bs.why_out_sentence({**base, "arms": arms((-1.5, 60.0), (-0.2, 80.0), (9.0, 4.0)), "eligible_arms": [0, 1], "live_arm": 2,
                                 "policy_out_share": 1.0})
    assert "Every eligible arm scores below 0 bp (best: arm 1, -0.20 bp on 80.0 fills)" in below and "quotes nothing" in below
    assert "stayed out 100%" in below
    above = bs.why_out_sentence({**base, "arms": arms((3.0, 70.0), (-1.0, 60.0), (0.0, 0.0)), "eligible_arms": [0, 1], "live_arm": 0})
    assert "best eligible arm, 0, scores +3.00 bp on 70.0 fills" in above and "the live arm is 0" in above
    assert bs.why_out_sentence({**base, "arms": [{"arm": 0, "score_bp": None, "fills": None}], "eligible_arms": [], "live_arm": 0}) == "No arm scores recorded yet."


def test_agent_bundle_carries_the_eligibility_facts(three_days):
    mo = load_bundle(three_days, "paper-ANKRUSDT-agent")["model"]
    assert mo["min_arm_fills"] == 50 and mo["eligible_arms"] == [] and mo["start_arm"] == 11


def test_state_intervals_without_fills_still_give_a_now_state(three_days):
    e = load_bundle(three_days, "paper-ANKRUSDT-agent")
    assert e["fills"] == [] and e["now"]["state"]["bid"]["state"] == "POLICY_OUT" and e["now"]["state"]["ask"]["state"] == "POLICY_OUT"
    assert "no state recorded" not in e["headline"] and "policy stays out" in e["headline"]


def test_favourable_glitch_is_info_and_says_in_our_favour(tmp_path):
    base = make_base(tmp_path)                             # the glitch fill sells at 57,882 into a 56,000 mid: it paid us
    bs.build(base, now_us=T0 + 3600 * S)
    b = load_bundle(base, "testnet-BTCUSDT-join")
    glitch = [i for i in b["incidents"] if i["kind"] == "artifact_fill" and "57882.6" in i["sentence"]]
    assert len(glitch) == 1 and glitch[0]["severity"] == "info" and "in our favour" in glitch[0]["sentence"]
    assert glitch[0]["cost_usd"] == 0.0 and "costing -" not in glitch[0]["sentence"]
    assert b["by_range"]["all"]["counts"]["open_incidents"] == sum(1 for i in b["incidents"] if i["severity"] in ("high", "medium"))


def test_order_age_sentence_says_it_is_not_queue_time(three_days):
    b = load_bundle(three_days, "testnet-BTCUSDT-join")
    assert b["funnel"]["median_replace_s"] == pytest.approx(16.0, abs=0.5)
    s = b["by_range"]["all"]["takeaways"]["queue_wait"]
    assert "Median order age at fill 15.9 s" in s and "about every 16 s" in s and "not time in the queue" in s

def test_loss_stop_state_says_since_the_stop_fired_and_empty_agent_says_so(three_days):
    b = load_bundle(three_days, "testnet-BTCUSDT-join")
    assert f"fired at {bs.hhmm(T0 * 1 + 216_000 * S)}" in b["now"]["state"]["bid"]["reason"]
    assert b["now"]["state"]["bid"]["since_us"] == T0 + 216_000 * S - S // 4 or b["now"]["state"]["bid"]["since_us"] <= T0 + 216_000 * S
    mo = {"min_arm_fills": 50.0, "start_arm": 2, "entry_threshold_bp": 0.0, "policy_out_share": 0.96, "live_arm": 2, "eligible_arms": [],
          "arms": [{"arm": i, "score_bp": 0.0, "fills": 0.0} for i in range(3)]}
    s = bs.why_out_sentence(mo)
    assert "none has a shadow fill yet" in s and "most conservative setting, arm 2" in s and "stayed out 96%" in s



# ---- showcase S6: what the execution test caught
def _cited(b, row):
    """The quantity a row's citation points at, read from the bundle itself (None when the cited thing is not there)."""
    c = row["cites"]
    if c["kind"] == "incident":
        ids = {i["id"] for i in b["incidents"]}
        return len(c["ids"]) if c["ids"] and set(c["ids"]) <= ids else None
    key = c["key"]
    if key == "states.NO_BALANCE":
        return sum(1 for s in ("bid", "ask") for iv in b["states"][s] if iv["state"] == "NO_BALANCE") or None
    if key == "funnel.reject_reasons":
        return sum(r["n"] for r in b["funnel"]["reject_reasons"] if "immediately match" in r["error"]) or None
    if key == "attribution.counts.artifact_fills":
        return b["attribution"]["counts"]["artifact_fills"] or None
    return None


def test_every_caught_row_cites_a_count_or_incident_that_is_in_the_bundle(tmp_path):
    base = make_base(tmp_path)
    bs.build(base, now_us=T0 + 3600 * S)
    b = load_bundle(base, "testnet-BTCUSDT-join")
    rows = b["caught"]
    ids = {r["id"] for r in rows}
    assert {"post_only", "book_glitch"} <= ids                       # the fixture has one rejected order and a glitch fill
    for r in rows:
        assert r["status"] in ("fixed", "open", "by design") and r["finding"] and r["evidence"]
        assert _cited(b, r) is not None, r["id"]
        if r["cites"]["kind"] == "count":
            assert _cited(b, r) == r["n"], r["id"]                    # the row's number is the cited number
    glitch = next(r for r in rows if r["id"] == "book_glitch")
    assert glitch["usd"] == pytest.approx(b["attribution"]["total"]["artifact"])
    assert b["takeaways"]["caught"].startswith(f"{len(rows)} finding")


def test_nothing_to_cite_means_no_row_and_paper_sessions_have_none(tmp_path):
    base = make_base(tmp_path, glitch=False)
    bs.build(base, now_us=T0 + 3600 * S)
    b = load_bundle(base, "testnet-BTCUSDT-join")
    assert "book_glitch" not in {r["id"] for r in b["caught"]}
    assert "no_balance" not in {r["id"] for r in b["caught"]}        # no NO_BALANCE interval in the log: nothing is invented
    p = load_bundle(base, "paper-ANKRUSDT-agent")
    assert p["caught"] == [] and "Nothing is recorded" in p["takeaways"]["caught"]


def test_pnl_summary_sentence_matches_the_tiles_of_its_range(three_days):
    for key, e in load_bundle(three_days, "testnet-BTCUSDT-join")["by_range"].items():
        t = e["tiles"]
        s = e["takeaways"]["pnl_summary"]
        assert f"Net {t['net']:+.2f} USDT" in s and f"fees {t['fees']:+.2f}" in s and f"book glitches {t['artifact']:+.2f}" in s, key
        assert s.endswith("Not a strategy result.")
