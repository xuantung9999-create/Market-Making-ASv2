"""Task L1: quote-state, richer place/fill records, session log, status state (all additive)."""
import json

import pytest

from mm.testnet import BinanceError, Executor, TestnetSession
from tests.test_testnet import FakeClient, K_ASK, K_BID, MID, RULES, _feed, make

T_MS = 1_700_000_000_123


class TimedClient(FakeClient):
    """Fake exchange whose responses carry the exchange's own times (ms)."""
    def new_order(self, symbol, side, price, qty, cid):
        r = super().new_order(symbol, side, price, qty, cid)
        r["transactTime"] = T_MS
        return r

    def fill(self, oid, qty):
        super().fill(oid, qty)
        self.book[oid]["updateTime"] = T_MS + 500


def mk(tmp_path, **kw):
    c = TimedClient()
    args = dict(lot_usd=100.0, q_max=2, maker_fee_bps=10.0, max_daily_loss_usd=1e9, out_dir=tmp_path)
    args.update(kw)
    return c, Executor("BTCUSDT", RULES, c, **args)


def rows(tmp_path, kind):
    out = []
    for f in sorted((tmp_path / "BTCUSDT").glob(f"{kind}_*.jsonl")):
        out += [json.loads(x) for x in f.read_text().splitlines()]
    return out


def states(tmp_path):
    return [(r["side"], r["state"]) for r in rows(tmp_path, "state")]


INFO = {"book": (49_999.99, 50_000.01, 3.0, 4.0), "action": {1: "JOIN", -1: "BACK"}, "live_arm": 5,
        "pred_bp": {1: 1.5, -1: None}}


def test_quoting_state(tmp_path):
    c, ex = mk(tmp_path)
    ex.step({1: K_BID, -1: K_ASK}, MID, 10_000_000, INFO)
    assert ex.state_log.cur[1]["state"] == "QUOTING" and ex.state_log.cur[-1]["state"] == "QUOTING"
    assert set(states(tmp_path)) == {(1, "QUOTING"), (-1, "QUOTING")}


def test_state_logged_on_change_and_every_60s(tmp_path):
    c, ex = mk(tmp_path)
    for i in range(3):
        ex.step({1: K_BID, -1: K_ASK}, MID, 10_000_000 + i * 1_000_000, INFO)
    assert len(states(tmp_path)) == 2                      # one line per side, no repeats
    ex.step({1: K_BID, -1: K_ASK}, MID, 10_000_000 + 61_000_000, INFO)
    assert len(states(tmp_path)) == 4                      # one more per side after 60 s
    ex.step({1: None, -1: K_ASK}, MID, 10_000_000 + 62_000_000, INFO)
    assert (1, "POLICY_OUT") in states(tmp_path)


def test_warmup_and_stale_feed(tmp_path):
    c, ex = mk(tmp_path)
    ex.step({1: None, -1: None}, MID, 1_000_000, {**INFO, "warmup": True})
    assert {s for _, s in states(tmp_path)} == {"WARMUP"}
    ex.step({1: None, -1: None}, MID, 2_000_000, {**INFO, "stale": True})
    assert ex.state_log.cur[1]["state"] == "STALE_FEED"


def test_policy_out_carries_arm_and_score(tmp_path):
    c, ex = mk(tmp_path)
    ex.step({1: None, -1: None}, MID, 1_000_000, {**INFO, "score_bp": -3.0})
    cur = ex.state_log.cur[1]
    assert cur["state"] == "POLICY_OUT" and cur["detail"]["live_arm"] == 5 and cur["detail"]["score_bp"] == -3.0


def test_loss_stop_state(tmp_path):
    c, ex = mk(tmp_path, max_daily_loss_usd=1.0)
    ex.step({1: K_BID, -1: K_ASK}, MID, 1_000_000, INFO)
    ex.cash -= 5.0
    ex.step({1: K_BID, -1: K_ASK}, MID, 2_000_000, INFO)
    assert ex.state_log.cur[1]["state"] == "LOSS_STOP" and ex.state_log.cur[-1]["state"] == "LOSS_STOP"


def test_inventory_cap_state(tmp_path):
    c, ex = mk(tmp_path, q_max=2)
    ex.pos = 2 * 100 / MID
    ex.step({1: K_BID, -1: K_ASK}, MID, 1_000_000, INFO)
    assert ex.state_log.cur[1]["state"] == "INV_CAP" and ex.state_log.cur[-1]["state"] == "QUOTING"
    assert "lots" in ex.state_log.cur[1]["detail"]


def test_no_balance_is_logged_where_it_returned_silently(tmp_path):
    c, ex = mk(tmp_path, base_free=0.0)
    ex.step({1: None, -1: K_ASK}, MID, 1_000_000, INFO)
    assert c.calls == []                                   # still no order
    assert ex.state_log.cur[-1]["state"] == "NO_BALANCE"
    c2, ex2 = mk(tmp_path / "b", quote_free=1.0)
    ex2.step({1: K_BID, -1: None}, MID, 1_000_000, INFO)
    assert c2.calls == [] and ex2.state_log.cur[1]["state"] == "NO_BALANCE"


def test_below_min_state(tmp_path):
    c, ex = mk(tmp_path, lot_usd=1.0)
    ex.step({1: K_BID, -1: None}, MID, 1_000_000, INFO)
    assert ex.state_log.cur[1]["state"] == "BELOW_MIN"


def test_rejected_state_includes_error(tmp_path):
    c, ex = mk(tmp_path)
    c.reject_next = True
    ex.step({1: K_BID, -1: None}, MID, 1_000_000, INFO)
    cur = ex.state_log.cur[1]
    assert cur["state"] == "REJECTED" and "-2010" in str(cur["detail"])


def test_exchange_error_state(tmp_path):
    c, ex = mk(tmp_path)
    ex.mark_error("HTTP 503 down", 5_000_000)
    assert ex.state_log.cur[1]["state"] == "EXCHANGE_ERROR" and ex.state_log.cur[-1]["state"] == "EXCHANGE_ERROR"


def test_place_record_has_book_mid_action_arm_pred(tmp_path):
    c, ex = mk(tmp_path)
    ex.step({1: K_BID, -1: K_ASK}, MID, 1_000_000, INFO)
    places = [r for r in rows(tmp_path, "orders") if r["op"] == "place"]
    b = next(r for r in places if r["side"] == 1)
    a = next(r for r in places if r["side"] == -1)
    assert (b["bid"], b["ask"], b["bid_qty"], b["ask_qty"], b["mid"]) == (49_999.99, 50_000.01, 3.0, 4.0, MID)
    assert (b["action"], b["live_arm"], b["pred_bp"]) == ("JOIN", 5, 1.5)
    assert a["action"] == "BACK" and "pred_bp" not in a     # no prediction -> key left out


def test_place_record_without_info_still_has_mid(tmp_path):
    c, ex = mk(tmp_path)
    ex.step({1: K_BID, -1: None}, MID, 1_000_000)
    r = next(r for r in rows(tmp_path, "orders") if r["op"] == "place")
    assert r["mid"] == MID and "bid" not in r


def test_fill_record_carries_exchange_time_and_context(tmp_path):
    c, ex = mk(tmp_path)
    ex.step({1: K_BID, -1: None}, MID, 1_000_000, INFO)
    oid = ex.orders[1].order_id
    c.fill(oid, 0.002)
    ex.step({1: K_BID, -1: None}, MID, 2_000_000, INFO)
    f = rows(tmp_path, "fills")[0]
    assert f["fill_ts_us"] == (T_MS + 500) * 1000
    assert f["place_ts_us"] == T_MS * 1000
    assert (f["bid"], f["ask"]) == (49_999.99, 50_000.01)
    assert f["fee_est"] == pytest.approx(49_999.99 * 0.002 * 10 / 1e4)
    assert f["ts_us"] > 0                                   # existing fields unchanged


def test_status_has_state_and_session_start(tmp_path):
    c, ex = mk(tmp_path)
    ex.step({1: K_BID, -1: None}, MID, 7_000_000, INFO)
    st = ex.status(MID)
    assert st["state"]["bid"]["state"] == "QUOTING" and st["state"]["bid"]["since_us"] == 7_000_000
    assert st["state"]["ask"]["state"] == "POLICY_OUT"
    assert st["session_start_us"] > 0
    for k in ("symbol", "pos", "lots", "pnl", "fees_est", "fills", "rejects", "stopped", "open"):
        assert k in st                                      # existing keys unchanged


def test_session_log_start_and_stop(tmp_path):
    c, ex = mk(tmp_path)
    ex.log_session("start", {"policy": "join"}, base_free=1.0, quote_free=2.0)
    ex.log_session("stop", {"policy": "join"})
    r = rows(tmp_path, "session") if False else [json.loads(x) for x in (tmp_path / "BTCUSDT" / "session.jsonl").read_text().splitlines()]
    assert [x["op"] for x in r] == ["start", "stop"]
    assert r[0]["args"] == {"policy": "join"} and r[0]["base_free"] == 1.0 and r[0]["pid"] > 0
    assert "pos_at_start" in r[0]


def test_session_wires_info_and_stops_cleanly(tmp_path):
    c = TimedClient()
    s = TestnetSession(["BTCUSDT"], c, {"BTCUSDT": RULES}, policy="join", warmup_s=5, lot_usd=100, q_max=2,
                       state_dir=tmp_path / "state", out_dir=tmp_path)
    ex = s.execs["BTCUSDT"]
    t0 = 1_700_000_000.0
    for i in range(10):
        _feed(s, "BTCUSDT", t0 + i, 49_999.99, 50_000.01, trade=(50_000.0, i % 2 == 0))
        s.tick(int((t0 + i) * 1e6))
        s.execute(int((t0 + i) * 1e6))
        if i == 1:
            assert ex.state_log.cur[1]["state"] == "WARMUP"
    assert ex.state_log.cur[1]["state"] == "QUOTING"
    place = next(r for r in rows(tmp_path, "orders") if r["op"] == "place" and r["side"] == 1)
    assert place["bid"] == 49_999.99 and place["action"] == "JOIN" and place["mid"] == 50_000.0
    s.shutdown()
    assert (tmp_path / "BTCUSDT" / "session.jsonl").read_text().strip().splitlines()[-1].count('"stop"') == 1
